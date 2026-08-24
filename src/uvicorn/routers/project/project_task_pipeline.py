"""
Эндпоинты конвейера агентов: чтение состояния и переходы, требующие человека.

Сам конвейер крутится в `src/project/task/`; здесь только точки, где в него
вмешивается пользователь. CRUD задач — в `project_task.py`.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.project.task.task_diff import task_diff_build, task_diff_build_task
from src.project.task.task_log import (task_log_list, task_log_read,
                                       task_log_rows_running)
from src.project.task.task_metadata import (
    TASK_METADATA_KEY_BUGFIX,
    TASK_METADATA_KEY_MERGED,
    TASK_METADATA_KEY_PLAN,
    task_metadata_parse,
    task_metadata_row_apply,
    task_metadata_update,
)
from src.project.task.task_plan import (
    task_plan_goals_get,
    task_plan_goals_merge,
    task_plan_parse,
    task_plan_serialize,
)
from src.project.task.task_pipeline import task_pipeline_shells_restart
from src.project.task.task_report import task_report_write
from src.project.task.task_role import TASK_ROLE_TITLE, task_role_project_work_dir
from src.project.task.task_state import task_state_kanban_sql, task_state_type_to_dev
from src.project.task.task_stop import task_stop_apply, task_stop_clear
from src.project.task.task_revision import (
    TASK_REVISION_LIMIT,
    task_revision_add,
    task_revision_delete,
    task_revision_get,
    task_revision_list,
)
from src.project.task.task_worktree import task_worktree_merge

# Состояния, в которых план можно трогать: конвейер над ним не работает и подзадач
# по нему ещё (или уже) нет. `approved`/`processing` сюда не входят намеренно — план там
# либо раскладывается, либо выполняется, и подмена его на ходу рассинхронизировала бы
# подзадачи с планом, из которого они выросли.
_PLAN_EDITABLE_STATES: list[str | None] = [None, 'plan_approval', 'done', 'failed']

# Удаление подзадач плана. `pipeline_from_plan` здесь обязателен: дерево общее, и
# «дети задачи» — это ещё и человеческая декомпозиция, которую сброс плана трогать
# не должен. Удаляем строго то, что конвейер сам и создал.
_SUBTASKS_DELETE_SQL = "DELETE FROM project_task WHERE parent_id = %s AND pipeline_from_plan = 1"

router = APIRouter()


@router.get('/task/{task_id}/pipeline')
async def project_task_pipeline_get(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, pipeline_state, pipeline_plan, pipeline_error FROM project_task WHERE id = %s",
            (task_id,)
        )
        task = await db.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail='task not found')

        # Подзадачи конвейера — дети этой же таблицы, разложенные из плана. Имена полей
        # оставлены прежними (`state`, `attempt_count`, `last_error`): панель плана
        # читает подзадачу, а не задачу, и колонки конвейера ей не нужны.
        await db.execute(
            "SELECT id, position, title, description, pipeline_state AS state, "
            "       pipeline_attempt_count AS attempt_count, pipeline_error AS last_error "
            "  FROM project_task WHERE parent_id = %s AND pipeline_from_plan = 1 "
            " ORDER BY position, id",
            (task_id,)
        )
        subtasks = await db.fetchall()

        await db.execute(
            "SELECT a.id, a.task_id AS subtask_id, a.attempt_no, a.role, a.status, "
            "       a.output, a.error, a.created_at "
            "  FROM project_task_attempt a JOIN project_task s ON s.id = a.task_id "
            " WHERE s.parent_id = %s AND s.pipeline_from_plan = 1 ORDER BY a.id",
            (task_id,)
        )
        attempts = await db.fetchall()

    plan_text, _ = task_plan_parse(task['pipeline_plan'] or '')
    return {
        'pipeline_state': task['pipeline_state'],
        'plan_text':      plan_text,
        # Цели отдаём из плана, а не из `task.goals`: в задаче они уже смешаны с
        # целями человека, а панель показывает именно предложенное менеджером.
        'goals':          task_plan_goals_get(task['pipeline_plan'] or ''),
        'error':          task['pipeline_error'],
        'subtasks':       [dict(r) for r in (subtasks or [])],
        'attempts':       [dict(r) for r in (attempts or [])],
    }


@router.post('/task/{task_id}/pipeline/start')
async def project_task_pipeline_start(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Отправить задачу в конвейер. Вход только явный — обычные задачи агенты не трогают.

    Снятый флажок фазы кнопка снимает: нажатие — это и есть просьба взять задачу в
    работу прямо сейчас, а с пометкой она ушла бы в `new` и там же осталась — захват её
    не видит (`task_metadata_plan_free_sql`, `task_metadata_bugfix_free_sql`). Ключи
    стираем (`None`), а не пишем `true`: умолчание у обоих «включено».

    Стираем оба разом, не разбирая тип задачи: у обычной задачи `to_bugfix` не
    используется, у бага — `to_planning`, и лишнее стирание никого не задевает. Разбор
    же по типу пришлось бы повторять здесь целиком (`task_role`), а забытая ветка дала
    бы ровно тот тупик, от которого эта строка и защищает.
    """
    await task_stop_clear(task_id, user.username)
    await task_metadata_update(task_id, {TASK_METADATA_KEY_PLAN: None,
                                         TASK_METADATA_KEY_BUGFIX: None})
    return await _pipeline_state_set(task_id, expected=None, new_state='new',
                                     report=f'{user.username} отправил задачу в конвейер — ждёт плана от менеджера')


@router.post('/task/{task_id}/pipeline/approve')
async def project_task_pipeline_approve(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Человек утвердил план — оркестратор разложит его на подзадачи.

    Вместе с состоянием меняем тип: `plan` -> `dev`, задача переезжает на вкладку
    «Разработка» (`task_state_type_to_dev`). Утверждение плана — это и есть конец
    планирования, и по пометке «в разработку» тип менялся именно здесь; у нажатия
    кнопки смысл тот же. Порядок обязателен: сначала переход состояния со сверкой
    гонки, тип — только удавшемуся нажатию.
    """
    result = await _pipeline_state_set(
        task_id, expected='plan_approval', new_state='approved',
        report=f'{user.username} утвердил план — ждёт разложения на подзадачи')
    if await task_state_type_to_dev(task_id):
        await task_report_write(task_id, 'Планирование закончено — тип сменён на «Разработка»')
    return result


@router.post('/task/{task_id}/pipeline/reject')
async def project_task_pipeline_reject(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Отклонить план и вывести задачу из конвейера. План сохраняется для разбора."""
    return await _pipeline_state_set(
        task_id, expected='plan_approval', new_state=None, ok=False,
        report=f'{user.username} отклонил план — задача выведена из конвейера, агенты её не берут')


@router.post('/task/{task_id}/pipeline/review')
async def project_task_pipeline_review(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Отправить существующий план менеджеру на пересмотр («Обновить план»).

    Второй вход в конвейер: обычный отбор идёт по отсутствию плана, а тут план как раз
    есть — поэтому отдельное состояние `reviewing`, из которого задачу заберёт
    `_step_manager_review`.
    """
    await _plan_editable_task(task_id)

    result = await _pipeline_state_set(
        task_id, expected=_PLAN_EDITABLE_STATES, new_state='reviewing',
        report=f'{user.username} отправил план на пересмотр — прежние подзадачи удалены')

    # Подзадачи удаляем после захвата состояния, а не до: проиграв гонку двойному
    # клику, мы бы уже снесли чужую работу. Они принадлежали старому плану, а
    # `_step_plan_split` только добавляет строки — без удаления новый план лёг бы
    # поверх старого. Список подзадач сохранён в ревизии; попытки
    # (`project_task_attempt`) уезжают по CASCADE — это осознанная потеря.
    async with mysql_get_db_async() as db:
        await db.execute(_SUBTASKS_DELETE_SQL, (task_id,))
        await db.connection.commit()

    return result


@router.post('/task/{task_id}/pipeline/retry')
async def project_task_pipeline_retry(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Повторить сорвавшийся шаг конвейера.

    Возвращаем не в одно фиксированное состояние: `failed` — общий исход трёх разных
    шагов, и вернуть задачу нужно к тому, который её уронил. Иначе она зависнет —
    отбор у каждого шага свой, и `new` у задачи с готовым планом и целями не подберёт
    никто (`task_claim_task_unplanned` берёт только беcплановые).

    * есть подзадачи      -> `processing`: план уже материализован, менеджер не нужен;
    * план есть, подзадач нет -> `approved`: сорвалось разложение, повторяем его;
    * плана нет           -> `new`: за планом к менеджеру.

    Вместе с состоянием перезапускаем и агентов в оболочках
    (`task_pipeline_shells_restart`): срыв по таймауту оставляет дочерний Claude
    Code с брошенным ходом, и новый прогон ушёл бы в занятую оболочку.

    Остановку снимаем заодно: «Перезапустить» — это и есть «продолжаем», и оставленный
    запрет обернул бы нажатие сменой состояния без единого прогона следом.

    Замечание QA у разблокированных подзадач сохраняем — почему, см. комментарий
    у самого UPDATE ниже.
    """
    await task_stop_clear(task_id, user.username)

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, project_id, pipeline_state, pipeline_plan FROM project_task WHERE id = %s",
            (task_id,))
        task = await db.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail='task not found')
        if task['pipeline_state'] != 'failed':
            raise HTTPException(
                status_code=409,
                detail=f'Перезапускать нечего: задача не в состоянии failed '
                       f'(сейчас: {task["pipeline_state"] or "—"})')

        await db.execute(
            "SELECT COUNT(*) AS total, SUM(pipeline_state = 'blocked') AS blocked "
            "  FROM project_task WHERE parent_id = %s AND pipeline_from_plan = 1", (task_id,))
        counts = await db.fetchone()

    total   = int(counts['total'] or 0)
    blocked = int(counts['blocked'] or 0)

    if total:
        # Снимаем блок до перехода состояния, а не после: `task_state_task_finalize`
        # забирает задачи в `processing`, у которых все подзадачи терминальны, и успела бы
        # уронить её обратно в `failed` в зазоре между двумя запросами.
        # Счётчик попыток обнуляем — иначе `task_claim_subtask_developable` захватит
        # подзадачу и тут же вернёт её в `blocked` по исчерпанному лимиту.
        #
        # `pipeline_error` при этом не трогаем. Замечание QA — единственное, что
        # говорит следующему кругу, чего не хватило: `_run_developer` передаёт его
        # разработчику как `task_last_error`, и по нему в промпте раскрывается блок
        # «предыдущая попытка не прошла проверку QA — разбирайся с ошибкой, а не
        # начинай подзадачу заново». Очистка здесь превращала перезапуск в старт
        # с чистого листа: агент терял и замечание, и указание не переделывать
        # сделанное (контекст оболочки перезапуск гасит отдельно).
        kanban_sql, kanban_params = task_state_kanban_sql('planned')
        async with mysql_get_db_async() as db:
            await db.execute(
                f"UPDATE project_task SET pipeline_state = 'planned', {kanban_sql + ', ' if kanban_sql else ''}"
                "       pipeline_attempt_count = 0, "
                "       pipeline_locked_at = NULL, pipeline_locked_by = '' "
                " WHERE parent_id = %s AND pipeline_from_plan = 1 AND pipeline_state = 'blocked'",
                kanban_params + [task_id])
            await db.connection.commit()
        new_state = 'processing'
        note = (f'снят блок с подзадач: {blocked}' if blocked
                else 'подзадачи вернулись в работу')
    elif task_plan_parse(task['pipeline_plan'] or '')[1]:
        new_state = 'approved'
        note = 'план уже есть — ждёт разложения на подзадачи'
    else:
        new_state = 'new'
        note = 'ждёт плана от менеджера'

    # Перезапуск до смены состояния: иначе тик успел бы забрать задачу и отправить
    # прогон в оболочку ровно в тот момент, когда мы её гасим.
    roles = await task_pipeline_shells_restart(task)
    if roles:
        titles = ', '.join(TASK_ROLE_TITLE.get(role, role) for role in roles)
        note += f'; перезапущены оболочки: {titles}'

    return await _pipeline_state_set(task_id, expected='failed', new_state=new_state,
                                     report=f'{user.username} перезапустил конвейер — {note}')


@router.post('/task/{task_id}/pipeline/stop')
async def project_task_pipeline_stop(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Остановить работу над задачей — снятый флажок «в разработку» рядом со статусом.

    В отличие от «Отклонить», задачу из конвейера не выводим и состояние не теряем:
    строка возвращается туда, откуда её взяли, и ждёт человека. Продолжение — возврат
    того же флажка (`/pipeline/resume`) или флажка фазы, и задача идёт дальше с того
    же места.

    Подробности — в `task_stop`: там же объяснено, почему запрет живёт в `metadata`,
    а не в человеческом `status`.
    """
    result = await task_stop_apply(task_id, user.username)
    if not result:
        raise HTTPException(status_code=404, detail='task not found')

    return {'ok': True, **result, 'task': await _task_row(task_id)}


@router.post('/task/{task_id}/pipeline/resume')
async def project_task_pipeline_resume(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Снять остановку — задачу снова видно отбору.

    Ничего не запускает руками: работу отдаст ближайший тик оркестратора по тому же
    `pipeline_state`, в который её вернула остановка. Повторное нажатие безвредно.
    """
    if not await _task_row(task_id):
        raise HTTPException(status_code=404, detail='task not found')

    resumed = await task_stop_clear(task_id, user.username)
    return {'ok': True, 'resumed': resumed, 'task': await _task_row(task_id)}


@router.post('/task/{task_id}/worktree/merge')
async def project_task_worktree_merge(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Влить ветку подзадачи в главную ветку проекта и снять её рабочий каталог.

    Кнопка «mr2master&rm_worktree» в колонке прогресса. Делается по кнопке, а не
    автоматом после `done`: закрытая подзадача ещё не значит принятая работа —
    merge request может ждать ревью, а каталог нужен, чтобы посмотреть, что там
    вышло. Решение остаётся за человеком.

    Номером можно дать и задачу целиком: ветки заводят под подзадачи, поэтому её
    вливаем всеми ветками подряд, в порядке подзадач. Первый же отказ останавливает
    остальные — сливать дальше поверх несведённого значит множить разбор.

    Слияние локальное, без `push` — отправку в общий репозиторий человек делает сам.
    Отказ (грязный каталог, конфликт, нет ветки) отдаём как 400 с текстом от git:
    разбирать такое всё равно человеку, и общая формулировка ему не поможет.

    Удавшееся слияние помечается в задаче (`TASK_METADATA_KEY_MERGED`), и повторное
    нажатие эндпоинт уже не пускает: ветки влиты, каталоги сняты, второй раз вливать
    нечего. Отказ здесь — 409, а не 400: это не поломка, а «уже сделано».
    """
    work_dir, subtask_ids, task = await _diff_target(task_id)

    merged_before = task_metadata_parse(task.get('metadata')).get(TASK_METADATA_KEY_MERGED)
    if merged_before:
        at = merged_before.get('at') if isinstance(merged_before, dict) else ''
        by = merged_before.get('by') if isinstance(merged_before, dict) else ''
        raise HTTPException(status_code=409,
                            detail='работа задачи уже влита в главную ветку'
                                   + (f' — {by}' if by else '') + (f', {at}' if at else ''))

    merged: list[str] = []
    base, removed = '', True
    for subtask_id in subtask_ids:
        result = await task_worktree_merge(work_dir, subtask_id)
        if not result['ok']:
            done = f' (влито до отказа: {", ".join(merged)})' if merged else ''
            raise HTTPException(status_code=400, detail=result['error'] + done)

        merged.append(result['branch'])
        base = result['base']
        # `removed` собираем по всем веткам, а не берём у последней: не снявшийся
        # каталог одной подзадачи — повод сходить в лог, даже если остальные снялись.
        removed = removed and bool(result['removed'])
        await task_report_write(
            subtask_id, f'{user.username} влил ветку {result["branch"]} в {result["base"]}'
                        + ('' if result['removed'] else ' (рабочий каталог снять не удалось — смотрите лог)'))

    # Отметка ставится одна на задачу и только после всех веток: слияние половины
    # плана — это не «влито», и серая кнопка на нём соврала бы. Первый же отказ выше
    # уходит исключением, до сюда не доходя.
    merged_meta = {'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'by': user.username,
                   'base': base, 'branches': merged}
    await task_metadata_update(task_id, {TASK_METADATA_KEY_MERGED: merged_meta})

    return {'ok': True, 'merged': merged, 'branch': ', '.join(merged),
            'base': base, 'removed': removed, 'merged_meta': merged_meta}


@router.get('/task/{task_id}/diff')
async def project_task_diff(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Разница главной ветки проекта и ветки подзадачи — чем занят `task_diff.py`.

    Нужен потому, что merge request на сервере эту разницу показать не может: ветка
    режется от локальной главной ветки, а MR сравнивает её с `origin/master`, и
    коммиты, которых на сервере ещё нет, приезжают в MR как работа подзадачи.
    Читает страница `/admin/task/diff`.

    Номером берём и задачу целиком, и отдельную подзадачу. Обычно спрашивают задачу:
    человеку нужно, что она изменила в проекте, а не что сделала каждая ветка плана.

    Только чтение: ни слияния, ни коммитов здесь нет — для этого отдельная кнопка
    и отдельные права (`PLANNING_UPDATE`). Проверка «пройдёт ли слияние» в ответе
    есть (`merge`) — она репозиторий не меняет.
    """
    work_dir, subtask_ids, task = await _diff_target(task_id)

    # Одна ветка — это либо подзадача, либо задача, которую не раскладывали на план.
    result = (await task_diff_build(work_dir, task_id) if subtask_ids == [task_id]
              else await task_diff_build_task(work_dir, subtask_ids))
    result['task'] = {'id': task['id'], 'title': task['title'],
                      'parent_id': task['parent_id']}
    # Отметка о состоявшемся слиянии — по ней страница гасит кнопку «Merge». Основная
    # — своя, из `metadata`: в ней есть кто и когда принял работу. Запасная — от git
    # (`merge['merged']`): она без имён, зато находит и то, что влили до появления
    # отметки или руками в консоли.
    merged = task_metadata_parse(task.get('metadata')).get(TASK_METADATA_KEY_MERGED)
    if not merged and (result.get('merge') or {}).get('merged'):
        merged = {'base': result['merge'].get('base') or result.get('base') or ''}
    result['merged'] = merged or None

    # Пустой ответ — не ошибка HTTP: «ветки ещё нет» и «в ветке ничего нет» страница
    # показывает сама и текстом понятнее, чем красная плашка от 400.
    return result


@router.get('/task/{task_id}/plan/revisions')
async def project_task_plan_revisions(task_id: int, limit: int = TASK_REVISION_LIMIT,
                                      user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Ревизии плана от свежих к старым. Самая свежая совпадает с текущим планом.

    `limit` нужен странице: чипсы рисуются по короткому окну, а «…ещё N» перечитывает
    историю целиком. Потолок жёсткий — в каждой ревизии лежит полный текст плана.
    """
    revisions, total = await task_revision_list(task_id, limit=max(1, min(int(limit), 500)))
    return {'revisions': revisions, 'total': total}


@router.get('/task/{task_id}/plan/revision/{revision_no}')
async def project_task_plan_revision(task_id: int, revision_no: int,
                                     user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Одна ревизия целиком — для чипсов за пределами отданного списком окна."""
    revision = await task_revision_get(task_id, revision_no)
    if not revision:
        raise HTTPException(status_code=404, detail='revision not found')
    return {'revision': revision}


@router.post('/task/{task_id}/plan/revision/{revision_no}/restore')
async def project_task_plan_revision_restore(task_id: int, revision_no: int,
                                             user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Вернуть план из ревизии.

    `pipeline_state` не трогаем: восстановление — это правка плана, а не переход
    конвейера. Новая ревизия при этом создаётся, поэтому откат виден в истории, а не
    подменяет её — в append-only журнале «отменить» значит «дописать».
    """
    task = await _plan_editable_task(task_id)

    revision = await task_revision_get(task_id, revision_no)
    if not revision:
        raise HTTPException(status_code=404, detail='revision not found')

    # Цели вливаем, а не перезаписываем: человек мог отметить сделанные цели уже после
    # той ревизии, и восстановление плана не повод сбрасывать эти галочки.
    goals_json = task_plan_goals_merge(task['goals'], revision['goals'])
    plan_json  = task_plan_serialize(revision['plan_text'], revision['subtasks'], revision['goals'])

    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task SET pipeline_plan = %s, goals = %s WHERE id = %s",
            (plan_json, goals_json, task_id),
        )
        await db.connection.commit()

    created = await task_revision_add(
        task_id, revision['plan_text'], revision['goals'], revision['subtasks'],
        author_kind='user', author_id=user.user_id, author_name=user.username)

    return {'ok': True, 'revision_no': created or revision_no}


@router.delete('/task/{task_id}/plan/reset')
async def project_task_plan_reset(task_id: int,
                                  user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Очистить план и цели, вернуть задачу в начало конвейера.

    pipeline_plan = '', goals = '', pipeline_state = NULL — задача снова
    попадётся оркестратору и получит план от менеджера.

    Возвращаем строку задачи целиком: сброс двигает не одно поле, а обе оси сразу
    (`goals` и человеческий `status`), и странице нужен свежий снимок — иначе форма
    останется с прежними целями и следующим «Сохранить» вернёт их в базу.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id FROM project_task WHERE id = %s", (task_id,))
        if not await db.fetchone():
            raise HTTPException(status_code=404, detail='task not found')

        # Человеческий статус возвращаем в `pending` вручную: `pipeline_state = NULL`
        # таблице соответствия неизвестен, а «вернулась в начало» на обеих осях
        # выглядит одинаково — задача снова ждёт менеджера.
        kanban_sql, kanban_params = task_state_kanban_sql('new')
        await db.execute(
            f"UPDATE project_task SET pipeline_plan = '', goals = '', {kanban_sql + ', ' if kanban_sql else ''}"
            "pipeline_state = NULL, pipeline_error = '', "
            "pipeline_locked_at = NULL, pipeline_locked_by = '' "
            "WHERE id = %s", kanban_params + [task_id])
        # Подзадачи принадлежали снесённому плану, а `_step_plan_split` только
        # добавляет строки: без удаления новый план лёг бы поверх старого. Тот же
        # порядок, что и у «Обновить план»; список остаётся в ревизиях.
        await db.execute(_SUBTASKS_DELETE_SQL, (task_id,))
        await db.connection.commit()

        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()

    await task_report_write(task_id, f'{user.username} сбросил план и цели — задача вернулась в начало конвейера')
    return {'ok': True, 'task': task_metadata_row_apply(task)}


@router.delete('/task/{task_id}/plan/revision/{revision_no}')
async def project_task_plan_revision_delete(task_id: int, revision_no: int,
                                            user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Удалить одну ревизию плана.

    Номера не пересчитываются — удаляем строку, остальные номера остаются на месте.
    """
    async with mysql_get_db_async() as db:
        await db.execute("SELECT id FROM project_task WHERE id = %s", (task_id,))
        row = await db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='task not found')

    await task_revision_delete(task_id, revision_no)
    return {'ok': True}


async def _task_row(task_id: int) -> dict | None:
    """Строка задачи для ответа — с разобранным `metadata`. Нет задачи — None."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()

    return task_metadata_row_apply(task) if task else None


@router.get('/task/logs/{project_id}')
async def project_task_logs(project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Живые журналы проекта: что показывать на вкладке «Журналы» страницы задач.

    Номер проекта обязателен, потому что каталоги у проектов свои: журнал лежит в
    каталоге строки внутри репозитория проекта, и общий список смешал бы работу
    соседних. Тот же номер выбран селектором проекта на странице.

    Список строится по каталогам на диске, а не по таблице задач: журнал живёт в
    каталоге строки и исчезает вместе с ним после слияния ветки — таблица об этом
    ничего не знает. Названия и состояния подставляем из БД: файлы имён не знают.

    Путь `/task/logs/...` объявлен до `/task/{task_id}/log`: иначе FastAPI разобрал
    бы «logs» как номер задачи и ответил бы 422 на каждый запрос списка.
    """
    work_dir = await task_role_project_work_dir(project_id)
    items = task_log_list(work_dir) if work_dir else []

    # Строки с идущим прогоном добавляем к тем, у кого уже есть файл: файл
    # появляется по концу круга, и строка, которую агент обрабатывает впервые,
    # в список не попадала — хотя показать по ней уже есть что.
    running = await task_log_rows_running()
    seen = {item['task_id'] for item in items}
    for task_id, role in running.items():
        if task_id not in seen:
            items.append({'task_id': task_id, 'bytes': 0, 'updated_at': ''})

    # Кто в работе прямо сейчас — знает страница: она их подсвечивает и ставит
    # наверх. Роль оттуда же: по ней видно, чей это круг, без открытия журнала.
    for item in items:
        item['running'] = item['task_id'] in running
        item['role'] = running.get(item['task_id'], '')

    if not items:
        return {'result': []}

    async with mysql_get_db_async() as db:
        placeholders = ', '.join(['%s'] * len(items))
        await db.execute(
            f"SELECT s.id, s.title, s.parent_id, s.status, s.pipeline_state, "
            f"       COALESCE(s.project_id, p.project_id) AS project_id "
            f"  FROM project_task s LEFT JOIN project_task p ON p.id = s.parent_id "
            f" WHERE s.id IN ({placeholders})", [item['task_id'] for item in items])
        tasks = {row['id']: row for row in (await db.fetchall() or [])}

    # Каталоги на диске уже принадлежат проекту, а идущие прогоны собраны по всей
    # установке — чужие отсеиваем здесь, иначе в списке проекта появились бы
    # строки соседнего.
    items = [item for item in items
             if int((tasks.get(item['task_id']) or {}).get('project_id') or 0) == project_id]

    for item in items:
        task = tasks.get(item['task_id']) or {}
        item['title'] = str(task.get('title') or '')
        item['parent_id'] = task.get('parent_id')
        item['status'] = task.get('status') or ''
        item['pipeline_state'] = task.get('pipeline_state') or ''

    # Сначала те, над кем работают прямо сейчас, дальше по свежести записи.
    # Идущий прогон файла ещё не имеет и по времени правки ушёл бы в самый низ —
    # то есть ровно то, что человеку нужнее всего, оказывалось дальше всего.
    items.sort(key=lambda item: (item['running'], item['updated_at'] or ''), reverse=True)

    return {'result': items}


@router.get('/task/{task_id}/log')
async def project_task_log(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Журнал и состояние строки: чем агент занят сейчас и докуда дошёл.

    Пишет их сам агент по ходу работы — `.task-log.md` (хронология, дописывается)
    и `.task-state.md` (сделано/осталось/затыки, перезаписывается). Подробности,
    зачем они и где лежат, — в `src/project/task/task_log.py`.

    Номер берём и подзадачи, и задачи: у задачи с планом свой каталог есть не
    всегда, зато есть журнал менеджера в постоянном архиве.

    Путь собирается по номеру строки через `task_log_dir` — из запроса не приходит
    ни куска пути. Иначе ручка превратилась бы в чтение произвольного файла с диска.

    Пустой ответ не ошибка: строка могла ещё не браться в работу, а агент — не
    дойти до первой записи. Плашку про это рисует страница.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT s.id, s.parent_id, COALESCE(s.project_id, p.project_id) AS project_id "
            "  FROM project_task s LEFT JOIN project_task p ON p.id = s.parent_id "
            " WHERE s.id = %s", (task_id,))
        task = await db.fetchone()

    if not task:
        raise HTTPException(status_code=404, detail='task not found')

    work_dir = await task_role_project_work_dir(task['project_id'])
    if not work_dir:
        return {'log': '', 'state': '', 'dir': '', 'task_id': task_id}

    return {**await task_log_read(work_dir, task_id), 'task_id': task_id}


async def _diff_target(task_id: int) -> tuple[str, list, dict]:
    """
    Каталог проекта и подзадачи, по веткам которых считать разницу или слияние.

    Один помощник на страницу разницы и на кнопку слияния: они обязаны понимать номер
    одинаково, иначе кнопка вольёт не то, что человек посмотрел.

    Номер подзадачи — это она сама, одна ветка. Номер разложенной задачи — все её
    подзадачи по порядку: своей ветки у неё нет, вся работа лежит в ветках плана.
    Задача без подзадач — снова одна ветка, своя: конвейер отдаёт разработку листу,
    а лист бывает и верхнего уровня.

    Returns: `(рабочий каталог, номера подзадач, строка задачи)`. Отказ — HTTP.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT s.id, s.title, s.parent_id, s.metadata, "
            "       COALESCE(s.project_id, p.project_id) AS project_id "
            "  FROM project_task s LEFT JOIN project_task p ON p.id = s.parent_id "
            " WHERE s.id = %s",
            (task_id,)
        )
        task = await db.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail='task not found')

        subtask_ids = [task_id]
        if not task['parent_id']:
            await db.execute(
                "SELECT id FROM project_task WHERE parent_id = %s ORDER BY position, id", (task_id,))
            # Пустой список — не отказ: у нераспланированной задачи ветка своя.
            subtask_ids = [row['id'] for row in (await db.fetchall() or [])] or [task_id]

    work_dir = await task_role_project_work_dir(task['project_id'])
    if not work_dir:
        raise HTTPException(status_code=400, detail='у проекта не задан рабочий каталог (карточка проекта)')

    return work_dir, subtask_ids, task


async def _plan_editable_task(task_id: int) -> dict:
    """
    Задача, план которой сейчас можно переписать. Иначе 404/400/409 с русским текстом.

    Отдельная проверка на живые подзадачи — страховка от рассинхрона: состояние
    задачи и состояния её подзадач ведутся разными шагами конвейера, и подменить план
    под работающими подзадачами хуже, чем отказать лишний раз.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, pipeline_state, pipeline_plan, goals FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail='task not found')

        await db.execute(
            "SELECT COUNT(*) AS cnt FROM project_task "
            " WHERE parent_id = %s AND pipeline_from_plan = 1 "
            "   AND pipeline_state NOT IN ('done', 'blocked')",
            (task_id,),
        )
        busy = await db.fetchone()

    if task['pipeline_state'] not in _PLAN_EDITABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f'План занят конвейером (состояние: {task["pipeline_state"]}) — пересмотр недоступен')

    if int(busy['cnt'] if busy else 0):
        raise HTTPException(status_code=409, detail='По плану ещё выполняются подзадачи — пересмотр недоступен')

    # Смотрим на текст плана, а не на подзадачи: план, написанный человеком руками,
    # подзадач не имеет, но пересматривать и восстанавливать его совершенно осмысленно.
    if not task_plan_parse(task['pipeline_plan'] or '')[0].strip():
        raise HTTPException(status_code=400, detail='Плана нет — сначала отправьте задачу в конвейер')

    return dict(task)


async def _pipeline_state_set(task_id: int, expected: str | None | list, new_state: str | None,
                              report: str = '', ok: bool | None = True) -> dict:
    """
    Условный перевод состояния. Сверка с `expected` идёт прямо в UPDATE, иначе
    двойной клик в UI проскочит гонку и утвердит план дважды.

    `expected` — одно состояние либо список допустимых; `None` внутри означает «вне
    конвейера» (`pipeline_state IS NULL`).

    `report` пишется только после удавшегося перехода: проигравший гонку клик состояние
    не менял, и строка в журнале от него означала бы событие, которого не было.
    """
    states = list(expected) if isinstance(expected, (list, tuple)) else [expected]
    where_state = ' OR '.join('pipeline_state IS NULL' if s is None else 'pipeline_state = %s' for s in states)
    kanban_sql, kanban_params = task_state_kanban_sql(new_state)
    params: list = [new_state] + kanban_params + [s for s in states if s is not None] + [task_id]

    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET pipeline_state = %s, {kanban_sql + ', ' if kanban_sql else ''}"
            f"pipeline_error = '', "
            f"pipeline_locked_at = NULL, pipeline_locked_by = '' "
            f"WHERE ({where_state}) AND id = %s",
            params
        )
        updated = db.rowcount
        await db.connection.commit()

        row = None
        if not updated:
            await db.execute("SELECT pipeline_state FROM project_task WHERE id = %s", (task_id,))
            row = await db.fetchone()

    if not updated:
        if not row:
            raise HTTPException(status_code=404, detail='task not found')
        raise HTTPException(
            status_code=409,
            detail=f'Задача не в состоянии {_states_label(states)} (сейчас: {row["pipeline_state"] or "—"})'
        )

    if report:
        await task_report_write(task_id, report, ok=ok)

    return {'ok': True, 'pipeline_state': new_state}


def _states_label(states: list) -> str:
    return ' / '.join(s if s else 'вне конвейера' for s in states)

"""
Эндпоинты конвейера агентов: чтение состояния и переходы, требующие человека.

Сам конвейер крутится в `src/project/task/`; здесь только точки, где в него
вмешивается пользователь. CRUD задач — в `project_task.py`.
"""
from fastapi import APIRouter, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.project.task.task_plan import (
    task_plan_goals_get,
    task_plan_goals_merge,
    task_plan_parse,
    task_plan_serialize,
)
from src.project.task.task_revision import (
    TASK_REVISION_LIMIT,
    task_revision_add,
    task_revision_get,
    task_revision_list,
)

# Состояния, в которых план можно трогать: конвейер над ним не работает и подзадач
# по нему ещё (или уже) нет. `approved`/`split` сюда не входят намеренно — план там
# либо раскладывается, либо выполняется, и подмена его на ходу рассинхронизировала бы
# подзадачи с планом, из которого они выросли.
_PLAN_EDITABLE_STATES: list[str | None] = [None, 'pending_approval', 'done', 'failed']

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

        await db.execute(
            "SELECT id, position, title, description, state, attempt_count, last_error "
            "  FROM project_task_subtask WHERE task_id = %s ORDER BY position, id",
            (task_id,)
        )
        subtasks = await db.fetchall()

        await db.execute(
            "SELECT a.id, a.subtask_id, a.attempt_no, a.role, a.status, a.output, a.error, a.created_at "
            "  FROM project_task_attempt a JOIN project_task_subtask s ON s.id = a.subtask_id "
            " WHERE s.task_id = %s ORDER BY a.id",
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
    """Отправить задачу в конвейер. Вход только явный — обычные задачи агенты не трогают."""
    return await _pipeline_state_set(task_id, expected=None, new_state='new')


@router.post('/task/{task_id}/pipeline/approve')
async def project_task_pipeline_approve(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Человек утвердил план — оркестратор разложит его на подзадачи."""
    return await _pipeline_state_set(task_id, expected='pending_approval', new_state='approved')


@router.post('/task/{task_id}/pipeline/reject')
async def project_task_pipeline_reject(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Отклонить план и вывести задачу из конвейера. План сохраняется для разбора."""
    return await _pipeline_state_set(task_id, expected='pending_approval', new_state=None)


@router.post('/task/{task_id}/pipeline/review')
async def project_task_pipeline_review(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """
    Отправить существующий план менеджеру на пересмотр («Обновить план»).

    Второй вход в конвейер: обычный отбор идёт по отсутствию плана, а тут план как раз
    есть — поэтому отдельное состояние `review`, из которого задачу заберёт
    `_step_manager_review`.
    """
    await _plan_editable_task(task_id)

    result = await _pipeline_state_set(task_id, expected=_PLAN_EDITABLE_STATES, new_state='review')

    # Подзадачи удаляем после захвата состояния, а не до: проиграв гонку двойному
    # клику, мы бы уже снесли чужую работу. Они принадлежали старому плану, а
    # `_step_plan_split` только добавляет строки — без удаления новый план лёг бы
    # поверх старого. Список подзадач сохранён в ревизии; попытки
    # (`project_task_attempt`) уезжают по CASCADE — это осознанная потеря.
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_task_subtask WHERE task_id = %s", (task_id,))
        await db.connection.commit()

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
            "SELECT COUNT(*) AS cnt FROM project_task_subtask "
            " WHERE task_id = %s AND state NOT IN ('done', 'blocked')",
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


async def _pipeline_state_set(task_id: int, expected: str | None | list, new_state: str | None) -> dict:
    """
    Условный перевод состояния. Сверка с `expected` идёт прямо в UPDATE, иначе
    двойной клик в UI проскочит гонку и утвердит план дважды.

    `expected` — одно состояние либо список допустимых; `None` внутри означает «вне
    конвейера» (`pipeline_state IS NULL`).
    """
    states = list(expected) if isinstance(expected, (list, tuple)) else [expected]
    where_state = ' OR '.join('pipeline_state IS NULL' if s is None else 'pipeline_state = %s' for s in states)
    params: list = [new_state] + [s for s in states if s is not None] + [task_id]

    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET pipeline_state = %s, pipeline_error = '', "
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

    return {'ok': True, 'pipeline_state': new_state}


def _states_label(states: list) -> str:
    return ' / '.join(s if s else 'вне конвейера' for s in states)

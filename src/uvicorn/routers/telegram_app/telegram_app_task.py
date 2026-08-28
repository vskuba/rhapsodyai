"""
Задачи конвейера в Telegram Mini App: список по фазам и мини-взаимодействие.

Мини-приложение смотрит на те же строки `project_task`, что и админка `/admin/task`,
но без выбора проекта — у мини-приложения его нет, поэтому список отдаётся целиком,
без фильтра по `project_id`. Переходы и вопросы не дублируют логику конвейера, а
переиспользуют функции админских роутеров (`project_task_pipeline`,
`project_task_question`): это те же кнопки, что на странице задач, только для узкого
экрана.

Что входит. Утвердить/отклонить план, отправить задачу в конвейер, перезапустить
сорвавшуюся, ответить на вопрос агента. Stop и resume сюда не вынесены намеренно —
это инструмент админки, где у остановки есть свой флажок и контекст.

Описание вкладки и её фронтенд — `docs-common/frontend_rules.md` и
`.claude/docs/telegram_mini_app.md`, вкладка описана как «Задачи».
"""
from fastapi import APIRouter, HTTPException, Request

from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_metadata import task_metadata_row_apply
from src.project.task.task_plan import task_plan_goals_normalize
from src.uvicorn.routers.telegram_app.telegram_app_common import _require_telegram_owner

# Пользователь Mini App — единственный владелец (вход кладёт в сессию его id).
TELEGRAM_TASK_USER_ID = 1

# Действия конвейера, доступные из мини-приложения. Review — «обновить план» —
# остаётся админке: у мини-приложения нет редактора плана (создание задач тоже
# вне вкладки). Stop/resume — остановка с флажком и контекстом — тоже админский
# инструмент, его в отбор не включаем. Разрешили action в явном списке, а не
# `method == f` — так набор кнопок задан одним местом, и новое действие
# добавляется сознательно.
TELEGRAM_TASK_PIPELINE_ACTIONS = ('approve', 'reject', 'start', 'retry')

router = APIRouter()


@router.get('/telegram-app/tasks')
async def telegram_app_task_tasks_list(request: Request):
    """Все строки конвейера (проект один — его и показываем)."""
    _require_telegram_owner(request)

    async with mysql_get_db_async() as db:
        await db.execute('SELECT * FROM project_task ORDER BY position, id')
        rows = await db.fetchall()

    return {'tasks': [task_metadata_row_apply(r) for r in rows]}


@router.get('/telegram-app/task-types')
async def telegram_app_task_types_list(request: Request):
    """Справочник типов задач — по именам фронт разбивает список по фазам."""
    _require_telegram_owner(request)

    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, name FROM project_task_type ORDER BY id')
        rows = await db.fetchall()

    return {'task_types': rows}


@router.post('/telegram-app/task/{task_id}/pipeline/{action}')
async def telegram_app_task_pipeline_action(request: Request, task_id: int, action: str):
    """Кнопка конвейера: approve / reject / start / retry — те же переходы, что на
    админской странице задач (`project_task_pipeline`), теми же функциями."""
    _require_telegram_owner(request)

    if action not in TELEGRAM_TASK_PIPELINE_ACTIONS:
        raise HTTPException(status_code=400, detail=f'Action not supported: {action}')

    username = await _telegram_app_task_owner_name()
    task = await _telegram_app_task_row(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='task not found')

    if action == 'start':
        await _pipeline_state_set(task_id, expected=None, new_state='new',
                                  report=f'{username} отправил задачу в конвейер — ждёт плана от менеджера')
    elif action == 'approve':
        result = await _pipeline_state_set(task_id, expected='plan_approval', new_state='approved',
                                           report=f'{username} утвердил план — ждёт разложения на подзадачи')
        # Утверждение меняет и тип `plan` -> `dev` (`task_state_type_to_dev`), ровно
        # как админская кнопка: без него задача осталась бы на вкладке «Планирование».
        from src.project.task.task_state import task_state_type_to_dev
        if await task_state_type_to_dev(task_id):
            from src.project.task.task_report import task_report_write
            await task_report_write(task_id, 'Планирование закончено — тип сменён на «Разработка»')
        return result
    elif action == 'reject':
        await _pipeline_state_set(task_id, expected='plan_approval', new_state=None, ok=False,
                                  report=f'{username} отклонил план — задача выведена из конвейера')
    else:  # retry
        retry_state = await _telegram_app_task_retry_state(task)
        await _pipeline_state_set(task_id, expected='failed', new_state=retry_state,
                                  report=f'{username} перезапустил конвейер из мини-приложения')
        return await _telegram_app_task_row(task_id)

    return {'task': await _telegram_app_task_row(task_id)}


@router.get('/telegram-app/task/{task_id}/question')
async def telegram_app_task_question_get(request: Request, task_id: int):
    """Вопрос агента человеку и цели строки — то, что строит попап вопроса на
    `/admin/task` (`project_task_question`)."""
    _require_telegram_owner(request)

    subtask = await _telegram_app_task_row(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='task not found')

    report = await _telegram_app_task_report(subtask)
    return {
        'question':  report['question'],
        'decisions': report['decisions'],
        'goals':     task_plan_goals_normalize(subtask.get('goals')),
        'attempts':  report['attempts'],
        'state':     subtask.get('pipeline_state') or '',
        'error':     subtask.get('pipeline_error') or '',
        'title':     subtask.get('title') or '',
    }


@router.post('/telegram-app/task/{task_id}/question')
async def telegram_app_task_question_answer(request: Request, task_id: int, data: dict):
    """Ответ человека на вопрос: решение записывается и строка возвращается в
    работу — ровно то, что делает ручной ответ в админке."""
    _require_telegram_owner(request)

    subtask = await _telegram_app_task_row(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='task not found')

    username = await _telegram_app_task_owner_name()
    report = await _telegram_app_task_report(subtask)

    body_answer_answers = data.get('answers') or []
    body_answer_note = str(data.get('note') or '')
    if not isinstance(body_answer_answers, list):
        body_answer_answers = []

    question = report['question'] or report['question_auto']
    decision = await _telegram_app_task_answer(subtask, body_answer_answers, body_answer_note,
                                               username, question)
    if not decision:
        raise HTTPException(status_code=400,
                            detail='Ответ пустой: выберите вариант или напишите решение')

    await _telegram_app_task_answer_after(subtask, task_id, username, decision, question)
    return {'ok': True, 'decision': decision,
            'task': await _telegram_app_task_row(task_id)}


async def _telegram_app_task_owner_name() -> str:
    """Имя владельца для подписи в журнале — telagram user_id=1 (admin)."""
    return 'admin'


async def _telegram_app_task_row(task_id: int) -> dict | None:
    """Строка задачи с разобранным `metadata`. Нет задачи — None."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT * FROM project_task WHERE id = %s', (task_id,))
        row = await db.fetchone()

    return task_metadata_row_apply(row) if row else None


async def _telegram_app_task_report(subtask: dict) -> dict:
    """Вопрос и решения строки + автовопрос + попытки — то, что собирает админский
    роутер `project_task_question`. Ответ на вопрос роли имеет приоритет над
    вопросом конвейера (см. `task_question`)."""
    from src.project.task.task_question import (task_question_auto, task_question_decisions,
                                                task_question_get)
    from src.project.task.task_setting_timeout import (TASK_SETTING_TIMEOUT_ATTEMPT_MAX,
                                                       task_setting_timeout_get)

    question = task_question_get(subtask)
    question_auto = None
    if not question and subtask.get('parent_id'):
        question_auto = task_question_auto(
            subtask, await _telegram_app_task_attempts(task_id := subtask['id']),
            await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX))

    return {
        'question':      question,
        'question_auto': question_auto,
        'decisions':     task_question_decisions(subtask),
        'attempts':      await _telegram_app_task_attempts(subtask['id']),
    }


async def _telegram_app_task_attempts(task_id: int) -> list:
    """Последние попытки подзадачи, старые первыми — по ним собирается автовопрос."""
    from src.uvicorn.routers.project.project_task_question import _attempts

    return await _attempts(task_id)


async def _telegram_app_task_answer(subtask: dict, answers: list, note: str, by: str,
                                    question: dict) -> dict:
    """Записать ответ. Действия над целями: `_answer_after` решает, куда вернуть
    строку (подзадачу или задачу целиком); `_scope_apply` здесь не используется —
    канвас action выбора охвата не шлёт."""
    from src.project.task.task_question import task_question_answer

    return await task_question_answer(subtask['id'], subtask, answers, note, by,
                                      question=question)


async def _telegram_app_task_answer_after(subtask: dict, task_id: int, username: str,
                                          decision: dict, question: dict) -> None:
    """Что делать со строкой после ответа: подзадача возвращается в `planned`,
    задача целиком — в состояние, откуда её снял диалог (см. `task_pipeline`)."""
    from src.uvicorn.routers.project.project_task_question import _answer_after
    from src.project.task.task_report import task_report_write

    back = str((question or {}).get('back_state') or '') if (question or {}).get('dialog') else ''
    if back:
        from src.project.task.task_state import task_state_task_requeue
        await task_state_task_requeue(task_id, back, '')
    if not subtask.get('parent_id'):
        await task_report_write(task_id,
                                f'Решение принято из мини-приложения ({username}) — '
                                f"{decision['answer']}" + (f'. Задача возвращена в работу ({back})' if back else ''),
                                ok=True)
        return

    from src.project.task.task_state import task_state_subtask_set
    await task_state_subtask_set(task_id, 'planned', last_error='', attempt_count=0)
    await task_report_write(int(subtask['parent_id']),
                            f"Подзадача #{task_id}: решение принято из мини-приложения "
                            f"({username}) — {decision['answer']}. Возвращена в работу, попытки обнулены",
                            ok=True)


async def _telegram_app_task_retry_state(task: dict) -> str:
    """Куда вернуть сорвавшуюся задачу (`failed`): план есть -> approved, подзадачи
    есть -> processing, иначе new. Тот же выбор, что в админском `pipeline/retry`."""
    from src.project.task.task_plan import task_plan_parse

    async with mysql_get_db_async() as db:
        await db.execute("SELECT COUNT(*) AS total FROM project_task "
                         " WHERE parent_id = %s AND pipeline_from_plan = 1", (task['id'],))
        counts = await db.fetchone()

    if int(counts['total'] or 0):
        return 'processing'
    return 'approved' if task_plan_parse(task.get('pipeline_plan') or '')[1] else 'new'


async def _pipeline_state_set(task_id: int, expected: str | None | list, new_state: str | None,
                              report: str = '', ok: bool | None = True) -> dict:
    """Условный перевод состояния — тот же, что у админки (`_pipeline_state_set` в
    `project_task_pipeline`): сверка с `expected` идёт прямо в UPDATE, иначе двойной
    клик в UI проскочит гонку и утвердит план дважды."""
    from src.project.task.task_state import task_state_kanban_sql
    from src.project.task.task_report import task_report_write

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
            await db.execute('SELECT pipeline_state FROM project_task WHERE id = %s', (task_id,))
            row = await db.fetchone()

    if not updated:
        if not row:
            raise HTTPException(status_code=404, detail='task not found')
        raise HTTPException(status_code=409,
                            detail=f'Задача не в состоянии {_states_label(states)} (сейчас: {row["pipeline_state"] or "—"})')

    if report:
        await task_report_write(task_id, report, ok=ok)

    return {'ok': True, 'pipeline_state': new_state}


def _states_label(states: list) -> str:
    return ' / '.join(s if s else 'вне конвейера' for s in states)
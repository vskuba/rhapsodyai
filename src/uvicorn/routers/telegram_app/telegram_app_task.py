"""
Вкладка «Задачи» мини-приложения Telegram: список, фазовые флажки и вопросы.

Точки повторяют то, что человек делает на `/admin/task`, — список задач, флажки фаз,
утверждение плана и ответ на вопрос роли, — и собраны в одном модуле, потому что рисует
их одна вкладка. Механика та же, что у страницы задач; разница одна: пускаем по
`telegram_owner_id` (`_require_telegram_owner`), а не по роли RBAC.

Вопрос отвечается двумя точками — прочитать и ответить. Вопрос роли отвечает только
записью; вопрос конвейера (подзадача встала) ещё и исполняет: варианты там — действия
над целями (`task_goal_scope`, `task_goal_replan_send`), и «раздробить» без самого
дробления было бы обещанием, а не ответом.
"""
from fastapi import APIRouter, Request, HTTPException
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_depend import TASK_DEPEND_DONE_STATES, task_depend_of
from src.project.task.task_metadata import (    TASK_METADATA_KEY_DEV, TASK_METADATA_KEY_PLAN, TASK_METADATA_KEY_TEST, task_metadata_row_apply, task_metadata_update)
from src.project.task.task_report import task_report_write
from src.project.task.task_state import (    task_state_dev_to_testing, task_state_plan_to_development, task_state_type_to_dev)
from src.project.task.task_stop import task_stop_clear
from src.uvicorn.routers.project.project_task_pipeline import _pipeline_state_set
from src.uvicorn.routers.telegram_app.telegram_app_common import _require_telegram_owner
from contextlib import suppress
from pydantic import BaseModel
from datetime_.datetime_ import datetime_offset_apply, datetime_utc_now
from setting_.setting_ import setting_get
from src.project.task.task_goal_replan import TASK_GOAL_REPLAN_STATE, task_goal_replan_send
from src.project.task.task_goal_scope import task_goal_scope_drop, task_goal_scope_split
from src.project.task.task_log import task_log_dir
from src.project.task.task_log_decision import task_log_decision_write
from src.project.task.task_metadata import task_metadata_row_apply
from src.project.task.task_plan import task_plan_goals_normalize
from src.project.task.task_role import task_role_project_work_dir
from src.project.task.task_question import (TASK_QUESTION_ACTION_DROP, TASK_QUESTION_ACTION_PLAN, TASK_QUESTION_ACTION_SPLIT, task_question_answer, task_question_auto, task_question_batch, task_question_batch_answer, task_question_decisions, task_question_get, task_question_plan_append)
from src.project.task.task_setting_timeout import (TASK_SETTING_TIMEOUT_ATTEMPT_MAX, task_setting_timeout_get)
from src.project.task.task_state import task_state_subtask_set, task_state_task_requeue

router = APIRouter()

# Куда возвращается подзадача после ответа. `planned` — начало круга Developer → QA:
# ответ меняет условия работы, и правильный следующий шаг — заново взяться за
# подзадачу, а не отдать на проверку то, что сделано до развилки.
TASK_QUESTION_STATE_BACK = 'planned'

# Сколько последних попыток читаем: по ним собирается автовопрос конвейера.
TASK_QUESTION_ATTEMPTS_MAX = 10


class TaskQuestionAnswer(BaseModel):
    """Ответ человека: выбранные варианты, отмеченные цели и свободный текст."""
    answers: list[str] = []
    note: str = ''
    goal_indexes: list[int] = []
    # Номер вопроса пачки разведки. `None` — одиночный вопрос. Отдельным полем, а не
    # «первый без ответа»: порядок ответов свободный, человек возвращается к уже
    # отвеченным, чтобы их поправить.
    index: int | None = None


@router.get('/telegram-app/tasks')
async def telegram_app_task_tasks_list(request: Request):
    """Список задач для вкладки «Задачи» мини-приложения.

    Возвращает те же поля, что страница /admin/task: каждую строку
    `project_task` пропускает через `task_metadata_row_apply` и дополняет
    зависимостями. Самих задач там сотни, поэтому связи кладём одним запросом
    на всю выдачу, а не вторым запросом на каждую строку. Отвечает только
    владельцу по `telegram_owner_id`.
    """
    _require_telegram_owner(request)

    async with mysql_get_db_async() as db:
        await db.execute('SELECT * FROM project_task ORDER BY position, id')
        rows = await db.fetchall()

    tasks = [task_metadata_row_apply(r) for r in rows]
    await _telegram_app_task_depend_attach(tasks)

    return {'result': {'tasks': tasks}}


@router.post('/telegram-app/task/{task_id}/metadata')
async def telegram_app_task_metadata_patch(task_id: int, data: dict, request: Request):
    """Поставить фазовый флажок задачи: «в планирование», «в разработку», «в тестирование».

    Точечно поправить `metadata`, как на /admin/task (`project_task_metadata_patch`):
    свои ключи перезаписать, чужие оставить. Мини-приложение шлёт только флажки фаз
    (`to_planning`, `to_development`, `to_testing`) — то, что рисует в карточке, и
    чужие ключи не трогает. Повторяет за админкой две немедленные пометки: «в
    разработку» и «в тестирование» переводят фазу, если задача уже достигла нужного
    рубежа (план написан, разработка закончена), и снимают остановку. Отвечает только
    владельцу по `telegram_owner_id`.
    """
    _require_telegram_owner(request)

    patch = data.get('patch')
    if not isinstance(patch, dict) or not patch:
        raise HTTPException(status_code=400, detail='patch must be a non-empty object')

    allowed = (TASK_METADATA_KEY_PLAN, TASK_METADATA_KEY_DEV, TASK_METADATA_KEY_TEST)
    if any(k not in allowed for k in patch):
        raise HTTPException(status_code=400, detail='only phase flags are allowed')

    owner = str(request.session.get('telegram_owner_id'))
    if patch.get(TASK_METADATA_KEY_DEV) is True \
            or (TASK_METADATA_KEY_TEST in patch and patch[TASK_METADATA_KEY_TEST] is not False):
        await task_stop_clear(task_id, owner)

    await task_metadata_update(task_id, patch)
    if patch.get(TASK_METADATA_KEY_DEV) is True and await task_state_plan_to_development(task_id):
        await task_report_write(
            task_id,
            f'{owner} пометил задачу «в разработку»: план утверждён, '
            'тип сменён на «Разработка»')
    if TASK_METADATA_KEY_TEST in patch and patch[TASK_METADATA_KEY_TEST] is not False \
            and await task_state_dev_to_testing(task_id):
        await task_report_write(
            task_id,
            f'{owner} пометил задачу «в тестирование»: разработка закончена, '
            'тип сменён на «Тестирование»')

    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()

    if not task:
        raise HTTPException(status_code=404, detail='task not found')

    return {'result': {'task': task_metadata_row_apply(task)}}


@router.post('/telegram-app/task/{task_id}/pipeline/approve')
async def telegram_app_task_pipeline_approve(task_id: int, request: Request):
    """Утвердить план из мини-приложения: состояние `plan_approval` -> `approved`, тип `plan` -> `dev`.

    Тот же переход, что кнопка «Утвердить» на /admin/task
    (`project_task_pipeline_approve`): сначала перевод состояния со сверкой гонки,
    тип — только удавшемуся нажатию. Отвечает только владельцу по `telegram_owner_id`.
    """
    _require_telegram_owner(request)

    result = await _pipeline_state_set(
        task_id, expected='plan_approval', new_state='approved',
        report='План утверждён — ждёт разложения на подзадачи')
    if await task_state_type_to_dev(task_id):
        await task_report_write(task_id, 'Планирование закончено — тип сменён на «Разработка»')
    return {'result': result}


@router.get('/telegram-app/task/{task_id}/question')
async def telegram_app_task_question_get(request: Request, task_id: int):
    """
    Вопрос по подзадаче, её цели и уже принятые решения.

    Вопрос роли имеет приоритет над вопросом конвейера: роль спросила о конкретной
    развилке, и подменять её вопрос общим «что делаем с целями» значит потерять то,
    ради чего прогон вообще остановился.

    Автовопрос собирается только по подзадаче: его варианты дробят и сокращают
    цели, а у задачи целиком цели ведёт план менеджера — там охват меняют не так.
    Цели и попытки отдаём всегда: отвечающий на вопрос роли тоже смотрит, чем
    подзадачу примут и обрывались ли прогоны.
    """
    _require_telegram_owner(request)

    subtask = await _subtask_row(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='task not found')

    attempts = await _attempts(task_id)
    question = task_question_get(subtask)
    if not question and subtask.get('parent_id'):
        question = task_question_auto(
            subtask, attempts,
            await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX))

    return {
        'question':  question,
        # Пачка вопросов разведки: у каждого свой черновик ответа. Отдаём целиком —
        # человек переключается между ними и правит уже отвеченные, потому что
        # ответ на третий вопрос нередко меняет ответ на первый.
        'questions': task_question_batch(subtask),
        'decisions': task_question_decisions(subtask),
        'goals':     task_plan_goals_normalize(subtask.get('goals')),
        'attempts':  attempts,
        'state':     subtask.get('pipeline_state') or '',
        'error':     subtask.get('pipeline_error') or '',
        'title':     subtask.get('title') or '',
    }


@router.post('/telegram-app/task/{task_id}/question/answer')
async def telegram_app_task_question_answer(request: Request, task_id: int,
                                            body: TaskQuestionAnswer):
    """
    Ответить на вопрос подзадачи и вернуть её в работу.

    Действие над целями исполняется до записи решения: дробление и сокращение могут
    отказать (отмечены все цели, ни одной), и записывать решение о том, чего не
    произошло, нельзя. Счётчик попыток обнуляется — круги до вопроса потрачены на
    работу, которая упиралась в нерешённое, считать их неудачами нечестно.
    """
    _require_telegram_owner(request)
    by = str(request.session.get("telegram_owner_id") or '')

    subtask = await _subtask_row(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='Task not found')

    # Пачка вопросов разведки — свой путь. Ответ на один её вопрос ложится черновиком
    # и задачу не отпускает: пока остаётся хоть одна развилка, исполнитель вернулся
    # бы ровно в то, из-за чего встал. Действия над целями сюда не идут.
    if body.index is not None:
        result = await task_question_batch_answer(task_id, subtask, int(body.index),
                                                  body.answers, body.note, by)
        if not result:
            raise HTTPException(status_code=400,
                                detail='Ответ пустой или вопроса с таким номером нет')
        if not result['done']:
            return {'ok': True, 'left': result['left'], 'done': False}

        # Пачка закрылась — дальше как у одиночного вопроса: показать решения и
        # вернуть задачу в работу.
        for decision in result['decisions']:
            await _answer_show(task_id, subtask, decision, {})
        state = await _answer_after(subtask, task_id, by,
                                    result['decisions'][-1], {}, '')

        return {'ok': True, 'left': 0, 'done': True,
                'decisions': result['decisions'], 'state': state}

    # Вопрос берём тот же, что показал бы читатель: у автовопроса в мешке ничего не
    # лежит, и без него в решение попал бы голый ключ `goals_split` вместо подписи.
    question = task_question_get(subtask)
    if not question and not subtask.get('parent_id'):
        # Автовопрос — про охват подзадачи; у корневой задачи цели ведёт план, и
        # трогать их отсюда нельзя.
        raise HTTPException(status_code=409,
                            detail='По задаче целиком вопрос задаёт только менеджер при планировании')
    if not question:
        question = task_question_auto(
            subtask, await _attempts(task_id),
            await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX))

    scope = await _scope_apply(subtask, body)
    if scope and not scope.get('ok'):
        raise HTTPException(status_code=400,
                            detail=scope.get('error') or 'Действие над целями не выполнено')

    decision = await task_question_answer(task_id, subtask, body.answers,
                                          _note_with_scope(body.note, scope), by,
                                          question=question)
    if not decision:
        raise HTTPException(status_code=400,
                            detail='Ответ пустой: выберите вариант или напишите решение')

    await _answer_show(task_id, subtask, decision, question)

    scope_state = (TASK_GOAL_REPLAN_STATE
                   if scope.get('subtask_id') and TASK_QUESTION_ACTION_PLAN in {str(a) for a in body.answers}
                   else '')
    state = await _answer_after(subtask, task_id, by, decision, question, scope_state)

    return {'ok': True, 'decision': decision, 'state': state, 'scope': scope}


async def _telegram_app_task_depend_attach(tasks: list) -> None:
    """Положить на каждую строку её зависимости; сбой связей список не роняет.

    Локальная копия того же приёма, что в `project_task._tasks_depend_attach`:
    строк на выдаче сотни, и запрос на каждую был бы пустым ходом. `task_depend_of`
    берёт сразу все номера. Строкам без связей кладём пустые списки, а не
    отсутствие ключей, — фронтенду не приходится различать «связей нет» и
    «поле забыли положить». `depend_blocked` — кто из предшественников ещё не
    закрыт: ответ на вопрос «почему подзадача стоит».
    """
    for task in tasks:
        task['depends_on'] = []
        task['depend_blocked'] = []

    ids = [int(t['id']) for t in tasks if t.get('id')]
    if not ids:
        return

    try:
        links = await task_depend_of(ids)
        if not links:
            return

        # Кто из предшественников ещё не закрыт — по той же выдаче, без похода в
        # базу: состояния всех строк уже здесь.
        state_by_id = {int(t['id']): str(t.get('pipeline_state') or '') for t in tasks}
        for task in tasks:
            deps = links.get(int(task['id']), [])
            task['depends_on'] = deps
            task['depend_blocked'] = [
                dep for dep in deps
                if state_by_id.get(dep, '') not in TASK_DEPEND_DONE_STATES]
    except Exception as error:
        logger_info(f'telegram_app_task: зависимости не приложены: {type(error).__name__}: {error}')


async def _answer_show(task_id: int, subtask: dict, decision: dict, question: dict) -> None:
    """
    Показать решение человеку: в плане подзадачи и в журнале строки.

    Роль получает решение из мешка через промпт; эти две записи — только
    видимость. Поэтому сбой любой из них ответ не отменяет.
    """
    if subtask.get('parent_id'):
        with suppress(Exception):
            await task_question_plan_append(task_id, subtask, decision, question)

    with suppress(Exception):
        offset = await setting_get('timezone', '+0')
        task_log_decision_write(
            task_log_dir(await task_role_project_work_dir(subtask.get('project_id')), task_id),
            decision, question,
            datetime_offset_apply(datetime_utc_now(), offset),
            str(question.get('role') or ''))


async def _answer_after(subtask: dict, task_id: int, by: str, decision: dict,
                        question: dict, scope_state: str = '') -> str:
    """
    Что делать со строкой после ответа. Возвращает её новое состояние.

    Подзадача уходит в `planned` с обнулённым счётчиком. Возврат менеджеру
    (`scope_state`) уже поставил строке своё состояние `new`, и общий `planned`
    его перебил бы — строка ушла бы не на планирование, а в круг с тем же
    неподъёмным охватом.
    """
    if not subtask.get('parent_id'):
        back = str((question or {}).get('back_state') or '') if (question or {}).get('dialog') else ''
        if back:
            await task_state_task_requeue(task_id, back, '')
        await task_report_write(
            task_id,
            f"Решение принято ({by}) — {decision['answer']}"
            + (f'. Задача возвращена в работу ({back})' if back else ''),
            ok=True)
        return back or str(subtask.get('pipeline_state') or '')

    if str(scope_state or '') == TASK_GOAL_REPLAN_STATE:
        await task_report_write(
            int(subtask['parent_id']),
            f"Подзадача #{task_id}: решение принято ({by}) — {decision['answer']}. "
            f"Возвращена менеджеру на разбиение", ok=True)
        return TASK_GOAL_REPLAN_STATE

    await task_state_subtask_set(task_id, TASK_QUESTION_STATE_BACK, last_error='', attempt_count=0)
    title = str(subtask.get('title') or '').strip()
    label = f'Подзадача #{task_id}' + (f' «{title}»' if title else '')
    await task_report_write(int(subtask['parent_id']),
                            f"{label}: решение принято ({by}) — {decision['answer']}. "
                            f"Возвращена в работу, попытки обнулены", ok=True)

    return TASK_QUESTION_STATE_BACK


async def _scope_apply(subtask: dict, body: TaskQuestionAnswer) -> dict:
    """
    Исполнить действие над целями, если оно выбрано. Нечего делать — `{}`.

    Ключи действий приходят только из автовопроса; ответ на вопрос роли их не
    содержит, и проверять тип вопроса отдельно не нужно.
    """
    picked = {str(a) for a in (body.answers or [])}

    if TASK_QUESTION_ACTION_SPLIT in picked:
        return await task_goal_scope_split(subtask, body.goal_indexes)
    if TASK_QUESTION_ACTION_DROP in picked:
        return await task_goal_scope_drop(subtask, body.goal_indexes)
    # Возврат менеджеру — не действие над целями, а признание, что охват задали
    # неподъёмный: строка уходит в `new`, откуда её забирает планирование.
    if TASK_QUESTION_ACTION_PLAN in picked:
        return await task_goal_replan_send(subtask)

    # `goals_keep` — осознанный отказ менять охват: он запишется решением, но
    # делать по нему нечего.
    return {}


def _note_with_scope(note: str, scope: dict) -> str:
    """Дописать к ответу, что именно случилось с целями — роль прочтёт следующим кругом."""
    text = str(note or '').strip()
    if not scope or not scope.get('ok'):
        return text

    if scope.get('moved_text'):
        done = (f"вынесено в подзадачу #{scope['subtask_id']}: "
                + '; '.join(scope['moved_text']))
    elif scope.get('dropped_text'):
        done = 'убраны цели: ' + '; '.join(scope['dropped_text'])
    else:
        return text

    return f'{text} ({done})' if text else done


async def _attempts(task_id: int) -> list:
    """Последние попытки подзадачи, старые первыми — по ним собирается автовопрос."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT attempt_no, role, status, error, duration_ms, created_at "
            "  FROM project_task_attempt WHERE task_id = %s ORDER BY id DESC LIMIT %s",
            (task_id, TASK_QUESTION_ATTEMPTS_MAX))
        rows = await db.fetchall()

    return list(reversed(rows))


async def _subtask_row(task_id: int) -> dict | None:
    """Строка подзадачи с разобранным `metadata`. Нет строки — None."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        row = await db.fetchone()

    return task_metadata_row_apply(row) if row else None

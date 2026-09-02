from fastapi import APIRouter, Request, HTTPException

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_depend import TASK_DEPEND_DONE_STATES, task_depend_of
from src.project.task.task_metadata import (
    TASK_METADATA_KEY_DEV,
    TASK_METADATA_KEY_PLAN,
    TASK_METADATA_KEY_TEST,
    task_metadata_row_apply,
    task_metadata_update,
)
from src.project.task.task_report import task_report_write
from src.project.task.task_state import (
    task_state_dev_to_testing,
    task_state_plan_to_development,
    task_state_type_to_dev,
)
from src.project.task.task_stop import task_stop_clear
from src.uvicorn.routers.project.project_task_pipeline import _pipeline_state_set
from src.uvicorn.routers.telegram_app.telegram_app_common import _require_telegram_owner

router = APIRouter()


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

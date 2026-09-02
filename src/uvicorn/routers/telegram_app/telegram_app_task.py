from fastapi import APIRouter, Request

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_depend import TASK_DEPEND_DONE_STATES, task_depend_of
from src.project.task.task_metadata import task_metadata_row_apply
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

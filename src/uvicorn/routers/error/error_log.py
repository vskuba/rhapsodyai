"""Ручки журнала ошибок: вкладка «Журнал» на странице трасс.

Страница трасс (`/admin/workflow_trace`) отвечает на вопрос «что делал движок
workflow». Вкладка «Журнал» отвечает на соседний и более общий: **«что вообще
ломалось на установке»** — падения роутеров, воркеров, кронджобов, телеграм-бота.
Раньше ответ лежал в `docker logs` четырёх контейнеров и в `app.log` внутри них.

Хранение, отпечаток повтора и правила чистки — `src/error/error_log.py`; сюда
ошибки попадают сами, через обработчик корневого логгера
(`src/error/error_log_handler.py`).
"""

from fastapi import APIRouter, Depends

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.error.error_log import (ERROR_LOG_PAGE, error_log_clear, error_log_delete,
                                 error_log_rows, error_log_trim)

router = APIRouter(prefix='/api/error_log', tags=['error_log'])


@router.get('', include_in_schema=False)
async def error_log_list(source: str = '', level: str = '', q: str = '',
                         page: int = 1, per_page: int = ERROR_LOG_PAGE,
                         user=Depends(AuthChecker([AuthPermission.ERROR_LOG_VIEW]))):
    """Страница журнала — свежее сверху.

    Args:
        source: чей процесс (`uvicorn`, `worker`, `telegram`, `cronjob`). Пусто — любой.
        level: `ERROR` или `CRITICAL`. Пусто — любой.
        q: подстрока в тексте ошибки, в трассировке или в имени логгера.
        page, per_page: страница и её размер.

    Returns:
        dict: `result` — `rows`, `total`, `page`, `pages`, `sources`.

    ⚠ Заодно чистит записи старше `ERROR_LOG_KEEP_DAYS`. Отдельного расписания у
    чистки нет намеренно — так же чистится трасса workflow, при показе списка.
    """
    await error_log_trim()

    return {'result': await error_log_rows(source=source, level=level, q=q,
                                           page=page, per_page=per_page)}


@router.delete('/{error_id}', include_in_schema=False)
async def error_log_remove(error_id: int,
                           user=Depends(AuthChecker([AuthPermission.ERROR_LOG_DELETE]))):
    """Убирает одну запись — разобрались и больше не хотим её видеть.

    Повторный вызов не ошибка: результат тот же — записи нет.
    """
    return {'result': {'deleted': await error_log_delete(error_id)}}


@router.delete('', include_in_schema=False)
async def error_log_remove_all(source: str = '',
                               user=Depends(AuthChecker([AuthPermission.ERROR_LOG_DELETE]))):
    """Чистит журнал целиком либо по одному источнику.

    Args:
        source: чей процесс убрать. Пусто — все.
    """
    return {'result': {'deleted': await error_log_clear(source)}}

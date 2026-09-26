"""Ручки журнала установки: страница «Журнал», подвкладка «Ошибки».

Страница `/admin/journal` отвечает на вопрос «что происходило на установке».
Сегодня всё, что в журнал попадает, — это сбои: падения роутеров, воркеров,
кронджобов, телеграм-бота. Раньше ответ лежал в `docker logs` четырёх
контейнеров и в `app.log` внутри них.

⚠ Подвкладка с другим предметом (события, походы наружу) принесёт **свои**
ручки: общей «дай журнал» здесь нет намеренно — у разных предметов разные поля
и разные отборы, и одна лента утопила бы один в другом.

Хранение, отпечаток повтора и правила чистки — `src/journal/journal.py`; записи
попадают туда сами, через обработчик корневого логгера
(`src/journal/journal_handler.py`).
"""

from fastapi import APIRouter, Depends

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.journal.journal import (JOURNAL_PAGE, journal_clear, journal_delete,
                                 journal_rows, journal_trim)

router = APIRouter(prefix='/api/journal', tags=['journal'])


@router.get('', include_in_schema=False)
async def journal_list(source: str = '', level: str = '', q: str = '',
                       page: int = 1, per_page: int = JOURNAL_PAGE,
                       user=Depends(AuthChecker([AuthPermission.JOURNAL_VIEW]))):
    """Страница журнала — свежее сверху.

    Args:
        source: чей процесс (`uvicorn`, `worker`, `telegram`, `cronjob`). Пусто — любой.
        level: `ERROR` или `CRITICAL`. Пусто — любой.
        q: подстрока в тексте записи, в трассировке или в имени логгера.
        page, per_page: страница и её размер.

    Returns:
        dict: `result` — `rows`, `total`, `page`, `pages`, `sources`.

    ⚠ Заодно чистит записи старше `JOURNAL_KEEP_DAYS`. Отдельного расписания у
    чистки нет намеренно — так же чистится трасса workflow, при показе списка.
    """
    await journal_trim()

    return {'result': await journal_rows(source=source, level=level, q=q,
                                         page=page, per_page=per_page)}


@router.delete('/{record_id}', include_in_schema=False)
async def journal_remove(record_id: int,
                         user=Depends(AuthChecker([AuthPermission.JOURNAL_DELETE]))):
    """Убирает одну запись — разобрались и больше не хотим её видеть.

    Повторный вызов не ошибка: результат тот же — записи нет.
    """
    return {'result': {'deleted': await journal_delete(record_id)}}


@router.delete('', include_in_schema=False)
async def journal_remove_all(source: str = '',
                             user=Depends(AuthChecker([AuthPermission.JOURNAL_DELETE]))):
    """Чистит журнал целиком либо по одному источнику.

    Args:
        source: чей процесс убрать. Пусто — все.
    """
    return {'result': {'deleted': await journal_clear(source)}}

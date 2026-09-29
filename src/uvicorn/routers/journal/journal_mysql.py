"""Ручки журнала запросов к базе: страница «Журнал», подвкладка «MySQL».

Предмет у подвкладки свой, поэтому и ручки свои: у запросов другие поля
(счётчики, время, строки) и другие отборы (сортировка по цене), и общая «дай
журнал» утопила бы один предмет в другом. Так и задумано — см. шапку
`src/uvicorn/routers/journal/journal.py`.

Хранение, накопление и правила чистки — `src/journal/journal_mysql.py`; сам счёт
идёт в общем слое (`py_modules/mysql_/mysql_watch.py`) и в код приложения не
заглядывает.

⚠ Права те же, что у подвкладки ошибок (`journal:view` / `journal:delete`):
раздел один, страница одна, и «одна подвкладка открылась, вторая ответила 403»
читалось бы как поломка.

⚠⚠ **Этот роутер подключается РАНЬШЕ соседнего** (`main_uvicorn.py`). У того
объявлено `DELETE /api/journal/{record_id}`, и подключись он первым — на
`DELETE /api/journal/mysql` FastAPI попытался бы прочитать «mysql» номером
записи и ответил бы 422 вместо чистки.
"""

from fastapi import APIRouter, Depends

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.journal.journal_mysql import (JOURNAL_MYSQL_PAGE, journal_mysql_clear,
                                       journal_mysql_delete, journal_mysql_flush,
                                       journal_mysql_rows, journal_mysql_trim)

router = APIRouter(prefix='/api/journal/mysql', tags=['journal'])


@router.get('', include_in_schema=False)
async def journal_mysql_list(source: str = '', q: str = '', order: str = 'total_ms',
                             page: int = 1, per_page: int = JOURNAL_MYSQL_PAGE,
                             user=Depends(AuthChecker([AuthPermission.JOURNAL_VIEW]))):
    """Страница журнала запросов — самое дорогое сверху.

    Args:
        source: чей процесс (`uvicorn`, `worker`, `telegram`, `cronjob`). Пусто — любой.
        q: подстрока в тексте запроса или в его значениях.
        order: чем сортировать — `total_ms`, `max_ms`, `avg_ms`, `hits`, `rows`, `last_at`.
        page, per_page: страница и её размер.

    Returns:
        dict: `result` — `rows`, `total`, `page`, `pages`, `sources`, `orders`,
        `enabled`, `totals`.

    ⚠ Перед выдачей сбрасывает накопленное этим процессом (`journal_mysql_flush`):
    иначе человек, открывший страницу ради «что происходит прямо сейчас», видел
    бы картину получасовой давности плюс-минус такт сброса. Соседние процессы
    (воркеры, бот) сбрасывают своё сами, по своему такту.

    ⚠ Заодно чистит строки старше `JOURNAL_MYSQL_KEEP_DAYS`. Отдельного
    расписания у чистки нет намеренно — так же чистится подвкладка ошибок.
    """
    await journal_mysql_flush()
    await journal_mysql_trim()

    return {'result': await journal_mysql_rows(source=source, q=q, order=order,
                                               page=page, per_page=per_page)}


@router.delete('/{record_id}', include_in_schema=False)
async def journal_mysql_remove(record_id: int,
                               user=Depends(AuthChecker([AuthPermission.JOURNAL_DELETE]))):
    """Убирает одну строку. Повторный вызов не ошибка: результат тот же."""
    return {'result': {'deleted': await journal_mysql_delete(record_id)}}


@router.delete('', include_in_schema=False)
async def journal_mysql_remove_all(source: str = '',
                                   user=Depends(AuthChecker([AuthPermission.JOURNAL_DELETE]))):
    """Обнуляет счётчики целиком либо по одному процессу.

    Args:
        source: чей процесс убрать. Пусто — все.

    Здесь это обычный ход, а не крайняя мера: счётчики копятся с начала времён, и
    после правки запроса старые числа мешают увидеть, стало ли лучше.
    """
    return {'result': {'deleted': await journal_mysql_clear(source)}}

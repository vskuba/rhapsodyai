"""Ручки страницы «Тесты → E2E»: прогоны, их строки и кадры.

Страница `/admin/e2e` отвечает на вопрос «как выглядел интерфейс на последнем
прогоне и что в нём разъехалось». Читает она таблицу `test_e2e`
(`src/e2e/e2e.py`), кадры лежат файлами (`src/e2e/e2e_shot.py`).

⚠ Кадр отдаётся по **номеру строки**, а не по пути: путь берётся из базы.
Присланный путь не спасает никакая проверка — см. шапку `e2e_shot.py`.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.e2e.e2e import e2e_row_get, e2e_run_list, e2e_run_rows
from src.e2e.e2e_shot import e2e_shot_path
from src.worker.e2e_worker import e2e_worker_enqueue, e2e_worker_running

router = APIRouter(prefix='/api/e2e', tags=['e2e'])


@router.get('/run', include_in_schema=False)
async def e2e_run_list_route(limit: int = 30,
                             user=Depends(AuthChecker([AuthPermission.E2E_VIEW]))):
    """Список прогонов — свежий сверху.

    Args:
        limit: сколько прогонов вернуть.

    Returns:
        dict: `result` — список карточек прогона (`run_uuid`, `started_at`,
        `tests`, `failed`, `errored`, `status`).
    """
    return {'result': await e2e_run_list(limit=limit)}


@router.post('/run', include_in_schema=False)
async def e2e_run_start_route(user=Depends(AuthChecker([AuthPermission.E2E_RUN]))):
    """Прогнать случаи сейчас, не дожидаясь ночного расписания.

    Returns:
        dict: `result` — `started`, `job_id`, `reason`.

    ⚠⚠ Работа уезжает в очередь, а ручка отвечает сразу: прогон длится минуты,
    и держать на нём обработчик запроса нельзя — браузер оборвёт его по своему
    таймауту, а работа останется идти в осиротевшем обработчике.

    ⚠ Второй прогон не заводится, пока идёт первый (single-flight): десять
    нажатий кнопки иначе дают десять браузеров на одной машине.
    """
    return {'result': e2e_worker_enqueue()}


@router.get('/run/status', include_in_schema=False)
async def e2e_run_status_route(user=Depends(AuthChecker([AuthPermission.E2E_VIEW]))):
    """Идёт ли прогон прямо сейчас — чтобы страница знала, ждать ей или нет.

    ⚠ Стоит **выше** `/run/{run_uuid}` намеренно: иначе FastAPI отдаст этот
    адрес обработчику с параметром, и `status` приедет туда как имя прогона.
    """
    return {'result': {'running': e2e_worker_running()}}


@router.get('/run/{run_uuid}', include_in_schema=False)
async def e2e_run_get_route(run_uuid: str,
                            user=Depends(AuthChecker([AuthPermission.E2E_VIEW]))):
    """Один прогон целиком: карточка и строки тестов с областями.

    Args:
        run_uuid: метка прогона; `last` — самый свежий.
    """
    return {'result': await e2e_run_rows('' if run_uuid == 'last' else run_uuid)}


@router.get('/row/{row_id}', include_in_schema=False)
async def e2e_row_get_route(row_id: int,
                            user=Depends(AuthChecker([AuthPermission.E2E_VIEW]))):
    """Одна строка теста — кадр, области, консоль."""
    row = await e2e_row_get(row_id)
    if not row:
        raise HTTPException(status_code=404, detail='Строка теста не найдена')
    return {'result': row}


@router.get('/shot/{row_id}', include_in_schema=False)
async def e2e_shot_route(row_id: int, plain: int = 0,
                         user=Depends(AuthChecker([AuthPermission.E2E_VIEW]))):
    """Кадр строки теста картинкой.

    Args:
        row_id: номер строки в `test_e2e`.
        plain: 1 — кадр без рамок областей (рамка села поверх дефекта).
    """
    row = await e2e_row_get(row_id)
    if not row:
        raise HTTPException(status_code=404, detail='Строка теста не найдена')

    relative = row.get('shot_plain_path') if plain else row.get('shot_path')
    path = e2e_shot_path(relative or '')
    if not path:
        raise HTTPException(status_code=404, detail='Кадр не найден')

    return FileResponse(path, media_type='image/png')

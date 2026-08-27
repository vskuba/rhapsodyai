"""Ручка автора сценариев: цель словами на входе, готовый сценарий на выходе.

Логика цикла — в `browser_author_run.py`; здесь только права и коды ответа.
Ручка длинная по времени (несколько витков с LLM и прогонами в браузере), поэтому
её держат отдельно от быстрого CRUD сценариев: у клиента к ней свой таймаут.

Код 200 приходит и на недостигнутой цели: автор всё равно вернёт написанное,
журнал витков и причину остановки — по ним видно, чинить промпт или формулировку
цели. Ошибка запроса — это когда контейнер-браузер недоступен или задание не
проходит схему.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.uvicorn.routers.browser.browser_author_run import BrowserAuthorRequest, browser_author_run_browser_author_run

router = APIRouter(prefix='/api/browser/scenario', tags=['browser'])


@router.post('/author')
async def browser_author_post(data: BrowserAuthorRequest,
                              user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Пишет сценарий под цель и сохраняет его: `active`, если прошёл проверку с нуля."""
    try:
        result = await browser_author_run_browser_author_run(data, user_id=user.user_id)
    except HTTPException:
        raise
    except Exception as e:
        # Сюда доходят только сбои окружения — контейнер не ответил, LLM не
        # настроена. Всё, что случилось внутри цикла, автор возвращает результатом.
        raise HTTPException(status_code=502, detail=f'автор сценария не отработал: {e}')

    return {'result': result}

from fastapi import APIRouter, Depends, HTTPException, Request, status

from net_.net_private import net_private_request
from src.cronjob.cronjob import Cronjob, CronjobJsonRequest


def cronjob_require_private(request: Request) -> None:
    """Пустить в `/cronjob` только изнутри: петля или частная сеть, без публичных прокси-хопов.

    ⚠ Вторая линия: первая — Caddy (403 на публичном хосте, :8090 только из docker-сети)
    и порты uvicorn на 127.0.0.1. Ручка в `public_paths` мидлвари, сессии не требует —
    поэтому без этой проверки её открывает одна ошибка в конфиге прокси.
    """
    client_host = request.client.host if request.client else ''
    if not net_private_request(client_host, request.headers.get('x-forwarded-for')):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Forbidden')


router = APIRouter(dependencies=[Depends(cronjob_require_private)])


@router.post("/cronjob")
async def cronjob_default(json_request: CronjobJsonRequest):
    result = await Cronjob(json_request).execute()
    if result.status == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.error_message)
    return result

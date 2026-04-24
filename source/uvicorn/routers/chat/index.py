from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi import Response
from config.config import config_get

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def default():
    with open(config_get('DATA_DIR') + '/' + config_get('UVICORN_DIR') +"/chat/index.html", "r", encoding="utf-8") as f:
        return f.read()


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)  # 204 No Content

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi import Response

from queue_.queue_ import queue_get_all

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def default(request: Request):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/chat.html"
    )


@router.get("/admin/agent", response_class=HTMLResponse)
async def default(request: Request):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/agent.html"
    )


@router.get("/admin/queue", response_class=HTMLResponse)
async def queue_status_ui(request: Request):
    queues = queue_get_all()

    # Генерируем простые строки таблицы
    rows = ""
    for name, q in queues.items():
        size = q.qsize() if hasattr(q, 'qsize') else "N/A"
        rows += f"<tr><td>{name}</td><td><b>{size}</b></td></tr>"

    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/queue.html",
        {
            "rows": rows
        }
    )


@router.get("/admin/converter/text-to-fact", response_class=HTMLResponse)
async def default(request: Request):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/converter_text_to_fact.html"
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)  # 204 No Content

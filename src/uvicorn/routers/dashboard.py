from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi import Response

from queue_.queue_ import queue_get_all
from src.auth.auth import get_current_user
from src.auth.auth_session import AuthSession

router = APIRouter()


async def require_auth(request: Request) -> AuthSession:
    """Dependency that requires authentication for HTML routes.
    Redirects to login if not authenticated (401), re-raises 403."""
    try:
        user = await get_current_user(request)
        return user
    except HTTPException as e:
        # Only redirect on 401 (not authenticated)
        # Let 403 (forbidden) and other errors propagate
        if e.status_code == 401:
            raise HTTPException(status_code=302, detail="Not authenticated", headers={"Location": "/login"})
        raise


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "login.html"
    )


@router.get("/", response_class=HTMLResponse)
async def default(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/chat.html"
    )


@router.get("/admin/node", response_class=HTMLResponse)
async def node(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/node.html"
    )


@router.get("/admin/agent", response_class=HTMLResponse)
async def agent(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/agent.html"
    )


@router.get("/admin/session", response_class=HTMLResponse)
async def session(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/session.html"
    )


@router.get("/admin/user", response_class=HTMLResponse)
async def user_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/user.html"
    )


@router.get("/admin/cabinet", response_class=HTMLResponse)
async def cabinet_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/cabinet.html"
    )


@router.get("/admin/workflow", response_class=HTMLResponse)
async def workflow_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/workflow.html"
    )


@router.get("/admin/fact", response_class=HTMLResponse)
async def fact_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/fact.html"
    )


@router.get("/admin/fact_collection", response_class=HTMLResponse)
async def fact_collection_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/fact_collection.html"
    )


@router.get("/admin/tool", response_class=HTMLResponse)
async def tool_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/tool.html"
    )


@router.get("/admin/variable", response_class=HTMLResponse)
async def workflow_variable_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/agent_workflow_variable.html"
    )


@router.get("/admin/queue", response_class=HTMLResponse)
async def queue_page(request: Request, user: AuthSession = Depends(require_auth)):
    queues = queue_get_all()

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
async def converter_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/converter_text_to_fact.html"
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

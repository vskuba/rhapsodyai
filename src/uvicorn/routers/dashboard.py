import traceback

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi import Response
from jinja2 import TemplateNotFound

from logging_.logging_ import logger_info
from queue_.queue_ import queue_get_all
from src.auth.auth import get_current_user
from src.auth.auth_session import AuthSession

router = APIRouter()

template_role_mapping: dict = {
    '/admin/variable': [
        {
            'role': {'manager_dating', 'manager_dating_junior'},
            'template': 'custom/dating/agent_workflow_variable_public.html'
        }
    ],
}


def get_template_for_role(path: str, role: str, value: str, jinja2_template) -> str:
    """Return the template path for a given route and role, or None if not found."""
    for mapping in template_role_mapping.get(path, []):
        if role in mapping['role']:
            template_path = mapping['template']
            try:
                if jinja2_template:
                    jinja2_template.env.get_template(template_path)
                return template_path
            except TemplateNotFound as e:
                backtrace = traceback.format_exc()
                logger_info(
                    f"❌ Ошибка, кастомный шаблон '{template_path}' не найден: {e}."
                    f"Полный стек вызовов:\n{backtrace}"
                )
    return value


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
async def agent_workflow_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/agent_workflow.html"
    )


@router.get("/admin/workflow_trace", response_class=HTMLResponse)
async def workflow_trace_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/workflow_trace.html"
    )


@router.get("/admin/llm", response_class=HTMLResponse)
async def llm_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/llm.html"
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


@router.get("/admin/plan", response_class=HTMLResponse)
async def plan_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/plan.html"
    )


@router.get("/admin/planning", response_class=HTMLResponse)
async def planning_page(request: Request, user: AuthSession = Depends(require_auth)):
    from py_modules.setting_.setting_ import setting_get
    tz_offset = await setting_get('timezone', '+0')
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/planning.html",
        {"tz_offset": str(tz_offset or '+0')},
    )


@router.get("/admin/developing", response_class=HTMLResponse)
async def developing_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/developing.html",
    )


@router.get("/admin/planning-phase-source", response_class=HTMLResponse)
async def planning_phase_source_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/planning_phase_source.html",
    )


@router.get("/admin/planning-blocks", response_class=HTMLResponse)
async def planning_blocks_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/planning_blocks.html",
    )


@router.get("/admin/task", response_class=HTMLResponse)
async def task_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/task.html",
    )


@router.get("/admin/design", response_class=HTMLResponse)
async def design_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/design.html",
    )


@router.get("/admin/tool", response_class=HTMLResponse)
async def tool_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/tool.html"
    )


@router.get("/admin/role", response_class=HTMLResponse)
async def role_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/role.html"
    )


@router.get("/admin/seed", response_class=HTMLResponse)
async def seed_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/seed.html"
    )


@router.get("/admin/backup", response_class=HTMLResponse)
async def backup_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/backup.html"
    )


@router.get("/admin/variable", response_class=HTMLResponse)
async def workflow_variable_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        get_template_for_role(
            request.url.path,
            user.role,
            "admin/agent_workflow_variable_public.html",
            request.app.state.jinja2_template
        )
    )


@router.get("/admin/setting", response_class=HTMLResponse)
async def setting_page(request: Request, user: AuthSession = Depends(require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/setting.html"
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


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

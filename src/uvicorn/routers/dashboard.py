import traceback
import urllib.parse

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi import Response
from jinja2 import TemplateNotFound

from logging_.logging_ import logger_info
from queue_.queue_ import queue_get_all
from src.auth.auth import auth_get_current_user
from src.auth.auth_session import AuthSession

router = APIRouter()

template_role_mapping: dict = {
    '/admin/variable': [
        {
            'role': {'manager_dating', 'manager_dating_junior'},
            'template': 'custom/dating/node_variable.html'
        }
    ],
}


def dashboard_get_template_for_role(path: str, role: str, value: str, jinja2_template) -> str:
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


async def dashboard_require_auth(request: Request) -> AuthSession:
    """Dependency that requires authentication for HTML routes.
    Redirects to login if not authenticated (401), re-raises 403."""
    try:
        user = await auth_get_current_user(request)
        return user
    except HTTPException as e:
        # Only redirect on 401 (not authenticated)
        # Let 403 (forbidden) and other errors propagate
        if e.status_code == 401:
            next_path = request.url.path
            if request.url.query:
                next_path += '?' + request.url.query
            next_param = urllib.parse.quote(next_path, safe='')
            raise HTTPException(status_code=302, detail="Not authenticated",
                                headers={"Location": f"/login?next={next_param}"})
        raise


@router.get("/login", response_class=HTMLResponse)
async def dashboard_login_page(request: Request):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "login.html"
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard_default(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/chat.html"
    )


@router.get("/admin/node", response_class=HTMLResponse)
async def dashboard_node(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/node.html"
    )


@router.get("/admin/agent", response_class=HTMLResponse)
async def dashboard_agent(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/agent.html"
    )


@router.get("/admin/session", response_class=HTMLResponse)
async def dashboard_session(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/session.html"
    )


@router.get("/admin/user", response_class=HTMLResponse)
async def dashboard_user_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/user.html"
    )


@router.get("/admin/miniapp", response_class=HTMLResponse)
async def dashboard_miniapp_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/miniapp.html"
    )


@router.get("/admin/playwright", response_class=HTMLResponse)
async def dashboard_playwright_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/playwright.html"
    )


@router.get("/admin/cabinet", response_class=HTMLResponse)
async def dashboard_cabinet_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/cabinet.html"
    )


@router.get("/admin/workflow", response_class=HTMLResponse)
async def dashboard_agent_workflow_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/agent_workflow.html"
    )


@router.get("/admin/workflow_trace", response_class=HTMLResponse)
async def dashboard_workflow_trace_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/workflow_trace.html"
    )


@router.get("/admin/journal", response_class=HTMLResponse)
async def dashboard_journal_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    """
    Журнал установки — своей страницей, а не вкладкой внутри трасс.

    Предмет другой. Трассы отвечают на вопрос «что делал движок workflow»: запуски,
    шаги, токены. Журнал — «что происходило на установке» в целом. Общего у них
    только пункт меню «Логи».

    ⚠ **Журнал — раздел с подвкладками, а не один список.** Сейчас в нём одна,
    «Ошибки» (`.claude/docs/journal.md`); соседние по этому же вопросу
    добавляются кнопкой и панелью в шаблоне, без правки роутера.
    """
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/journal.html"
    )


@router.get("/admin/cronicle", response_class=HTMLResponse)
async def dashboard_cronicle_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    """Планировщик Cronicle: расписание, включатель и прогоны за сегодня.

    ⚠ Страница **не заменяет** панель Cronicle и не пытается: заведение событий,
    цепочки и веб-хуки остаются там. Здесь три вопроса, за которыми в чужую
    панель ходить не хочется: что запланировано, что сегодня отработало и как
    выключить событие на время.
    """
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/cronicle.html"
    )


@router.get("/admin/e2e", response_class=HTMLResponse)
async def dashboard_e2e_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    """E2E-проверки интерфейса: прогоны, их кадры и разъехавшиеся области.

    ⚠ «Тесты» — своя группа меню, а не подпункт «Логов». Предмет другой: журнал
    отвечает «что упало», а здесь — «что нарисовалось не так», и падения при этом
    нет ни одного. Соседние виды проверок добавляются сюда же, кнопкой и панелью.
    """
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/e2e.html"
    )


@router.get("/admin/llm", response_class=HTMLResponse)
async def dashboard_llm_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/llm.html"
    )


@router.get("/admin/fact", response_class=HTMLResponse)
async def dashboard_fact_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/fact.html"
    )


@router.get("/admin/fact_collection", response_class=HTMLResponse)
async def dashboard_fact_collection_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/fact_collection.html"
    )


@router.get("/admin/plan", response_class=HTMLResponse)
async def dashboard_plan_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/plan.html"
    )


@router.get("/admin/planning", response_class=HTMLResponse)
async def dashboard_planning_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    from setting_.setting_ import setting_get
    tz_offset = await setting_get('timezone', '+0')
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/planning.html",
        {"tz_offset": str(tz_offset or '+0')},
    )


@router.get("/admin/project", response_class=HTMLResponse)
async def dashboard_project_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project.html",
    )


@router.get("/admin/developing", response_class=HTMLResponse)
async def dashboard_developing_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/developing.html",
    )


@router.get("/admin/planning-phase-source", response_class=HTMLResponse)
async def dashboard_planning_phase_source_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/planning_phase_source.html",
    )


@router.get("/admin/task", response_class=HTMLResponse)
async def dashboard_task_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/task.html",
    )


@router.get("/admin/task/diff", response_class=HTMLResponse)
async def dashboard_task_diff_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    """Разница главной ветки и ветки подзадачи. Номер подзадачи — в `?task=<id>`."""
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/task_diff.html",
    )


@router.get("/admin/browser", response_class=HTMLResponse)
async def dashboard_browser_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    """Список заведённых сайтов контейнера-браузера (`browser.md`)."""
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/browser.html",
        {"browser_page": "sites"},
    )


@router.get("/admin/browser/error", response_class=HTMLResponse)
async def dashboard_browser_error_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    """
    Ошибки браузера — своей страницей, а не вкладкой внутри сайта.

    Ошибки к сайту не привязаны: их шлют клиенты — соседние проекты, которые ходят в
    браузер и сценарии по API. Сайт в такой записи бывает, но бывает и нет, и внутри
    страницы одного сайта они выглядели как «ошибки этого сайта», хотя фильтра по
    нему там никогда не было.

    Ход выполнения сценария живёт не здесь, а на вкладке «Журналы»: там трасса по
    шагам, а здесь — то, о чём сообщил чужой проект.

    Шаблон тот же, что у сайтов, — разделён параметром, а не копией.
    """
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/browser.html",
        {"browser_page": "error"},
    )


@router.get("/admin/browser/proxy", response_class=HTMLResponse)
async def dashboard_browser_proxy_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    """
    Выходные адреса — своей страницей, а не вкладкой внутри сайта.

    ⚠ **Реестр общий на установку.** Прокси не принадлежит сайту-закладке: через
    один и тот же канал ходит и Chromium к любому сайту, и соседний проект своими
    запросами. Вкладка внутри «Сайта» обещала обратное — что выход настраивается
    для выбранного вверху сайта, — а на деле при переключении сайтов показывала
    один и тот же список. Человек, менявший сайт и видевший те же строки, законно
    решал, что страница сломана.

    Тот же довод и то же решение, что у ошибок (`/admin/browser/error`): предмет не
    привязан к сайту — значит и страница своя.

    Шаблон тот же, что у сайтов, — разделён параметром, а не копией.
    """
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/browser.html",
        {"browser_page": "proxy"},
    )


@router.get("/admin/browser/site", response_class=HTMLResponse)
async def dashboard_browser_site_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    """
    Работа по одному сайту: сессии, сценарии, workflow, ошибки.

    Шаблон тот же, что у списка сайтов, — разделён параметром, а не копией.
    Страница на четыре тысячи строк, и второй её экземпляр разошёлся бы с первым
    при первой же правке.
    """
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/browser.html",
        {"browser_page": "site"},
    )


@router.get("/admin/design", response_class=HTMLResponse)
async def dashboard_design_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/design.html",
    )


@router.get("/admin/tool", response_class=HTMLResponse)
async def dashboard_tool_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/tool.html"
    )


@router.get("/admin/team", response_class=HTMLResponse)
async def dashboard_team_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/project/team.html"
    )


@router.get("/admin/role", response_class=HTMLResponse)
async def dashboard_role_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/role.html"
    )


@router.get("/admin/seed", response_class=HTMLResponse)
async def dashboard_seed_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/seed.html"
    )


@router.get("/admin/backup", response_class=HTMLResponse)
async def dashboard_backup_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/backup.html"
    )


@router.get("/admin/variable", response_class=HTMLResponse)
async def dashboard_workflow_variable_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        dashboard_get_template_for_role(
            request.url.path,
            user.role,
            "admin/node_variable.html",
            request.app.state.jinja2_template
        )
    )


@router.get("/admin/setting", response_class=HTMLResponse)
async def dashboard_setting_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
    return request.app.state.jinja2_template.TemplateResponse(
        request,
        "admin/setting.html"
    )


@router.get("/admin/queue", response_class=HTMLResponse)
async def dashboard_queue_page(request: Request, user: AuthSession = Depends(dashboard_require_auth)):
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
async def dashboard_favicon():
    return Response(status_code=204)

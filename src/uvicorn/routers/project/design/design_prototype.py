import asyncio
import uuid

from fastapi import APIRouter, Depends, Request, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.agent_repository import AgentRepository
from src.uvicorn.routers.project.project_common import _tools_load

_AUTO_BLOCKS_AGENT_NAME = 'planning_wireframe_composer'
_AUTO_BLOCKS_TIMEOUT = 120.0

router = APIRouter()


@router.get("/design/prototype/pages/{project_id}")
async def design_prototype_pages(
    request: Request,
    project_id: int,
    user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, description, page_type, state_id, roles "
            "FROM project_design_prototype_page WHERE project_id = %s ORDER BY state_id, order_index, id",
            (project_id,)
        )
        rows = await db.fetchall()
    return {"pages": [dict(r) for r in rows]}


@router.put("/design/prototype/page/{page_id}")
async def design_prototype_page_update(
    request: Request,
    page_id: int,
    data: dict,
    user=Depends(AuthChecker([AuthPermission.DESIGN_CREATE])),
):
    fields = {}
    for f in ('name', 'description', 'page_type', 'tags', 'roles'):
        if f in data:
            val = data[f]
            fields[f] = str(val).strip()[:500] if val is not None else None
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    set_clause = ', '.join(f'`{k}` = %s' for k in fields)
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_design_prototype_page SET {set_clause} WHERE id = %s",
            (*fields.values(), page_id)
        )
        await db.execute(
            "SELECT id, name, description, page_type, tags, roles FROM project_design_prototype_page WHERE id = %s",
            (page_id,)
        )
        row = await db.fetchone()
        await db.connection.commit()
    return {"result": dict(row) if row else None}


@router.get("/design/prototype/page/{page_id}/render")
async def design_prototype_page_render(
    request: Request,
    page_id: int,
    user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW])),
):
    """Assembles page HTML from its block widgets for iframe preview."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT p.name AS page_name, p.state, "
            "       b.name AS block_name, "
            "       w.css, w.html "
            "FROM project_design_prototype_page_block pb "
            "JOIN project_design_prototype_page p ON p.id = pb.page_id "
            "JOIN project_design_ui_block b ON b.id = pb.block_id "
            "LEFT JOIN project_design_prototype_widget w ON w.id = pb.widget_id "
            "WHERE pb.page_id = %s "
            "ORDER BY pb.section, pb.order_index",
            (page_id,)
        )
        rows = await db.fetchall()

    if not rows:
        return {"html": "<body style='font-family:sans-serif;padding:40px;color:#666'>Страница пуста</body>"}

    css_parts = []
    html_parts = []
    for r in rows:
        if r.get("css"):
            css_parts.append(str(r["css"]))
        if r.get("html"):
            html_parts.append(f'<!-- {r["block_name"]} -->\n{r["html"]}')

    combined = (
        "<!DOCTYPE html><html><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<link href='https://cdn.jsdelivr.net/npm/tailwindcss@2/dist/tailwind.min.css' rel='stylesheet'>"
        f"<style>{''.join(css_parts)}</style>"
        "</head><body>"
        + "\n".join(html_parts)
        + "</body></html>"
    )
    return {"html": combined}


@router.post("/design/prototype/page/{page_id}/auto-blocks")
async def design_page_auto_blocks(
    request: Request,
    page_id: int,
    data: dict = None,
    user=Depends(AuthChecker([AuthPermission.DESIGN_CREATE])),
):
    """Агент planning_wireframe_composer назначает блоки проекта по секциям страницы."""
    project_id = int((data or {}).get('project_id') or 0)
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id FROM project_design_prototype_page WHERE id = %s AND project_id = %s",
            (page_id, project_id)
        )
        if not await db.fetchone():
            raise HTTPException(status_code=404, detail="Page not found")

    agent = await AgentRepository().find_one_by({'name': _AUTO_BLOCKS_AGENT_NAME})
    if not agent:
        return {'error': f'Agent {_AUTO_BLOCKS_AGENT_NAME!r} not found'}

    entities_llm = await ai_llm_node_get(agent['node_id'])
    if not entities_llm:
        return {'error': 'LLM не настроены для агента'}

    workflow_data = await ai_workflow_load(agent['workflow_id'])
    session_uuid = str(uuid.uuid4())
    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user='',
            user_id=user.user_id,
            entity_agent=agent,
            session_uuid=session_uuid,
            workflow_id=agent['workflow_id'],
        ),
        'planning_page_id': str(page_id),
        'planning_project_id': str(project_id),
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    agent_manager = request.app.state.agent_manager
    framework_model = await agent_manager.framework_model_create({
        'entity_agent': agent,
        'entities_llm': entities_llm,
        'workflow_steps': workflow_data['steps'],
        'workflow_variables': wf_vars,
        'prompt_user': '',
        'user_id': user.user_id,
        'companion_id': None,
        'session_uuid': session_uuid,
        'tools': await _tools_load(),
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)
    try:
        await asyncio.wait_for(future, timeout=_AUTO_BLOCKS_TIMEOUT)
    except asyncio.TimeoutError:
        pass

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT pb.block_id, b.name AS block_name, pb.order_index, pb.section "
            "FROM project_design_prototype_page_block pb "
            "JOIN project_design_ui_block b ON b.id = pb.block_id "
            "WHERE pb.page_id = %s ORDER BY pb.section, pb.order_index",
            (page_id,)
        )
        rows = await db.fetchall()

    return {'result': [dict(r) for r in (rows or [])]}

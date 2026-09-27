import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, Request, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/design/ui-components")
async def design_ui_components_list(
    request: Request,
    user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, description, variants, sizes, states, tailwind_example, tags "
            "FROM project_design_ui_component ORDER BY name ASC"
        )
        rows = await db.fetchall()
    return {"result": rows}


@router.get("/design/ui-components/{component_id}")
async def design_ui_component_get(
    request: Request,
    component_id: int,
    user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, description, variants, sizes, states, tailwind_example, tags "
            "FROM project_design_ui_component WHERE id = %s LIMIT 1",
            (component_id,)
        )
        row = await db.fetchone()
    return {"result": row}


@router.post("/design/ui-components")
async def design_ui_component_create(
    request: Request,
    data: dict,
    user=Depends(AuthChecker([AuthPermission.DESIGN_CREATE])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_design_ui_component "
            "(name, description, variants, sizes, states, tailwind_example, tags) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                data.get("name", ""),
                data.get("description", ""),
                data.get("variants", ""),
                data.get("sizes", ""),
                data.get("states", ""),
                data.get("tailwind_example", ""),
                data.get("tags", ""),
            )
        )
        component_id = db.lastrowid
    return {"result": component_id}


@router.put("/design/ui-components/{component_id}")
async def design_ui_component_update(
    request: Request,
    component_id: int,
    data: dict,
    user=Depends(AuthChecker([AuthPermission.DESIGN_UPDATE])),
):
    fields = ["name", "description", "variants", "sizes", "states", "tailwind_example", "tags"]
    updates = {f: data[f] for f in fields if f in data}
    if not updates:
        return {"result": 0}

    set_clause = ", ".join(f"`{k}` = %s" for k in updates)
    values = list(updates.values()) + [component_id]
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_design_ui_component SET {set_clause} WHERE id = %s",
            values
        )
        affected = db.rowcount
    return {"result": affected}


@router.delete("/design/ui-components/{component_id}")
async def design_ui_component_delete(
    request: Request,
    component_id: int,
    user=Depends(AuthChecker([AuthPermission.DESIGN_DELETE])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "DELETE FROM project_design_ui_component WHERE id = %s",
            (component_id,)
        )
        affected = db.rowcount
    if not affected:
        return {"status": "error", "message": "Компонент не найден"}
    return {"status": "success"}

# ─── Project States ──────────────────────────────────────────────────────────

@router.get("/design/states")
async def design_states_list(user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute("SELECT id, name, description FROM project_state ORDER BY id ASC")
        rows = await db.fetchall()
    return {"result": rows}


# ─── Design Tokens ───────────────────────────────────────────────────────────

@router.get("/design/tokens")
async def design_tokens_list(user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, title, description, tokens, created_at FROM project_design_token ORDER BY created_at DESC"
        )
        rows = await db.fetchall()
    for row in rows:
        if isinstance(row.get('tokens'), str):
            try:
                row['tokens'] = json.loads(row['tokens'])
            except Exception:
                row['tokens'] = {}
    return {"result": rows}


@router.post("/design/tokens")
async def design_tokens_create(data: dict, user=Depends(AuthChecker([AuthPermission.DESIGN_CREATE]))):
    tokens = data.get("tokens", {})
    tokens_str = json.dumps(tokens, ensure_ascii=False) if isinstance(tokens, dict) else tokens
    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_design_token (name, title, description, tokens) VALUES (%s, %s, %s, %s)",
            (data.get("name", ""), data.get("title", ""), data.get("description", ""), tokens_str)
        )
        new_id = db.lastrowid
        if hasattr(db, 'connection') and db.connection:
            await db.connection.commit()
    return {"result": new_id}


@router.delete("/design/tokens/{token_id}")
async def design_tokens_delete(token_id: int, user=Depends(AuthChecker([AuthPermission.DESIGN_DELETE]))):
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_design_token WHERE id = %s", (token_id,))
        if hasattr(db, 'connection') and db.connection:
            await db.connection.commit()
    return {"result": "ok"}


@router.post("/design/tokens/generate")
async def design_tokens_generate(data: dict, user=Depends(AuthChecker([AuthPermission.DESIGN_CREATE]))):
    project_description = str(data.get("description") or "").strip()
    name = str(data.get("name") or "generated").strip()
    title = str(data.get("title") or "Сгенерированные токены").strip()

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT a.id, a.name, a.title, a.node_id, a.workflow_id, a.workflow_variable "
            "FROM agent a WHERE a.name = 'design_tokens_manager' LIMIT 1"
        )
        entity_agent = await db.fetchone()
    if not entity_agent:
        raise HTTPException(status_code=503, detail="Агент design_tokens_manager не найден")

    entities_llm = await ai_llm_node_get(entity_agent['node_id'], output_type='text')
    if not entities_llm:
        raise HTTPException(status_code=503, detail="LLM не настроены")

    prompt = (
        f"Generate design tokens for this project: {project_description}"
        if project_description else
        "Generate a clean, modern, minimal design token set."
    )

    workflow_id = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)

    session_uuid = str(uuid.uuid4())
    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=prompt,
            user_id=user.user_id,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
        ),
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    agent_wv = entity_agent.get('workflow_variable') or '{}'
    try:
        wf_vars.update(json.loads(agent_wv))
    except Exception:
        pass

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    agent_manager = AiFrameworkAgentManager()
    framework_model = await agent_manager.framework_model_create({
        'entity_agent': entity_agent,
        'entities_llm': entities_llm,
        'workflow_steps': workflow_data['steps'],
        'workflow_variables': wf_vars,
        'prompt_user': prompt,
        'user_id': user.user_id,
        'session_uuid': session_uuid,
        'tools': {},
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=120.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Таймаут генерации токенов")

    try:
        tokens = json.loads(result_text)
    except Exception:
        raise HTTPException(status_code=502, detail="LLM вернул невалидный JSON токенов")

    tokens_str = json.dumps(tokens, ensure_ascii=False)
    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_design_token (name, title, description, tokens) VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE title=%s, description=%s, tokens=%s, updated_at=NOW()",
            (name, title, project_description or None, tokens_str,
             title, project_description or None, tokens_str)
        )
        new_id = db.lastrowid
        if hasattr(db, 'connection') and db.connection:
            await db.connection.commit()
    return {"result": {"id": new_id, "name": name, "title": title, "tokens": tokens}}


@router.get("/design/project/{project_id}/chips")
async def design_project_chips_get(
    project_id: int,
    user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT cloud_tags, entities FROM project WHERE id = %s LIMIT 1",
            (project_id,)
        )
        row = await db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Проект не найден")

    def _parse(val):
        if not val:
            return []
        try:
            result = json.loads(val)
            return result if isinstance(result, list) else []
        except Exception:
            return []

    return {
        "cloud_tags": _parse(row["cloud_tags"]),
        "entities": _parse(row["entities"]),
    }


@router.patch("/design/project/{project_id}/chips")
async def design_project_chips_update(
    project_id: int,
    data: dict,
    user=Depends(AuthChecker([AuthPermission.DESIGN_UPDATE])),
):
    fields, vals = [], []
    if "cloud_tags" in data:
        tags = data["cloud_tags"]
        if not isinstance(tags, list):
            raise HTTPException(status_code=422, detail="cloud_tags должен быть массивом")
        fields.append("cloud_tags = %s")
        vals.append(json.dumps(tags, ensure_ascii=False))
    if "entities" in data:
        ents = data["entities"]
        if not isinstance(ents, list):
            raise HTTPException(status_code=422, detail="entities должен быть массивом")
        fields.append("entities = %s")
        vals.append(json.dumps(ents, ensure_ascii=False))
    if not fields:
        raise HTTPException(status_code=422, detail="Нет полей для обновления")
    vals.append(project_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project SET {', '.join(fields)} WHERE id = %s",
            vals
        )
        if hasattr(db, 'connection') and db.connection:
            await db.connection.commit()
    return {"ok": True}


@router.post("/design/wireframe/compose/{project_id}")
async def design_wireframe_compose(
    project_id: int,
    data: dict = None,
    user=Depends(AuthChecker([AuthPermission.DESIGN_CREATE])),
):
    """Запускает агент planning_wireframe_composer для проекта (или одной страницы)."""
    page_id = int((data or {}).get('page_id') or 0)
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT a.id, a.name, a.title, a.node_id, a.workflow_id, a.workflow_variable "
            "FROM agent a WHERE a.name = 'planning_wireframe_composer' LIMIT 1"
        )
        entity_agent = await db.fetchone()
    if not entity_agent:
        raise HTTPException(status_code=503, detail="Агент planning_wireframe_composer не найден")

    entities_llm = await ai_llm_node_get(entity_agent['node_id'], output_type='text')
    if not entities_llm:
        raise HTTPException(status_code=503, detail="LLM не настроены для узла агента")

    workflow_id = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)

    session_uuid = str(uuid.uuid4())
    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=f"Compose wireframes for project {project_id}",
            user_id=user.user_id,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
        ),
        'planning_project_id': str(project_id),
        'planning_page_id': str(page_id),
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    agent_wv = entity_agent.get('workflow_variable') or '{}'
    try:
        wf_vars.update(json.loads(agent_wv))
    except Exception:
        pass

    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, path FROM tool WHERE id > 0')
        tool_rows = await db.fetchall()
    tools = {r['name'].strip(): r['path'].strip() for r in (tool_rows or []) if r.get('name') and r.get('path')}

    _skip_tools = {'planning_phase_save', 'planning_design_page_wireframe_save'}
    steps = [s for s in workflow_data['steps']
             if s.get('tool_name') not in _skip_tools
             and s.get('metadata', {}).get('tool_invoke', {}).get('tool_name') not in _skip_tools]

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    agent_manager = AiFrameworkAgentManager()
    framework_model = await agent_manager.framework_model_create({
        'entity_agent': entity_agent,
        'entities_llm': entities_llm,
        'workflow_steps': steps,
        'workflow_variables': wf_vars,
        'prompt_user': f"Compose wireframes for project {project_id}",
        'user_id': user.user_id,
        'session_uuid': session_uuid,
        'tools': tools,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        await asyncio.wait_for(future, timeout=180.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Таймаут генерации вайрфреймов")

    return {"result": "ok", "project_id": project_id}


@router.get("/design/ui-block-types")
async def design_ui_block_types_list(
    user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, title, description FROM project_design_ui_block_type ORDER BY title ASC"
        )
        rows = await db.fetchall()
    return {"result": rows}


@router.get("/design/ui-blocks")
async def design_ui_blocks_list(
    user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT b.id, b.name, b.description, b.stateless, b.tags, b.slot, b.slots, b.section, "
            "       b.width_min, b.height_min, b.type_id, t.name AS type_name "
            "FROM project_design_ui_block b "
            "LEFT JOIN project_design_ui_block_type t ON t.id = b.type_id "
            "ORDER BY b.name ASC"
        )
        rows = await db.fetchall()
    return {"result": rows}


@router.get("/design/ui-blocks/{block_id}")
async def design_ui_block_get(
    block_id: int,
    user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT b.id, b.name, b.description, b.stateless, b.tags, b.slot, b.slots, b.html, b.css, b.vars, "
            "       b.section, b.width_min, b.height_min, b.type_id, t.name AS type_name "
            "FROM project_design_ui_block b "
            "LEFT JOIN project_design_ui_block_type t ON t.id = b.type_id "
            "WHERE b.id = %s LIMIT 1",
            (block_id,)
        )
        row = await db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Блок не найден")
    return {"result": row}


@router.delete("/design/ui-blocks/{block_id}")
async def design_ui_block_delete(
    block_id: int,
    user=Depends(AuthChecker([AuthPermission.DESIGN_DELETE])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id FROM project_design_ui_block WHERE id = %s LIMIT 1",
            (block_id,)
        )
        row = await db.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Блок не найден")
        await db.execute("DELETE FROM project_design_ui_block WHERE id = %s", (block_id,))
        await db.connection.commit()
    return {"result": True}
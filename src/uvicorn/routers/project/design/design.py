import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, Request, HTTPException

import httpx

from config.config import config_get
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get, ai_llm_provider
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
        'companion_id': None,
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
        'companion_id': None,
        'session_uuid': session_uuid,
        'tools': tools,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        await asyncio.wait_for(future, timeout=180.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Таймаут генерации вайрфреймов")

    return {"result": "ok", "project_id": project_id}


@router.get("/design/ui-blocks")
async def design_ui_blocks_list(
    user=Depends(AuthChecker([AuthPermission.DESIGN_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, description, stateless, tags, slot, slots "
            "FROM project_design_ui_block ORDER BY name ASC"
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
            "SELECT id, name, description, stateless, tags, slot, slots, html, css, vars "
            "FROM project_design_ui_block WHERE id = %s LIMIT 1",
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
            "SELECT id FROM project_design_ui_block WHERE id = %s AND project_id IS NULL LIMIT 1",
            (block_id,)
        )
        row = await db.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Блок не найден")
        await db.execute("DELETE FROM project_design_ui_block WHERE id = %s", (block_id,))
        await db.connection.commit()
    return {"result": True}


@router.post("/design/page/{page_id}/auto-blocks")
async def design_page_auto_blocks(
    page_id: int,
    data: dict = None,
    user=Depends(AuthChecker([AuthPermission.DESIGN_CREATE])),
):
    """LLM назначает блоки проекта по секциям страницы. Не меняет wireframe-текст и grid_layout."""
    project_id = int((data or {}).get('project_id') or 0)
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT grid_layout FROM project_design_prototype_page WHERE id = %s AND project_id = %s",
            (page_id, project_id)
        )
        page_row = await db.fetchone()
        if not page_row:
            raise HTTPException(status_code=404, detail="Page not found")

        raw_gl = page_row.get('grid_layout')
        try:
            grid_layout = json.loads(raw_gl) if isinstance(raw_gl, str) else (raw_gl or [])
        except Exception:
            grid_layout = []
        if not grid_layout:
            grid_layout = [{'w': [100], 'h': 400}]

        await db.execute(
            "SELECT id, name, description FROM project_design_ui_block "
            "WHERE project_id = %s ORDER BY order_index",
            (project_id,)
        )
        block_rows = await db.fetchall()

    if not block_rows:
        return {'result': []}

    # Build section labels from grid
    sections = []
    for li, level in enumerate(grid_layout):
        for ci in range(len(level.get('w') or [100])):
            sections.append(f"{li + 1}.{ci + 1}")

    blocks_info = '\n'.join(
        f"{b['id']}: {b['name']}" + (f" — {(b.get('description') or '')[:80]}" if b.get('description') else '')
        for b in block_rows
    )

    prompt = (
        f"Distribute these UI blocks across wireframe sections.\n\n"
        f"Sections: {', '.join(sections)}\n\n"
        f"Blocks:\n{blocks_info}\n\n"
        f"Rules:\n"
        f"- Every block must appear exactly once.\n"
        f"- Fill all sections roughly equally.\n"
        f"- order_index starts at 0 within each section.\n\n"
        f"Respond with ONLY a JSON array, no markdown:\n"
        f'[{{"block_id": 1, "section": "1.1", "order_index": 0}}, ...]'
    )

    entities_llm = await ai_llm_node_get(None, output_type='text')
    if not entities_llm:
        raise HTTPException(status_code=503, detail="No LLM configured")

    llm = entities_llm[0]
    provider = ai_llm_provider(llm['name'])
    base_url = (config_get(provider.upper() + '_API_URL') or '').rstrip('/')
    api_key = config_get(provider.upper() + '_API_KEY') or ''
    model_name = llm['name'][len(provider) + 1:]

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "Output only valid JSON, no prose."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
            }
        )
        resp.raise_for_status()
        raw = resp.json()['choices'][0]['message']['content'].strip()

    if raw.startswith('```'):
        raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

    try:
        assignments = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="LLM returned invalid JSON")

    def _sec_to_flat(label: str) -> int:
        try:
            parts = label.split('.')
            lv = min(int(parts[0]) - 1, len(grid_layout) - 1)
            co = min(int(parts[1]) - 1, len(grid_layout[lv].get('w') or [100]) - 1)
            return sum(len(grid_layout[l].get('w') or [100]) for l in range(lv)) + co
        except Exception:
            return 0

    block_name_map = {b['id']: b['name'] for b in block_rows}

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_design_prototype_page_block WHERE page_id = %s", (page_id,))
        result_blocks = []
        for item in (assignments if isinstance(assignments, list) else []):
            bid = int(item.get('block_id') or 0)
            if bid not in block_name_map:
                continue
            flat = _sec_to_flat(str(item.get('section') or '1.1'))
            order_idx = int(item.get('order_index') or 0)
            await db.execute(
                "INSERT INTO project_design_prototype_page_block (page_id, block_id, order_index, section) "
                "VALUES (%s, %s, %s, %s)",
                (page_id, bid, order_idx, flat)
            )
            result_blocks.append({
                'block_id': bid,
                'block_name': block_name_map[bid],
                'widget_name': '',
                'widget_id': None,
                'order_index': order_idx,
                'section': flat,
            })

    return {'result': result_blocks}

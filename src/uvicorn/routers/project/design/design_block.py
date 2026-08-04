import asyncio
import json
import httpx
import uuid
from http.client import HTTPException

from fastapi import APIRouter, Request, Depends

from ai.ai_llm import ai_llm_provider
from config.config import config_get
from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.agent_repository import AgentRepository
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.uvicorn.routers.project.project_common import _tools_load

_BLOCK_REGEN_WORKFLOW_ID = 50
_BLOCK_REGEN_AGENT_ID    = 83
_BLOCK_REGEN_TIMEOUT     = 240.0

router = APIRouter()


@router.get('/design/{project_id}/blocks')
async def planning_blocks_get(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute(
            """SELECT b.id, b.name, b.title, b.description, b.created_by, b.order_index,
                      w.id AS w_id, w.name AS w_name, w.description AS w_desc,
                      w.css AS w_css, w.html AS w_html, w.order_index AS w_order
               FROM project_design_ui_block b
               LEFT JOIN project_design_prototype_widget w ON w.block_id = b.id
               WHERE b.project_id = %s
               ORDER BY b.name, w.order_index""",
            (project_id,)
        )
        rows = await db.fetchall()

    blocks: dict = {}
    for r in (rows or []):
        bid = r['id']
        if bid not in blocks:
            blocks[bid] = {
                'id': bid,
                'name': r['name'],
                'title': r.get('title') or r['name'],
                'description': r['description'],
                'created_by': r['created_by'],
                'order_index': r['order_index'],
                'widgets': [],
            }
        if r['w_id']:
            blocks[bid]['widgets'].append({
                'id': r['w_id'], 'name': r['w_name'], 'description': r['w_desc'],
                'css': r['w_css'], 'html': r['w_html'], 'order_index': r['w_order'],
            })

    return {'result': list(blocks.values())}


@router.put('/design/block/{block_id}/title')
async def planning_block_title_update(request: Request, block_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Обновить пользовательское название блока (title). Техническое name не изменяется."""
    title = str(data.get('title') or '').strip()[:255] or None
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_design_ui_block SET title = %s WHERE id = %s",
            (title, block_id)
        )
        await db.connection.commit()
    return {'result': {'block_id': block_id, 'title': title}}


@router.get('/design/{project_id}/wireframe-pages')
async def planning_wireframe_pages(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Возвращает страницы с их вайрфреймами и блоками."""
    async with mysql_get_db_async() as db:
        await db.execute(
            """SELECT p.id, p.name, p.page_type, p.wireframe, p.grid_layout, p.parent_id, p.order_index,
                      pb.block_id, pb.widget_name, pb.widget_id, pb.order_index AS block_order,
                      pb.section AS block_section,
                      b.name AS block_name
               FROM project_design_prototype_page p
               LEFT JOIN project_design_prototype_page_block pb ON pb.page_id = p.id
               LEFT JOIN project_design_ui_block b ON b.id = pb.block_id
               WHERE p.project_id = %s
               ORDER BY p.order_index, pb.section, pb.order_index""",
            (project_id,)
        )
        rows = await db.fetchall()

    pages = {}
    for r in (rows or []):
        pid = r['id']
        if pid not in pages:
            import json as _json
            raw_layout = r.get('grid_layout')
            if isinstance(raw_layout, str):
                try:
                    raw_layout = _json.loads(raw_layout)
                except Exception:
                    raw_layout = None
            pages[pid] = {
                'id': pid,
                'name': r['name'],
                'page_type': r['page_type'],
                'wireframe': r['wireframe'],
                'grid_layout': raw_layout,
                'parent_id': r['parent_id'],
                'blocks': [],
            }
        if r['block_id']:
            pages[pid]['blocks'].append({
                'block_id': r['block_id'],
                'block_name': r['block_name'],
                'widget_name': r['widget_name'],
                'widget_id': r['widget_id'],
                'order_index': r['block_order'],
                'section': int(r.get('block_section') or 0),
            })

    return {'result': list(pages.values())}


@router.get('/design/block/{block_id}/widgets')
async def planning_block_widgets_get(request: Request, block_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, description, css, html, created_by, order_index "
            "FROM project_design_prototype_widget WHERE block_id = %s ORDER BY order_index",
            (block_id,)
        )
        rows = await db.fetchall()
    return {'result': [dict(r) for r in (rows or [])]}


@router.post('/design/block/{block_id}/widget')
async def planning_widget_create(request: Request, block_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    name = str(data.get('name') or '').strip()[:255]
    if not name:
        return {'error': 'name is required'}
    description = str(data.get('description') or '').strip() or None
    css = str(data.get('css') or '').strip() or None
    html = str(data.get('html') or '').strip() or None
    async with mysql_get_db_async() as db:
        await db.execute("SELECT COALESCE(MAX(order_index), -1) + 1 AS next FROM project_design_prototype_widget WHERE block_id = %s", (block_id,))
        row = await db.fetchone()
        order_index = int(row['next']) if row else 0
        await db.execute(
            "INSERT INTO project_design_prototype_widget (block_id, name, description, css, html, created_by, order_index) VALUES (%s, %s, %s, %s, %s, 'user', %s)",
            (block_id, name, description, css, html, order_index)
        )
        new_id = db.lastrowid
        await db.execute("SELECT id, name, description, css, html, created_by, order_index FROM project_design_prototype_widget WHERE id = %s", (new_id,))
        widget = await db.fetchone()
        await db.connection.commit()
    return {'result': dict(widget) if widget else None}


@router.put('/design/widget/{widget_id}')
async def planning_widget_update(request: Request, widget_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    fields = {}
    if 'name' in data:
        fields['name'] = str(data['name'])[:255]
    if 'description' in data:
        fields['description'] = str(data['description']) or None
    if 'css' in data:
        fields['css'] = str(data['css']) or None
    if 'html' in data:
        fields['html'] = str(data['html']) or None
    if not fields:
        return {'result': None}
    set_clause = ', '.join(f'`{k}` = %s' for k in fields)
    values = list(fields.values()) + [widget_id]
    async with mysql_get_db_async() as db:
        await db.execute(f"UPDATE project_design_prototype_widget SET {set_clause} WHERE id = %s", values)
        await db.execute("SELECT id, name, description, css, html, created_by, order_index FROM project_design_prototype_widget WHERE id = %s", (widget_id,))
        widget = await db.fetchone()
        await db.connection.commit()
    return {'result': dict(widget) if widget else None}


@router.delete('/design/widget/{widget_id}')
async def planning_widget_delete(request: Request, widget_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_design_prototype_widget WHERE id = %s", (widget_id,))
        await db.connection.commit()
    return {'result': True}


@router.put('/design/page/{page_id}/blocks')
async def planning_page_blocks_update(request: Request, page_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Заменяет блоки страницы и пересчитывает wireframe-текст."""
    blocks = data.get('blocks') or []
    grid_layout = data.get('grid_layout')

    sorted_blocks = sorted(blocks, key=lambda x: (int(x.get('section') or 0), int(x.get('order_index') or 0)))
    valid_block_ids = [int(b.get('block_id') or 0) for b in sorted_blocks if b.get('block_id')]

    async with mysql_get_db_async() as db:
        # Pre-fetch all block names in one query to avoid N+1
        block_name_map: dict[int, str] = {}
        if valid_block_ids:
            placeholders = ','.join(['%s'] * len(valid_block_ids))
            await db.execute(
                f"SELECT id, name FROM project_design_ui_block WHERE id IN ({placeholders})",
                valid_block_ids
            )
            for row in (await db.fetchall() or []):
                block_name_map[row['id']] = row['name']

        await db.execute("DELETE FROM project_design_prototype_page_block WHERE page_id = %s", (page_id,))

        wireframe_parts = []
        for item in sorted_blocks:
            block_id = int(item.get('block_id') or 0)
            if not block_id or block_id not in block_name_map:
                continue
            block_name = block_name_map[block_id]
            widget_name = str(item.get('widget_name') or '').strip()
            order_index = int(item.get('order_index') or 0)
            section = int(item.get('section') or 0)

            widget_id = None
            if widget_name:
                await db.execute(
                    "SELECT id FROM project_design_prototype_widget WHERE block_id = %s AND name = %s",
                    (block_id, widget_name)
                )
                w_row = await db.fetchone()
                if w_row:
                    widget_id = w_row['id']
                else:
                    await db.execute(
                        "INSERT INTO project_design_prototype_widget (block_id, name, created_by, order_index) VALUES (%s, %s, 'user', 0)",
                        (block_id, widget_name)
                    )
                    widget_id = db.lastrowid

            await db.execute(
                "INSERT INTO project_design_prototype_page_block "
                "(page_id, block_id, widget_id, widget_name, order_index, section) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (page_id, block_id, widget_id, widget_name, order_index, section)
            )
            wireframe_parts.append(f"{block_name} [{widget_name}]" if widget_name else block_name)

        wireframe_text = ' → '.join(wireframe_parts)
        grid_layout_json = json.dumps(grid_layout) if grid_layout is not None else None
        await db.execute(
            "UPDATE project_design_prototype_page SET wireframe = %s, grid_layout = %s WHERE id = %s",
            (wireframe_text, grid_layout_json, page_id)
        )
        await db.connection.commit()

    return {'result': {'page_id': page_id, 'wireframe': wireframe_text, 'blocks': len(blocks)}}


@router.post('/design/block/{block_id}/regenerate')
async def planning_block_regenerate(request: Request, block_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Запустить AI-перегенерацию блока: новое описание + виджеты с CSS."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT project_id FROM project_design_ui_block WHERE id = %s", (block_id,)
        )
        row = await db.fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail='Block not found')
    project_id = row['project_id']

    agent_repo = AgentRepository()
    agent = await agent_repo.find_one_by({'name': 'planning_block_regenerator'})
    if not agent:
        return {'error': 'Agent planning_block_regenerator not found'}

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
        'planning_project_id': str(project_id),
        'block_id': str(block_id),
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
        await asyncio.wait_for(future, timeout=_BLOCK_REGEN_TIMEOUT)
    except asyncio.TimeoutError:
        pass

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, title, description, created_by, order_index FROM project_design_ui_block WHERE id = %s",
            (block_id,)
        )
        block = await db.fetchone()
        await db.execute(
            "SELECT id, name, description, css, html, order_index FROM project_design_prototype_widget WHERE block_id = %s ORDER BY order_index",
            (block_id,)
        )
        widgets = await db.fetchall()

    result = dict(block) if block else {'id': block_id}
    if result.get('title') is None:
        result['title'] = result.get('name', '')
    result['widgets'] = [dict(w) for w in (widgets or [])]
    return {'result': result}


@router.put('/design/block/{block_id}')
async def planning_block_update(request: Request, block_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Обновить описание/название блока."""
    fields = {}
    if 'name' in data and data['name']:
        fields['name'] = str(data['name'])[:255]
    if 'description' in data:
        fields['description'] = str(data['description']) or None
    if not fields:
        return {'result': None}
    set_clause = ', '.join(f'`{k}` = %s' for k in fields)
    values = list(fields.values()) + [block_id]
    async with mysql_get_db_async() as db:
        await db.execute(f"UPDATE project_design_ui_block SET {set_clause} WHERE id = %s", values)
        await db.execute(
            "SELECT id, name, title, description, created_by, order_index FROM project_design_ui_block WHERE id = %s",
            (block_id,)
        )
        block = await db.fetchone()
        await db.connection.commit()
    return {'result': dict(block) if block else None}


@router.delete('/design/block/{block_id}')
async def planning_block_delete(request: Request, block_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Удалить блок и все его виджеты и состояния."""
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_design_prototype_page_block WHERE block_id = %s", (block_id,))
        await db.execute("DELETE FROM project_design_prototype_widget WHERE block_id = %s", (block_id,))
        await db.execute("DELETE FROM project_design_ui_block WHERE id = %s", (block_id,))
        await db.connection.commit()
    return {'result': True}


@router.post('/design/{project_id}/block')
async def planning_block_create(request: Request, project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Создать новый блок вручную."""
    name = str(data.get('name') or '').strip()[:255]
    if not name:
        return {'error': 'name is required'}
    description = str(data.get('description') or '').strip() or None
    async with mysql_get_db_async() as db:
        await db.execute("SELECT COALESCE(MAX(order_index), -1) + 1 AS next FROM project_design_ui_block WHERE project_id = %s", (project_id,))
        row = await db.fetchone()
        order_index = int(row['next']) if row else 0
        await db.execute(
            "INSERT INTO project_design_ui_block (project_id, name, description, created_by, order_index) VALUES (%s, %s, %s, 'user', %s)",
            (project_id, name, description, order_index)
        )
        new_id = db.lastrowid
        await db.connection.commit()
    return {'result': {'id': new_id, 'name': name, 'description': description, 'created_by': 'user', 'order_index': order_index, 'widgets': []}}


@router.post('/design/{project_id}/block/generate')
async def planning_block_generate(request: Request, project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Создать новый блок из описания и сразу сгенерировать виджеты через WF50."""
    name = str(data.get('name') or '').strip()[:255]
    description = str(data.get('description') or '').strip() or None
    if not name:
        return {'error': 'name is required'}

    async with mysql_get_db_async() as db:
        await db.execute("SELECT COALESCE(MAX(order_index), -1) + 1 AS next FROM project_design_ui_block WHERE project_id = %s", (project_id,))
        row = await db.fetchone()
        order_index = int(row['next']) if row else 0
        await db.execute(
            "INSERT INTO project_design_ui_block (project_id, name, description, created_by, order_index) VALUES (%s, %s, %s, 'user', %s)",
            (project_id, name, description, order_index)
        )
        block_id = db.lastrowid
        await db.connection.commit()

    agent = await AgentRepository().find_one_by({'name': 'planning_block_regenerator'})
    if not agent:
        return {'error': 'Agent planning_block_regenerator not found', 'block_id': block_id}

    entities_llm = await ai_llm_node_get(agent['node_id'])
    if not entities_llm:
        return {'error': 'LLM не настроены для агента', 'block_id': block_id}

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
        'planning_project_id': str(project_id),
        'block_id': str(block_id),
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
        await asyncio.wait_for(future, timeout=_BLOCK_REGEN_TIMEOUT)
    except asyncio.TimeoutError:
        pass

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, title, description, created_by, order_index FROM project_design_ui_block WHERE id = %s",
            (block_id,)
        )
        block = await db.fetchone()
        await db.execute(
            "SELECT id, name, description, css, html, order_index FROM project_design_prototype_widget WHERE block_id = %s ORDER BY order_index",
            (block_id,)
        )
        widgets = await db.fetchall()

    result = dict(block) if block else {'id': block_id, 'name': name}
    if result.get('title') is None:
        result['title'] = result.get('name', '')
    result['widgets'] = [dict(w) for w in (widgets or [])]
    return {'result': result}


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

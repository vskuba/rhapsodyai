import json

from mysql_.mysql_ import mysql_get_db_async


async def planning_block_regenerate_context_load(project_id: int, block_id: int) -> dict:
    """
    Загружает контекст для AI-перегенерации одного блока:
    информацию о проекте, о блоке, на каких страницах используется.
     - project_id: ID проекта
     - block_id: ID блока для перегенерации
    Returns:
        dict:
            block_json (str): JSON блока {id, name, description, widgets}
            pages_json (str): JSON страниц, где используется блок
            project_idea (str): идея проекта
            blocks_context (str): список всех блоков (для согласованности стиля)
    """
    project_id = int(project_id)
    block_id = int(block_id)

    async with mysql_get_db_async() as db:
        await db.execute("SELECT id, idea, title FROM project WHERE id = %s", (project_id,))
        proj = await db.fetchone()

        await db.execute(
            "SELECT id, name, description, stateless FROM project_design_ui_block WHERE id = %s",
            (block_id,)
        )
        block_row = await db.fetchone()

        if not block_row:
            return {'error': f'Block {block_id} not found'}

        await db.execute(
            "SELECT id, name, description, css, html, order_index "
            "FROM project_design_prototype_widget WHERE block_id = %s ORDER BY order_index",
            (block_id,)
        )
        widget_rows = await db.fetchall()

        await db.execute(
            """SELECT p.id, p.name, p.page_type, pb.widget_name
               FROM project_design_prototype_page_block pb
               JOIN project_design_prototype_page p ON pb.page_id = p.id
               WHERE pb.block_id = %s AND p.project_id = %s""",
            (block_id, project_id)
        )
        page_rows = await db.fetchall()

        await db.execute(
            "SELECT DISTINCT state FROM project_design_prototype_page WHERE project_id = %s ORDER BY state",
            (project_id,)
        )
        state_rows = await db.fetchall()

        await db.execute(
            "SELECT name, description FROM project_design_ui_block WHERE project_id = %s ORDER BY name",
            (project_id,)
        )
        all_blocks = await db.fetchall()

    page_states = [r['state'] for r in (state_rows or [])] or ['anon', 'auth']

    block_data = {
        'id': block_row['id'],
        'name': block_row['name'],
        'description': block_row['description'] or '',
        'stateless': bool(block_row.get('stateless')),
        'widgets': [
            {'id': w['id'], 'name': w['name'], 'description': w.get('description') or '',
             'css': w.get('css') or '', 'html': w.get('html') or ''}
            for w in (widget_rows or [])
        ],
    }

    pages_data = [
        {'id': p['id'], 'name': p['name'], 'page_type': p['page_type'], 'widget_used': p['widget_name']}
        for p in (page_rows or [])
    ]

    blocks_context = '\n'.join(
        f"- {b['name']}: {b['description'] or ''}" for b in (all_blocks or [])
    )

    return {
        'block_json':       json.dumps(block_data, ensure_ascii=False),
        'pages_json':       json.dumps(pages_data, ensure_ascii=False),
        'page_states_json': json.dumps(page_states, ensure_ascii=False),
        'project_idea':     (proj.get('idea') or proj.get('title') or '') if proj else '',
        'blocks_context':   blocks_context,
    }


async def planning_block_ai_update(block_id: int, description: str, widgets_json: list) -> dict:
    """
    Сохраняет AI-обновлённое описание блока и его виджеты (с CSS).
    Существующие виджеты удаляются и заменяются новыми.
     - block_id: ID блока
     - description: новое описание блока
     - widgets_json: список [{name, description, css, html}]
    Returns:
        dict: block_id (int), widgets_count (int)
    """
    block_id = int(block_id)
    if isinstance(widgets_json, str):
        try:
            widgets_json = json.loads(widgets_json)
        except Exception:
            widgets_json = []
    if not isinstance(widgets_json, list):
        widgets_json = []

    async with mysql_get_db_async() as db:
        if description:
            await db.execute(
                "UPDATE project_design_ui_block SET description = %s WHERE id = %s",
                (str(description)[:2000], block_id)
            )

        await db.execute("DELETE FROM project_design_prototype_widget WHERE block_id = %s", (block_id,))
        count = 0
        for i, w in enumerate(widgets_json):
            if not isinstance(w, dict):
                continue
            name = str(w.get('name') or '')[:255].strip()
            if not name:
                continue
            await db.execute(
                "INSERT INTO project_design_prototype_widget "
                "(block_id, name, description, css, html, created_by, order_index) "
                "VALUES (%s, %s, %s, %s, %s, 'ai', %s)",
                (block_id, name, w.get('description') or None, w.get('css') or None, w.get('html') or None, i)
            )
            count += 1

        await db.connection.commit()

    return {'block_id': block_id, 'widgets_count': count}


async def planning_block_section_memory_load(project_id: int) -> dict:
    """
    Загружает карту блок→секция из поля default_section блоков проекта.
    Используется как контекст для LLM при генерации вайрфреймов.
     - project_id: ID проекта
    Returns:
        block_section_memory: текст для LLM (BlockName: секция 1.2)
        block_section_json: JSON {BlockName: "1.2"}
    """
    project_id = int(project_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT name, default_section FROM project_design_ui_block "
            "WHERE project_id = %s AND default_section IS NOT NULL ORDER BY name",
            (project_id,)
        )
        rows = await db.fetchall()

    if not rows:
        return {
            'block_section_memory': '(нет сохранённых назначений секций — назначь секции самостоятельно)',
            'block_section_json': '{}',
        }

    memory = {}
    lines = []
    for r in rows:
        memory[r['name']] = r['default_section']
        lines.append(f"- {r['name']}: секция {r['default_section']}")

    return {
        'block_section_memory': '\n'.join(lines),
        'block_section_json':   json.dumps(memory, ensure_ascii=False),
    }

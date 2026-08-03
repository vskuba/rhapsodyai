import json

from mysql_.mysql_ import mysql_get_db_async


async def design_widget_save(block_id: int, widgets_json: list) -> dict:
    """
    Сохраняет виджеты (стилизованные варианты) блока.
    Удаляет существующие виджеты блока и записывает новые.
     - block_id: ID блока из project_design_ui_block
     - widgets_json: список виджетов, каждый содержит name, description, css, html
    Returns:
        dict: widgets_count (int)
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
        await db.execute("DELETE FROM project_design_prototype_widget WHERE block_id = %s", (block_id,))
        count = 0
        for i, widget in enumerate(widgets_json):
            if not isinstance(widget, dict):
                continue
            name = str(widget.get('name') or '')[:255]
            if not name:
                continue
            description = widget.get('description') or None
            css = widget.get('css') or None
            html = widget.get('html') or None
            await db.execute(
                "INSERT INTO project_design_prototype_widget "
                "(block_id, name, description, css, html, created_by, order_index) "
                "VALUES (%s, %s, %s, %s, %s, 'ai', %s)",
                (block_id, name, description, css, html, i)
            )
            count += 1
        await db.connection.commit()

    return {'widgets_count': count}


async def design_widget_list(block_id: int) -> dict:
    """
    Возвращает виджеты блока.
     - block_id: ID блока
    Returns:
        dict: widgets (list) — каждый виджет содержит id, name, description, css, html
    """
    block_id = int(block_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, description, css, html, created_by, order_index "
            "FROM project_design_prototype_widget WHERE block_id = %s ORDER BY order_index",
            (block_id,)
        )
        rows = await db.fetchall()
    return {'widgets': [dict(r) for r in (rows or [])]}


async def design_widget_validate(w_widgets: list) -> dict:
    """
    Фильтрует список виджетов: удаляет записи без html или без css.
    Используется после LLM-шага генерации виджетов перед сохранением.
     - w_widgets: список виджетов [{name, description, html, css}]
    Returns:
        dict: w_widgets (list) — только виджеты с непустыми html и css,
              w_widgets_valid_count (int), w_widgets_removed_count (int)
    """
    if isinstance(w_widgets, str):
        try:
            w_widgets = json.loads(w_widgets)
        except Exception:
            w_widgets = []
    if not isinstance(w_widgets, list):
        w_widgets = []

    valid = []
    for w in w_widgets:
        if not isinstance(w, dict):
            continue
        name = str(w.get('name') or '').strip()
        html = str(w.get('html') or '').strip()
        css = str(w.get('css') or '').strip()
        if name and html and css:
            valid.append(w)

    return {
        'w_widgets': valid,
        'w_widgets_valid_count': len(valid),
        'w_widgets_removed_count': len(w_widgets) - len(valid),
    }


async def design_widget_block_ids_get(project_id: int) -> dict:
    """
    Возвращает список ID блоков проекта для итерации генерации виджетов.
     - project_id: ID проекта
    Returns:
        dict: block_ids_json (str) — JSON-массив ID блоков, blocks_count (int)
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id FROM project_design_ui_block WHERE project_id = %s ORDER BY id",
            (int(project_id),)
        )
        rows = await db.fetchall()
    ids = [r['id'] for r in (rows or [])]
    return {
        'block_ids_json': json.dumps(ids),
        'blocks_count': len(ids),
    }


async def design_widget_iter_step(project_id: int, block_ids_json: str, iter_index: str) -> dict:
    """
    Извлекает один блок по индексу из массива и загружает контекст для генерации виджетов.
    Используется внутри workflow_invoke repeat для пошагового обхода блоков.
     - project_id: ID проекта
     - block_ids_json: JSON-массив ID блоков ("[1, 2, 3]")
     - iter_index: текущий индекс ("0", "1", ...)
    Returns:
        dict:
            w_block_id (int): ID текущего блока
            w_next_index (str): следующий индекс (для outputs_map в repeat)
            w_is_done (str): "true" если это последний блок, иначе "false"
            w_project_idea (str): идея проекта
            w_block_name (str): название блока
            w_block_description (str): описание блока
            w_block_stateless (str): "true" если блок stateless, иначе "false"
            w_page_states_json (str): JSON-массив состояний страниц проекта (["anon","auth"])
            w_blocks_context (str): краткий список всех блоков (для согласованности стиля)
    """
    project_id = int(project_id)
    idx = int(iter_index)

    if isinstance(block_ids_json, str):
        try:
            ids = json.loads(block_ids_json)
        except Exception:
            ids = []
    else:
        ids = list(block_ids_json)

    _empty = {
        'w_block_id': 0, 'w_next_index': str(idx), 'w_is_done': 'true',
        'w_project_idea': '', 'w_block_name': '', 'w_block_description': '',
        'w_block_stateless': 'false', 'w_page_states_json': '["anon","auth"]', 'w_blocks_context': '',
    }
    if not ids or idx >= len(ids):
        return _empty

    block_id = int(ids[idx])
    next_index = idx + 1
    is_done = 'true' if next_index >= len(ids) else 'false'

    async with mysql_get_db_async() as db:
        await db.execute("SELECT idea, title FROM project WHERE id = %s", (project_id,))
        proj = await db.fetchone()
        project_idea = ((proj.get('idea') or proj.get('title') or '') if proj else '')

        await db.execute(
            "SELECT name, description, stateless FROM project_design_ui_block WHERE id = %s",
            (block_id,)
        )
        block = await db.fetchone()

        await db.execute(
            "SELECT DISTINCT state FROM project_design_prototype_page WHERE project_id = %s ORDER BY state",
            (project_id,)
        )
        page_state_rows = await db.fetchall()

        await db.execute(
            "SELECT name, description FROM project_design_ui_block WHERE project_id = %s ORDER BY name",
            (project_id,)
        )
        all_blocks = await db.fetchall()

    if not block:
        return _empty

    page_states = [r['state'] for r in (page_state_rows or [])] or ['anon', 'auth']
    blocks_context = '\n'.join(f"- {b['name']}: {b.get('description') or ''}" for b in (all_blocks or []))
    is_stateless = bool(block.get('stateless'))

    return {
        'w_block_id': block_id,
        'w_next_index': str(next_index),
        'w_is_done': is_done,
        'w_project_idea': project_idea,
        'w_block_name': block['name'],
        'w_block_description': block.get('description') or '',
        'w_block_stateless': 'true' if is_stateless else 'false',
        'w_page_states_json': json.dumps(page_states, ensure_ascii=False),
        'w_blocks_context': blocks_context,
    }

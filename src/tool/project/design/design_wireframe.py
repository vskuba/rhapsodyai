import json
import re as _re

from mysql_.mysql_ import mysql_get_db_async


async def design_wireframe_context_load(project_id: int, page_id: int = 0) -> dict:
    """
    Загружает контекст для генерации вайрфреймов: список страниц и список блоков проекта.
     - project_id: ID проекта
     - page_id: если > 0, возвращает только эту страницу
    Returns:
        dict:
            pages_json (str): JSON-массив страниц [{id, name, description, page_type, roles}]
            blocks_json (str): JSON-массив блоков проекта [{id, name, description, states}]
            ui_blocks_json (str): JSON-массив UI-блоков из библиотеки [{id, name, description, tags}]
            pages_count (int): количество страниц
            blocks_count (int): количество блоков
    """
    project_id = int(project_id)
    page_id = int(page_id) if page_id else 0

    async with mysql_get_db_async() as db:
        if page_id:
            await db.execute(
                "SELECT id, name, description, page_type, roles "
                "FROM project_design_prototype_page WHERE project_id = %s AND id = %s",
                (project_id, page_id)
            )
        else:
            await db.execute(
                "SELECT id, name, description, page_type, roles "
                "FROM project_design_prototype_page WHERE project_id = %s ORDER BY order_index",
                (project_id,)
            )
        page_rows = await db.fetchall()

        await db.execute(
            "SELECT id, name, description FROM project_design_ui_block "
            "WHERE project_id = %s ORDER BY order_index",
            (project_id,)
        )
        block_rows = await db.fetchall()

        await db.execute(
            "SELECT id, name, description, tags FROM project_design_ui_block "
            "WHERE vars IS NOT NULL ORDER BY name ASC"
        )
        ui_block_rows = await db.fetchall()

    pages = [{'id': r['id'], 'name': r['name'], 'description': r['description'] or '',
               'page_type': r['page_type'], 'roles': r['roles']} for r in (page_rows or [])]

    blocks_with_states = [
        {'id': b['id'], 'name': b['name'], 'description': b['description'] or '', 'states': []}
        for b in (block_rows or [])
    ]

    ui_blocks = [{'id': r['id'], 'name': r['name'],
                  'description': r['description'] or '',
                  'tags': r['tags'] or ''} for r in (ui_block_rows or [])]

    return {
        'pages_json': json.dumps(pages, ensure_ascii=False),
        'blocks_json': json.dumps(blocks_with_states, ensure_ascii=False),
        'ui_blocks_json': json.dumps(ui_blocks, ensure_ascii=False),
        'pages_count': len(pages),
        'blocks_count': len(blocks_with_states),
    }


async def design_wireframe_page_save(project_id: int, wireframes_json: list, filter_page_id: int = 0) -> dict:
    """
    Сохраняет вайрфреймы для страниц проекта.
    Поддерживает два формата wireframe:
      Новый: "[1.1. Header:Dark, Sidebar:Nav], [1.2. Main:Light], [2.1. Footer:Main]"
             — с нумерацией уровней и секций; автоматически строит grid_layout
      Старый: "Header [Dark] -> Main -> Footer [Light]"
             — плоский список блоков без секций
     - project_id: ID проекта
     - wireframes_json: список [{page_name, wireframe}]
     - filter_page_id: если > 0, сохраняет только эту страницу (игнорирует остальные)
    Returns:
        dict: saved_count (int) — количество обновлённых страниц
    """
    filter_page_id = int(filter_page_id) if filter_page_id else 0
    project_id = int(project_id)
    if isinstance(wireframes_json, str):
        try:
            wireframes_json = json.loads(wireframes_json)
        except Exception:
            wireframes_json = []
    if not isinstance(wireframes_json, list):
        wireframes_json = []

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, grid_layout FROM project_design_prototype_page WHERE project_id = %s",
            (project_id,)
        )
        page_rows = await db.fetchall()
        page_by_name: dict[str, list[int]] = {}
        existing_grid: dict[int, str | None] = {}
        for r in (page_rows or []):
            key = str(r['name']).lower().strip()
            page_by_name.setdefault(key, []).append(r['id'])
            existing_grid[r['id']] = r.get('grid_layout')

        await db.execute(
            "SELECT id, name FROM project_design_ui_block WHERE project_id = %s",
            (project_id,)
        )
        block_rows = await db.fetchall()
        block_by_name = {str(r['name']).lower().strip(): r['id'] for r in (block_rows or [])}
        block_id_by_name = {str(r['name']).strip(): r['id'] for r in (block_rows or [])}

        widget_cache: dict = {}

        async def _get_or_create_widget(block_id: int, widget_name: str) -> int | None:
            if not widget_name:
                return None
            if block_id not in widget_cache:
                await db.execute(
                    "SELECT id, name FROM project_design_prototype_widget WHERE block_id = %s",
                    (block_id,)
                )
                rows = await db.fetchall()
                widget_cache[block_id] = {str(r['name']).lower().strip(): r['id'] for r in (rows or [])}
            key = widget_name.lower().strip()
            wid = widget_cache[block_id].get(key)
            if not wid:
                await db.execute(
                    "INSERT INTO project_design_prototype_widget (block_id, name, created_by, order_index) "
                    "VALUES (%s, %s, 'ai', %s)",
                    (block_id, widget_name[:255], len(widget_cache[block_id]))
                )
                wid = db.lastrowid
                widget_cache[block_id][key] = wid
            return wid

        section_memory_updates: dict = {}
        saved = 0

        for item in wireframes_json:
            if not isinstance(item, dict):
                continue
            page_name = str(item.get('page_name') or '').strip()
            wireframe = str(item.get('wireframe') or '').strip()

            page_ids: list[int] = page_by_name.get(page_name.lower(), [])
            if not page_ids:
                for pname, pids in page_by_name.items():
                    if page_name.lower() in pname or pname in page_name.lower():
                        page_ids = pids
                        break
            if not page_ids:
                continue
            if filter_page_id:
                page_ids = [pid for pid in page_ids if pid == filter_page_id]
                if not page_ids:
                    continue

            sections, is_structured = _parse_wireframe_structured(wireframe)

            for page_id in page_ids:
                if is_structured:
                    raw_existing = existing_grid.get(page_id)
                    if raw_existing:
                        try:
                            grid_layout = json.loads(raw_existing) if isinstance(raw_existing, str) else raw_existing
                        except Exception:
                            grid_layout = _grid_layout_from_sections(sections)
                    else:
                        grid_layout = _grid_layout_from_sections(sections)
                    grid_layout_json = json.dumps(grid_layout, ensure_ascii=False)

                    await db.execute(
                        "UPDATE project_design_prototype_page SET wireframe = %s, grid_layout = %s WHERE id = %s",
                        (wireframe, grid_layout_json, page_id)
                    )
                    await db.execute(
                        "DELETE FROM project_design_prototype_page_block WHERE page_id = %s",
                        (page_id,)
                    )

                    for level_1, col_1, entries in sections:
                        flat_idx = _section_to_flat(level_1, col_1, grid_layout)
                        section_label = f'{level_1}.{col_1}'
                        for order_idx, (block_name, widget_name) in enumerate(entries):
                            bid = (block_by_name.get(block_name.lower().strip())
                                   or block_id_by_name.get(block_name.strip()))
                            if not bid:
                                continue
                            wid = await _get_or_create_widget(bid, widget_name) if widget_name else None
                            await db.execute(
                                "INSERT INTO project_design_prototype_page_block "
                                "(page_id, block_id, widget_id, widget_name, order_index, section) "
                                "VALUES (%s, %s, %s, %s, %s, %s) "
                                "ON DUPLICATE KEY UPDATE widget_id=%s, widget_name=%s, order_index=%s, section=%s",
                                (page_id, bid, wid, widget_name, order_idx, flat_idx,
                                 wid, widget_name, order_idx, flat_idx)
                            )
                            if block_name not in section_memory_updates:
                                section_memory_updates[block_name] = section_label
                else:
                    await db.execute(
                        "UPDATE project_design_prototype_page SET wireframe = %s WHERE id = %s",
                        (wireframe or None, page_id)
                    )
                    parsed_blocks = []
                    explicit_blocks = item.get('blocks') or []
                    if isinstance(explicit_blocks, list) and explicit_blocks:
                        for b in explicit_blocks:
                            if isinstance(b, dict):
                                parsed_blocks.append({
                                    'block_name': str(b.get('block_name') or ''),
                                    'widget_name': str(b.get('widget_name') or ''),
                                })
                            elif isinstance(b, str):
                                parsed_blocks.append({'block_name': b, 'widget_name': ''})
                    elif wireframe:
                        for part in _re.split(r'\s*->\s*|\s*→\s*', wireframe):
                            m = _re.match(r'^(.+?)\s*\[(.+?)\]\s*$', part.strip())
                            if m:
                                parsed_blocks.append({'block_name': m.group(1).strip(), 'widget_name': m.group(2).strip()})
                            else:
                                bname = part.strip().strip('[]')
                                if bname:
                                    parsed_blocks.append({'block_name': bname, 'widget_name': ''})

                    if parsed_blocks:
                        await db.execute(
                            "DELETE FROM project_design_prototype_page_block WHERE page_id = %s",
                            (page_id,)
                        )
                        for order_idx, entry in enumerate(parsed_blocks):
                            bid = block_by_name.get(entry['block_name'].lower().strip())
                            if not bid:
                                continue
                            wname = entry['widget_name'] or ''
                            wid = await _get_or_create_widget(bid, wname) if wname else None
                            await db.execute(
                                "INSERT INTO project_design_prototype_page_block "
                                "(page_id, block_id, widget_id, widget_name, order_index) "
                                "VALUES (%s, %s, %s, %s, %s) "
                                "ON DUPLICATE KEY UPDATE widget_id=%s, widget_name=%s, order_index=%s",
                                (page_id, bid, wid, wname, order_idx, wid, wname, order_idx)
                            )

            saved += 1

        for block_name, section_label in section_memory_updates.items():
            bid = (block_by_name.get(block_name.lower().strip())
                   or block_id_by_name.get(block_name.strip()))
            if bid:
                await db.execute(
                    "UPDATE project_design_ui_block SET default_section = %s WHERE id = %s",
                    (section_label, bid)
                )

        await db.connection.commit()

    return {'saved_count': saved}


async def design_wireframe_page_block_save(page_blocks_json: list) -> dict:
    """
    Привязывает блоки к страницам.
     - page_blocks_json: список {page_id, block_id, order_index}
    Returns:
        dict: saved_count (int)
    """
    if isinstance(page_blocks_json, str):
        try:
            page_blocks_json = json.loads(page_blocks_json)
        except Exception:
            page_blocks_json = []

    count = 0
    async with mysql_get_db_async() as db:
        for item in page_blocks_json:
            if not isinstance(item, dict):
                continue
            page_id = item.get('page_id')
            block_id = item.get('block_id')
            if not page_id or not block_id:
                continue
            order_index = int(item.get('order_index') or 0)
            await db.execute(
                "INSERT INTO project_design_prototype_page_block (page_id, block_id, order_index) "
                "VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE order_index=%s",
                (page_id, block_id, order_index, order_index)
            )
            count += 1

    return {'saved_count': count}


# ── Structured wireframe helpers ──────────────────────────────────────────────

def _parse_wireframe_structured(wireframe_text: str):
    """
    Парсит новый формат вайрфрейма: [1.1. Header:Dark, Sidebar:Nav], [1.2. Main:Light]
    Returns: (sections, is_structured)
      sections: [(level_1based, col_1based, [(block_name, widget_name), ...])]
    """
    if not wireframe_text or not _re.search(r'\[\s*\d+\.\d+\.', wireframe_text):
        return [], False
    pattern = _re.compile(r'\[\s*(\d+)\.(\d+)\.\s*([^\]]+)\]')
    sections = []
    for m in pattern.finditer(wireframe_text):
        level = int(m.group(1))
        col = int(m.group(2))
        entries = []
        for entry in _re.split(r',\s*', m.group(3).strip()):
            entry = entry.strip()
            if not entry:
                continue
            if ':' in entry:
                parts = entry.split(':', 1)
                entries.append((parts[0].strip(), parts[1].strip()))
            else:
                entries.append((entry, ''))
        sections.append((level, col, entries))
    return sections, bool(sections)


def _grid_layout_from_sections(sections: list) -> list:
    """Строит grid_layout [{w:[%,...], h:px}] из распарсенных секций."""
    if not sections:
        return [{'w': [100], 'h': 300}]
    max_level = max(s[0] for s in sections)
    layout = []
    for lvl in range(1, max_level + 1):
        level_secs = [s for s in sections if s[0] == lvl]
        max_col = max((s[1] for s in level_secs), default=1)
        each = 100 // max_col
        ws = [each] * max_col
        ws[0] += 100 - sum(ws)
        layout.append({'w': ws, 'h': 300})
    return layout


def _section_to_flat(level_1: int, col_1: int, grid_layout: list) -> int:
    """Конвертирует 1-based (level, col) в плоский индекс секции."""
    max_level = len(grid_layout)
    actual_level = min(level_1 - 1, max_level - 1)
    flat = sum(len(grid_layout[l]['w']) for l in range(actual_level))
    actual_col = min(col_1 - 1, len(grid_layout[actual_level]['w']) - 1)
    flat += actual_col
    return flat

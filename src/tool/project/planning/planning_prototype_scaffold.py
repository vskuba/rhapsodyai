"""
Сборка каркаса страницы и загрузка layout из БД.

- planning_prototype_page_layout_load — загрузка grid_layout + блоки по секциям.
- planning_prototype_scaffold_build — генерация HTML-каркаса с CSS Grid.
- planning_prototype_blocks_pending — фильтр неотрендеренных блоков.

Соседние модули: `planning_prototype_state` — пути, `_normalize_grid_layout` внутри,
`planning_prototype_page_save` — сохранение собранной страницы.
"""
import json
import os
import re

from mysql_.mysql_ import mysql_get_db_async
from src.tool.project.planning.planning_prototype_state import (
    PROTOTYPE_FILES_DIR,
    _prototype_latest_version,
    _prototype_next_version_dir,
)

# ── детали реализации ─────────────────────────────────────────────────────────

def _normalize_grid_layout(raw) -> list:
    default = [{'w': [33, 33, 34], 'h': 300}] * 3
    if not isinstance(raw, list) or not raw:
        return default
    if isinstance(raw[0], int):
        result = []
        for cols in raw:
            cols = max(1, int(cols))
            each = 100 // cols
            ws = [each] * cols
            ws[0] += 100 - sum(ws)
            result.append({'w': ws, 'h': 300})
        return result
    result = []
    for lvl in raw:
        if not isinstance(lvl, dict):
            result.append({'w': [100], 'h': 300})
            continue
        w = lvl.get('w')
        if not isinstance(w, list) or not w:
            w = [100]
        h = int(lvl.get('h') or 300)
        result.append({'w': [int(x) for x in w], 'h': h})
    return result


# ── Загрузка layout ────────────────────────────────────────────────────────────

async def planning_prototype_page_layout_load(project_id: int, page_title: str) -> dict:
    """
    Загружает layout-структуру страницы из БД: grid_layout + блоки по секциям.
     - project_id: ID проекта
     - page_title: название страницы (ищется по совпадению)
    Returns:
        grid_layout_json: JSON-строка формата [{w:[%,...],h:px}, ...]
        blocks_sections_json: JSON-массив [{block_id, block_name, block_description, widget_name, section, order_index}]
        layout_spec: читаемый текст структуры для LLM
        page_wireframe: wireframe-текст страницы
        page_id: ID найденной страницы (0 если не найдена)
    """
    project_id = int(project_id)
    page_title_lower = str(page_title or '').strip().lower()

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, wireframe, grid_layout FROM project_design_prototype_page "
            "WHERE project_id = %s ORDER BY order_index",
            (project_id,)
        )
        pages = await db.fetchall()

    page = None
    for p in (pages or []):
        if page_title_lower == str(p['name'] or '').lower():
            page = p
            break
    if not page:
        for p in (pages or []):
            pname = str(p['name'] or '').lower()
            if page_title_lower in pname or pname in page_title_lower:
                page = p
                break

    if not page:
        return {
            'grid_layout_json': '[{"w":[100],"h":300}]',
            'blocks_sections_json': '[]',
            'layout_spec': '',
            'page_wireframe': '',
            'page_id': 0,
        }

    page_id = page['id']
    page_wireframe = page.get('wireframe') or ''
    raw_layout = page.get('grid_layout')
    if isinstance(raw_layout, str):
        try:
            raw_layout = json.loads(raw_layout)
        except Exception:
            raw_layout = None
    grid_layout = _normalize_grid_layout(raw_layout)

    async with mysql_get_db_async() as db:
        await db.execute(
            """SELECT pb.block_id, pb.section, pb.order_index, pb.widget_name,
                      b.name AS block_name, b.description AS block_description
               FROM project_design_prototype_page_block pb
               JOIN project_design_ui_block b ON b.id = pb.block_id
               WHERE pb.page_id = %s
               ORDER BY pb.section, pb.order_index""",
            (page_id,)
        )
        block_rows = await db.fetchall()

    blocks_sections = [
        {
            'block_id':          br['block_id'],
            'block_name':        br['block_name'] or '',
            'block_description': br['block_description'] or '',
            'widget_name':       br['widget_name'] or '',
            'section':           int(br['section'] or 0),
            'order_index':       int(br['order_index'] or 0),
        }
        for br in (block_rows or [])
    ]

    cumulative = 0
    spec_lines = []
    for level_idx, level in enumerate(grid_layout):
        cols = len(level['w'])
        col_parts = []
        for col in range(cols):
            flat_idx = cumulative + col
            sec_blocks = [b['block_name'] for b in blocks_sections if b['section'] == flat_idx]
            content = ' + '.join(sec_blocks) if sec_blocks else '(empty)'
            col_parts.append(f'{content} [{level["w"][col]}%]')
        col_label = '1 col' if cols == 1 else f'{cols} cols'
        spec_lines.append(f'Level {level_idx + 1} ({col_label}, h={level["h"]}px): {" | ".join(col_parts)}')
        cumulative += cols

    return {
        'grid_layout_json':    json.dumps(grid_layout, ensure_ascii=False),
        'blocks_sections_json': json.dumps(blocks_sections, ensure_ascii=False),
        'layout_spec':         '\n'.join(spec_lines),
        'page_wireframe':      page_wireframe,
        'page_id':             page_id,
    }


# ── Сборка каркаса ─────────────────────────────────────────────────────────────

def planning_prototype_scaffold_build(grid_layout_json: str, blocks_sections_json: str) -> dict:
    """
    Генерирует детерминированный HTML-каркас с CSS Grid из grid_layout.
     - grid_layout_json: JSON-строка [{w:[%,...],h:px}, ...]
     - blocks_sections_json: JSON-массив [{block_id, block_name, block_description, section, order_index}]
    Returns:
        scaffold_html: HTML-каркас с <!-- BLOCK:id --> плейсхолдерами
        blocks_json: JSON-массив [{id, name, component, description}] для цикла рендеринга
    """
    try:
        raw = json.loads(grid_layout_json) if isinstance(grid_layout_json, str) else grid_layout_json
    except Exception:
        raw = None
    grid_layout = _normalize_grid_layout(raw)

    try:
        blocks_sections = json.loads(blocks_sections_json) if isinstance(blocks_sections_json, str) else blocks_sections_json
    except Exception:
        blocks_sections = []
    if not isinstance(blocks_sections, list):
        blocks_sections = []

    used_ids: dict = {}

    def _make_id(name: str) -> str:
        base = re.sub(r'[^a-zA-Z0-9]', '_', str(name).lower()).strip('_')
        base = re.sub(r'_+', '_', base) or 'block'
        if not re.match(r'[a-z]', base[0]):
            base = 'block_' + base
        count = used_ids.get(base, 0)
        used_ids[base] = count + 1
        return base if count == 0 else f'{base}_{count}'

    block_meta = [
        {
            'id':          _make_id(b.get('block_name', 'block')),
            'name':        b.get('block_name', ''),
            'description': b.get('block_description', ''),
            'section':     int(b.get('section', 0)),
            'order_index': int(b.get('order_index', 0)),
        }
        for b in blocks_sections
    ]

    section_blocks: dict = {}
    for bm in block_meta:
        section_blocks.setdefault(bm['section'], []).append(bm)
    for sec in section_blocks:
        section_blocks[sec].sort(key=lambda b: b['order_index'])

    levels_html = []
    cumulative = 0
    for level_idx, level in enumerate(grid_layout):
        widths = level['w']
        height = level['h']
        cols_css = ' '.join(f'{w}%' for w in widths)
        cells_html = []
        for col_idx, _ in enumerate(widths):
            flat_idx = cumulative + col_idx
            sec_blocks = section_blocks.get(flat_idx, [])
            placeholders = (
                '\n'.join(f'      <div id="{b["id"]}"><!-- BLOCK:{b["id"]} --></div>' for b in sec_blocks)
                if sec_blocks else '      <!-- empty -->'
            )
            cells_html.append(f'    <div class="wf-cell">\n{placeholders}\n    </div>')
        levels_html.append(
            f'  <div class="wf-level" style="grid-template-columns:{cols_css};min-height:{height}px;">\n'
            + '\n'.join(cells_html)
            + '\n  </div>'
        )
        cumulative += len(widths)

    scaffold_html = (
        '<style>\n'
        '  *,*::before,*::after{box-sizing:border-box;}\n'
        '  .wf-page{display:flex;flex-direction:column;width:100%;max-width:1280px;margin:0 auto;}\n'
        '  .wf-level{display:grid;width:100%;overflow:hidden;}\n'
        '  .wf-cell{overflow:hidden;position:relative;}\n'
        '</style>\n'
        '<div class="wf-page">\n'
        + '\n'.join(levels_html)
        + '\n</div>'
    )

    seen_ids: set = set()
    blocks_for_render = []
    for bm in block_meta:
        if bm['id'] not in seen_ids:
            seen_ids.add(bm['id'])
            blocks_for_render.append({'id': bm['id'], 'name': bm['name'], 'component': bm['name'], 'description': bm['description']})

    return {
        'scaffold_html': scaffold_html,
        'blocks_json':   json.dumps(blocks_for_render, ensure_ascii=False),
    }


# ── Pending блоки ──────────────────────────────────────────────────────────────

async def planning_prototype_blocks_pending(page_blocks_json: str, components_html_map: str) -> dict:
    """
    Фильтрует список блоков страницы — возвращает только те, которые ещё не отрендерены.
     - page_blocks_json: JSON-массив [{id, component, description}]
     - components_html_map: JSON-словарь {component_id: html}
    Returns:
        dict: blocks_pending_json (JSON-массив), pending_count (int)
    """
    try:
        blocks = json.loads(page_blocks_json) if isinstance(page_blocks_json, str) else (page_blocks_json or [])
    except Exception:
        blocks = []
    try:
        cmap = json.loads(components_html_map) if isinstance(components_html_map, str) else (components_html_map or {})
    except Exception:
        cmap = {}
    pending = [b for b in blocks if isinstance(b, dict) and b.get('id') and b.get('id') not in cmap]
    return {'blocks_pending_json': json.dumps(pending, ensure_ascii=False), 'pending_count': len(pending)}

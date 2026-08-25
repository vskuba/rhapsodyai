"""
Сохранение ресурсов прототипа: изображения и маппинг блоков → UI-компоненты.

- planning_image_save — сохранение base64-изображений в папку проекта.
- planning_blocks_component_map — детерминированный маппинг блоков → UI-компоненты.

Соседние модули: `planning_prototype_state` — пути и хелперы версий.
"""
import base64
import hashlib
import json
import os
import re

from src.tool.project.planning.planning_prototype_state import (
    PROTOTYPE_FILES_DIR,
    _prototype_latest_version,
    _widget_to_ui_component,
)


# ── Сохранение изображений ──────────────────────────────────────────────────────

async def planning_image_save(project_id: int, image_b64: str, filename: str = '') -> dict:
    """
    Сохраняет base64-изображение в data/planning/{project_id}/public/images/.
     - project_id: ID проекта
     - image_b64: base64-строка изображения (PNG/JPEG)
     - filename: имя файла; если пусто — генерируется автоматически
    Returns:
        dict: saved (int), file_path (str), url_path (str)
    """
    project_id = int(project_id)
    image_b64 = str(image_b64 or '').strip()

    if not image_b64:
        return {'saved': 0, 'file_path': '', 'url_path': ''}

    try:
        img_bytes = base64.b64decode(image_b64)
    except Exception:
        return {'saved': 0, 'file_path': '', 'url_path': ''}

    version_num, version_dir = _prototype_latest_version(project_id)
    if not version_dir:
        version_num = 1
        version_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id), 'design', 'v1')
    images_dir = os.path.join(version_dir, 'public', 'images')
    os.makedirs(images_dir, exist_ok=True)

    if not filename:
        h = hashlib.md5(img_bytes[:256]).hexdigest()[:8]
        filename = f'img_{h}.png'

    safe_name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', filename)
    if '.' not in safe_name:
        safe_name += '.png'

    file_path = os.path.join(images_dir, safe_name)
    with open(file_path, 'wb') as f:
        f.write(img_bytes)

    url_path = f'/planning/preview/{project_id}/v{version_num}/public/images/{safe_name}'
    return {'saved': 1, 'file_path': file_path, 'url_path': url_path}


# ── Маппинг блоков → UI-компоненты ─────────────────────────────────────────────

async def planning_blocks_component_map(
    project_id: int,
    blocks_sections_json: str,
    page_blocks_raw_json: str = '',
    ui_components_list: str = '',
) -> dict:
    """
    Детерминированно маппит блоки страницы → UI-компоненты без LLM.
     - page_blocks_raw_json: JSON [{id, name, component, description}] — scaffold-блоки (приоритет)
     - blocks_sections_json: JSON [{block_id, block_name, block_description, widget_name, ...}]
    Returns:
        dict: blocks (JSON [{id, component, description}])
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute("SELECT name FROM project_design_ui_component")
        comp_rows = await db.fetchall()
    known_components = {r['name'] for r in (comp_rows or [])}

    raw_blocks = None
    if page_blocks_raw_json:
        try:
            raw_blocks = json.loads(page_blocks_raw_json) if isinstance(page_blocks_raw_json, str) else page_blocks_raw_json
        except Exception:
            raw_blocks = None

    if raw_blocks and isinstance(raw_blocks, list):
        blocks_out = []
        seen_ids: set = set()
        for b in raw_blocks:
            if not isinstance(b, dict):
                continue
            block_id = str(b.get('id') or '')
            block_name = str(b.get('name') or block_id)
            if block_id in seen_ids:
                continue
            seen_ids.add(block_id)
            component = _widget_to_ui_component('', block_name, known_components)
            blocks_out.append({'id': block_id, 'component': component, 'description': str(b.get('description') or f'{block_name} component')})
        return {'blocks': json.dumps(blocks_out, ensure_ascii=False)}

    def _make_id(name: str) -> str:
        base = re.sub(r'[^a-zA-Z0-9]', '_', str(name).lower()).strip('_')
        base = re.sub(r'_+', '_', base) or 'block'
        if not re.match(r'[a-z]', base[0]):
            base = 'block_' + base
        return base

    try:
        blocks_sections = json.loads(blocks_sections_json) if isinstance(blocks_sections_json, str) else (blocks_sections_json or [])
    except Exception:
        blocks_sections = []

    seen_ids2: set = set()
    blocks_out2 = []
    for b in (blocks_sections or []):
        if not isinstance(b, dict):
            continue
        widget_name = str(b.get('widget_name') or '')
        block_name = str(b.get('block_name') or '')
        block_id = _make_id(block_name) if block_name else str(b.get('block_id') or 'block')
        if block_id in seen_ids2:
            continue
        seen_ids2.add(block_id)
        component = _widget_to_ui_component(widget_name, block_name, known_components)
        blocks_out2.append({'id': block_id, 'component': component, 'description': str(b.get('block_description') or f'{block_name} component')})
    return {'blocks': json.dumps(blocks_out2, ensure_ascii=False)}

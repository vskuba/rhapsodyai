"""
Сохранение компонентов и страниц прототипа.

- planning_prototype_component_save — сохранение HTML-компонента в кэш и на диск.
- planning_prototype_page_assemble — вставка компонентов в каркас.
- planning_prototype_page_save — финальное сохранение HTML на диск.

Соседние модули: `planning_prototype_state` — пути и хелперы версий, `planning_prototype_scaffold` — каркас.
"""
import json
import os
import re

from src.tool.project.planning.planning_prototype_state import (
    PROTOTYPE_FILES_DIR,
    _prototype_latest_version,
    _prototype_next_version_dir,
)


# ── Сохранение компонентов ─────────────────────────────────────────────────────

async def planning_prototype_component_save(
    project_id: int, version: int,
    component_id: str, component_html: str,
    components_html_map: str,
) -> dict:
    """
    Сохраняет отрендеренный HTML-компонент в кэш и на диск.
     - project_id: ID проекта
     - version: версия прототипа
     - component_id: уникальный ID компонента
     - component_html: HTML-код компонента
     - components_html_map: текущий кэш {component_id: html} (JSON-строка)
    Returns:
        dict: components_html_map (обновлённый JSON), saved (int)
    """
    project_id = int(project_id)
    version = int(version or 0)
    component_id = str(component_id or '').strip()
    component_html = str(component_html or '').strip()
    try:
        cmap = json.loads(components_html_map) if isinstance(components_html_map, str) else (components_html_map or {})
    except Exception:
        cmap = {}

    if not component_id or not component_html:
        return {'components_html_map': json.dumps(cmap, ensure_ascii=False), 'saved': 0}

    cmap[component_id] = component_html

    if version > 0:
        comp_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id), 'design', f'v{version}', 'components')
        os.makedirs(comp_dir, exist_ok=True)
        safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', component_id)
        with open(os.path.join(comp_dir, f'{safe_id}.html'), 'w', encoding='utf-8') as f:
            f.write(component_html)

    return {'components_html_map': json.dumps(cmap, ensure_ascii=False), 'saved': 1}


# ── Сборка страницы ────────────────────────────────────────────────────────────

async def planning_prototype_page_assemble(
    scaffold_html: str,
    page_blocks_json: str,
    components_html_map: str,
) -> dict:
    """
    Собирает финальный HTML страницы: вставляет компоненты в каркас.
     - scaffold_html: HTML-каркас с <!-- BLOCK:id --> плейсхолдерами
     - page_blocks_json: JSON-массив [{id, component, description}]
     - components_html_map: JSON-словарь {component_id: html}
    Returns:
        dict: page_html (готовый HTML), blocks_injected (int)
    """
    scaffold_html = str(scaffold_html or '').strip()
    try:
        blocks = json.loads(page_blocks_json) if isinstance(page_blocks_json, str) else (page_blocks_json or [])
    except Exception:
        blocks = []
    try:
        cmap = json.loads(components_html_map) if isinstance(components_html_map, str) else (components_html_map or {})
    except Exception:
        cmap = {}

    page_html = scaffold_html
    injected = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        bid = str(block.get('id') or '').strip()
        if not bid:
            continue
        block_html = cmap.get(bid)
        if block_html:
            page_html = page_html.replace(f'<!-- BLOCK:{bid} -->', block_html)
            injected += 1

    return {'page_html': page_html, 'blocks_injected': injected}


# ── Обёртка в базовый шаблон ───────────────────────────────────────────────────

def _wrap_page_in_base_template(body_html: str, design_tokens: str = '{}', page_title: str = 'Page') -> str:
    try:
        tokens = json.loads(design_tokens) if isinstance(design_tokens, str) else design_tokens
    except Exception:
        tokens = {}
    tailwind_config = ''
    if tokens:
        tailwind_config = f'\n  <script>tailwind.config = {json.dumps({"theme": {"extend": tokens}}, ensure_ascii=False)}</script>'
    return (
        f'<!DOCTYPE html>\n<html lang="ru">\n<head>\n'
        f'  <meta charset="UTF-8">\n'
        f'  <meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'  <title>{page_title}</title>\n'
        f'  <script src="https://cdn.tailwindcss.com"></script>{tailwind_config}\n'
        f'</head>\n<body>\n{body_html}\n</body>\n</html>'
    )


# ── Сохранение страницы ────────────────────────────────────────────────────────

async def planning_prototype_page_save(
    project_id: int, version: int, filename: str, html_content: str,
    design_tokens: str = '{}', page_title: str = '',
) -> dict:
    """
    Сохраняет одну HTML-страницу прототипа. Если html_content — body-фрагмент,
    автоматически оборачивает в базовый шаблон с Tailwind и дизайн-токенами.
     - project_id: ID проекта
     - version: номер версии прототипа
     - filename: имя файла (index.html, dashboard.html, ...)
     - html_content: HTML страницы или body-фрагмент
     - design_tokens: JSON дизайн-токенов
     - page_title: заголовок страницы для <title>
    Returns:
        dict: saved (int), filename (str), preview_path (str)
    """
    project_id = int(project_id)
    version = int(version or 0)
    filename = str(filename or '').strip()
    html_content = str(html_content or '').strip()

    if not filename or not html_content:
        return {'saved': 0, 'filename': filename, 'preview_path': ''}

    if not html_content.lstrip().lower().startswith('<!doctype'):
        title = page_title or filename.replace('.html', '').replace('_', ' ').title()
        html_content = _wrap_page_in_base_template(html_content, design_tokens or '{}', title)

    safe_name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', filename)
    if not safe_name.endswith('.html'):
        safe_name += '.html'

    if version <= 0:
        version_num, version_dir = _prototype_latest_version(project_id)
        if not version_dir:
            version_num, version_dir = _prototype_next_version_dir(project_id)
    else:
        version_num = version
        version_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id), 'design', f'v{version_num}')

    os.makedirs(version_dir, exist_ok=True)

    with open(os.path.join(version_dir, safe_name), 'w', encoding='utf-8') as f:
        f.write(html_content)

    preview_path = f'/planning/preview/{project_id}/design/v{version_num}/'
    return {'saved': 1, 'filename': safe_name, 'preview_path': preview_path}

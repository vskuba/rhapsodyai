import json
import os
import re

from mysql_.mysql_ import mysql_get_db_async

PROTOTYPE_FILES_DIR = '/app/data/planning'

_TRANSLIT_MAP = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh',
    'з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o',
    'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts',
    'ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
}

_KEYWORD_COMPONENT_MAP = {
    'header': 'TopBar', 'topbar': 'TopBar', 'navbar': 'NavigationMenu',
    'navigation': 'NavigationMenu', 'menu': 'NavigationMenu', 'sidebar': 'NavigationMenu',
    'footer': 'Footer',
    'chart': 'DataTable', 'graph': 'DataTable', 'stats': 'DataTable', 'analytics': 'DataTable',
    'table': 'DataTable', 'datatable': 'DataTable', 'list': 'List',
    'form': 'Form', 'auth': 'Form', 'login': 'Form', 'register': 'Form', 'signup': 'Form',
    'search': 'SearchInput', 'filter': 'SearchInput',
    'card': 'Card', 'article': 'Card', 'content': 'Card', 'text': 'Card',
    'image': 'Card', 'photo': 'Carousel', 'carousel': 'Carousel',
    'tab': 'Tabs', 'accordion': 'Accordion',
    'progress': 'ProgressBar', 'step': 'StepProgress',
    'badge': 'Badge', 'alert': 'Alert', 'toast': 'Toast',
    'avatar': 'Avatar', 'user': 'Avatar',
    'button': 'Button', 'action': 'Button',
    'input': 'Input', 'textarea': 'Textarea', 'select': 'Select',
    'modal': 'Modal', 'drawer': 'Drawer', 'sheet': 'Sheet',
    'tree': 'TreeView', 'breadcrumb': 'Breadcrumb',
    'rating': 'Rating', 'slider': 'Slider', 'switch': 'Switch',
    'calendar': 'Calendar', 'date': 'DatePicker',
    'file': 'FileUpload', 'upload': 'FileUpload',
    'empty': 'EmptyState', 'error': 'EmptyState', 'notfound': 'EmptyState',
    'pricing': 'Card', 'plan': 'Card', 'feature': 'Card',
    'hero': 'Card', 'banner': 'Card', 'cta': 'Button',
    'comment': 'List', 'review': 'List',
    'dashboard': 'DataTable', 'summary': 'DataTable',
}


async def planning_prototype_context_load(project_id: int) -> dict:
    """
    Загружает контекст для генерации HTML-прототипа: дизайн-документ + идея проекта + дизайн-токены.
     - project_id: ID проекта
    Returns:
        dict:
            idea (str): исходная идея продукта.
            design_content (str): содержимое дизайн-документа.
            project_title (str): название проекта.
            design_tokens (str): JSON-строка дизайн-токенов для tailwind.config (или '{}').
            sitemap_pages_json (str): JSON-массив [{filename, title}].
            design_ui_components (str): раздел UI-компонентов из дизайн-документа.
            design_wireframes (str): раздел Вайрфреймы страниц из дизайн-документа.
            design_sitemap (str): раздел Карта страниц из дизайн-документа.
    """
    project_id = int(project_id)

    async with mysql_get_db_async() as db:
        await db.execute("SELECT title, idea FROM project WHERE id = %s", (project_id,))
        proj = await db.fetchone()

        await db.execute(
            "SELECT content FROM project_planning_document WHERE project_id = %s AND doc_type = 'design' ORDER BY id DESC LIMIT 1",
            (project_id,)
        )
        design_doc = await db.fetchone()

        if not design_doc:
            await db.execute(
                "SELECT content FROM project_planning_document WHERE project_id = %s AND doc_type = 'blueprint' ORDER BY id DESC LIMIT 1",
                (project_id,)
            )
            design_doc = await db.fetchone()

        await db.execute(
            "SELECT content FROM project_planning_document WHERE project_id = %s AND doc_type = 'design_tokens' ORDER BY id DESC LIMIT 1",
            (project_id,)
        )
        tokens_doc = await db.fetchone()

    design_tokens = str((tokens_doc or {}).get('content') or '{}').strip()
    try:
        json.loads(design_tokens)
    except Exception:
        design_tokens = '{}'

    design_content_str = str((design_doc or {}).get('content') or '')
    sitemap_pages = _parse_sitemap_pages(design_content_str)

    if not sitemap_pages:
        async with mysql_get_db_async() as db:
            await db.execute(
                "SELECT name, page_type FROM project_design_prototype_page "
                "WHERE project_id = %s AND parent_id IS NULL ORDER BY order_index",
                (project_id,)
            )
            db_pages = await db.fetchall()
        for i, p in enumerate(db_pages or []):
            name = str(p['name'] or '').strip()
            if not name:
                continue
            if i == 0:
                filename = 'index.html'
            else:
                filename = _sitemap_filename(name)
                if not filename:
                    filename = _transliterate_filename(name)
            sitemap_pages.append({'filename': filename, 'title': name})

    design_sitemap = _extract_md_section(design_content_str, 'Карта страниц')
    if not design_sitemap and sitemap_pages:
        design_sitemap = '\n'.join(f'- {p["filename"]} ({p["title"]})' for p in sitemap_pages)

    return {
        'idea':                str((proj or {}).get('idea') or ''),
        'design_content':      design_content_str,
        'project_title':       str((proj or {}).get('title') or ''),
        'design_tokens':       design_tokens,
        'sitemap_pages_json':  json.dumps(sitemap_pages, ensure_ascii=False),
        'design_ui_components': _extract_md_section(design_content_str, 'UI-компоненты'),
        'design_wireframes':   _extract_md_section(design_content_str, 'Вайрфреймы страниц'),
        'design_sitemap':      design_sitemap,
    }


async def planning_prototype_init(project_id: int) -> dict:
    """
    Создаёт новую версионированную директорию прототипа и запись project_planning_document.
     - project_id: ID проекта
    Returns:
        dict: version (int), doc_id (int), preview_path (str)
    """
    project_id = int(project_id)
    version_num, version_dir = _prototype_next_version_dir(project_id)
    os.makedirs(version_dir, exist_ok=True)

    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_planning_document (project_id, doc_type, title, content, version, status) "
            "VALUES (%s, 'prototype', %s, '', %s, 'final')",
            (project_id, f'HTML Прототип v{version_num}', version_num)
        )
        doc_id = db.lastrowid
        await db.connection.commit()

    preview_path = f'/planning/preview/{project_id}/design/v{version_num}/'
    return {'version': version_num, 'doc_id': doc_id, 'preview_path': preview_path}


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


async def planning_prototype_save(project_id: int, html_content: str, html_pages_json: str = '') -> dict:
    """
    Сохраняет HTML-прототип в новую версионированную директорию и создаёт запись prototype.
     - project_id: ID проекта
     - html_content: HTML-код главной страницы (index.html)
     - html_pages_json: JSON-строка {"features.html": "...HTML..."}
    Returns:
        dict: saved (int), doc_id (int), page_count (int), preview_path (str), version (int)
    """
    project_id = int(project_id)
    html_content = str(html_content or '').strip()
    html_pages_json = str(html_pages_json or '').strip()

    if not html_content:
        return {'saved': 0, 'doc_id': 0, 'page_count': 0, 'preview_path': '', 'version': 0}

    version_num, version_dir = _prototype_next_version_dir(project_id)
    os.makedirs(version_dir, exist_ok=True)

    with open(os.path.join(version_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html_content)

    page_count = 1
    if html_pages_json:
        try:
            pages = json.loads(html_pages_json)
            if isinstance(pages, dict):
                for fname, page_html in pages.items():
                    safe_name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', fname)
                    if not safe_name.endswith('.html'):
                        safe_name += '.html'
                    with open(os.path.join(version_dir, safe_name), 'w', encoding='utf-8') as f:
                        f.write(str(page_html or ''))
                    page_count += 1
        except Exception:
            pass

    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_planning_document (project_id, doc_type, title, content, version, status) "
            "VALUES (%s, 'prototype', %s, %s, %s, 'final')",
            (project_id, f'HTML Прототип v{version_num}', html_content, version_num)
        )
        doc_id = db.lastrowid
        await db.connection.commit()

    preview_path = f'/planning/preview/{project_id}/design/v{version_num}/'
    return {'saved': 1, 'doc_id': doc_id, 'page_count': page_count, 'preview_path': preview_path, 'version': version_num}


async def planning_prototype_pages_patch(project_id: int, html_pages_patch_json: str) -> dict:
    """
    Сохраняет недостающие/исправленные HTML-страницы прототипа на диск (не трогает index.html).
     - html_pages_patch_json: JSON-строка {"page.html": "...HTML..."}
    """
    project_id = int(project_id)
    patch = str(html_pages_patch_json or '').strip()
    if not patch or patch in ('{}', '[]', ''):
        return {'saved': 0, 'page_count': 0}
    try:
        pages = json.loads(patch)
        if not isinstance(pages, dict):
            return {'saved': 0, 'page_count': 0}
    except Exception:
        return {'saved': 0, 'page_count': 0}

    _, version_dir = _prototype_latest_version(project_id)
    if not version_dir:
        _, version_dir = _prototype_next_version_dir(project_id)
    os.makedirs(version_dir, exist_ok=True)

    count = 0
    for filename, page_html in pages.items():
        safe_name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', str(filename))
        if not safe_name.endswith('.html'):
            safe_name += '.html'
        with open(os.path.join(version_dir, safe_name), 'w', encoding='utf-8') as fh:
            fh.write(str(page_html or ''))
        count += 1

    return {'saved': 1, 'page_count': count}


async def planning_pages_check(project_id: int) -> dict:
    """
    Проверяет соответствие HTML-файлов в папке проекта карте страниц из дизайн-документа.
    Returns:
      sitemap_pages_json, existing_pages_json, missing_pages_json, unlinked_pages_json, needs_fix
    """
    project_id = int(project_id)
    project_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id))

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT content FROM project_planning_document WHERE project_id = %s AND doc_type = 'design' ORDER BY id DESC LIMIT 1",
            (project_id,)
        )
        doc = await db.fetchone()

    sitemap_pages = _parse_sitemap_pages(str((doc or {}).get('content') or ''))

    existing = []
    page_html: dict[str, str] = {}
    if os.path.isdir(project_dir):
        for fname in sorted(os.listdir(project_dir)):
            if fname.endswith('.html'):
                existing.append(fname)
                try:
                    with open(os.path.join(project_dir, fname), encoding='utf-8') as fh:
                        page_html[fname] = fh.read()
                except Exception:
                    page_html[fname] = ''

    outgoing: dict[str, set] = {}
    for fname, html in page_html.items():
        outgoing[fname] = set(re.findall(r'href=["\']([a-zA-Z0-9_\-]+\.html)["\']', html))

    incoming: dict[str, int] = {f: 0 for f in existing}
    for fname, links in outgoing.items():
        for linked in links:
            if linked in incoming:
                incoming[linked] += 1

    sitemap_filenames = [p['filename'] for p in sitemap_pages]
    missing = [f for f in sitemap_filenames if f not in existing]
    unlinked = [f for f in existing if f != 'index.html' and incoming.get(f, 0) == 0]

    return {
        'sitemap_pages_json':  json.dumps(sitemap_pages, ensure_ascii=False),
        'existing_pages_json': json.dumps(existing, ensure_ascii=False),
        'missing_pages_json':  json.dumps(missing, ensure_ascii=False),
        'unlinked_pages_json': json.dumps(unlinked, ensure_ascii=False),
        'needs_fix':           'yes' if (missing or unlinked) else 'no',
    }


async def planning_prototype_qa_scan(project_id: int, version: int = 0) -> dict:
    """
    QA-проверка прототипа: BFS-обход HTML-файлов по ссылкам.
     - project_id: ID проекта
     - version: номер версии прототипа (0 = последняя)
    Returns:
        dict: version, pages_checked, ok, issues, entry_points, qa_summary
    """
    from src.tool.web.web_ import html_crawl
    from bs4 import BeautifulSoup as _BS

    project_id = int(project_id)
    version = int(version)

    design_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id), 'design')
    if not os.path.isdir(design_dir):
        return {'error': 'No prototype directory', 'qa_summary': 'Прототип не найден.', 'pages_checked': 0, 'ok': 0, 'issues': 0, 'entry_points': 0, 'version': 0}

    if version == 0:
        existing = [d for d in os.listdir(design_dir) if d.startswith('v') and d[1:].isdigit() and os.path.isdir(os.path.join(design_dir, d))]
        if not existing:
            return {'error': 'No prototype versions', 'qa_summary': 'Версии не найдены.', 'pages_checked': 0, 'ok': 0, 'issues': 0, 'entry_points': 0, 'version': 0}
        version = max(int(d[1:]) for d in existing)

    version_dir = os.path.join(design_dir, f'v{version}')
    index_html = os.path.join(version_dir, 'index.html')

    if not os.path.isfile(index_html):
        html_files = sorted(f for f in os.listdir(version_dir) if f.endswith('.html') and os.path.isfile(os.path.join(version_dir, f)))
        if not html_files:
            return {'error': f'No HTML files in v{version}', 'qa_summary': f'HTML-файлы не найдены в v{version}.', 'pages_checked': 0, 'ok': 0, 'issues': 0, 'entry_points': 0, 'version': version}
        index_html = os.path.join(version_dir, html_files[0])

    project_title = ''
    try:
        async with mysql_get_db_async() as db:
            await db.execute("SELECT title FROM project WHERE id=%s", (project_id,))
            row = await db.fetchone()
            if row:
                project_title = str(row['title'] or '')
    except Exception:
        pass

    expected_pages: dict[str, dict] = {}
    try:
        ctx = await planning_prototype_context_load(project_id)
        sitemap_pages = json.loads(ctx.get('sitemap_pages_json') or '[]')
        async with mysql_get_db_async() as db:
            await db.execute(
                "SELECT name, page_type, tags FROM project_design_prototype_page WHERE project_id=%s AND parent_id IS NULL ORDER BY order_index",
                (project_id,)
            )
            db_pages = await db.fetchall()
        meta_by_name = {str(r['name']).lower().strip(): r for r in (db_pages or [])}
        for p in sitemap_pages:
            pname = str(p.get('title') or '').lower().strip()
            db_row = meta_by_name.get(pname) or {}
            page_type = str(db_row.get('page_type') or 'feature')
            raw_tags = str(db_row.get('tags') or '')
            tag_list = [t.strip().lower() for t in raw_tags.split(',') if t.strip()]
            if page_type == 'technical' and 'direct' not in tag_list:
                tag_list.append('direct')
            expected_pages[p['filename']] = {'title': p.get('title', ''), 'tags': tag_list}
    except Exception:
        pass

    entry_points: list[str] = [index_html]
    index_fname = os.path.basename(index_html)
    for fname, meta in expected_pages.items():
        if fname == index_fname:
            continue
        if 'index' in meta['tags']:
            fpath = os.path.join(version_dir, fname)
            if os.path.isfile(fpath):
                entry_points.append(fpath)

    all_reached: dict[str, dict] = {}
    all_broken: list[dict] = []

    for ep in entry_points:
        ep_name = os.path.basename(ep)
        via = 'main_crawl' if ep == index_html else f'index:{ep_name}'
        result = await html_crawl(ep, version_dir)
        for p in result.get('pages_found', []):
            fname = p['file']
            if fname not in all_reached:
                all_reached[fname] = {**p, 'via': via}
        for b in result.get('broken_links', []):
            key = (b['href'], b['on_page'])
            if not any((x['href'], x['on_page']) == key for x in all_broken):
                all_broken.append(b)

    direct_checked: list[dict] = []
    reached_fnames = set(all_reached.keys())
    for fname, meta in sorted(expected_pages.items()):
        if 'direct' not in meta['tags'] or fname in reached_fnames:
            continue
        fpath = os.path.join(version_dir, fname)
        if not os.path.isfile(fpath):
            direct_checked.append({'page': fname, 'label': meta['title'], 'status': 'missing', 'via': 'direct', 'note': 'Файл не найден'})
            continue
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                text_len = len(_BS(fh.read(), 'html.parser').get_text().strip())
            direct_checked.append({'page': fname, 'label': meta['title'], 'status': 'ok' if text_len > 50 else 'empty', 'via': 'direct'})
        except Exception as e:
            direct_checked.append({'page': fname, 'label': meta['title'], 'status': 'error', 'via': 'direct', 'note': str(e)[:100]})

    pages_result: list[dict] = []
    for fname, info in sorted(all_reached.items(), key=lambda x: (x[1].get('depth', 0), x[0])):
        title = expected_pages.get(fname, {}).get('title', '') or fname
        pages_result.append({'page': fname, 'label': title, 'status': info['status'],
                              'depth': info.get('depth', 0), 'via': info['via'],
                              'linked_from': info.get('linked_from', '')})
    pages_result.extend(direct_checked)

    all_handled = {p['page'] for p in pages_result}
    for fname, meta in sorted(expected_pages.items()):
        if fname in all_handled or fname == index_fname:
            continue
        if 'direct' in meta['tags'] or 'index' in meta['tags']:
            continue
        pages_result.append({'page': fname, 'label': meta['title'], 'status': 'not_linked', 'via': 'none', 'note': 'Страница не слинкована'})

    ok_pages = [p for p in pages_result if p['status'] == 'ok']
    issue_pages = [p for p in pages_result if p['status'] != 'ok']

    lines = [
        f'## QA-отчёт прототипа: {project_title} (v{version})',
        '',
        f'**Проверено:** {len(pages_result)} | **OK:** {len(ok_pages)} | **Проблемы:** {len(issue_pages)}',
        f'**Точек входа:** {len(entry_points)}',
        '',
        '### ✅ Страницы — OK',
    ]
    for p in ok_pages:
        via_str = f' *({p["via"]})*' if p.get('via') != 'main_crawl' else ''
        depth_str = f' depth={p["depth"]}' if p.get('depth') else ''
        lines.append(f'- `{p["page"]}` ({p["label"]}){via_str}{depth_str}')

    if issue_pages:
        lines.extend(['', '### ❌ Проблемы'])
        for p in issue_pages:
            lines.append(f'- `{p["page"]}` ({p["label"]}) — **{p["status"]}** {p.get("note", "")}')

    if all_broken:
        lines.extend(['', '### 🔗 Битые ссылки'])
        for b in all_broken[:20]:
            lines.append(f'- `{b["href"]}` на `{b["on_page"]}`')

    html_count = len([f for f in os.listdir(version_dir) if f.endswith('.html') and os.path.isfile(os.path.join(version_dir, f))])
    lines.append(f'\n**Версия:** v{version} | **Файлов на диске:** {html_count}')

    return {
        'version':       version,
        'pages_checked': len(pages_result),
        'ok':            len(ok_pages),
        'issues':        len(issue_pages),
        'entry_points':  len(entry_points),
        'qa_summary':    '\n'.join(lines),
    }


async def planning_image_save(project_id: int, image_b64: str, filename: str = '') -> dict:
    """
    Сохраняет base64-изображение в data/planning/{project_id}/public/images/.
     - project_id: ID проекта
     - image_b64: base64-строка изображения (PNG/JPEG)
     - filename: имя файла; если пусто — генерируется автоматически
    Returns:
        dict: saved (int), file_path (str), url_path (str)
    """
    import base64 as _b64
    project_id = int(project_id)
    image_b64 = str(image_b64 or '').strip()

    if not image_b64:
        return {'saved': 0, 'file_path': '', 'url_path': ''}

    try:
        img_bytes = _b64.b64decode(image_b64)
    except Exception:
        return {'saved': 0, 'file_path': '', 'url_path': ''}

    version_num, version_dir = _prototype_latest_version(project_id)
    if not version_dir:
        version_num = 1
        version_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id), 'design', 'v1')
    images_dir = os.path.join(version_dir, 'public', 'images')
    os.makedirs(images_dir, exist_ok=True)

    if not filename:
        import hashlib
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


async def planning_sitemap_check(project_id: int) -> dict:
    """
    Проверяет покрытие sitemap: находит дыры, orphan-страницы, непокрытые роли/сущности.
     - project_id: ID проекта
    Returns:
        dict:
            sitemap_data (str): текстовый отчёт для LLM
            total_pages (int): общее количество страниц
            total_blocks (int): общее количество блоков
    """
    import json as _json
    project_id = int(project_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, parent_id, name, description, page_type, roles "
            "FROM project_design_prototype_page WHERE project_id = %s ORDER BY order_index",
            (project_id,)
        )
        page_rows = await db.fetchall()

        await db.execute(
            "SELECT id, name, created_by FROM project_design_ui_block WHERE project_id = %s",
            (project_id,)
        )
        block_rows = await db.fetchall()

        await db.execute("SELECT roles, entities FROM project WHERE id = %s", (project_id,))
        proj = await db.fetchone()

    pages = [dict(r) for r in page_rows]

    roles_raw = (proj or {}).get('roles') or '[]'
    entities_raw = (proj or {}).get('entities') or '[]'
    try:
        roles = _json.loads(roles_raw) if isinstance(roles_raw, str) else roles_raw
    except Exception:
        roles = []
    try:
        entities = _json.loads(entities_raw) if isinstance(entities_raw, str) else entities_raw
    except Exception:
        entities = []

    by_type: dict = {}
    by_role: dict = {}
    for p in pages:
        pt = p.get('page_type') or 'feature'
        by_type[pt] = by_type.get(pt, 0) + 1
        for r in str(p.get('roles') or '').split(','):
            r = r.strip()
            if r:
                by_role.setdefault(r, []).append(p['name'])

    has_404 = any('404' in p['name'] or 'Not Found' in p['name'] for p in pages)
    has_500 = any('500' in p['name'] or 'Ошибка' in p['name'] for p in pages)
    has_auth = any(p.get('page_type') == 'auth' for p in pages)

    lines = [
        '=== SITEMAP SUMMARY ===',
        f"Всего страниц: {len(pages)} (feature: {by_type.get('feature', 0)}, auth: {by_type.get('auth', 0)}, technical: {by_type.get('technical', 0)})",
        f"Роли в проекте: {', '.join(roles) if roles else 'не определены'}",
        f"Сущности: {', '.join(str(e) for e in entities[:15]) if entities else 'не определены'}",
        f"Страница 404: {'да' if has_404 else 'НЕТ'}",
        f"Страница 500: {'да' if has_500 else 'НЕТ'}",
        f"Auth-страницы: {'есть' if has_auth else 'НЕТ'}",
        '',
        f'=== СТРАНИЦЫ ({len(pages)}) ===',
    ]
    for p in pages:
        indent = '  ' if p.get('parent_id') else ''
        lines.append(f"{indent}- {p['name']} [{p.get('page_type', '?')}] roles={p.get('roles', '')}")

    lines.append('')
    lines.append(f'=== БЛОКИ ({len(block_rows)}) ===')
    for b in block_rows:
        lines.append(f"- {b['name']}")

    lines.append('')
    lines.append('=== ПОКРЫТИЕ ПО РОЛЯМ ===')
    for role, pg_names in by_role.items():
        lines.append(f"{role}: {len(pg_names)} стр. — {', '.join(pg_names[:5])}")

    return {
        'sitemap_data': '\n'.join(lines),
        'total_pages': len(pages),
        'total_blocks': len(block_rows),
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _prototype_next_version_dir(project_id: int) -> tuple[int, str]:
    design_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id), 'design')
    os.makedirs(design_dir, exist_ok=True)
    existing = [d for d in os.listdir(design_dir) if d.startswith('v') and d[1:].isdigit() and os.path.isdir(os.path.join(design_dir, d))]
    version_num = max((int(d[1:]) for d in existing), default=0) + 1
    return version_num, os.path.join(design_dir, f'v{version_num}')


def _prototype_latest_version(project_id: int) -> tuple[int, str] | tuple[None, None]:
    design_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id), 'design')
    if not os.path.isdir(design_dir):
        return None, None
    existing = [d for d in os.listdir(design_dir) if d.startswith('v') and d[1:].isdigit() and os.path.isdir(os.path.join(design_dir, d))]
    if not existing:
        return None, None
    version_num = max(int(d[1:]) for d in existing)
    return version_num, os.path.join(design_dir, f'v{version_num}')


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


def _transliterate_filename(name: str) -> str:
    slug = ''.join(_TRANSLIT_MAP.get(c, c) for c in name.lower())
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
    return (slug or 'page') + '.html'


def _sitemap_filename(raw: str) -> str:
    raw = raw.strip().strip('`').strip()
    if not raw or raw.lower() in ('файл', 'url', 'страница', 'file', 'page', 'filename', '---', '-'):
        return ''
    raw = raw.split('?')[0].split('#')[0].rstrip('/')
    part = raw.split('/')[-1]
    if not part or part == '.':
        part = 'index'
    part = re.sub(r'[^a-zA-Z0-9_\-]', '_', part).strip('_')
    if not part or not re.search(r'[a-zA-Z0-9]', part):
        return ''
    if not part.endswith('.html'):
        part += '.html'
    return part.lower()


def _extract_md_section(markdown_text: str, heading: str) -> str:
    pattern = r'##\s+' + re.escape(heading) + r'[^\n]*\n(.*?)(?=\n##\s|\Z)'
    m = re.search(pattern, markdown_text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ''


def _parse_sitemap_pages(markdown_text: str) -> list[dict]:
    m = re.search(r'##\s+Карта\s+страниц[^\n]*\n(.*?)(?=\n##\s|\Z)', markdown_text, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    section = m.group(1)
    seen, pages = set(), []
    for line in section.split('\n'):
        line = line.strip()
        if line.startswith('|'):
            cols = [c.strip() for c in line.strip('|').split('|')]
            if len(cols) < 2:
                continue
            filename = _sitemap_filename(cols[0])
            if not filename:
                continue
            title = cols[1].strip()
        elif re.match(r'^[\*\-]\s+', line):
            bullet_m = re.match(r'^[\*\-]\s+`?(\S+?)`?\s+\(([^)]+)\)', line)
            if not bullet_m:
                continue
            filename = _sitemap_filename(bullet_m.group(1))
            if not filename:
                continue
            title = bullet_m.group(2).strip()
        else:
            continue
        if filename not in seen:
            seen.add(filename)
            pages.append({'filename': filename, 'title': title})
    return pages


def _widget_to_ui_component(widget_name: str, block_name: str, known_components: set) -> str:
    if widget_name in known_components:
        return widget_name
    if block_name in known_components:
        return block_name
    tokens = [t.lower() for t in re.findall(r'[A-Z][a-z]+|[a-z]+|[A-Z]+(?=[A-Z]|$)', widget_name or block_name)]
    for token in tokens:
        if token in _KEYWORD_COMPONENT_MAP:
            candidate = _KEYWORD_COMPONENT_MAP[token]
            if candidate in known_components:
                return candidate
    return 'Card'

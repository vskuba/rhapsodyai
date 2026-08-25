import json
import os
import re

from mysql_.mysql_ import mysql_get_db_async
from src.tool.project.planning.planning_prototype import planning_prototype_context_load
from src.tool.project.planning.planning_prototype_state import (
    PROTOTYPE_FILES_DIR,
    _KEYWORD_COMPONENT_MAP,
    _parse_sitemap_pages,
    _prototype_latest_version,
    _prototype_next_version_dir,
    _widget_to_ui_component,
)


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

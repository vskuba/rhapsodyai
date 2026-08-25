"""
QA-проверка прототипа: BFS-обход HTML-файлов по ссылкам, отчёт по страницам.

- planning_prototype_qa_scan — полный QA-отчёт: проверенные/битые страницы,
  ссылки, точки входа, сводка Markdown.

Соседние модули: `planning_prototype` — загрузка контекста, `planning_prototype_state` — пути и парсинг, `planning_prototype_render` — сохранение.
"""
import json
import os

from mysql_.mysql_ import mysql_get_db_async
from src.tool.project.planning.planning_prototype import planning_prototype_context_load
from src.tool.project.planning.planning_prototype_state import (
    PROTOTYPE_FILES_DIR,
    _parse_sitemap_pages,
)


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

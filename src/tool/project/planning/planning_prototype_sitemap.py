"""
Проверки sitemap и соответствия файлов карточке страниц.

- planning_pages_check — сверяет .html-файлы на диске с картой из дизайн-документа,
  ищет пропущенные и неотлинкованные страницы.
- planning_sitemap_check — отчёт по sitemap: роли, сущности, типы страниц, блоки.

Соседние модули: `planning_prototype_state` — пути и парсинг sitemap,
`planning_prototype_qa` — BFS-обход HTML-файлов, `planning_prototype_render` — сохранение.
"""
import json
import os
import re

from mysql_.mysql_ import mysql_get_db_async
from src.tool.project.planning.planning_prototype_state import (
    PROTOTYPE_FILES_DIR,
    _parse_sitemap_pages,
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

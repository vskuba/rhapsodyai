import json
import os
import re

from mysql_.mysql_ import mysql_get_db_async
from src.tool.project.planning.planning_prototype_state import (
    PROTOTYPE_FILES_DIR,
    _extract_md_section,
    _parse_sitemap_pages,
    _prototype_latest_version,
    _prototype_next_version_dir,
    _sitemap_filename,
    _transliterate_filename,
)


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

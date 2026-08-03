import os
import re

from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response, RedirectResponse

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.project.planning.planning_document_repository import PlanningDocumentRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.uvicorn.routers.project.project_common import (
    _PROTOTYPE_DIR, _MIME_MAP, _WIDGET_SCRIPT, _doc_filename, _markdown_to_pdf,
)

router = APIRouter()

_DOCS_DIR = '/app/docs/planning'

_PLACEHOLDER_RE = re.compile(r'^\{.*\}$|^\[.*\]$')

_phase_sections_cache: dict | None = None


@router.get('/planning/phase-sections')
async def project_planning_phase_sections(request: Request, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    global _phase_sections_cache
    if _phase_sections_cache is None:
        _phase_sections_cache = await _build_phase_sections()
    return {'result': _phase_sections_cache}


@router.get('/planning/document/{doc_id}')
async def project_planning_document_get(request: Request, doc_id: int,
                                        user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningDocumentRepository()
    return {'result': await repo.find(doc_id)}


@router.get('/planning/document/{doc_id}/view')
async def project_planning_document_view(request: Request, doc_id: int,
                                         user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Отдаёт документ как HTML-страницу. Для prototype — редирект на версионированную директорию."""
    repo = PlanningDocumentRepository()
    doc = await repo.find(doc_id)
    if not doc:
        return Response(content='Not found', status_code=404)
    if doc.get('doc_type') == 'prototype':
        project_id = doc.get('project_id')
        version_num = doc.get('version') or 1
        if project_id:
            version_dir = os.path.join(_PROTOTYPE_DIR, str(project_id), 'design', f'v{version_num}')
            if os.path.isfile(os.path.join(version_dir, 'index.html')):
                return RedirectResponse(url=f'/planning/preview/{project_id}/design/v{version_num}/index.html',
                                        status_code=302)
            # Обратная совместимость: старые прототипы без версии лежат прямо в project_dir
            legacy_dir = os.path.join(_PROTOTYPE_DIR, str(project_id))
            if os.path.isfile(os.path.join(legacy_dir, 'index.html')):
                return RedirectResponse(url=f'/planning/preview/{project_id}/index.html', status_code=302)
    content = str(doc.get('content') or '')
    return Response(content=content.encode('utf-8'), media_type='text/html; charset=utf-8')


@router.get('/planning/project/{project_id}/prototypes')
async def project_prototypes(request: Request, project_id: int,
                             user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Список всех версий прототипа проекта."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, version, title, status, created_at FROM project_planning_document "
            "WHERE project_id = %s AND doc_type = 'prototype' ORDER BY version DESC",
            (project_id,)
        )
        rows = await db.fetchall()
    result = []
    for r in (rows or []):
        version_num = r['version'] or 1
        version_dir = os.path.join(_PROTOTYPE_DIR, str(project_id), 'design', f'v{version_num}')
        has_files = os.path.isfile(os.path.join(version_dir, 'index.html'))
        result.append({
            'doc_id': r['id'],
            'version': version_num,
            'title': r['title'],
            'status': r['status'],
            'created_at': r['created_at'],
            'preview_url': f'/planning/preview/{project_id}/design/v{version_num}/index.html' if has_files else None,
        })
    return {'result': result}


@router.delete('/planning/project/{project_id}/prototype/{version}')
async def planning_prototype_version_delete(
        request: Request, project_id: int, version: int,
        user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))
):
    """Удаляет конкретную версию прототипа (файлы + DB запись)."""
    import shutil
    async with mysql_get_db_async() as db:
        await db.execute(
            "DELETE FROM project_planning_document WHERE project_id = %s AND doc_type = 'prototype' AND version = %s",
            (project_id, version)
        )
        await db.connection.commit()
    version_dir = os.path.join(_PROTOTYPE_DIR, str(project_id), 'design', f'v{version}')
    if os.path.isdir(version_dir):
        shutil.rmtree(version_dir, ignore_errors=True)
    return {'result': {'project_id': project_id, 'version': version}}


@router.get('/planning/preview/{project_id}/{path:path}')
async def planning_preview_file(request: Request, project_id: int, path: str,
                                user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Отдаёт статические файлы прототипа. Поддерживает v{N}/ префикс и legacy пути."""
    from fastapi import HTTPException
    if not path:
        path = 'index.html'
    safe_path = os.path.normpath(path).lstrip('/')
    if '..' in safe_path:
        raise HTTPException(status_code=400, detail='Bad path')
    file_path = os.path.join(_PROTOTYPE_DIR, str(project_id), safe_path)
    if not os.path.isfile(file_path):
        # Fallback: ссылки вида journalist/dashboard.html → journalist_dashboard.html
        parts = safe_path.split('/')
        for i, part in enumerate(parts):
            if part.startswith('v') and part[1:].isdigit():
                remaining = parts[i + 1:]
                if len(remaining) > 1:
                    flat_name = '_'.join(remaining)
                    flat_path = os.path.join(_PROTOTYPE_DIR, str(project_id), *parts[:i + 1], flat_name)
                    if os.path.isfile(flat_path):
                        correct_url = '/planning/preview/' + str(project_id) + '/' + '/'.join(
                            parts[:i + 1]) + '/' + flat_name
                        return RedirectResponse(url=correct_url, status_code=302)
                break
        raise HTTPException(status_code=404, detail='File not found')
    ext = os.path.splitext(file_path)[1].lower()
    media_type = _MIME_MAP.get(ext, 'application/octet-stream')
    with open(file_path, 'rb') as f:
        content = f.read()
    if ext == '.html':
        html = content.decode('utf-8', errors='replace')
        snippet = _WIDGET_SCRIPT.format(pid=project_id, pn=safe_path.replace('"', ''))
        idx = html.lower().rfind('</body>')
        html = (html[:idx] + snippet + '\n' + html[idx:]) if idx >= 0 else html + '\n' + snippet
        content = html.encode('utf-8')
    return Response(content=content, media_type=media_type)


@router.get('/planning/document/{doc_id}/download')
async def project_planning_document_download(request: Request, doc_id: int,
                                             user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningDocumentRepository()
    doc = await repo.find(doc_id)
    if not doc:
        return Response(content='Not found', status_code=404)
    content = str(doc.get('content') or '')
    doc_title = str(doc.get('title') or doc.get('doc_type') or 'document')
    filename = await _doc_filename(doc.get('project_id'), doc.get('doc_type'), doc_title, 'md')
    return Response(
        content=content.encode('utf-8'),
        media_type='text/markdown; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@router.get('/planning/document/{doc_id}/download/pdf')
async def project_planning_document_download_pdf(request: Request, doc_id: int,
                                                 user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningDocumentRepository()
    doc = await repo.find(doc_id)
    if not doc:
        return Response(content='Not found', status_code=404)
    content = str(doc.get('content') or '')
    doc_title = str(doc.get('title') or doc.get('doc_type') or 'document')
    filename = await _doc_filename(doc.get('project_id'), doc.get('doc_type'), doc_title, 'pdf')
    pdf_bytes = _markdown_to_pdf(doc_title, content)
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


async def _load_phase_source() -> list[dict]:
    async with mysql_get_db_async() as db:
        await db.execute('SELECT phase_key, title, doc_file, header_mode FROM project_planning_phase_source')
        rows = await db.fetchall()
    return list(rows or [])


def _parse_doc_sections(filename: str, mode: str) -> list[str]:
    """mode: 'output_template' — берём ## под первым # {…} заголовком;
             '## ' / '### ' — берём заголовки с этим префиксом."""
    path = os.path.join(_DOCS_DIR, filename)
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()

    if mode == 'output_template':
        in_template = False
        sections = []
        for line in lines:
            stripped = line.rstrip()
            if stripped.startswith('# ') and not stripped.startswith('## '):
                in_template = '{' in stripped
                continue
            if not in_template:
                continue
            if stripped.startswith('## ') and not stripped.startswith('### '):
                raw = stripped[3:].strip()
                if raw and not _PLACEHOLDER_RE.match(raw):
                    sections.append(raw)
        return sections

    prefix = mode  # '## ' or '### '
    prefix_len = len(prefix)
    sections = []
    for line in lines:
        stripped = line.rstrip()
        if stripped.startswith(prefix) and not stripped[prefix_len:].startswith('#'):
            raw = stripped[prefix_len:].strip()
            if raw and not _PLACEHOLDER_RE.match(raw):
                sections.append(raw)
    return sections


async def _build_phase_sections() -> dict:
    source = await _load_phase_source()
    sections: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    for row in source:
        phase_key = row['phase_key']
        titles[phase_key] = row['title']
        if row['doc_file']:
            sections[phase_key] = _parse_doc_sections(row['doc_file'], row['header_mode'])
    return {'sections': sections, 'titles': titles}

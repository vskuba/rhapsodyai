import os

from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.uvicorn.routers.project import project_document as project_planning_document

_DOCS_DIR = '/app/docs/planning'

router = APIRouter()


@router.get('/planning/phase-source/doc/{filename}')
async def project_planning_phase_source_doc(
    request: Request,
    filename: str,
    user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW])),
):
    if '/' in filename or '..' in filename:
        return Response(content='Bad filename', status_code=400)
    path = os.path.join(_DOCS_DIR, filename)
    if not os.path.isfile(path):
        return Response(content='Not found', status_code=404)
    with open(path, encoding='utf-8') as f:
        content = f.read()
    return Response(content=content.encode('utf-8'), media_type='text/plain; charset=utf-8')


@router.get('/planning/phase-source/list')
async def project_planning_phase_source_list(
    request: Request,
    user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, phase_key, title, doc_file, header_mode '
            'FROM project_planning_phase_source ORDER BY id'
        )
        rows = await db.fetchall()
    return {'result': list(rows or [])}


@router.post('/planning/phase-source')
async def project_planning_phase_source_create(
    request: Request,
    user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW])),
):
    body = await request.json()
    phase_key = str(body.get('phase_key', '')).strip()
    title = str(body.get('title', '')).strip()
    doc_file = str(body.get('doc_file', '')).strip()
    header_mode = str(body.get('header_mode', '## ')).strip()

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_planning_phase_source (phase_key, title, doc_file, header_mode) '
            'VALUES (%s, %s, %s, %s)',
            (phase_key, title, doc_file, header_mode),
        )
        new_id = db.lastrowid
        await db.execute('SELECT id, phase_key, title, doc_file, header_mode FROM project_planning_phase_source WHERE id=%s', (new_id,))
        row = await db.fetchone()

    project_planning_document._phase_sections_cache = None
    return {'result': dict(row) if row else None}


@router.put('/planning/phase-source/{source_id}')
async def project_planning_phase_source_update(
    request: Request,
    source_id: int,
    user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW])),
):
    body = await request.json()
    fields = {}
    for col in ('phase_key', 'title', 'doc_file', 'header_mode'):
        if col in body:
            fields[col] = str(body[col]).strip()

    if not fields:
        return {'result': None}

    set_clause = ', '.join(f'{k}=%s' for k in fields)
    values = list(fields.values()) + [source_id]

    async with mysql_get_db_async() as db:
        await db.execute(
            f'UPDATE project_planning_phase_source SET {set_clause} WHERE id=%s', values
        )
        await db.execute('SELECT id, phase_key, title, doc_file, header_mode FROM project_planning_phase_source WHERE id=%s', (source_id,))
        row = await db.fetchone()

    project_planning_document._phase_sections_cache = None
    return {'result': dict(row) if row else None}


@router.delete('/planning/phase-source/{source_id}')
async def project_planning_phase_source_delete(
    request: Request,
    source_id: int,
    user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW])),
):
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM project_planning_phase_source WHERE id=%s', (source_id,))

    project_planning_document._phase_sections_cache = None
    return {'result': True}

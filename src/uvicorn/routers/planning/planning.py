from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.planning_document_repository import PlanningDocumentRepository
from src.mysql_.repository.planning_phase_repository import PlanningPhaseRepository
from src.mysql_.repository.planning_project_repository import PlanningProjectRepository

router = APIRouter()


@router.get('/planning/project/list')
async def planning_project_list(request: Request, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningProjectRepository()
    return {'result': await repo.find_by({}, 'id DESC')}


@router.get('/planning/project/{project_id}')
async def planning_project_get(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningProjectRepository()
    return {'result': await repo.find(project_id)}


@router.post('/planning/project')
async def planning_project_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    repo = PlanningProjectRepository()
    title = str(data.get('title') or '').strip()
    idea = str(data.get('idea') or '').strip()
    if not idea:
        return {'error': 'idea is required'}
    if not title:
        title = idea[:80]
    project_id = await repo.add({
        'node_id': 9,
        'user_id': user.get('id', 0),
        'title': title,
        'idea': idea,
        'status': 'pending',
        'phase_current': '',
    })
    return {'result': project_id}


@router.put('/planning/project/{project_id}')
async def planning_project_update(request: Request, project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    repo = PlanningProjectRepository()
    update = {}
    if 'title' in data:
        update['title'] = str(data['title'])
    if 'status' in data:
        update['status'] = str(data['status'])
    if update:
        await repo.update(project_id, update)
    return {'result': project_id}


@router.delete('/planning/project/{project_id}')
async def planning_project_delete(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_DELETE]))):
    repo = PlanningProjectRepository()
    await repo.delete(project_id)
    return {'result': project_id}


# ─── Phases ──────────────────────────────────────────────────────────────────

@router.get('/planning/project/{project_id}/phases')
async def planning_phases_get(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningPhaseRepository()
    return {'result': await repo.find_by({'project_id': project_id}, 'id ASC')}


# ─── Documents ───────────────────────────────────────────────────────────────

@router.get('/planning/project/{project_id}/documents')
async def planning_documents_get(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningDocumentRepository()
    return {'result': await repo.find_by({'project_id': project_id}, 'id ASC')}


@router.get('/planning/document/{doc_id}')
async def planning_document_get(request: Request, doc_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningDocumentRepository()
    return {'result': await repo.find(doc_id)}


@router.get('/planning/document/{doc_id}/download')
async def planning_document_download(request: Request, doc_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningDocumentRepository()
    doc = await repo.find(doc_id)
    if not doc:
        return Response(content='Not found', status_code=404)
    content = str(doc.get('content') or '')
    title = str(doc.get('title') or doc.get('doc_type') or 'document')
    safe_name = ''.join(c if c.isalnum() or c in '-_ ' else '_' for c in title).strip()[:80]
    filename = (safe_name or 'document') + '.md'
    return Response(
        content=content.encode('utf-8'),
        media_type='text/markdown; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename*=UTF-8\'\'{filename}'}
    )

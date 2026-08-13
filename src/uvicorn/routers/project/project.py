
from fastapi import APIRouter, Depends

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.project.project_repository import PlanningProjectRepository

router = APIRouter()


@router.get('/project/list')
async def project_admin_list(user=Depends(AuthChecker([AuthPermission.PROJECT_VIEW]))):
    """Список всех проектов."""
    repo = PlanningProjectRepository()
    return {'result': await repo.find_by({}, 'id ASC')}


@router.get('/project/{project_id}')
async def project_admin_get(project_id: int, user=Depends(AuthChecker([AuthPermission.PROJECT_VIEW]))):
    """Детальная информация по проекту."""
    repo = PlanningProjectRepository()
    return {'result': await repo.find(project_id)}


@router.post('/project')
async def project_admin_create(data: dict, user=Depends(AuthChecker([AuthPermission.PROJECT_CREATE]))):
    """Создание нового проекта."""
    repo = PlanningProjectRepository()
    title = str(data.get('title') or '').strip()
    idea = str(data.get('idea') or '').strip()
    work_dir = str(data.get('work_dir') or '').strip()
    if not title:
        return {'error': 'title is required'}
    if not idea:
        idea = title[:200]
    if not work_dir:
        work_dir = idea[:200]
    async with mysql_get_db_async() as db:
        await db.execute('SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM project')
        row = await db.fetchone()
        next_id = int(row['next_id']) if row else 1
    project_id = await repo.add({
        'node_id': 6,
        'user_id': 0,
        'title': title,
        'idea': idea,
        'work_dir': work_dir,
        'status': 'complete',
        'phase_current': 'complete',
        'position': 0,
    })
    return {'result': project_id}


@router.put('/project/{project_id}')
async def project_admin_update(project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PROJECT_UPDATE]))):
    """Обновление проекта."""
    repo = PlanningProjectRepository()
    update = {}
    if 'title' in data:
        update['title'] = str(data['title'])
    if 'idea' in data:
        update['idea'] = str(data['idea'])
    if 'status' in data:
        update['status'] = str(data['status'])
    if 'work_dir' in data:
        update['work_dir'] = str(data['work_dir'])
    if 'phase_current' in data:
        update['phase_current'] = str(data['phase_current'])
    if 'description' in data:
        update['description'] = str(data['description'])
    if update:
        await repo.update(project_id, update)
    return {'result': project_id}


@router.delete('/project/{project_id}')
async def project_admin_delete(project_id: int, user=Depends(AuthChecker([AuthPermission.PROJECT_DELETE]))):
    """Удаление проекта."""
    repo = PlanningProjectRepository()
    await repo.delete(project_id)
    return {'result': project_id}

import json
import os

from fastapi import APIRouter, Request, Depends, HTTPException

from src.mysql_.repository.project.planning.planning_document_repository import PlanningDocumentRepository
from src.mysql_.repository.project.planning.planning_phase_repository import PlanningPhaseRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.project.project_repository import PlanningProjectRepository
from mysql_.mysql_ import mysql_get_db_async
from py_modules.setting_.setting_ import setting_get
from src.project.team.team_member import team_member_cards_ensure
from src.worker.project.planning_worker import planning_worker_enqueue
from src.uvicorn.routers.project.project_common import _CRONICLE_SCHEDULE_FILE

router = APIRouter()


@router.get('/planning/project/list')
async def project_planning_list(request: Request, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningProjectRepository()
    return {'result': await repo.find_by({}, 'position ASC, id DESC')}


@router.get('/planning/project/{project_id}')
async def project_planning_get(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningProjectRepository()
    return {'result': await repo.find(project_id)}


@router.post('/planning/project')
async def project_planning_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    repo = PlanningProjectRepository()
    title = str(data.get('title') or '').strip()
    idea = str(data.get('idea') or '').strip()
    if not idea:
        return {'error': 'idea is required'}
    if not title:
        title = idea[:80]
    async with mysql_get_db_async() as db:
        await db.execute('SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM project')
        row = await db.fetchone()
        next_pos = int(row['next_pos']) if row else 0
    project_id = await repo.add({
        'node_id': 6,
        'user_id': user.user_id,
        'title': title,
        'idea': idea,
        'status': 'pending',
        'phase_current': '',
        'position': next_pos,
    })
    await team_member_cards_ensure(project_id)
    planning_worker_enqueue(project_id)
    return {'result': project_id}


@router.put('/planning/project/reorder')
async def project_planning_reorder(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    ids = data.get('ids') or []
    if not ids or not isinstance(ids, list):
        return {'error': 'ids required'}
    async with mysql_get_db_async() as db:
        for pos, project_id in enumerate(ids):
            await db.execute('UPDATE project SET position = %s WHERE id = %s', (pos, int(project_id)))
    return {'result': 'ok'}


@router.put('/planning/project/{project_id}')
async def project_planning_update(request: Request, project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    repo = PlanningProjectRepository()
    update = {}
    if 'title' in data:
        update['title'] = str(data['title'])
    if 'idea' in data:
        update['idea'] = str(data['idea'])
    if 'status' in data:
        update['status'] = str(data['status'])
    if update:
        await repo.update(project_id, update)
    return {'result': project_id}


@router.post('/planning/project/{project_id}/retry')
async def project_planning_retry(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Полный сброс: удаляет все фазы и документы проекта, запускает с нуля."""
    async with mysql_get_db_async() as db:
        await db.execute(
            """UPDATE project
               SET status = 'pending', phase_current = '',
                   score_market = NULL, score_feasibility = NULL, score_financial = NULL,
                   score_total = NULL, score_verdict = NULL, score_investment = NULL,
                   score_time_to_market = NULL, score_summary = NULL
             WHERE id = %s""",
            (project_id,)
        )
        await db.execute(
            "DELETE FROM project_planning_phase WHERE project_id = %s",
            (project_id,)
        )
        await db.execute(
            "DELETE FROM project_planning_document WHERE project_id = %s",
            (project_id,)
        )
        await db.connection.commit()
    planning_worker_enqueue(project_id)
    return {'result': project_id}


@router.post('/planning/project/{project_id}/phase/{phase}/retry')
async def project_planning_phase_retry(
    request: Request, project_id: int, phase: str,
    user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))
):
    """Сброс одной фазы: удаляет её запись и документы, возвращает проект в pending."""
    valid_phases = {'analyze', 'market', 'product', 'tech', 'gtm', 'financial', 'blueprint', 'score', 'supplement', 'design', 'prototype', 'sitemap_check', 'design_pages', 'design_wireframe'}
    is_supplement_sub = phase.startswith('supplement_')
    if phase not in valid_phases and not is_supplement_sub:
        raise HTTPException(status_code=400, detail=f'Unknown phase: {phase}')

    async with mysql_get_db_async() as db:
        if is_supplement_sub:
            await db.execute("DELETE FROM project_planning_phase WHERE project_id = %s AND phase = %s", (project_id, phase))
            await db.execute("DELETE FROM project_planning_document WHERE project_id = %s AND doc_type = %s", (project_id, phase))
        elif phase == 'supplement':
            await db.execute("DELETE FROM project_planning_phase WHERE project_id = %s AND phase LIKE 'supplement_%%'", (project_id,))
            await db.execute("DELETE FROM project_planning_document WHERE project_id = %s AND doc_type LIKE 'supplement_%%'", (project_id,))
        elif phase == 'design':
            # Удаляем design и все её дочерние фазы (prototype, sitemap_check)
            await db.execute(
                "DELETE FROM project_planning_phase WHERE project_id = %s AND (phase = 'design' OR parent_phase = 'design')",
                (project_id,)
            )
            await db.execute(
                "DELETE FROM project_planning_document WHERE project_id = %s AND doc_type IN ('design','design_tokens','design_ui_components','design_wireframes','design_sitemap','design_specs','prototype','sitemap_check')",
                (project_id,)
            )
        else:
            await db.execute("DELETE FROM project_planning_phase WHERE project_id = %s AND phase = %s", (project_id, phase))
            await db.execute("DELETE FROM project_planning_document WHERE project_id = %s AND doc_type = %s", (project_id, phase))

        if phase == 'score':
            await db.execute(
                """UPDATE project SET
                   score_market = NULL, score_feasibility = NULL, score_financial = NULL,
                   score_total = NULL, score_verdict = NULL, score_investment = NULL,
                   score_time_to_market = NULL, score_summary = NULL
                 WHERE id = %s""",
                (project_id,)
            )

        await db.execute(
            "UPDATE project SET status = 'pending' WHERE id = %s AND status NOT IN ('running')",
            (project_id,)
        )
        await db.connection.commit()

    planning_worker_enqueue(project_id)
    return {'result': project_id}


@router.delete('/planning/project/{project_id}')
async def project_planning_delete(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_DELETE]))):
    import shutil
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_planning_phase    WHERE project_id = %s", (project_id,))
        await db.execute("DELETE FROM project_planning_document WHERE project_id = %s", (project_id,))
        # Задачи удаляем явно: FK от `project_task.project_id` к `project` в схеме
        # нет — есть только связь с родительской строкой. Без этого задачи удалённого
        # проекта оставались сиротами: числятся за проектом, которого нет, и не видны
        # ни в одном разрезе страницы, потому что та строится от списка проектов.
        # Сначала дети, потом родители — обратно порядку создания.
        await db.execute("DELETE FROM project_task WHERE parent_id IS NOT NULL AND project_id = %s",
                         (project_id,))
        await db.execute("DELETE FROM project_task WHERE project_id = %s", (project_id,))
        await db.execute("DELETE FROM project  WHERE id = %s",         (project_id,))
        await db.connection.commit()
    project_dir = f'/app/data/planning/{project_id}'
    if os.path.isdir(project_dir):
        shutil.rmtree(project_dir, ignore_errors=True)
    return {'result': project_id}


@router.get('/planning/cronicle/schedule')
async def project_planning_cronicle_schedule(request: Request, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Возвращает минуты запуска каждой planning-фазы из файла расписания Cronicle."""
    try:
        with open(_CRONICLE_SCHEDULE_FILE) as f:
            data = json.load(f)
    except Exception:
        return {'result': {}}
    schedule = {}
    for item in data.get('items', []):
        title = item.get('title', '')
        if not title.startswith('planning_'):
            continue
        phase = title.replace('planning_', '')
        timing = item.get('timing', {})
        minutes = timing.get('minutes', [])
        hours = timing.get('hours', [])
        if minutes:
            schedule[phase] = {'minutes': sorted(minutes), 'hours': sorted(hours)}
    return {'result': schedule}


@router.get('/planning/project/{project_id}/phases')
async def project_planning_phases_get(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningPhaseRepository()
    phases = await repo.find_by({'project_id': project_id}, 'id ASC')
    for ph in (phases or []):
        phase_key = str(ph.get('phase') or '')
        ph['cronicle_last_run'] = str(await setting_get(f'planning_cronicle_{phase_key}') or '')
    return {'result': phases}


@router.get('/planning/project/{project_id}/documents')
async def project_planning_documents_get(request: Request, project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    repo = PlanningDocumentRepository()
    return {'result': await repo.find_by({'project_id': project_id}, 'id ASC')}


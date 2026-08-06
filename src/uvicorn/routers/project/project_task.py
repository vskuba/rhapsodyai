import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.agent_repository import AgentRepository

_TASK_AI_AGENT_NAME = 'task_ai_generator'
_TASK_AI_TIMEOUT    = 60.0

router = APIRouter()


@router.get('/tasks')
async def project_tasks_all(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM task ORDER BY position, id")
        rows = await db.fetchall()
    return {'tasks': [dict(r) for r in rows]}


@router.get('/tasks/{project_id}')
async def project_tasks_list(project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT * FROM task WHERE project_id = %s ORDER BY position, id",
            (project_id,)
        )
        rows = await db.fetchall()
    return {'tasks': [dict(r) for r in rows]}


@router.post('/tasks/{project_id}')
async def project_task_create(project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    title = str(data.get('title') or '').strip()
    if not title:
        raise HTTPException(status_code=400, detail='title required')

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS pos FROM task WHERE project_id = %s",
            (project_id,)
        )
        row = await db.fetchone()
        next_pos = row['pos'] if row else 0

        await db.execute(
            "INSERT INTO task (project_id, title, description, goals, status, report, position) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (project_id, title, str(data.get('description') or ''), str(data.get('goals') or ''),
             str(data.get('status') or 'pending'), str(data.get('report') or ''), next_pos)
        )
        await db.connection.commit()
        task_id = db.lastrowid

        await db.execute("SELECT * FROM task WHERE id = %s", (task_id,))
        task = await db.fetchone()

    return {'task': dict(task)}


@router.put('/task/{task_id}')
async def project_task_update(task_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    allowed = {'title', 'description', 'goals', 'status', 'report'}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail='nothing to update')

    set_clause = ', '.join(f'`{k}` = %s' for k in updates)
    values = list(updates.values()) + [task_id]

    async with mysql_get_db_async() as db:
        await db.execute(f"UPDATE task SET {set_clause} WHERE id = %s", values)
        await db.connection.commit()
        await db.execute("SELECT * FROM task WHERE id = %s", (task_id,))
        task = await db.fetchone()

    if not task:
        raise HTTPException(status_code=404, detail='task not found')
    return {'task': dict(task)}


@router.delete('/task/{task_id}')
async def project_task_delete(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM task WHERE id = %s", (task_id,))
        await db.connection.commit()
    return {'ok': True}


@router.post('/task/ai-generate')
async def project_task_ai_generate(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    description = str(data.get('description') or '').strip()
    if not description:
        raise HTTPException(status_code=400, detail='description required')

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'name': _TASK_AI_AGENT_NAME})
    if not entity_agent:
        raise HTTPException(status_code=404, detail='AI агент не найден')

    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        raise HTTPException(status_code=503, detail='LLM не настроены')

    workflow_data = await ai_workflow_load(entity_agent['workflow_id'])
    session_uuid = str(uuid.uuid4())
    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=description,
            user_id=user.user_id,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=entity_agent['workflow_id'],
        ),
        'task_description': description,
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    agent_manager = request.app.state.agent_manager
    framework_model = await agent_manager.framework_model_create({
        'entity_agent':      entity_agent,
        'entities_llm':      entities_llm,
        'workflow_steps':    workflow_data['steps'],
        'workflow_variables': wf_vars,
        'prompt_user':       description,
        'user_id':           user.user_id,
        'companion_id':      None,
        'session_uuid':      session_uuid,
        'tools':             {},
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=_TASK_AI_TIMEOUT)
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=504, detail='Превышено время ожидания AI')

    raw = str(result_text).removeprefix('json:').strip()
    parsed = json_from_string(raw)
    if not parsed or not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail='AI вернул некорректный ответ')

    title       = str(parsed.get('title') or '').strip()
    description = str(parsed.get('description') or '').strip()
    goals_raw   = parsed.get('goals') or []
    if isinstance(goals_raw, list):
        goals = [{'text': str(g), 'done': False} for g in goals_raw if g]
    else:
        goals = []

    return {'title': title, 'description': description, 'goals': goals}

import asyncio
import uuid

from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.agent_repository import AgentRepository
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.worker.project.planning_worker import planning_worker_enqueue

router = APIRouter()


@router.post('/planning/ideas/generate')
async def project_idea_planning_ideas_generate(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Генерирует 7 идей продуктов по заданной нише через AI."""
    from json_.json_ import json_from_string
    import ast

    niche = str(data.get('niche') or '').strip()
    if not niche:
        return {'error': 'niche is required'}

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'name': 'planning_idea_generator'})
    if not entity_agent:
        return {'error': 'Агент не найден'}

    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        return {'error': 'LLM не настроены'}

    workflow_data = await ai_workflow_load(entity_agent['workflow_id'])
    session_uuid = str(uuid.uuid4())
    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=niche,
            user_id=user.user_id,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=entity_agent['workflow_id'],
        ),
        'planning_niche': niche,
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    agent_manager = request.app.state.agent_manager
    framework_model = await agent_manager.framework_model_create({
        'entity_agent': entity_agent,
        'entities_llm': entities_llm,
        'workflow_steps': workflow_data['steps'],
        'workflow_variables': wf_vars,
        'prompt_user': niche,
        'user_id': user.user_id,
        'session_uuid': session_uuid,
        'tools': {},
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=90.0)
    except asyncio.TimeoutError:
        future.cancel()
        return {'error': 'Превышено время ожидания (90с)'}
    except Exception as e:
        return {'error': f'Ошибка workflow: {e}'}

    ideas = []
    if isinstance(result_text, list):
        ideas = result_text
    else:
        clean_text = str(result_text).removeprefix('json:')
        parsed = json_from_string(clean_text) or None
        if not parsed:
            try:
                parsed = ast.literal_eval(clean_text)
            except Exception:
                pass
        if isinstance(parsed, dict):
            ideas = parsed.get('ideas_json') or parsed.get('ideas') or []
        elif isinstance(parsed, list):
            ideas = parsed

    if not ideas:
        return {'error': 'LLM не вернул идеи', 'raw': str(result_text)[:500]}

    return {'result': ideas}


@router.post('/planning/ideas/bulk-create')
async def project_idea_planning_ideas_bulk_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Создаёт несколько проектов из списка идей."""
    ideas = data.get('ideas') or []
    if not ideas:
        return {'error': 'ideas is required'}

    created = []
    async with mysql_get_db_async() as db:
        for item in ideas:
            title = str(item.get('title') or '').strip()
            idea  = str(item.get('idea')  or '').strip()
            if not idea:
                continue
            if not title:
                title = idea[:80]
            await db.execute(
                "INSERT INTO project (node_id, user_id, title, idea, status, phase_current) VALUES (6, %s, %s, %s, 'pending', '')",
                (user.user_id, title, idea)
            )
            created.append({'id': db.lastrowid, 'title': title})
        await db.connection.commit()

    for item in created:
        planning_worker_enqueue(item['id'])

    return {'result': created}

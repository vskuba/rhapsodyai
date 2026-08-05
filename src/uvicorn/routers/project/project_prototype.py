import asyncio
import os
import re
import uuid

from fastapi import APIRouter, HTTPException, Request, Depends

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.uvicorn.routers.project.project_common import _PROTOTYPE_DIR, _tools_load, _strip_widget_elements

router = APIRouter()


@router.post('/planning/prototype/{project_id}/refine')
async def planning_prototype_refine(request: Request, project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Дорабатывает HTML-страницу прототипа по запросу пользователя через LLM."""
    from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
    from src.ai.ai_llm import ai_llm_node_get
    from src.mysql_.repository.agent_repository import AgentRepository

    page_name = str(data.get('page_name') or 'index.html').strip('/')
    refine_request = str(data.get('request') or '').strip()
    reference_url = str(data.get('reference_url') or '').strip()
    reference_html = str(data.get('reference_html') or '').strip()
    reference_css = str(data.get('reference_css') or '').strip()
    target_html = str(data.get('target_html') or '').strip()
    if not refine_request and not reference_html:
        return {'error': 'request or reference_html is required'}
    if not refine_request:
        if target_html and reference_html:
            refine_request = 'Трансформировать выделенный блок прототипа в стиле эталонного блока, сохранив оригинальный контент'
        else:
            refine_request = 'Применить выделенный блок к прототипу'
    if reference_url:
        refine_request = f'[Эталон: {reference_url}] {refine_request}'

    safe_path = os.path.normpath(page_name).lstrip('/')
    if '..' in safe_path or not safe_path.endswith('.html'):
        raise HTTPException(status_code=400, detail='Bad page_name')
    file_path = os.path.join(_PROTOTYPE_DIR, str(project_id), safe_path)
    if not os.path.isfile(file_path):
        return {'error': 'Page not found'}

    with open(file_path, 'r', encoding='utf-8') as f:
        current_html = f.read()

    current_html = re.sub(
        r'<script>window\.__PROTO_WIDGET__[^<]*</script>\s*\n?'
        r'<script src="/static/js/planning/prototype-editor-widget\.js"></script>\s*\n?',
        '',
        current_html,
    )

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'name': 'planning_prototype_refiner'})
    if not entity_agent:
        return {'error': 'Агент planning_prototype_refiner не найден'}

    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        return {'error': 'LLM не настроены для ноды агента'}

    workflow_data = await ai_workflow_load(entity_agent['workflow_id'])
    session_uuid = str(uuid.uuid4())
    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=refine_request,
            user_id=user.user_id,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=entity_agent['workflow_id'],
        ),
        'prototype_html': current_html,
        'refinement_request': refine_request,
        'page_name': safe_path,
        'reference_url': reference_url,
        'reference_html': reference_html,
        'reference_css': reference_css,
        'target_html': target_html,
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
        'prompt_user': refine_request,
        'user_id': user.user_id,
        'companion_id': None,
        'session_uuid': session_uuid,
        'tools': await _tools_load(),
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=120.0)
    except asyncio.TimeoutError:
        future.cancel()
        return {'error': 'Превышено время ожидания (120с)'}
    except Exception as e:
        return {'error': f'Ошибка workflow: {e}'}

    refined_html = str(result_text or '').strip()
    md_match = re.search(r'```(?:html)?\s*\n([\s\S]+?)\n```', refined_html)
    if md_match:
        refined_html = md_match.group(1).strip()

    if not refined_html or '<' not in refined_html:
        return {'error': 'LLM не вернул корректный HTML'}

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(refined_html)

    return {'result': 'ok', 'page': safe_path}


@router.post('/planning/prototype/{project_id}/patch')
async def planning_prototype_patch(request: Request, project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Сохраняет HTML страницы прототипа напрямую (без LLM) — для delete/move операций."""
    page_name = str(data.get('page_name') or 'index.html').strip('/')
    html = str(data.get('html') or '').strip()

    if not html or '<' not in html:
        return {'error': 'html is required'}

    safe_path = os.path.normpath(page_name).lstrip('/')
    if '..' in safe_path or not safe_path.endswith('.html'):
        raise HTTPException(status_code=400, detail='Bad page_name')
    file_path = os.path.join(_PROTOTYPE_DIR, str(project_id), safe_path)
    if not os.path.isfile(file_path):
        return {'error': 'Page not found'}

    html = re.sub(
        r'<script>window\.__PROTO_WIDGET__[^<]*</script>\s*\n?'
        r'<script src="/static/js/planning/prototype-editor-widget\.js"></script>\s*\n?',
        '',
        html,
    )
    html = _strip_widget_elements(html)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return {'result': 'ok', 'page': safe_path}

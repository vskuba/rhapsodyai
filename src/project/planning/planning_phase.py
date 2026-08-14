"""
Движок фазы планирования: находит проекты, готовые к фазе, и прогоняет по каждому агента.

Потребителей два — `planning_worker` (событийный, job в Redis-очереди) и `planning_batch`
(пакетный, из Cronicle). Цепочка фаз здесь не описывается, она в `planning_chain`.
"""
import asyncio
import json
import uuid

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from py_modules.ai.ai_thread import ai_thread_framework_run
from queue_.queue_ import queue_init
from src.ai.ai_llm import ai_llm_node_get, ai_llm_speed_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository
from src.project.planning.planning_phase_query import planning_phase_query_pending_projects
from src.project.planning.planning_phase_state import (
    planning_phase_state_complete,
    planning_phase_state_cronicle_touch,
    planning_phase_state_failed,
    planning_phase_state_running,
    planning_phase_state_stuck_reset,
    planning_phase_state_waiting,
)

PHASE_TIMEOUT_MIN = 900.0   # минимальный таймаут (15 мин)
PHASE_TIMEOUT_MAX = 3600.0  # максимальный таймаут (1 час)
PLANNING_USER_ID = 1


async def planning_phase_run(
    agent_name: str,
    phase: str,
    requires_phases: list[str],
    extra_variables: dict | None = None,
    project_statuses: list[str] | None = None,
    restore_project_status: str | None = None,
    skip_init: bool = False,
    project_id_filter: int | None = None,
    parent_phase: str | None = None,
    mark_waiting: bool = False,
) -> dict:
    """
    Находит проекты где phase ещё не выполнена (и requires_phases все complete),
    запускает агента для каждого.

    Returns:
        processed: сколько проектов обработано успешно.
        errors: сколько завершилось ошибкой.

    skip_init=True: не поднимать очереди и поток движка и не трогать состояние
        Cronicle-прохода (touch, сброс застрявших). Так зовёт `planning_worker`:
        job поднимает инфраструктуру сам, один раз на всю цепочку проекта, а
        Cronicle-состояние принадлежит пакетному `planning_batch`.
    project_id_filter: обработать только конкретный проект (так зовёт воркер).
    """
    if not skip_init:
        queue_init([
            'chat', 'chat_response', 'chat_input_send',
            'task', 'task_abort', 'task_complete', 'task_continue',
            'tool', 'agent_abort', 'agent_response', 'ai_framework_model',
        ])
        asyncio.create_task(ai_thread_framework_run([AiFrameworkAgent()]))

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'name': agent_name})
    if not entity_agent or not entity_agent.get('workflow_id'):
        logger_info(f'planning: агент {agent_name!r} не найден')
        return {'processed': 0, 'errors': 0}

    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        logger_info(f'planning: нет LLM для ноды агента {agent_name!r}')
        return {'processed': 0, 'errors': 0}

    if not skip_init:
        await planning_phase_state_cronicle_touch(phase)
        await planning_phase_state_stuck_reset(phase)

    projects = await planning_phase_query_pending_projects(
        phase, requires_phases, project_statuses or ['pending', 'processing'], project_id_filter)
    if not projects:
        logger_info(f'planning [{phase}]: нет проектов для обработки')
        return {'processed': 0, 'errors': 0}

    workflow_id = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)
    agent_manager = AiFrameworkAgentManager()

    stats = {'processed': 0, 'errors': 0}

    for project in projects:
        project_id = project['id']
        try:
            await planning_phase_state_running(project_id, phase, parent_phase=parent_phase)

            session_uuid = str(uuid.uuid4())
            wf_vars = {
                **ai_workflow_variables_base(
                    prompt_user='',
                    user_id=PLANNING_USER_ID,
                    entity_agent=entity_agent,
                    session_uuid=session_uuid,
                    workflow_id=workflow_id,
                ),
                'planning_project_id': project_id,
                **(extra_variables or {}),
            }
            ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])
            wf_vars.update(_agent_variables_get(entity_agent))

            loop = asyncio.get_running_loop()
            future = loop.create_future()

            framework_model = await agent_manager.framework_model_create({
                'entity_agent': entity_agent,
                'entities_llm': entities_llm,
                'workflow_steps': workflow_data['steps'],
                'workflow_variables': wf_vars,
                'prompt_user': '',
                'user_id': PLANNING_USER_ID,
                'companion_id': None,
                'session_uuid': session_uuid,
                'tools': await _tools_load(),
            })
            agent_manager.framework_workflow_run(framework_model, future, loop)

            phase_timeout = await _timeout_get(entities_llm[0].get('id') if entities_llm else None)
            logger_info(f'planning [{phase}]: таймаут {phase_timeout:.0f}s')
            await asyncio.wait_for(future, timeout=phase_timeout)

            if mark_waiting:
                await planning_phase_state_waiting(project_id, phase, restore_project_status, session_uuid)
            else:
                await planning_phase_state_complete(project_id, phase, restore_project_status, session_uuid)
            stats['processed'] += 1
            logger_info(f'planning [{phase}]: project {project_id} — OK')

        except Exception as e:
            stats['errors'] += 1
            await planning_phase_state_failed(project_id, phase, str(e))
            logger_info(f'planning [{phase}]: project {project_id} — ERROR: {e}')

    return stats


def _agent_variables_get(entity_agent: dict) -> dict:
    """Константы из agent.workflow_variable. Битый JSON игнорируем — фаза важнее."""
    try:
        return json.loads(entity_agent.get('workflow_variable') or '{}')
    except (ValueError, TypeError):
        return {}


async def _timeout_get(llm_id: int | None) -> float:
    """
    Динамический таймаут на основе средней скорости LLM.
    Формула: avg_ms × 30 × 1.5 / 1000 (30 LLM-вызовов с запасом 50%),
    зажимается в [PHASE_TIMEOUT_MIN, PHASE_TIMEOUT_MAX].
    """
    speed = await ai_llm_speed_get(llm_id)
    avg_ms = speed['avg_ms']
    timeout = avg_ms / 1000.0 * 30 * 1.5
    result = max(PHASE_TIMEOUT_MIN, min(PHASE_TIMEOUT_MAX, timeout))
    logger_info(f'planning timeout: avg_ms={avg_ms:.0f}, расчёт={timeout:.0f}s → {result:.0f}s')
    return result


async def _tools_load() -> dict:
    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, path FROM tool WHERE id > 0')
        rows = await db.fetchall()
    return {r['name'].strip(): r['path'].strip() for r in (rows or []) if r.get('name') and r.get('path')}

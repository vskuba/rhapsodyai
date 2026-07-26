"""
Общая база для всех planning-кронджобов.
Каждый кронджоб находит проекты где предыдущая фаза завершена,
а текущая ещё не запущена, и запускает агента.
"""
import asyncio
import uuid

from src.ai.ai_llm import ai_llm_node_get, ai_llm_speed_get
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from queue_.queue_ import queue_init
from py_modules.ai.ai_thread import ai_thread_framework_run
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository

PHASE_TIMEOUT_MIN = 900.0   # минимальный таймаут (15 мин)
PHASE_TIMEOUT_MAX = 3600.0  # максимальный таймаут (1 час)
PLANNING_USER_ID = 1


async def planning_phase_run(
    agent_name: str,
    phase: str,
    requires_phases: list[str],
    extra_variables: dict | None = None,
) -> dict:
    """
    Находит проекты где phase ещё не выполнена (и requires_phases все complete),
    запускает агента для каждого.
    Возвращает статистику: {'processed': N, 'errors': M}
    """
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

    projects = await _pending_projects_get(phase, requires_phases)
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
            await _phase_mark_running(project_id, phase)

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

            # inject agent workflow_variable constants
            import json as _json
            agent_wv = entity_agent.get('workflow_variable') or '{}'
            try:
                wf_vars.update(_json.loads(agent_wv))
            except Exception:
                pass

            loop = asyncio.get_running_loop()
            future = loop.create_future()

            tools = await _tools_load()
            framework_model = await agent_manager.framework_model_create({
                'entity_agent': entity_agent,
                'entities_llm': entities_llm,
                'workflow_steps': workflow_data['steps'],
                'workflow_variables': wf_vars,
                'prompt_user': '',
                'user_id': PLANNING_USER_ID,
                'companion_id': None,
                'session_uuid': session_uuid,
                'tools': tools,
            })
            agent_manager.framework_workflow_run(framework_model, future, loop)

            phase_timeout = await _phase_timeout_get(entities_llm[0].get('id') if entities_llm else None)
            logger_info(f'planning [{phase}]: таймаут {phase_timeout:.0f}s')
            await asyncio.wait_for(future, timeout=phase_timeout)
            await _phase_mark_complete(project_id, phase)
            stats['processed'] += 1
            logger_info(f'planning [{phase}]: project {project_id} — OK')

        except Exception as e:
            stats['errors'] += 1
            await _phase_mark_failed(project_id, phase, str(e))
            logger_info(f'planning [{phase}]: project {project_id} — ERROR: {e}')

    return stats


async def _pending_projects_get(phase: str, requires_phases: list[str]) -> list:
    """
    Возвращает проекты, где:
    - все requires_phases завершены (status=complete)
    - phase ещё не существует в planning_phase (либо статус failed)
    """
    async with mysql_get_db_async() as db:
        if not requires_phases:
            # Первая фаза — просто берём pending/processing проекты
            await db.execute(
                """
                SELECT p.id FROM planning_project p
                WHERE p.status IN ('pending', 'processing')
                  AND NOT EXISTS (
                    SELECT 1 FROM planning_phase ph
                    WHERE ph.project_id = p.id AND ph.phase = %s AND ph.status IN ('running','complete')
                  )
                ORDER BY p.id ASC
                LIMIT 10
                """,
                (phase,)
            )
        else:
            # Проверяем что все required фазы complete
            placeholders = ', '.join(['%s'] * len(requires_phases))
            req_count = len(requires_phases)
            await db.execute(
                f"""
                SELECT p.id FROM planning_project p
                WHERE p.status IN ('pending', 'processing')
                  AND (
                    SELECT COUNT(*) FROM planning_phase ph
                    WHERE ph.project_id = p.id
                      AND ph.phase IN ({placeholders})
                      AND ph.status = 'complete'
                  ) = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM planning_phase ph2
                    WHERE ph2.project_id = p.id AND ph2.phase = %s AND ph2.status IN ('running','complete')
                  )
                ORDER BY p.id ASC
                LIMIT 10
                """,
                (*requires_phases, req_count, phase)
            )
        rows = await db.fetchall()
        return list(rows or [])


async def _phase_mark_running(project_id: int, phase: str) -> None:
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            INSERT INTO planning_phase (project_id, phase, status, started_at)
            VALUES (%s, %s, 'running', NOW())
            ON DUPLICATE KEY UPDATE status = 'running', started_at = NOW(), error = ''
            """,
            (project_id, phase)
        )
        await db.execute(
            "UPDATE planning_project SET status = 'processing', phase_current = %s WHERE id = %s",
            (phase, project_id)
        )
        await db.connection.commit()


async def _phase_mark_failed(project_id: int, phase: str, error: str) -> None:
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE planning_phase SET status = 'failed', error = %s WHERE project_id = %s AND phase = %s",
            (error[:500], project_id, phase)
        )
        await db.execute(
            "UPDATE planning_project SET status = 'error' WHERE id = %s",
            (project_id,)
        )
        await db.connection.commit()


async def _phase_mark_complete(project_id: int, phase: str) -> None:
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            INSERT INTO planning_phase (project_id, phase, status, completed_at)
            VALUES (%s, %s, 'complete', NOW())
            ON DUPLICATE KEY UPDATE status = 'complete', completed_at = NOW()
            """,
            (project_id, phase)
        )
        await db.connection.commit()


async def _phase_timeout_get(llm_id: int | None) -> float:
    """Динамический таймаут на основе средней скорости LLM.

    Формула: avg_ms × 30 × 1.5 / 1000 (30 LLM-вызовов с запасом 50%).
    Зажимается в [PHASE_TIMEOUT_MIN, PHASE_TIMEOUT_MAX].
    """
    speed = await ai_llm_speed_get(llm_id)
    avg_ms = speed['avg_ms']
    # 30 ≈ верхняя оценка LLM-вызовов в одной фазе (MapReduce + редюс + инструменты)
    timeout = avg_ms / 1000.0 * 30 * 1.5
    result = max(PHASE_TIMEOUT_MIN, min(PHASE_TIMEOUT_MAX, timeout))
    logger_info(f'planning timeout: avg_ms={avg_ms:.0f}, расчёт={timeout:.0f}s → {result:.0f}s')
    return result


async def _tools_load() -> dict:
    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, path FROM tool WHERE id > 0')
        rows = await db.fetchall()
    return {r['name'].strip(): r['path'].strip() for r in (rows or []) if r.get('name') and r.get('path')}

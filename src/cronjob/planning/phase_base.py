"""
Общая база для всех planning-кронджобов.
Каждый кронджоб находит проекты где предыдущая фаза завершена,
а текущая ещё не запущена, и запускает агента.
"""
import asyncio
import uuid

from datetime import datetime

from src.ai.ai_llm import ai_llm_node_get, ai_llm_speed_get
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from setting_.setting_ import setting_set
from queue_.queue_ import queue_init
from py_modules.ai.ai_thread import ai_thread_framework_run
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository

PHASE_TIMEOUT_MIN = 900.0   # минимальный таймаут (15 мин)
PHASE_TIMEOUT_MAX = 3600.0  # максимальный таймаут (1 час)
PLANNING_USER_ID = 1

_phase_titles_cache: dict[str, str] | None = None


async def _phase_titles_load() -> dict[str, str]:
    global _phase_titles_cache
    if _phase_titles_cache is None:
        async with mysql_get_db_async() as db:
            await db.execute('SELECT phase_key, title FROM project_planning_phase_source')
            rows = await db.fetchall()
        _phase_titles_cache = {r['phase_key']: r['title'] for r in (rows or [])}
    return _phase_titles_cache


async def _phase_title(phase: str) -> str:
    titles = await _phase_titles_load()
    return titles.get(phase, phase)


async def project_planning_phase_run(
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
    Возвращает статистику: {'processed': N, 'errors': M}

    skip_init=True: пропустить queue_init и ai_thread_framework_run
        (используется из planning_runner внутри uvicorn, где они уже запущены).
    project_id_filter: обработать только конкретный проект (для runner'а).
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
        await _cronicle_touch(phase)
        await _stuck_running_reset(phase)
    projects = await _pending_projects_get(phase, requires_phases, project_statuses or ['pending', 'processing'], project_id_filter)
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
            await _phase_mark_running(project_id, phase, parent_phase=parent_phase)

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
            if mark_waiting:
                await _phase_mark_waiting(project_id, phase, restore_project_status, session_uuid)
            else:
                await _phase_mark_complete(project_id, phase, restore_project_status, session_uuid)
            stats['processed'] += 1
            logger_info(f'planning [{phase}]: project {project_id} — OK')

        except Exception as e:
            stats['errors'] += 1
            await _phase_mark_failed(project_id, phase, str(e))
            logger_info(f'planning [{phase}]: project {project_id} — ERROR: {e}')

    return stats


async def _cronicle_touch(phase: str) -> None:
    """Сохраняет время последнего запуска Cronicle для данной фазы в setting."""
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    await setting_set(f'planning_cronicle_{phase}', now, dynamic=1)


async def _stuck_running_reset(phase: str) -> None:
    """Сбрасывает фазы застрявшие в running дольше PHASE_TIMEOUT_MAX (после рестарта uvicorn)."""
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            UPDATE project_planning_phase
               SET status = 'failed',
                   error  = 'Workflow прерван: uvicorn перезапустился во время выполнения'
             WHERE phase = %s
               AND status = 'running'
               AND started_at < NOW() - INTERVAL %s SECOND
            """,
            (phase, int(PHASE_TIMEOUT_MAX))
        )
        if db.rowcount:
            logger_info(f'planning [{phase}]: сброшено {db.rowcount} застрявших running-фаз')
        await db.connection.commit()


async def _pending_projects_get(
    phase: str,
    requires_phases: list[str],
    project_statuses: list[str] | None = None,
    project_id_filter: int | None = None,
) -> list:
    """
    Возвращает проекты, где:
    - все requires_phases завершены (status=complete)
    - phase ещё не существует в project_planning_phase (либо статус failed)

    project_id_filter: если задан — вернуть только этот проект (для runner'а).
    """
    statuses = project_statuses or ['pending', 'processing']
    status_placeholders = ', '.join(['%s'] * len(statuses))
    id_filter_sql = 'AND p.id = %s' if project_id_filter else ''
    id_filter_params = (project_id_filter,) if project_id_filter else ()

    async with mysql_get_db_async() as db:
        if not requires_phases:
            await db.execute(
                f"""
                SELECT p.id FROM project p
                WHERE p.status IN ({status_placeholders})
                  {id_filter_sql}
                  AND NOT EXISTS (
                    SELECT 1 FROM project_planning_phase ph
                    WHERE ph.project_id = p.id AND ph.phase = %s AND ph.status IN ('running','complete')
                  )
                ORDER BY p.id ASC
                LIMIT 10
                """,
                (*statuses, *id_filter_params, phase)
            )
        else:
            placeholders = ', '.join(['%s'] * len(requires_phases))
            req_count = len(requires_phases)
            await db.execute(
                f"""
                SELECT p.id FROM project p
                WHERE p.status IN ({status_placeholders})
                  {id_filter_sql}
                  AND (
                    SELECT COUNT(*) FROM project_planning_phase ph
                    WHERE ph.project_id = p.id
                      AND ph.phase IN ({placeholders})
                      AND ph.status IN ('complete', 'waiting')
                  ) = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM project_planning_phase ph2
                    WHERE ph2.project_id = p.id AND ph2.phase = %s AND ph2.status IN ('running','complete')
                  )
                ORDER BY p.id ASC
                LIMIT 10
                """,
                (*statuses, *id_filter_params, *requires_phases, req_count, phase)
            )
        rows = await db.fetchall()
        return list(rows or [])


async def _phase_mark_running(project_id: int, phase: str, parent_phase: str | None = None) -> None:
    title = await _phase_title(phase)
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            INSERT INTO project_planning_phase (project_id, phase, parent_phase, title, status, started_at)
            VALUES (%s, %s, %s, %s, 'running', NOW())
            ON DUPLICATE KEY UPDATE parent_phase = %s, title = %s, status = 'running', started_at = NOW(), error = ''
            """,
            (project_id, phase, parent_phase, title, parent_phase, title)
        )
        await db.execute(
            "UPDATE project SET status = 'processing', phase_current = %s WHERE id = %s",
            (phase, project_id)
        )
        await db.connection.commit()


async def _phase_mark_failed(project_id: int, phase: str, error: str) -> None:
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_planning_phase SET status = 'failed', error = %s WHERE project_id = %s AND phase = %s",
            (error[:500], project_id, phase)
        )
        await db.execute(
            "UPDATE project SET status = 'error' WHERE id = %s",
            (project_id,)
        )
        await db.connection.commit()


async def _phase_mark_complete(
    project_id: int,
    phase: str,
    restore_project_status: str | None = None,
    session_uuid: str | None = None,
) -> None:
    async with mysql_get_db_async() as db:
        tokens_input = tokens_output = 0
        if session_uuid:
            await db.execute(
                """
                SELECT COALESCE(SUM(COALESCE(s.tokens_input, 0)), 0)  AS tin,
                       COALESCE(SUM(COALESCE(s.tokens_output, 0)), 0) AS tout
                FROM agent_workflow_trace r
                JOIN agent_workflow_trace_step s ON s.run_id = r.id
                WHERE r.session_uuid = %s
                """,
                (session_uuid,)
            )
            row = await db.fetchone()
            if row:
                tokens_input = int(row['tin'])
                tokens_output = int(row['tout'])

        tokens_used = tokens_input + tokens_output
        title = await _phase_title(phase)
        await db.execute(
            """
            INSERT INTO project_planning_phase (project_id, phase, title, status, completed_at, tokens_used, tokens_input, tokens_output)
            VALUES (%s, %s, %s, 'complete', NOW(), %s, %s, %s)
            ON DUPLICATE KEY UPDATE title = %s, status = 'complete', completed_at = NOW(),
                tokens_used = %s, tokens_input = %s, tokens_output = %s
            """,
            (project_id, phase, title, tokens_used, tokens_input, tokens_output,
             title, tokens_used, tokens_input, tokens_output)
        )
        if restore_project_status:
            await db.execute(
                "UPDATE project SET status = %s WHERE id = %s",
                (restore_project_status, project_id)
            )
        await db.connection.commit()


async def _phase_mark_waiting(
    project_id: int,
    phase: str,
    restore_project_status: str | None = None,
    session_uuid: str | None = None,
) -> None:
    """Фаза выполнила свой workflow, но ожидает завершения дочерних фаз."""
    async with mysql_get_db_async() as db:
        tokens_input = tokens_output = 0
        if session_uuid:
            await db.execute(
                """
                SELECT COALESCE(SUM(COALESCE(s.tokens_input, 0)), 0)  AS tin,
                       COALESCE(SUM(COALESCE(s.tokens_output, 0)), 0) AS tout
                FROM agent_workflow_trace r
                JOIN agent_workflow_trace_step s ON s.run_id = r.id
                WHERE r.session_uuid = %s
                """,
                (session_uuid,)
            )
            row = await db.fetchone()
            if row:
                tokens_input = int(row['tin'])
                tokens_output = int(row['tout'])

        tokens_used = tokens_input + tokens_output
        title = await _phase_title(phase)
        await db.execute(
            """
            INSERT INTO project_planning_phase (project_id, phase, title, status, completed_at, tokens_used, tokens_input, tokens_output)
            VALUES (%s, %s, %s, 'waiting', NOW(), %s, %s, %s)
            ON DUPLICATE KEY UPDATE title = %s, status = 'waiting', completed_at = NOW(),
                tokens_used = %s, tokens_input = %s, tokens_output = %s
            """,
            (project_id, phase, title, tokens_used, tokens_input, tokens_output,
             title, tokens_used, tokens_input, tokens_output)
        )
        if restore_project_status:
            await db.execute(
                "UPDATE project SET status = %s WHERE id = %s",
                (restore_project_status, project_id)
            )
        await db.connection.commit()


async def project_planning_phase_parent_complete(project_id: int, parent_phase: str) -> None:
    """Проверяет все ли дочерние фазы завершены и если да — ставит родителю 'complete'."""
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(status = 'complete') AS done,
                   SUM(status = 'failed') AS failed
            FROM project_planning_phase
            WHERE project_id = %s AND parent_phase = %s
            """,
            (project_id, parent_phase)
        )
        row = await db.fetchone()

    if not row or not row['total']:
        return

    total = int(row['total'])
    done = int(row['done'] or 0)
    failed = int(row['failed'] or 0)

    if done == total or (total > 0 and done + failed == total):
        title = await _phase_title(parent_phase)
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                UPDATE project_planning_phase SET status = 'complete', completed_at = NOW()
                WHERE project_id = %s AND phase = %s AND status = 'waiting'
                """,
                (project_id, parent_phase)
            )
            await db.connection.commit()
        if failed:
            logger_info(f'planning [{parent_phase}]: дочерние фазы завершены (ошибок: {failed}/{total}) → complete')
        else:
            logger_info(f'planning [{parent_phase}]: все дочерние фазы завершены → complete')


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


async def project_planning_phase_run_single(
    agent_name: str,
    phase: str,
    project_id: int,
    parent_phase: str | None = None,
    extra_variables: dict | None = None,
) -> None:
    """
    Запускает фазу для конкретного проекта напрямую — без проверки prerequisites и статуса проекта.
    Используется для запуска из Design-модуля (prototype) внутри uvicorn (skip_init подразумевается).
    Перед вызовом фаза должна быть создана в БД (status='pending').
    """
    import json as _json

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'name': agent_name})
    if not entity_agent or not entity_agent.get('workflow_id'):
        await _phase_mark_failed(project_id, phase, f'Агент {agent_name!r} не найден')
        return

    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        await _phase_mark_failed(project_id, phase, f'Нет LLM для агента {agent_name!r}')
        return

    try:
        await _phase_mark_running(project_id, phase, parent_phase=parent_phase)

        session_uuid = str(uuid.uuid4())
        workflow_id = entity_agent['workflow_id']
        workflow_data = await ai_workflow_load(workflow_id)

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

        agent_wv = entity_agent.get('workflow_variable') or '{}'
        try:
            wf_vars.update(_json.loads(agent_wv))
        except Exception:
            pass

        tools = await _tools_load()
        agent_manager = AiFrameworkAgentManager()
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
            'tools': tools,
        })
        agent_manager.framework_workflow_run(framework_model, future, loop)

        phase_timeout = await _phase_timeout_get(entities_llm[0].get('id') if entities_llm else None)
        logger_info(f'planning [{phase}]: project {project_id} direct — таймаут {phase_timeout:.0f}s')

        await asyncio.wait_for(future, timeout=phase_timeout)
        await _phase_mark_complete(project_id, phase, session_uuid=session_uuid)
        logger_info(f'planning [{phase}]: project {project_id} direct — OK')

    except Exception as e:
        await _phase_mark_failed(project_id, phase, str(e))
        logger_info(f'planning [{phase}]: project {project_id} direct — ERROR: {e}')

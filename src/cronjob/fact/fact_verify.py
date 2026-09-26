"""
Крон фактчека: берет партию непроверенных фактов и прогоняет каждый через
workflow 'fact_verify' (веб-поиск + LLM-вердикт). Факт помечается verify_status
(ok | corrected | unverifiable); при corrected текст исправляется и qdrant_synced
сбрасывается — пересинк вектора подхватит существующий крон fact_qdrant_sync.

Запуск через Cronicle: POST /cronjob {"cronjob_path": "src/cronjob/fact/fact_verify.py",
"metadata": {"limit": 10}, "timeout": 600}
"""
import asyncio
import json
import sys
import uuid

from src.ai.ai_llm import ai_llm_node_get
from logging_.logging_ import logger_info, logging_init
from src.error.error_log_handler import error_log_handler_install
from mysql_.mysql_ import mysql_get_db_async
from queue_.queue_ import queue_init
from ai.ai_thread import ai_thread_framework_run
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository

VERIFY_USER_ID = 1  # только для атрибуции session/log; LLM теперь берутся у ноды агента
WORKFLOW_TIMEOUT = 120.0


async def main():
    logging_init()
    # Ошибки кронджоба — в общий журнал установки (вкладка «Журнал» на
    # странице трасс): он живёт минуту в отдельном процессе, и его отказ
    # иначе теряется вместе с этим процессом.
    error_log_handler_install('cronjob')

    # Мини-инфраструктура движка (как в main_uvicorn): LLM-шаги идут через
    # очередь ai_framework_model, которую обрабатывает фоновая задача
    queue_init([
        'chat',
        'chat_response',
        'chat_input_send',
        'task',
        'task_abort',
        'task_complete',
        'task_continue',
        'tool',
        'agent_abort',
        'agent_response',
        'ai_framework_model',
    ])
    framework_task = asyncio.create_task(ai_thread_framework_run([AiFrameworkAgent()]))

    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            metadata = {}
    limit = int(metadata.get('limit', 10))

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'name': 'fact_verifier'})
    if not entity_agent or not entity_agent.get('workflow_id'):
        print("Агент 'fact_verifier' с workflow не найден")
        return

    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, document FROM fact WHERE verified_at IS NULL ORDER BY id ASC LIMIT %s",
            (limit,)
        )
        facts = await db.fetchall()

    if not entities_llm:
        print("У ноды агента 'fact_verifier' нет LLM-моделей")
        return
    if not facts:
        print("Непроверенных фактов нет")
        return

    workflow_id = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)
    agent_manager = AiFrameworkAgentManager()

    stats = {'ok': 0, 'corrected': 0, 'unverifiable': 0, 'error': 0}

    for fact in facts:
        fact_id = fact['id']
        document = str(fact.get('document') or '').strip()
        if not document:
            continue

        session_uuid = str(uuid.uuid4())
        workflow_variables_all = {
            **ai_workflow_variables_base(
                prompt_user=document,
                user_id=VERIFY_USER_ID,
                entity_agent=entity_agent,
                session_uuid=session_uuid,
                workflow_id=workflow_id,
            ),
            'fact_id': fact_id,
        }
        ai_workflow_variables_defaults_apply(workflow_variables_all, workflow_data['variables'])

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        framework_model = await agent_manager.framework_model_create({
            "entity_agent": entity_agent,
            "entities_llm": entities_llm,
            "workflow_steps": workflow_data['steps'],
            "workflow_variables": workflow_variables_all,
            "prompt_user": document,
            "user_id": VERIFY_USER_ID,
            "companion_id": None,
            "session_uuid": session_uuid,
            "tools": await _tools_get(),
        })
        agent_manager.framework_workflow_run(framework_model, future, loop)

        try:
            result = str(await asyncio.wait_for(future, timeout=WORKFLOW_TIMEOUT)).strip()
            status = result if result in stats else 'error'
            stats[status] += 1
            line = f"fact {fact_id}: {result}"
        except Exception as e:
            stats['error'] += 1
            line = f"fact {fact_id}: ошибка — {repr(e)}"

        logger_info(f"🔎 Фактчек: {line}")
        print(line)

    summary = f"Проверено фактов: {len(facts)}. " + ", ".join(f"{k}: {v}" for k, v in stats.items() if v)
    logger_info(f"🔎 {summary}")
    print(summary)

    framework_task.cancel()


async def _tools_get() -> dict:
    """Карта инструментов name -> path для tool_invoke шагов workflow."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT name, path FROM tool WHERE id > 0")
        rows = await db.fetchall()
    return {t['name'].strip(): t['path'].strip() for t in rows if t.get('name') and t.get('path')}


if __name__ == '__main__':
    asyncio.run(main())

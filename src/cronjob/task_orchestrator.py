"""
Оркестратор конвейера задач: один тик машины состояний за запуск.
Cronicle: POST /cronjob {"cronjob_path":"src/cronjob/task_orchestrator.py","metadata":{"max_actions":1},"timeout":600}

metadata:
    max_actions — сколько действий сделать за запуск (по умолчанию 1).
"""
import asyncio
import json
import sys

from logging_.logging_ import logging_init
from mysql_.mysql_ import mysql_pool_close
from py_modules.ai.ai_thread import ai_thread_framework_run
from queue_.queue_ import queue_init
from src.ai.framework.agent.ai_framework import AiFrameworkAgent
from src.project.task.task_pipeline import task_pipeline_run


async def main():
    logging_init()

    # Мини-инфраструктура движка (как в main_uvicorn): Manager — обычный агент,
    # его LLM-шаги идут через очередь ai_framework_model, а её разбирает
    # фоновая задача. Без этого тик повиснет на ожидании ответа.
    queue_init([
        'chat', 'chat_response', 'chat_input_send',
        'task', 'task_abort', 'task_complete', 'task_continue',
        'tool', 'agent_abort', 'agent_response', 'ai_framework_model',
    ])
    framework_task = asyncio.create_task(ai_thread_framework_run([AiFrameworkAgent()]))

    metadata = {}
    if len(sys.argv) > 1:
        try:
            metadata = json.loads(sys.argv[1])
        except (ValueError, TypeError):
            pass

    try:
        stats = await task_pipeline_run(max_actions=int(metadata.get('max_actions') or 1))
        print(json.dumps(stats, ensure_ascii=False))
    finally:
        framework_task.cancel()
        # Процесс отдельный, пул свой — закрываем явно, иначе соединения утекают.
        await mysql_pool_close()


if __name__ == '__main__':
    asyncio.run(main())

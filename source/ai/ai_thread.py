import asyncio
import copy
import queue
import threading
import time
import traceback

from source.ai.framework.ai_framework import AiFrameworkModel, AbstractAiFramework
from source.ai.framework.pydanticai.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from source.ai.framework.pydanticai.ai_framework_agent_model_pydantic import AiFrameworkAgentModelPydantic
from source.ai.framework.pydanticai.ai_framework_agent_pydantic import AiFrameworkAgentPydantic
from source.ai.framework.pydanticai.ai_framework_task_model_pydantic import AiFrameworkTaskModelPydantic
from source.ai.framework.pydanticai.ai_framework_task_pydantic import \
    AiFrameworkTaskPydantic, AiFrameworkTaskManagerPydantic
from source.async_ import async_loop_init
from source.logging_ import logger_info
from source.queue import queue_get

thread_started: dict[str, AiFrameworkModel] = {}


def ai_thread_run_async(ai_framework: AbstractAiFramework, framework_model: AiFrameworkModel):  # Добавили task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop_task = loop.create_task(ai_framework.framework_run(framework_model))
        async_loop_init(loop, loop_task)
        loop.run_until_complete(loop_task)
    except asyncio.CancelledError:
        logger_info("🛑 Поток успешно отменен")
    finally:
        loop.close()


def ai_thread_framework_run(window_instance):
    ai_framework_manager_task = AiFrameworkTaskManagerPydantic()
    ai_framework_task = AiFrameworkTaskPydantic(ai_framework_manager_task)

    ai_framework_agent = AiFrameworkAgentPydantic(AiFrameworkAgentManagerPydantic())

    while True:
        try:
            framework_model = None

            try:
                task_name = queue_get()['task'].get_nowait()
                framework_model = ai_framework_manager_task.load(task_name)
            except queue.Empty:
                time.sleep(0.1)

            try:
                framework_model = queue_get()['agent'].get_nowait()
            except queue.Empty:
                time.sleep(0.1)

            if not framework_model:
                continue

            ai_framework = None
            if isinstance(framework_model, AiFrameworkTaskModelPydantic):
                queue_get()['chat'].put({'text': f'Запускаю задачу {framework_model.title}', 'who': 'agent'})
                ai_framework = ai_framework_task
            if isinstance(framework_model, AiFrameworkAgentModelPydantic):
                queue_get()['chat'].put({'text': f'Запускаю агента {framework_model.title}', 'who': 'agent'})
                ai_framework = ai_framework_agent

            if framework_model.name not in thread_started:
                thread = threading.Thread(
                    target=ai_thread_run_async,
                    args=(ai_framework, framework_model),
                    daemon=True
                )
                thread.start()

                thread_started[framework_model.name] = framework_model

                framework_model_monitor = copy.deepcopy(framework_model)
                window_instance.after(100, lambda: window_instance.thread_monitor(thread, framework_model_monitor))

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Сбой в запуске ai framework: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
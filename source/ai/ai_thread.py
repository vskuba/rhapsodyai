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
from source.async_ import async_loop_init, async_waiting_is_active, async_waiting_clear
from source.logging_ import logger_info
from source.queue_ import queue_get

thread_started: dict[str, AiFrameworkModel] = {}

ai_framework_manager_task = AiFrameworkTaskManagerPydantic()
ai_framework_task = AiFrameworkTaskPydantic(ai_framework_manager_task)

ai_framework_agent = AiFrameworkAgentPydantic(AiFrameworkAgentManagerPydantic())


def ai_thread_run_async(ai_framework: AbstractAiFramework, framework_model: AiFrameworkModel):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop_task = loop.create_task(ai_framework.framework_run(framework_model))

        if not framework_model.is_sub_thread:
            async_loop_init(loop, loop_task, framework_model.name)

        loop.run_until_complete(loop_task)
    except asyncio.CancelledError:
        logger_info("🛑 Поток успешно отменен")
    finally:
        loop.close()


def ai_thread_framework_run(window = None):
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
                ai_framework = ai_framework_task
            if isinstance(framework_model, AiFrameworkAgentModelPydantic):
                ai_framework = ai_framework_agent

            if window:
                if isinstance(framework_model, AiFrameworkTaskModelPydantic):
                    queue_get()['chat'].put({'text': f'Запускаю задачу {framework_model.title}', 'who': 'agent'})
                if isinstance(framework_model, AiFrameworkAgentModelPydantic):
                    if framework_model.is_sub_thread:
                        queue_get()['chat'].put({
                            'text': f'Спрашиваю у агента "{framework_model.title}": ' + framework_model.prompt,
                            'who': 'agent'}
                        )
                    else:
                        queue_get()['chat'].put({'text': f'Запускаю агента "{framework_model.title}"', 'who': 'agent'})

            if not ai_framework:
                raise ValueError(f'Не могу определить ai_framework')

            if framework_model.name not in thread_started:
                thread = threading.Thread(
                    target=ai_thread_run_async,
                    args=(ai_framework, framework_model),
                    daemon=True
                )
                thread.start()

                logger_info(f'Старт нового потока "{framework_model.name}"')
                thread_started[framework_model.name] = framework_model

                framework_model_monitor = copy.deepcopy(framework_model)
                thread_monitor(window, thread, framework_model_monitor)

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Сбой в запуске ai framework: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )


def thread_monitor(window, thread: threading.Thread, framework_model: AiFrameworkModel):
    if thread.is_alive():
        threading.Timer(0.5, thread_monitor, args=(window, thread, framework_model)).start()
    else:
        if framework_model.name in thread_started:
            del thread_started[framework_model.name]

        if framework_model.is_sub_thread and async_waiting_is_active():
            async_waiting_clear()

        if not framework_model.is_sub_thread:
            if window:
                window.thread_monitor(framework_model)

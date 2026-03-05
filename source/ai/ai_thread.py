import asyncio
import queue
import threading
import time
import traceback

from source.ai.ai_framework import AiFrameworkModel, AbstractAiFramework
from source.ai.framework.pydanticai.ai_framework_task_pydantic import \
    AiFrameworkTaskPydantic, AiFrameworkTaskManagerPydantic
from source.async_ import async_loop_init
from source.logging_ import logger_info
from source.queue import queue_get

thread_task_started: dict[str, AiFrameworkModel] = {}


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
    while True:
        try:
            time.sleep(0.1)

            task_tuple = ai_thread_framework_task()
            # agent_tuple = ai_thread_framework_agent()

            if task_tuple and task_tuple[1].name not in thread_task_started:
                task = task_tuple[1]
                thread = threading.Thread(
                    target=ai_thread_run_async,
                    args=(task_tuple[0], task),
                    daemon=True
                )
                thread.start()

                thread_task_started[task.name] = task
                queue_get()['chat'].put({'text': f'Запускаю задачу {task.title}', 'who': 'agent'})

                # Запускаем монитор через окно, передав поток и имя задачи
                window_instance.after(100, lambda: window_instance.thread_monitor(thread, task))

            # if agent_tuple and agent_tuple[1].name not in thread_task_started:
            #     task = task_tuple[1]
            #     thread = threading.Thread(
            #         target=ai_thread_run_async,
            #         args=(task_tuple[0], task),
            #         daemon=True
            #     )
            #     thread.start()
            #
            #     thread_task_started[task.name] = task
            #     queue_get()['chat'].put({'text': f'Запускаю задачу {task.title}', 'who': 'agent'})
            #
            #     # Запускаем монитор через окно, передав поток и имя задачи
            #     window_instance.after(100, lambda: window_instance.thread_monitor(thread, task))


        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Сбой в запуске ai framework: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )


def ai_thread_framework_task():
    try:
        task_name = queue_get()['task'].get_nowait()
    except queue.Empty:
        time.sleep(0.1)
        return None

    framework_manager = AiFrameworkTaskManagerPydantic()

    return AiFrameworkTaskPydantic(framework_manager), framework_manager.load(task_name)


# def ai_thread_framework_agent():
#     try:
#         agent_name = queue_get()['agent'].get_nowait()
#     except queue.Empty:
#         time.sleep(0.1)
#         return None
#
#     framework_manager = AiFrameworkManagerTaskPydantic()
#
#     return AiFrameworkTaskPydantic(framework_manager), framework_manager.load(agent_name)

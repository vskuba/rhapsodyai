import asyncio
import queue
import threading
import time
import traceback


from source.ai.ai_task import AbstractAiTask
from source.ai.ai_task_framework import AiFramework
from source.ai.framework.pydanticai.ai_task_framework_pydantic import AiPydanticFramework
from source.ai.framework.pydanticai.ai_task_pydantic import AiPydanticTaskManager
from source.async_ import async_loop_init
from source.logging_ import logger_info
from source.queue import queue_get

thread_task_started: dict[str, AbstractAiTask] = {}


def ai_thread_run_async(ai_framework: AiFramework, task: AbstractAiTask):  # Добавили task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop_task = loop.create_task(ai_framework.framework_run(task))
        async_loop_init(loop, loop_task)
        loop.run_until_complete(loop_task)
    except asyncio.CancelledError:
        logger_info("🛑 Поток успешно отменен")
    finally:
        loop.close()


def ai_thread_framework_run(window_instance):
    task_manager = AiPydanticTaskManager()
    while True:
        try:
            try:
                task = queue_get()['task'].get_nowait()

                if isinstance(task, AbstractAiTask) and task.name not in thread_task_started:
                    ai_framework_instance = AiFramework(AiPydanticFramework(task_manager=task_manager))

                    thread = threading.Thread(
                        target=ai_thread_run_async,
                        args=(ai_framework_instance, task),
                        daemon=True
                    )
                    thread.start()

                    thread_task_started[task.name] = task
                    queue_get()['chat'].put({'text': f'Запускаю задачу {task.title}', 'who': 'agent'})

                    # Запускаем монитор через окно, передав поток и имя задачи
                    window_instance.after(100, lambda: window_instance.thread_monitor(thread, task))

            except queue.Empty:
                time.sleep(0.1)
                continue

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Сбой в запуске ai framework: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

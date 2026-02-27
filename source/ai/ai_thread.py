import asyncio
import queue
import threading
import time

from source.ai.ai_framework import AiFramework
from source.ai.ai_task import AbstractAiTask
from source.ai.framework.pydanticai.ai_pydantic_framework import AiPydanticFramework
from source.ai.framework.pydanticai.ai_pydantic_task import AiPydanticTaskManager
from source.async_ import async_loop_init
from source.queue import queue_get

thread_task_started: dict[str, AbstractAiTask] = {}


def ai_thread_run_async(ai_framework: AiFramework, task: AbstractAiTask):  # Добавили task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async_loop_init(loop)
    try:
        loop.run_until_complete(ai_framework.framework_run(task))
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
                    task.aborted = False

                    # Запускаем монитор через окно, передав поток и имя задачи
                    window_instance.after(100, lambda: window_instance.thread_monitor(thread, task))

            except queue.Empty:
                time.sleep(0.1)
                continue

        except Exception as e:
            print(f"❌ Сбой в запуске ai framework: {e}")

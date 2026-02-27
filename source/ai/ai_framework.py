import asyncio
import queue
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from source.ai.ai_task import AbstractAiTask, AbstractAiTaskManager
from source.config import config_get
from source.logging_ import logger_info
from source.queue import queue_get
from source.window.ui import window_chat_active_task_clear, window_chat_active_task_display


@dataclass
class AIFrameworkResult:
    text: str


@dataclass
class AIFrameworkHistory(ABC):
    @abstractmethod
    def history_get(self):
        pass


class AbstractAIFramework(ABC):
    def __init__(self, task_manager: AbstractAiTaskManager):
        self.task_manager = task_manager
        self.engine_storage: dict[str, Any] = {}

    @abstractmethod
    def engine_prepare(self, task: AbstractAiTask):
        pass

    @abstractmethod
    async def engine_run(self, task: AbstractAiTask):
        pass

    @abstractmethod
    def engine_result_handle(self, result, task: AbstractAiTask) -> AIFrameworkResult | None:
        pass

    @abstractmethod
    def task_history_filename_get(self, task: AbstractAiTask) -> str:
        pass

    @abstractmethod
    def task_history_dir_get(self) -> str:
        pass

    @abstractmethod
    def task_history_save(self, result, task: AbstractAiTask):
        pass

    @abstractmethod
    def task_history_load(self, task: AbstractAiTask) -> AIFrameworkHistory:
        pass

    def task_report(self, task: AbstractAiTask, report: str) -> str:
        filename = f"{task.name}_{task.id}.txt"
        path = '/'.join([
            config_get('data_dir'),
            config_get('report_dir'),
            filename
        ])
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'a', encoding='utf-8') as f:
            f.write(report + "\n")

        return path

    async def framework_run(self, task: AbstractAiTask):
        task_exception: bool = False
        while True:
            await asyncio.sleep(0.1)

            try:
                queue_get()['task_abort'].get_nowait()
                logger_info(f'🛑 Команда на остановку задачи "{task.title}"')
                return
            except queue.Empty:
                pass

            if getattr(task, 'aborted', False):
                logger_info(f'🛑 Задача "{task.title}" прервана пользователем.')
                queue_get()['chat'].put({'text': f'Задача "{task.title}" прервана пользователем', 'who': 'agent'})
                self.task_manager.task_active_set(None)
                window_chat_active_task_clear()
                return

            try:
                if task_exception and task:
                    logger_info('Возобновляем задачу..')
                    task_exception = False

                logger_info('🚀 Задача из очереди: "%s"' % task.name)
                self.task_manager.task_active_set(task)
                window_chat_active_task_display(task)

                self.engine_prepare(task)

                result = await self.engine_run(task)
                response = self.engine_result_handle(result, task)

                if response is not None:
                    queue_get()['chat'].put({"text": response.text, "who": 'agent'})

                if self.task_manager.task_is_complete(task):
                    self.task_manager.task_active_set(None)
                    window_chat_active_task_clear()
                    return
                else:
                    task = self.task_manager.task_continue(task)
                    continue

            except Exception as e:
                logger_info(f"❌🚀 Сбой в цикле агента: {e}.")
                traceback.print_exc()
                queue_get()['chat'].put({"text": 'Произошла ошибка: %s' % e, "who": 'agent'})

                # rate limit handling
                if getattr(e, 'status_code', None) == 429:
                    return

                queue_get()['chat'].put({"text": 'Работа будет продолжена', "who": 'agent'})
                task_exception = True
                continue


class AiFramework:
    def __init__(self, strategy: AbstractAIFramework):
        self._strategy = strategy

    def engine_prepare(self, task: AbstractAiTask):
        return self._strategy.engine_prepare(task)

    async def engine_run(self, task: AbstractAiTask):
        return await self._strategy.engine_run(task)

    def engine_result_handle(self, result, task: AbstractAiTask) -> AIFrameworkResult | None:
        response = self._strategy.engine_result_handle(result, task)

        if response is None:
            print("Менеджер не смог обработать ответ")
            return None

        return response

    async def framework_run(self, task: AbstractAiTask):
        return await self._strategy.framework_run(task)

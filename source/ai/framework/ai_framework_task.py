import asyncio
import queue
import traceback

from abc import abstractmethod
from pathlib import Path
from source.ai.framework.ai_framework import AbstractAiFramework, AiFrameworkModel
from source.ai.framework.ai_framework_task_manager import AbstractAiFrameworkTaskManager
from source.ai.framework.ai_framework_task_model import AbstractAiFrameworkTaskModel
from source.config import config_get
from source.logging_ import logger_info
from source.queue import queue_get


class AbstractAiFrameworkTask(AbstractAiFramework):
    def __init__(self, framework_manager: AbstractAiFrameworkTaskManager):
        super().__init__(framework_manager)
        self.framework_manager: AbstractAiFrameworkTaskManager = framework_manager

    @abstractmethod
    def task_history_filename_get(self, task: AbstractAiFrameworkTaskModel) -> str:
        pass

    @abstractmethod
    def task_history_dir_get(self) -> str:
        pass

    @abstractmethod
    def task_history_save(self, result, task: AbstractAiFrameworkTaskModel):
        pass

    @abstractmethod
    def task_history_load(self, task: AbstractAiFrameworkTaskModel) -> list:
        pass

    def task_report(self, task: AbstractAiFrameworkTaskModel, report: str) -> str:
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

    async def framework_run(self, framework_model: AiFrameworkModel):
        catch_exception: bool = False
        while True:
            await asyncio.sleep(0.1)

            try:
                queue_get()['task_abort'].get_nowait()
                logger_info(f'🛑 Команда на остановку задачи "{framework_model.name}"')
                return
            except queue.Empty:
                pass

            try:
                if catch_exception and framework_model:
                    logger_info('Возобновляем задачу..')
                    catch_exception = False

                logger_info('🚀 Задача из очереди: "%s"' % framework_model.name)
                self.framework_manager.task_active_set(framework_model)

                self.engine_prepare(framework_model)

                result = await self.engine_run(framework_model)
                response = self.engine_result_handle(result, framework_model)

                if response is not None:
                    queue_get()['chat'].put({"text": response.text, "who": 'agent'})

                if self.framework_manager.is_complete(framework_model):
                    self.framework_manager.task_active_set(None)
                    queue_get()['task_complete'].put(True)
                    return
                else:
                    framework_model = self.framework_manager.switch_next_sub_task(framework_model)
                    continue

            except Exception as e:
                backtrace = traceback.format_exc()
                logger_info(
                    f"❌ Сбой в цикле агента: {e}."
                    f"Полный стек вызовов:\n{backtrace}"
                )

                queue_get()['chat'].put({"text": 'Произошла ошибка: %s' % e, "who": 'agent'})

                # rate limit handling
                if getattr(e, 'status_code', None) in [429, 413]:
                    return

                queue_get()['chat'].put({"text": 'Работа будет продолжена', "who": 'agent'})
                catch_exception = True
                continue
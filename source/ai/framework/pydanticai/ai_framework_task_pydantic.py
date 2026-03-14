import os
import traceback

from pydantic import TypeAdapter
from pathlib import Path
from source.ai.framework.ai_framework import AiFrameworkResult
from source.ai.framework.ai_framework_task import AbstractAiFrameworkTask
from source.ai.ai_mcp import AiMcpManager
from source.ai.framework.pydanticai.ai_framework_task_manager_pydantic import AiFrameworkTaskManagerPydantic
from source.ai.framework.pydanticai.ai_framework_task_model_pydantic import AiFrameworkTaskModelPydantic
from source.config import config_get
from pydantic_ai import Agent, AgentRunResult, ToolCallPart, ToolReturnPart, ModelMessage, ModelSettings
from source.logging_ import logger_info


class AiFrameworkTaskPydantic(AbstractAiFrameworkTask):
    def __init__(self, framework_manager: AiFrameworkTaskManagerPydantic):
        super().__init__(framework_manager)
        self.framework_manager: AiFrameworkTaskManagerPydantic = framework_manager

    def engine_prepare(self, framework_model: AiFrameworkTaskModelPydantic):
        """
        Создает типизированного агента Pydantic-AI.
        Результат работы агента всегда будет объектом ResponseModel.
        """
        task = framework_model

        index = task.name + str(task.sub_task_current_index)
        if index in self.engine_storage:
            return self.engine_storage[index]

        model = self.llm_model_get(framework_model)

        engine = Agent(
            model,
            system_prompt=task.system_prompt.strip(),
            output_type=task.response_model,
            retries=10,
            output_retries=10
        )

        self.engine_storage[task.name] = engine

        if not self.message_history:
            self.message_history = self.task_history_load(task)

        self.engine_tools_local_add(engine, task)

        return engine

    async def engine_run(self, framework_model: AiFrameworkTaskModelPydantic):
        logger_info(
            f'🧱 Подзадача {framework_model.sub_task_current_index + 1}/{len(framework_model.yaml.sub_tasks)}, '
            f'prompt: {framework_model.prompt}'
        )
        logger_info(
            f'🧠 Передаем историю агенту:\n'
            f'{self.message_history if self.message_history else "пока ничего нет"}'
        )

        engine = self.engine_storage[framework_model.name]
        ai_mcp_manager = AiMcpManager()

        try:
            if framework_model.mcp_servers:
                await ai_mcp_manager.mcp_server_add_tools(engine, framework_model)

            return await engine.run(
                user_prompt=framework_model.prompt,
                # message_history=self.history,
                model_settings=ModelSettings(
                    parallel_tool_calls=True,
                    temperature=0.0,
                )
            )
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при выполнении задачи {framework_model.name}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise e

        finally:
            if framework_model.mcp_servers:
                logger_info(f'Закрываем MCP сессии для задачи {framework_model.name}...')
                await ai_mcp_manager.mcp_server_close_all()

    def engine_result_handle(self, result: AgentRunResult,
                             framework_model: AiFrameworkTaskModelPydantic) -> AiFrameworkResult | None:
        task = framework_model

        report = "\n\n======== Ответ от LLM: \"%s\" (%d/%d) выполнена ==================================\n\n" % \
                 (task.title, task.sub_task_current_index + 1, len(task.yaml.sub_tasks))
        if not result or not str(result).strip():
            return None
        report += "\n\n------- System prompt ------------------------------------------------------------\n\n"
        report += task.system_prompt
        report += "\n\n------- Prompt -------------------------------------------------------------------\n\n"
        report += task.prompt
        report += "\n\n------- Expect response model ----------------------------------------------------\n\n"
        fields_info = "\n".join(
            f"  - {name}: {info.annotation} (desc: {info.description})"
            for name, info in task.response_model.model_fields.items()
        )
        report += f"{task.response_model.__name__}\nFields:\n{fields_info}"

        # если ответ просто текст, а не модель
        if not result.output or isinstance(result.output, str):
            return AiFrameworkResult(str(result.output))
        report += "\n\n------- Raw response --------------------------------------------------------------\n\n"
        report += str(result)
        report += "\n\n------- Instrument logs -----------------------------------------------------------\n\n"
        for msg in result.all_messages():
            if hasattr(msg, 'parts'):
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        report += f"🛠 Вызов инструмента: {part.tool_name} с аргументами: {part.args}"
                    elif isinstance(part, ToolReturnPart):
                        report += f"🛠 Инструмент {part.tool_name} вернул: {part.content}"
        report += "\n\n------- Model result ---------------------------------------------------------------\n\n"
        response_model_dict = result.output.model_dump()
        fields_info = "\n".join(
            f"  - {name}: {response_model_dict[name]}"
            for name, _ in task.response_model.model_fields.items()
        )
        report += fields_info

        text = result.output.text
        response_model_dict = result.output.model_dump()
        del response_model_dict['text']

        task.input_values = task.input_values | response_model_dict
        report += "\n\n------- Input values refresh ------------------------------------------------------------\n\n"
        report += str(task.input_values)

        messages_new = result.new_messages()
        if messages_new:
            self.message_history += result.new_messages()

        logger_info(f'🧠 Получили новые сообщения истории в задаче "{task.title}"'
                    f' ({task.sub_task_current_index + 1}/{len(task.yaml.sub_tasks)})\n'
                    f' {self.message_history}')

        if task.history_save:
            self.task_history_save(result, task)

        report += "\n\n------- Result processed ----------------------------------------------------------------\n\n"
        report += text
        report += "\n\n======= Конец ответа от LLM =============================================================\n\n"

        self.task_report(task, report)

        return AiFrameworkResult(text)

    def task_history_save(self, result, task: AiFrameworkTaskModelPydantic):
        messages = result.all_messages()

        filename = self.task_history_filename_get(task)
        file_path = Path(filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(filename, 'wb') as f:
            f.write(TypeAdapter(list[ModelMessage]).dump_json(messages))

        logger_info('🧠 Сохранили историю в файл')

    def task_history_load(self, task: AiFrameworkTaskModelPydantic) -> list[ModelMessage]:
        filename = self.task_history_filename_get(task)
        if not os.path.exists(filename):
            return []

        with open(filename, 'rb') as f:
            data = f.read()

            return TypeAdapter(list[ModelMessage]).validate_json(data)

    def task_history_dir_get(self) -> str:
        return config_get('data_dir') + '/' + config_get('history_dir')

    def task_history_filename_get(self, task: AiFrameworkTaskModelPydantic) -> str:
        return '%s/%s_history.json' % (self.task_history_dir_get(), task.name)

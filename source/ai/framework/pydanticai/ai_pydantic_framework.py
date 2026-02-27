import os
import re
from pathlib import Path

import httpx
from pydantic import TypeAdapter
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.openai import OpenAIProvider

from source.ai.ai_mcp import AiMcpManager
from source.ai.framework.pydanticai.ai_pydantic_task import AiPydanticTask

from source.ai.ai_framework import AbstractAIFramework, AIFrameworkResult, AIFrameworkHistory
from source.config import config_get
from pydantic_ai import Agent, AgentRunResult, ToolCallPart, ToolReturnPart, ModelMessage, ModelSettings
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel

from source.logging_ import log_request_body, log_response_body, logger_info


class AIPydanticFrameworkHistory(AIFrameworkHistory):
    def __init__(self, messages):
        self.messages: list = messages

    def history_get(self):
        return self.messages


class AiPydanticFramework(AbstractAIFramework):
    def engine_prepare(self, task: AiPydanticTask):
        """
        Создает типизированного агента Pydantic-AI.
        Результат работы агента всегда будет объектом ResponseModel.
        """
        index = task.name + str(task.sub_task_current_index)
        if index in self.engine_storage:
            return self.engine_storage[index]

        http_client = httpx.AsyncClient(event_hooks={
            'request': [log_request_body],
            'response': [log_response_body]
        })

        model = None
        model_name = config_get('llm')

        if 'claude' in model_name.lower():
            provider = AnthropicProvider(
                api_key=config_get('ANTHROPIC_API_KEY'),
                http_client=http_client
            )
            model = AnthropicModel(model_name, provider=provider)

        if 'llama' in model_name.lower() or 'qwen' in model_name.lower():
            provider = OpenAIProvider(
                base_url='http://localhost:11434/v1',
                api_key='ollama',
                http_client=http_client
            )
            model_name = re.sub(r'^[^/]*/', '', model_name)
            model = OpenAIChatModel(
                model_name=model_name,
                provider=provider
            )

        if 'gemini' in model_name.lower():
            model = GoogleModel(
                model_name=model_name.lower()
            )

        if 'groq' in model_name.lower():
            if 'groq:' in model_name.lower():
                model_name = re.sub(r'^groq:', '', model_name, flags=re.IGNORECASE)

            provider = GroqProvider(
                api_key=os.getenv('GROQ_API_KEY'),
                base_url='https://api.groq.com',
                http_client=http_client
            )
            model = GroqModel(
                model_name=model_name,
                provider=provider,
            )

        if not model:
            model = OpenAIChatModel(model_name)

        print(f'System prompt: \n{task.system_prompt}\n')
        engine = Agent(
            model,
            system_prompt=task.system_prompt,
            output_type=task.response_model,
            output_retries=15
        )

        for tool in task.tools:
            engine.tool_plain(tool)

        self.engine_storage[task.name] = engine

        return engine

    async def engine_run(self, task: AiPydanticTask):
        input_values = task.input_values_get()
        # print('Вводные данные: %s' % input_values)

        prompt = task.prompt.format(**input_values)
        prompt = re.sub(r"\{(\w+)}", '', re.sub(r'\s+', ' ', prompt).strip())

        task.prompt_finalized = prompt

        if input_values:
            input_data = "\n".join(
                [f"{k}: {str(v).strip()}" for k, v in input_values.items()])
            task.prompt_finalized = f"<input_data>\n{input_data}\n</input_data>\n\n{task.prompt_finalized}"

        logger_info(
            f'🧱 Подзадача {task.sub_task_current_index + 1}/{len(task.sub_task_list)}, '
            f'prompt: {task.prompt_finalized}'
        )

        engine = self.engine_storage[task.name]
        ai_mcp_manager = AiMcpManager()
        try:
            if task.mcp_servers:
                mcp_sessions = await ai_mcp_manager.mcp_server_session(task.mcp_servers)
                for mcp_server_name, session in mcp_sessions.items():
                    await ai_mcp_manager.mcp_server_add_tools(engine, mcp_server_name, session)

            return await engine.run(
                user_prompt=task.prompt_finalized,
                message_history=self.task_history_load(task),
                model_settings=ModelSettings(
                    parallel_tool_calls=True,
                    temperature=0.0,
                )
            )
        except Exception as e:
            logger_info(f'Ошибка при выполнении задачи {task.name}: {e}')
            raise e
        finally:
            if task.mcp_servers:
                logger_info(f'Закрываем MCP сессии для задачи {task.name}...')
                await ai_mcp_manager.mcp_server_close_all()

    def engine_result_handle(self, result: AgentRunResult, task: AiPydanticTask) -> AIFrameworkResult | None:
        report = "\n\n======== Ответ от LLM: \"%s\" (%d/%d) выполнена ==================================\n\n" % \
                 (task.title, task.sub_task_current_index + 1, len(task.sub_task_list))
        if not result or not str(result).strip():
            return None
        report += "\n\n------- System prompt ------------------------------------------------------------\n\n"
        report += task.system_prompt
        report += "\n\n------- Prompt -------------------------------------------------------------------\n\n"
        report += task.prompt_finalized
        report += "\n\n------- Expect response model ----------------------------------------------------\n\n"
        fields_info = "\n".join(
            f"  - {name}: {info.annotation} (desc: {info.description})"
            for name, info in task.response_model.model_fields.items()
        )
        report += f"{task.response_model.__name__}\nFields:\n{fields_info}"

        # если ответ просто текст, а не модель
        if not result.output or isinstance(result.output, str):
            return AIFrameworkResult(str(result.output))
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

        if task.history_save:
            self.task_history_save(result, task)

        report += "\n\n------- Result processed ----------------------------------------------------------------\n\n"
        report += text
        report += "\n\n======= Конец ответа от LLM =============================================================\n\n"

        self.task_report(task, report)

        return AIFrameworkResult(text)

    def task_history_save(self, result, task: AiPydanticTask):
        messages = result.all_messages()

        filename = self.task_history_filename_get(task)
        file_path = Path(filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(filename, 'wb') as f:
            f.write(TypeAdapter(list[ModelMessage]).dump_json(messages))

    def task_history_load(self, task: AiPydanticTask):
        filename = self.task_history_filename_get(task)
        if not os.path.exists(filename):
            return None

        with open(filename, 'rb') as f:
            data = f.read()

            return TypeAdapter(list[ModelMessage]).validate_json(data)

    def task_history_dir_get(self) -> str:
        return config_get('data_dir') + '/' + config_get('history_dir')

    def task_history_filename_get(self, task: AiPydanticTask) -> str:
        return '%s/%s_history.json' % (self.task_history_dir_get(), task.name)

import json
import os
import re
import traceback

from pydantic import BaseModel, Field, create_model
from typing import Any, Tuple, List

from source.ai.framework.ai_framework_task_manager import AbstractAiFrameworkTaskManager
from source.ai.framework.ai_framework_task_model import AiTaskYaml
from source.ai.tool.ai_tool import ai_tools_get, ai_tools_permanent_get
from source.ai.framework.pydanticai.ai_framework_task_model_pydantic import AiFrameworkTaskModelPydantic
from source.config import config_get
from source.logging_ import  logger_info
from source.mcp import mcp_config_get


class AiFrameworkTaskManagerPydantic(AbstractAiFrameworkTaskManager):

    def dir(self) -> str:
        return config_get('data_dir') + '/' + config_get('task_dir')

    def list(self) -> list[str]:
        if not os.path.exists(self.dir()):
            return []

        return [os.path.splitext(f)[0] for f in os.listdir(self.dir()) if f.endswith('.yml')]

    def filepath_get(self, name: str) -> str:
        if name not in self.list():
            raise ValueError("Task with name '%s' not found" % name)

        return self.dir() + '/' + name + '.yml'

    def create(self, task_yaml: AiTaskYaml, input_values: dict[str, Any],
               sub_task_index: int = 0) -> AiFrameworkTaskModelPydantic:
        try:
            title = task_yaml.title
            sub_task_current = task_yaml.sub_tasks[sub_task_index]

            type_mapping = {
                'str': str,
                'bool': bool,
                'int': int,
                'float': float,
                'list': list
            }

            prompt_system = task_yaml.system_prompt
            pattern = r"\{env:([^}]+)}"
            matches = re.findall(pattern, prompt_system)
            if matches:
                for var_name in matches:
                    env_value = os.getenv(var_name, "")
                    prompt_system = prompt_system.replace(f"{{env:{var_name}}}", env_value)

            prompt = sub_task_current.prompt

            prompt, response_model, response_model_input_values = self.prompt_parse_response_model(prompt)

            input_values = input_values | response_model_input_values

            prompt, input_fields = self.prompt_parse_input_fields(prompt, input_values, response_model)

            task = AiFrameworkTaskModelPydantic(
                name=task_yaml.filename,
                title=title,
                prompt=prompt,
                system_prompt=prompt_system,
                input_fields=input_fields,
                response_model=response_model,
                tools=sub_task_current.tools,
                sub_task_current_index=sub_task_index,
                mcp_servers=task_yaml.mcp_servers
            )

            task.input_values_set(input_values)
            task.history_save = task_yaml.history_save

            return task

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при создании задачи {task_yaml.filename}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise

    def prompt_parse_response_model(self, prompt: str) -> Tuple[str, BaseModel, dict[str, str]]:
        type_mapping = {
            'str': str,
            'bool': bool,
            'int': int,
            'float': float,
            'list': list
        }
        # Формируем поля для нашей модели
        pattern = r"\{\{([^}|]+)\|([^:]+):(" + "|".join(type_mapping) + r")\}\}"
        matches = re.findall(pattern, prompt)

        # ожидаем final_result только если нужна model response
        response_model_fields = {
            'text': (str, Field(description="Final result"))
        }
        response_model_input_values = {}

        if matches:
            response_model_fields \
                = {
                      var: (type_mapping.get(t, Any), Field(description=desc)) for desc, var, t in
                      matches
                  } | response_model_fields
            response_model_input_values = {var: name for name, var, _ in matches}
            prompt = re.sub(r"\{\{([^}|]+)\|[^:]+:(" + "|".join(type_mapping) + r")}}", r"\1", prompt)

            # json_response_model = [str({k: t[0].__name__ for k, t in response_model_fields.items()})]
            # json_keys = ','.join(json_response_model)
            # prompt_extra = f"""
            # IMPORTANT: Your response MUST be in JSON format.
            # The JSON must regarding follow structure: "{json_keys}".
            # """

        # Создаем класс на лету, наследуясь от BaseModel
        return prompt, create_model('ResponseModel', **response_model_fields), response_model_input_values

    def prompt_parse_input_fields(
            self, prompt: str,
            input_values: dict[str, Any],
            response_model: BaseModel
    ) -> Tuple[str, List[str]]:

        pattern = r"\{\{(.*?)\}\}"
        input_fields = re.findall(pattern, prompt)

        # 2. БЕЗОПАСНАЯ ЗАМЕНА (Вместо prompt.format)
        # Заменяем только те ключи, которые обернуты в двойные скобки
        for key, value in input_values.items():
            placeholder = f"{{{{{key}}}}}"  # Это строка "{{key}}"
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, str(value))

        # 3. Очистка: убираем лишние пробелы и оставшиеся неиспользованные {{...}}
        # Важно: используем нежадный поиск .*?, чтобы не удалить лишнего между тегами
        prompt = re.sub(r"\{\{.*?}}", '', prompt)
        prompt = re.sub(r'\s+', ' ', prompt).strip()

        # --- Далее ваш существующий код для блоков <input_data> и <expect_data> ---
        input_and_expected_data = []
        if input_values:
            json_input_str = json.dumps(input_values, ensure_ascii=False)
            input_and_expected_data.append(f"<input_data>{json_input_str}</input_data>")

        json_response_model = response_model.model_json_schema()
        # Безопасное получение типов для схемы
        json_response_model_str = {
            k: p.get('type', 'any')
            for k, p in json_response_model.get('properties', {}).items()
        }
        input_and_expected_data.append(f"<expect_data>{json_response_model_str}</expect_data>")

        prompt = '\n'.join(input_and_expected_data) + f'\n\n{prompt}'

        return prompt, input_fields

    def validate(self, task_yaml: AiTaskYaml):
        try:

            mcp_tools = []
            if task_yaml.mcp_servers:
                for mcp_server_name in task_yaml.mcp_servers:
                    mcp_server_name = mcp_server_name.lower()
                    mcp_config = mcp_config_get(mcp_server_name)

                    if not mcp_config:
                        raise ValueError(f"MCP сервер '{mcp_server_name}' не найден")

                    mcp_tools += [t.name for t in mcp_config.tools]
            local_tools = [t.__name__ for t in ai_tools_get() + ai_tools_permanent_get()]
            tools = local_tools + mcp_tools

            input_values = {}
            for sub_task in task_yaml.sub_tasks:

                for tool_name in sub_task.tools:
                    if not any(t == tool_name for t in tools):
                        raise ValueError(f"Инструмент '{tool_name}' не найден в доступных ai_tools и mcp_tools.")

                # validate input_fields
                prompt = sub_task.prompt
                prompt, response_model, response_model_input_values = self.prompt_parse_response_model(prompt)
                input_values = input_values | response_model_input_values
                self.prompt_parse_input_fields(prompt, input_values, response_model)

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Файл {task_yaml.filename}.yml validate ошибка: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise Exception(f'Variable {e} is not defined in input fields.')
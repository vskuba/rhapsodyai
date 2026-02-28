import os
import re
import traceback
from typing import Any, Callable

from pydantic import BaseModel, create_model, Field

from source.ai.ai_task import AbstractAiTaskManager, AbstractAiTask, AiSubTask
from source.config import config_get
from source.logging_ import logger_info


class AiPydanticTask(AbstractAiTask):
    def __init__(
            self,
            name: str,
            title: str,
            sub_task_list: list[AiSubTask],
            sub_task_current_index: int,
            input_fields: list[str],
            system_prompt: str,
            prompt: str,
            tools: list[Callable],
            response_model: BaseModel | str = str,
            mcp_servers: list[str] = list,
    ):
        super().__init__(name, title, sub_task_list, sub_task_current_index, input_fields, mcp_servers)
        self.name = name
        self.system_prompt = system_prompt
        self.prompt = prompt
        self.tools = tools
        self.response_model = response_model

    def input_values_get(self):
        return super().input_values_get()


class AiPydanticTaskManager(AbstractAiTaskManager):
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

    def load(self, name: str, input_values: dict[str, str], sub_task_index: int = 0) -> AiPydanticTask:
        try:
            task_dict = self.task_yaml_validate(name)

            title = task_dict['title']
            sub_task_list = [AiSubTask(**({'inputs_default': {}} | item)) for item in task_dict.get('sub_task', [])]
            sub_task = sub_task_list[sub_task_index]

            type_mapping = {
                'str': str,
                'bool': bool,
                'int': int,
                'float': float
            }

            prompt_system = task_dict.get('system_prompt', '')
            pattern = r"\{env:([^}]+)}"
            matches = re.findall(pattern, prompt_system)
            if matches:
                for var_name in matches:
                    env_value = os.getenv(var_name, "")
                    prompt_system = prompt_system.replace(f"{{env:{var_name}}}", env_value)

            prompt = sub_task.prompt
            prompt_extra = ''

            # Формируем поля для нашей модели
            pattern = r"\{([^}|]+)\|([^:]+):(" + "|".join(type_mapping) + r")\}"
            matches = re.findall(pattern, prompt)

            # ожидаем final_result только если нужна model response
            response_model_fields = {
                'text': (str, Field(description="Финальный результат"))
            }
            response_model_fields_mapping = {}

            if matches:
                response_model_fields \
                    = {
                          var: (type_mapping.get(t, Any), Field(description=desc)) for desc, var, t in
                          matches
                      } | response_model_fields
                response_model_fields_mapping = {var: name for name, var, _ in matches}
                prompt = re.sub(r"\{([^}|]+)\|[^:]+:(" + "|".join(type_mapping) + r")}", r"\1", prompt)

                prompt_extra = """
                ВАЖНО: Твой ответ ОБЯЗАТЕЛЬНО должен быть в формате JSON. 
                JSON должен содержать следующие ключи: "json_keys".
                """
                json_keys = '", "'.join(list(response_model_fields.keys()))
                prompt_extra = prompt_extra.replace('json_keys', json_keys)

            # Создаем класс на лету, наследуясь от BaseModel
            response_model = create_model('ResponseModel', **response_model_fields)

            pattern = r"\{([^}]+)\}"
            matches = re.findall(pattern, prompt)
            input_fields = [name for name in matches]

            task = AiPydanticTask(
                name=name,
                title=title,
                system_prompt=prompt_system + prompt_extra,
                prompt=prompt,
                input_fields=input_fields,
                response_model=response_model,
                tools=sub_task.tools,
                sub_task_list=sub_task_list,
                sub_task_current_index=sub_task_index,
                mcp_servers=task_dict.get('mcp_servers', [])
            )

            task.input_values_set(sub_task.inputs_default | input_values | response_model_fields_mapping)
            task.history_save = task_dict.get('history_save', False)

            return task

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при создании задачи {name}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise

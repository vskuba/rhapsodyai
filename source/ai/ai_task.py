import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import Field, BaseModel

from source.ai.framework.pydanticai.ai_pydantic_tool import ai_pydantic_tools_get
from source.config import config_get
from source.mcp import mcp_config_load


class AiTaskYamlSubTask(BaseModel):
    name: str
    prompt: str
    inputs_default: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)


class AiTaskYaml(BaseModel):
    title: str
    history_save: bool = False
    mcp_servers: list[str] = Field(default_factory=list)
    system_prompt: str
    sub_task: list[AiTaskYamlSubTask] = Field(default_factory=list)


@dataclass
class AiSubTask:
    name: str
    prompt: str
    tools: list[Callable]
    inputs_default: dict[str, str]


class AbstractAiTask(ABC):
    def __init__(
            self,
            name: str,
            title: str,
            sub_task_list: list[AiSubTask],
            sub_task_current_index: int,
            input_fields: list[str],
            mcp_servers: list[str],
    ):
        self.id = str(uuid.uuid4())
        self.name = name
        self.title = title
        self.sub_task_list = sub_task_list
        self.sub_task_current_index = sub_task_current_index
        self.input_fields = input_fields
        self.mcp_servers = mcp_servers
        self.input_values: dict[str, str] = {}
        self.prompt_finalized: str | None = None
        self.schema_error: str | None = None
        self.history_save: bool = False
        self.max_tool_calls: int | None = 1
        self.aborted: bool = False

    def input_values_set(self, values: dict[str, str]):
        for k in self.input_fields:
            if k not in values.keys():
                raise ValueError("Input field '%s' is required, but not found in input set values: %s" % (k, values))
        self.input_values = values
        # print('Задача %s, содержит значения для параметров: %s' % (self.name, values))

    def input_values_get(self):
        for k in self.input_fields:
            if k not in self.input_values:
                self.input_values[k] = ''
        return self.input_values


class AbstractAiTaskManager(ABC):
    def __init__(self):
        self.active_task: AbstractAiTask | None = None

    @abstractmethod
    def dir(self) -> str:
        pass

    @abstractmethod
    def list(self) -> list[str]:
        pass

    @abstractmethod
    def filepath_get(self, name: str) -> str:
        pass

    @abstractmethod
    def load(self, name: str, input_values: dict[str, str], sub_task_index: int = 0) -> AbstractAiTask:
        pass

    def task_yaml_validate(self, name: str) -> dict[str, Any]:
        try:
            with open(self.filepath_get(name), 'r') as f:
                task_dict = yaml.safe_load(f)

            task_yaml = AiTaskYaml(**task_dict) #validate yaml by model class

            #validate mcp_servers
            if task_yaml.mcp_servers:
                mcp_config = mcp_config_load()
                for mcp_server_name in task_yaml.mcp_servers:
                    if mcp_server_name.lower() not in {k.lower() for k in mcp_config.keys()}:
                        raise ValueError(f"MCP сервер '{mcp_server_name}' не настроен в системе (tab_mcp).")

            # validate local tools
            tools = ai_pydantic_tools_get()
            for sub_task in task_yaml.sub_task:
                if sub_task.tools:
                    for tool_name in sub_task.tools:

                        if not any(t.__name__ == tool_name for t in tools):
                            raise ValueError(f"Инструмент '{tool_name}' не найден в доступных ai_tools.")

            return task_dict
        except Exception as e:
            print(f"Task {name} validate error: {e}.")
            raise

    def task_is_complete(self, task: AbstractAiTask) -> bool:
        return len(task.sub_task_list) <= (task.sub_task_current_index + 1)

    def task_continue(self, task: AbstractAiTask) -> AbstractAiTask:
        sub_task = self.load(task.name, task.input_values, task.sub_task_current_index + 1)
        sub_task.id = task.id
        return sub_task

    def task_active_set(self, task: AbstractAiTask | None):
        self.active_task = task

    def task_active_get(self, sub_task_index: int = 0):
        return self.active_task if self.active_task else self.load(
            config_get('welcome_task_name'),
            {},
            sub_task_index
        )



    def task_schema_yaml_update(self, name: str, key: str, value: str | bool):
        filepath = self.filepath_get(name)
        path = Path(filepath)

        if not path.exists():
            print(f"Ошибка: Файл {filepath} не найден.")
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.load(f, Loader=yaml.FullLoader) or {}

            data[key] = value

            with open(path, 'w', encoding='utf-8') as f:
                # allow_unicode=True сохранит кириллицу (например, в заголовках)
                # sort_keys=False сохранит текущий порядок ключей
                yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

            print(f"Обновлено: {key} = {value} в файле {name}")

        except Exception as e:
            print(f"Ошибка при обновлении YAML: {e}")

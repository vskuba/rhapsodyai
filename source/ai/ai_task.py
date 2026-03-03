import traceback
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from pydantic import Field, BaseModel

from source.ai.ai_tool import ai_tools_get, ai_tools_permanent_get
from source.config import config_get
from source.logging_ import logger_info
from source.mcp import mcp_config_get


class AiTaskYamlSubTask(BaseModel):
    name: str
    prompt: str
    inputs_default: dict[str, Any] = Field(default_factory=dict)
    tools: Optional[list[str]] = Field(default_factory=list)


class AiTaskYaml(BaseModel):
    title: str
    history_save: bool = False
    mcp_servers: list[str] = Field(default_factory=list)
    system_prompt: str
    sub_tasks: list[AiTaskYamlSubTask] = Field(default_factory=list)
    filename: str | None = None


@dataclass
class AiSubTask:
    name: str
    prompt: str
    tools: list[Callable] = field(default_factory=list)


class AbstractAiTask(ABC):
    def __init__(
            self,
            name: str,
            title: str,
            prompt: str,
            system_prompt: str,
            sub_task_current_index: int,
            input_fields: list[str],
            mcp_servers: list[str],
    ):
        self.id = str(uuid.uuid4())
        self.name = name
        self.title = title
        self.prompt: str = prompt
        self.system_prompt = system_prompt
        self.sub_task_current_index = sub_task_current_index
        self.input_fields = input_fields
        self.mcp_servers = mcp_servers
        self.input_values: dict[str, str] = {}
        self.yaml: AiTaskYaml | None = None
        self.history_save: bool = False

    def input_values_set(self, values: dict[str, str]):
        for k in self.input_fields:
            if k not in values.keys():
                raise ValueError(
                    f'Input field "{k}" is required, but not found in input set values: "{values}"'
                )
        self.input_values = values
        # logger_info('Задача %s, содержит значения для параметров: %s' % (self.name, values))

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
    def create(self, task_yaml: AiTaskYaml, input_values: dict[str, Any], sub_task_index: int = 0) -> AbstractAiTask:
        pass

    def load(self, name: str) -> AbstractAiTask:
        try:
            with open(self.filepath_get(name), 'r') as f:
                task_dict = yaml.safe_load(f)

            task_yaml = AiTaskYaml(**task_dict)
            task_yaml.filename = name

            self.validate(task_yaml)

            task = self.create(task_yaml, {}, 0)
            task.yaml = task_yaml

            return task

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Файл {name}.yml загрузка ошибка: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise

    def validate(self, task_yaml: AiTaskYaml):
        try:

            # validate mcp_servers
            mcp_tools = []
            if task_yaml.mcp_servers:
                for mcp_server_name in task_yaml.mcp_servers:
                    mcp_server_name = mcp_server_name.lower()
                    mcp_config = mcp_config_get(mcp_server_name)

                    if not mcp_config:
                        raise ValueError(f"MCP сервер '{mcp_server_name}' не найден")

                    mcp_tools += [t.name for t in mcp_config.tools]

            # validate tools
            local_tools = [t.__name__ for t in ai_tools_get() + ai_tools_permanent_get()]

            tools = local_tools + mcp_tools
            for sub_task in task_yaml.sub_tasks:
                if sub_task.tools:
                    for tool_name in sub_task.tools:
                        if not any(t == tool_name for t in tools):
                            raise ValueError(f"Инструмент '{tool_name}' не найден в доступных ai_tools и mcp_tools.")

            # validate input_fields
            # input_fields = []
            # for sub_task in task_yaml.sub_task:
            #     input_fields += sub_task.inputs_default.keys()
            # task_dict['input_fields'] = input_fields

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Файл {task_yaml.filename}.yml validate ошибка: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise

    def switch_next_sub_task(self, task: AbstractAiTask) -> AbstractAiTask:
        sub_task = self.create(task.yaml, task.input_values, task.sub_task_current_index + 1)
        sub_task.id = task.id
        sub_task.yaml = task.yaml

        return sub_task

    def is_complete(self, task: AbstractAiTask) -> bool:
        return len(task.yaml.sub_tasks) <= (task.sub_task_current_index + 1)

    def task_active_set(self, task: AbstractAiTask | None):
        self.active_task = task

    def task_active_get(self):
        return self.active_task

    def task_schema_yaml_update(self, name: str, key: str, value: str | bool):
        filepath = self.filepath_get(name)
        path = Path(filepath)

        if not path.exists():
            logger_info(f"Ошибка: Файл {filepath} не найден.")
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.load(f, Loader=yaml.FullLoader) or {}

            data[key] = value

            with open(path, 'w', encoding='utf-8') as f:
                # allow_unicode=True сохранит кириллицу (например, в заголовках)
                # sort_keys=False сохранит текущий порядок ключей
                yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

            logger_info(f"Обновлено: {key} = {value} в файле {name}")

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при обновлении YAML {name}.yml: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )

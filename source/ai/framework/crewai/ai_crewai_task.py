import os
from dataclasses import dataclass

import yaml

from source.ai.ai_task import AbstractAiTaskManager, AbstractAiTask
from source.config import config_get


@dataclass
class TaskTool:
    name: str


@dataclass
class TaskAgent:
    name: str
    role: str
    goal: str
    backstory: str
    tools: list[TaskTool]
    max_rpm: int
    allow_delegation: bool = False


@dataclass
class TaskTask:
    description: str
    expected_output: str
    agent_name: str
    tools: list[TaskTool]


class AiCrewaiTask(AbstractAiTask):
    def __init__(self, name: str, agents: list[TaskAgent], tasks: list[TaskTask], input_fields: list[str] = None):
        super().__init__(name, name, input_fields)
        self.name = name
        self.agents = agents
        self.tasks = tasks
        self.input_fields = input_fields
        self.input_values: dict[str, str] = {}


class AiCrewaiTaskManager(AbstractAiTaskManager):
    def dir(self) -> str:
        return config_get('data_dir') + '/' + config_get('crewai_task_dir')

    def list(self) -> list[str]:
        if not os.path.exists(self.dir()):
            return []

        return [os.path.splitext(f)[0] for f in os.listdir(self.dir()) if f.endswith('.yml')]

    def load(self, name: str) -> AiCrewaiTask:
        try:
            if name not in self.list():
                raise ValueError("Task with name %s not found" % name)

            with open(self.dir() + '/' + name + '.yml', 'r') as f:
                data = yaml.safe_load(f)

            agents = [
                TaskAgent(
                    name=a['name'],
                    role=a['role'],
                    goal=a['goal'],
                    backstory=a['backstory'],
                    tools=[TaskTool(name=t) for t in a.get('tools', [])],
                    allow_delegation=a.get('allow_delegation', False),
                    max_rpm=a.get('max_rpm', 10),
                ) for a in data['agents']
            ]

            tasks = [
                TaskTask(
                    description=a['description'],
                    expected_output=a['expected_output'],
                    agent_name=a['agent_name'],
                    tools=[TaskTool(name=t) for t in a.get('tools', [])],
                ) for a in data['tasks']
            ]

            return AiCrewaiTask(
                name=data['name'],
                agents=agents,
                tasks=tasks,
                input_fields=data.get('input_fields', None)
            )

        except Exception as e:
            print(f"Error: {e}.")
            raise

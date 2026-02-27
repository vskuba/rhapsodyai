import asyncio
import json
from typing import Any

# from crewai import Agent, Task as crewaiTask, Crew, Process, LLM

from source.ai.framework.crewai.ai_crewai_task import AiCrewaiTask
from source.ai.framework.crewai.ai_crewai_tools import ai_crewia_tools_get
from source.ai.ai_framework import AbstractAIFramework, AIFrameworkResult
from source.config import config_get


embedder_config: Any = {
    "provider": "ollama",
    "config": {
        "model": "nomic-embed-text",
        "base_url": "http://localhost:11434"
    }
}


class AiCrewaiFramework(AbstractAIFramework):
    def engine_prepare(self, task: AiCrewaiTask):
        """
        Создает экипаж CrewAI и подзадачи на основе главной задачи.
        Распределяет подзадачи между членами экипажа (агентами) и ждет результата.
        """
        if task.name in self.engine_storage:
            return self.engine_storage[task.name]

        model_name = config_get('llm')
        if (
                model_name.startswith('gpt')
                or model_name.startswith('deepseek')
        ):
            llm = LLM(model=model_name)
        else:
            llm = LLM(
                model=model_name,
                temperature=0.1,
                cache={"no-cache": True}
            )

        crew_agents = {}
        for agent in task.agents:

            tools = []
            for agent_tool in agent.tools:
                tools.append(ai_crewia_tools_get()[agent_tool.name].tool)

            crew_agents[agent.name] = Agent(
                role=agent.role,
                goal=agent.goal,
                backstory=agent.backstory,
                tools=tools,
                llm=llm,
                verbose=True,
                max_iter=2,  # Ограничь количество попыток агента
                allow_delegation=agent.allow_delegation,
                max_rpm=agent.max_rpm,
                step_callback=crewai_agent_step_callback
            )

        crew_tasks = []
        for task in task.tasks:

            tools = []
            for task_tool in task.tools:
                tools.append(ai_crewia_tools_get()[task_tool.name].tool)

            crew_tasks.append(crewaiTask(
                description=task.description,
                expected_output=task.expected_output,
                agent=crew_agents[task.agent_name],
                tools=tools,
            ))

        engine = Crew(
            agents=list(crew_agents.values()),
            tasks=crew_tasks,
            embedder=embedder_config,
            process=Process.sequential,
            memory=False,
            step_callback=crewai_agent_step_callback,
            cache=False,
            verbose=True
        )

        self.engine_storage[task.name] = engine

        return engine

    async def task_run(self, task: AiCrewaiTask):
        input_values = task.input_values_get()
        print('Вводные данные: %s' % input_values)

        return await asyncio.to_thread(self.engine_storage[task.name].kickoff, inputs=input_values)

    def task_result_handle(self, result, task: AiCrewaiTask) -> AIFrameworkResult | None:
        if not result or not str(result).strip():
            return None

        row = str(result)
        row = row.strip().strip('`').replace('json', '', 1).strip()
        # print("Ответ от LLM: %s" % row)

        try:
            result = json.loads(row, object_hook=lambda d: AIFrameworkResult(**d))

            if isinstance(result, str):
                return AIFrameworkResult(row)

        except (ValueError, json.JSONDecodeError):
            return AIFrameworkResult(row)


def crewai_agent_step_callback(step):
    if hasattr(step, 'tool'):
        print(f"--- Агент использовал инструмент: {step.tool} ---")
        print(f"Аргументы: {step.tool_input}")
    elif hasattr(step, 'output'):
        print(f"--- Агент завершил шаг с результатом: {step.output[:50]}... ---")

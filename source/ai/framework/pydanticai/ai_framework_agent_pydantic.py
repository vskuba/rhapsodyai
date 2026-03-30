import traceback

from source.ai.ai_mcp import AiMcpManager
from source.ai.framework.ai_framework import AiFrameworkResult
from source.ai.framework.ai_framework_agent import AbstractAiFrameworkAgent
from source.ai.framework.pydanticai.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from source.ai.framework.pydanticai.ai_framework_agent_model_pydantic import AiFrameworkAgentModelPydantic
from source.ai.framework.pydanticai.ai_framework_task_model_pydantic import AiFrameworkTaskModelPydantic
from pydantic_ai import Agent, AgentRunResult, ModelSettings
from source.logging_ import logger_info


class AiFrameworkAgentPydantic(AbstractAiFrameworkAgent):
    def __init__(self, framework_manager: AiFrameworkAgentManagerPydantic):
        super().__init__(framework_manager)
        self.framework_manager: AiFrameworkAgentManagerPydantic = framework_manager

    def engine_prepare(self, framework_model: AiFrameworkAgentModelPydantic) -> Agent:
        """
        Создает типизированного агента Pydantic-AI.
        Результат работы агента всегда будет объектом ResponseModel.
        """
        model = self.llm_model_get(framework_model)

        engine = Agent(
            model,
            system_prompt=framework_model.system_prompt.strip(),
            output_type=framework_model.response_model,
            retries=10,
            output_retries=10
        )

        self.engine_storage[framework_model.name] = engine

        self.engine_tools_local_add(engine, framework_model)

        return engine

    async def engine_run(self, framework_model: AiFrameworkAgentModelPydantic):
        message_history = self.message_history_get(framework_model)

        logger_info(
            f'🧠 Передаем историю агенту:\n'
            f'{message_history if message_history else "пока ничего нет"}'
        )

        engine = self.engine_storage[framework_model.name]
        ai_mcp_manager = AiMcpManager()

        try:
            if framework_model.mcp_servers:
                await ai_mcp_manager.mcp_server_add_tools(engine, framework_model)

            return await engine.run(
                user_prompt=framework_model.prompt,
                message_history=message_history,
                model_settings=ModelSettings(
                    parallel_tool_calls=True,
                    temperature=0.0,
                )
            )
        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка агента {framework_model.name}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise e

        finally:
            if framework_model.mcp_servers:
                logger_info(f'Закрываем MCP сессии для задачи {framework_model.name}...')
                await ai_mcp_manager.mcp_server_close_all()

    def engine_result_handle(
            self, result: AgentRunResult,
            framework_model: AiFrameworkTaskModelPydantic
    ) -> AiFrameworkResult | None:
        # если ответ просто текст, а не модель
        if not result.output or isinstance(result.output, str):
            return AiFrameworkResult(str(result.output))

        text = result.output.text

        messages_new = result.new_messages()
        if messages_new:
            self.message_history_add(framework_model, result.new_messages() + [result.output])

        return AiFrameworkResult(text)
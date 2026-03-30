import os
import traceback
from functools import partial

from pydantic import create_model, Field
from source.ai.framework.ai_framework_agent_manager import AbstractAiFrameworkAgentManager
from source.ai.framework.ai_framework_agent_model import AiAgentYaml
from source.ai.framework.pydanticai.ai_framework_agent_model_pydantic import AiFrameworkAgentModelPydantic
from source.config import config_get
from source.logging_ import logger_info
from source.queue_ import queue_get


class AiFrameworkAgentManagerPydantic(AbstractAiFrameworkAgentManager):
    def dir(self) -> str:
        return config_get('data_dir') + '/' + config_get('agent_dir')

    def list(self) -> list[str]:
        if not os.path.exists(self.dir()):
            return []

        names = [os.path.splitext(f)[0] for f in os.listdir(self.dir()) if f.endswith('.yml')]

        return sorted(names)

    def filepath_get(self, name: str) -> str:
        if name not in self.list():
            raise ValueError("Agent with name '%s' not found" % name)

        return self.dir() + '/' + name + '.yml'

    def create(self, agent_yaml: AiAgentYaml) -> AiFrameworkAgentModelPydantic:
        try:

            system_prompt = """
              ⚠️ STRICT API MODE:
              1. To provide the final answer, you MUST ALWAYS call the "final_result" tool.
              2. NO markdown formatting (no ```json ... ```), NO preamble, NO conversational text outside the JSON.
                
              Example JSON final response:
              final_result({"text": "This is an example of your concise response here."})   
                        
              """

            async def on_complete(response_text: str, framework_model: AiFrameworkAgentModelPydantic):
                if framework_model.interaction == 'chat':
                    queue_get()['chat'].put({"text": response_text, "who": 'agent'})
                if framework_model.interaction == 'telegram':
                    queue_get()['telegram_response'].put({"text": response_text, "framework_model": framework_model})

            framework_model = AiFrameworkAgentModelPydantic(
                name=agent_yaml.filename,
                title=agent_yaml.title,
                description=agent_yaml.description,
                prompt='',
                system_prompt=system_prompt + agent_yaml.system_prompt,
                tools=agent_yaml.tools,
                response_model=create_model('ResponseModel', **{
                    'text': (str, Field(description="Final result"))
                }),
                interaction=agent_yaml.interaction if agent_yaml.interaction else 'chat',
                mcp_servers=agent_yaml.mcp_servers
            )

            framework_model.on_complete=partial(on_complete, framework_model=framework_model)

            return framework_model

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при создании агента {agent_yaml.title}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise

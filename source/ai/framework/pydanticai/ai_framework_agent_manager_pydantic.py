import os
import traceback

from pydantic import create_model, Field
from source.ai.framework.ai_framework_agent_manager import AbstractAiFrameworkAgentManager
from source.ai.framework.ai_framework_agent_model import AiAgentYaml
from source.ai.framework.pydanticai.ai_framework_agent_model_pydantic import AiFrameworkAgentModelPydantic
from source.config import config_get
from source.logging_ import logger_info


class AiFrameworkAgentManagerPydantic(AbstractAiFrameworkAgentManager):
    def dir(self) -> str:
        return config_get('data_dir') + '/' + config_get('agent_dir')

    def list(self) -> list[str]:
        if not os.path.exists(self.dir()):
            return []

        return [os.path.splitext(f)[0] for f in os.listdir(self.dir()) if f.endswith('.yml')]

    def filepath_get(self, name: str) -> str:
        if name not in self.list():
            raise ValueError("Agent with name '%s' not found" % name)

        return self.dir() + '/' + name + '.yml'

    def create(self, agent_yaml: AiAgentYaml) -> AiFrameworkAgentModelPydantic:
        try:

            system_prompt = """
              ⚠️ STRICT API MODE:
              1. Your response MUST be a single, valid JSON object.
              2. NO markdown formatting (no ```json ... ```), NO preamble, NO conversational text outside the JSON.
              3. If you are providing a final answer, use the "final_result" tool format or return a JSON object with a "text" field.
              4. Output ONLY the tool call, function "final_result".
                
              JSON structure:
              {"text": "Your concise response here."}
                
              REJECTION: Any output that is not valid JSON will be rejected.
              
              """

            return AiFrameworkAgentModelPydantic(
                name=agent_yaml.filename,
                title=agent_yaml.title,
                description=agent_yaml.description,
                prompt='',
                system_prompt=system_prompt + agent_yaml.system_prompt,
                tools=agent_yaml.tools,
                response_model=create_model('ResponseModel', **{
                    'text': (str, Field(description="Final result"))
                })
            )

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при создании агента {agent_yaml.title}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise

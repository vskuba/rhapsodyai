import traceback

from pydantic import create_model, Field
from source.ai.framework.ai_framework_agent_manager import AbstractAiFrameworkAgentManager
from source.ai.framework.pydanticai.ai_framework_agent_model_pydantic import AiFrameworkAgentModelPydantic
from source.logging_ import logger_info


class AiFrameworkAgentManagerPydantic(AbstractAiFrameworkAgentManager):
    def create(self, name: str) -> AiFrameworkAgentModelPydantic:
        try:

            return AiFrameworkAgentModelPydantic(
                name=name,
                title=name,
                prompt='',
                system_prompt="""
                Your goal research needed response for customer request. Use tool 'chat_me' to ask customer 
                for more details if needed. If you have all information to answer, answer with 
                final result and do not ask customer for more details.
                
                You response must be in JSON format with only one field 'text' - this is final result for customer request.
                Do not use any other fields in JSON, only 'text'.
                
                Example of your final response:
                {"text": "Final answer for customer request"}
                
                Use tools 'chromadb_memory_save' and 'chromadb_memory_search' to save and search information in memory.
                
                CORE RULES:
                1. NEVER invent or hallucinate data when customer ask you something
                2. ALWAYS call 'search_memories' before answering any factual question.
                3. If 'search_memories' returns no relevant information, you MUST:
                   - State clearly that you do not have this information in your memory.
                   - Ask the user to provide the data so you can save it using 'save_to_memory'.
                4. Do not use your general training data to answer questions that should be in the database.
                5. If the user provides new information, use 'save_to_memory' immediately.
                
                When customer provide url you can use tool 'web_read_page' for read page content and then save 
                it to memory with 'chromadb_memory_save' tool.
                
                """,
                tools=[],
                response_model=create_model('ResponseModel', **{
                    'text': (str, Field(description="Final result"))
                })
            )

        except Exception as e:
            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Ошибка при создании агента {name}: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise

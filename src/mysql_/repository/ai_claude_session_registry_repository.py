from mysql_.repository.abstract_repository import AbstractRepository


class AiClaudeSessionRegistryRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'ai_claude_session_registry'

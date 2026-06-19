from mysql_.repository.abstract_repository import AbstractRepository


class LlmRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'llm'

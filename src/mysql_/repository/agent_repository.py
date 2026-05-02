from mysql_.repository.abstract_repository import AbstractRepository


class AgentRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'agent'

from mysql_.repository.abstract_repository import AbstractRepository


class AgentWorkflowRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'workflow'

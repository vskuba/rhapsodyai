from mysql_.repository.abstract_repository import AbstractRepository


class AgentWorkflowVariableRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'workflow_variable'

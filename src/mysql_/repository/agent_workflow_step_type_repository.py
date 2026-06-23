from mysql_.repository.abstract_repository import AbstractRepository


class AgentWorkflowStepTypeRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'workflow_step_type'

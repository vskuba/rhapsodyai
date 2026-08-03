from mysql_.repository.abstract_repository import AbstractRepository


class PlanningPhaseRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'project_planning_phase'

from py_modules.mysql_.repository.abstract_repository import AbstractRepository


class ProjectTeamRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'project_team'

from mysql_.repository.abstract_repository import AbstractRepository


class CompanionSessionRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'companion_session'

from mysql_.repository.abstract_repository import AbstractRepository


class EventLogRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'event_log'

from mysql_.repository.abstract_repository import AbstractRepository


class UserRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'user'

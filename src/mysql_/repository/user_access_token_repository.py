from mysql_.repository.abstract_repository import AbstractRepository


class UserAccessTokenRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'user_access_token'

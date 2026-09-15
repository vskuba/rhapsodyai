from mysql_.repository.abstract_repository import AbstractRepository


class BrowserProxyRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'browser_proxy'

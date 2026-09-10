from mysql_.repository.abstract_repository import AbstractRepository


class BrowserSiteRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'browser_site'

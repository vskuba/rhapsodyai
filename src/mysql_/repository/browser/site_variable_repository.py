from py_modules.mysql_.repository.abstract_repository import AbstractRepository


class BrowserSiteVariableRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'browser_site_variable'

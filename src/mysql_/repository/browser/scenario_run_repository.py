from mysql_.repository.abstract_repository import AbstractRepository


class BrowserScenarioRunRepository(AbstractRepository):
    def table_name_get(self) -> str:
        return 'browser_scenario_run'

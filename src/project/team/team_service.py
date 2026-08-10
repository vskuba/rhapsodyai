from datetime import datetime

from src.mysql_.repository.project.team_repository import ProjectTeamRepository
from src.mysql_.repository.project.task_type_repository import ProjectTaskTypeRepository


class TeamService:
    """Сервис для работы с командой и задачами."""

    async def team_list_get(self):
        """Получить список всех членов команды."""
        repo = ProjectTeamRepository()
        return await repo.find_by({}, order_by='id')

    async def team_member_get(self, member_id: int):
        """Получить члена команды по ID."""
        repo = ProjectTeamRepository()
        return await repo.find(member_id)

    async def team_member_get_by_role(self, role: str):
        """Получить члена команды по роли (manager / developer / qa).

        Оболочка claude-shell знает свою роль по флагу запуска, а не числовой ID,
        поэтому пинг приходит с ролью.
        """
        repo = ProjectTeamRepository()
        return await repo.find_one_by({'role': role}, order_by='id')

    async def team_ping(self, member_id: int, session: dict = None):
        """Обновить время пинга члена команды.

        Args:
            member_id: ID члена команды.
            session:   Данные запущенной оболочки — pid, session_uuid, work_dir.
                       Пишутся только те ключи, которые пришли непустыми.
        """
        repo = ProjectTeamRepository()
        data = {'status': 'active', 'last_ping_at': datetime.now()}
        data.update(self._session_data(session))
        await repo.update(member_id, data)

    async def team_task_types_get(self):
        """Получить все типы задач."""
        repo = ProjectTaskTypeRepository()
        return await repo.find_by({}, order_by='id')

    async def team_activate(self, member_id: int, session: dict = None):
        """Активировать члена команды (взять на работу)."""
        repo = ProjectTeamRepository()
        data = {'status': 'active', 'last_ping_at': datetime.now()}
        data.update(self._session_data(session))
        await repo.update(member_id, data)

    async def team_deactivate(self, member_id: int):
        """Деактивировать члена команды (отпустить).

        pid и session_uuid чистятся: процесса, на который они указывали, больше
        нет, а на карточке /admin/team они читались бы как признак живой сессии.
        """
        repo = ProjectTeamRepository()
        await repo.update(member_id, {'status': 'inactive', 'pid': None,
                                      'session_uuid': None})

    @staticmethod
    def _session_data(session: dict = None) -> dict:
        """Отобрать поля запущенной оболочки, которые можно писать в project_team."""
        if not session:
            return {}
        allowed = ('pid', 'session_uuid', 'work_dir')
        return {key: session[key] for key in allowed
                if session.get(key) not in (None, '')}

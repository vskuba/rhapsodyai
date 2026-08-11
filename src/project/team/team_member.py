"""
Члены команды в таблице `project_team`: чтение, presence-пинг и переключение
статуса. Здесь всё, что относится к самой записи члена команды; сборкой карточек
в разрезе проектов занимается `team_project`.
"""
from datetime_.datetime_ import datetime_utc_now

from src.mysql_.repository.project.team_repository import ProjectTeamRepository

# Поля запущенной оболочки, которые можно писать в project_team. Остальное из
# пинга игнорируем: оболочка внешняя, доверять её полям на запись нельзя.
TEAM_MEMBER_SESSION_FIELDS = ('pid', 'session_uuid', 'work_dir')


async def team_member_list() -> list:
    """Все члены команды в порядке добавления."""
    return await ProjectTeamRepository().find_by({}, order_by='id')


async def team_member_get(member_id: int):
    """Член команды по ID."""
    return await ProjectTeamRepository().find(member_id)


async def team_member_get_by_role(role: str):
    """Член команды по роли (manager / developer / qa).

    Оболочка claude-shell знает свою роль по флагу запуска, а не числовой ID,
    поэтому пинг приходит с ролью.
    """
    return await ProjectTeamRepository().find_one_by({'role': role}, order_by='id')


async def team_member_ping(member_id: int, session: dict = None) -> None:
    """Обновить время пинга члена команды.

    Args:
        member_id: ID члена команды.
        session:   Данные запущенной оболочки — pid, session_uuid, work_dir.
                   Пишутся только те ключи, которые пришли непустыми.

    Время — UTC, а не пояс из настройки Setting: `/admin/team` читает
    last_ping_at как UTC (`new Date(str + 'Z')`), сам переводит в пояс браузера
    и там же считает свежесть пинга. Сдвинутое значение дало бы и неверное время
    на карточке, и вечно «активного» члена команды.
    """
    data = {'status': 'active', 'last_ping_at': datetime_utc_now()}
    data.update(_session_data(session))
    await ProjectTeamRepository().update(member_id, data)


async def team_member_activate(member_id: int, session: dict = None) -> None:
    """Активировать члена команды (взять на работу)."""
    data = {'status': 'active', 'last_ping_at': datetime_utc_now()}
    data.update(_session_data(session))
    await ProjectTeamRepository().update(member_id, data)


async def team_member_deactivate(member_id: int) -> None:
    """Деактивировать члена команды (отпустить).

    pid и session_uuid чистятся: процесса, на который они указывали, больше
    нет, а на карточке /admin/team они читались бы как признак живой сессии.
    """
    await ProjectTeamRepository().update(member_id, {'status': 'inactive', 'pid': None,
                                                     'session_uuid': None})


def _session_data(session: dict = None) -> dict:
    """Отобрать поля запущенной оболочки, которые можно писать в project_team."""
    if not session:
        return {}

    return {key: session[key] for key in TEAM_MEMBER_SESSION_FIELDS
            if session.get(key) not in (None, '')}

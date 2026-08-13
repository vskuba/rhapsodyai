"""
Члены команды в таблице `project_team`: чтение, presence-пинг и переключение
статуса. Здесь всё, что относится к самой записи члена команды; сборкой карточек
в разрезе проектов занимается `team_project`.

Карточка принадлежит проекту (`project_id`): у каждого проекта свой набор ролей
со своей командой запуска и своим каталогом. Поэтому роль сама по себе строку не
определяет — её выбирают парой «роль + проект», а `project_id IS NULL` остаётся
для карточек, заведённых до этого разделения.
"""
from datetime_.datetime_ import datetime_utc_now

from src.mysql_.repository.project.project_repository import PlanningProjectRepository
from src.mysql_.repository.project.team_repository import ProjectTeamRepository

# Поля запущенной оболочки, которые можно писать в project_team. Остальное из
# пинга игнорируем: оболочка внешняя, доверять её полям на запись нельзя.
TEAM_MEMBER_SESSION_FIELDS = ('pid', 'session_uuid', 'work_dir')

# Заготовка карточек нового проекта: роль → (имя, команда запуска оболочки).
# Ключи — те же роли, что рисует блок проекта на `/admin/team`, а команда здесь
# без `cd`: каталог подставляется на карточке из work_dir проекта.
TEAM_MEMBER_ROLE_CARD = {
    'manager':   ('Manager',   'claude-shell --gx10 --manager'),
    'developer': ('Developer', 'claude-shell --gx10 --developer'),
    'qa':        ('QA',        'claude-shell --gx10 --qa'),
}


async def team_member_list() -> list:
    """Все члены команды в порядке добавления."""
    return await ProjectTeamRepository().find_by({}, order_by='id')


async def team_member_get(member_id: int):
    """Член команды по ID."""
    return await ProjectTeamRepository().find(member_id)


async def team_member_get_by_role(role: str, project_id: int | None = None):
    """Член команды по роли (manager / developer / qa) в рамках проекта.

    Оболочка claude-shell знает свою роль по флагу запуска, а не числовой ID,
    поэтому пинг приходит с ролью. Проект вычисляется по каталогу запуска
    (`team_project_id_by_work_dir`) и может не определиться — оболочку могли
    поднять где угодно. Тогда берём первую карточку роли: пинг всё равно должен
    во что-то попасть, иначе внешняя оболочка получит 404 на ровном месте.
    """
    repo = ProjectTeamRepository()
    if project_id:
        member = await repo.find_one_by({'role': role, 'project_id': project_id}, order_by='id')
        if member:
            return member

    return await repo.find_one_by({'role': role}, order_by='id')


async def team_member_cards_ensure(project_id: int) -> int:
    """Завести проекту недостающие карточки ролей.

    Зовётся при создании проекта: блок на `/admin/team` рисуется по строкам
    `project_team`, и без своих карточек новый проект показывал бы роли без имён
    и без команды запуска. Уже существующие карточки не трогаем — имя, команду и
    каталог правит человек.

    Returns: сколько карточек создано.
    """
    project_id = int(project_id or 0)
    if project_id <= 0:
        return 0

    project = await PlanningProjectRepository().find(project_id)
    if not project:
        return 0

    repo = ProjectTeamRepository()
    existing = {str(row.get('role') or '')
                for row in await repo.find_by({'project_id': project_id}, order_by='id')}

    created = 0
    for role, (name, command) in TEAM_MEMBER_ROLE_CARD.items():
        if role in existing:
            continue
        await repo.add({'project_id': project_id, 'name': name, 'role': role,
                        'command': command, 'work_dir': str(project.get('work_dir') or '')})
        created += 1

    return created


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

"""
Команда в разрезе проектов: блоки для `/admin/team`, где каждая карточка — роль
на конкретном проекте, а её активность считается по свежести пинга сессии
claude-shell. Записью статусов членов команды занимается `team_member`.
"""
from datetime import datetime

from datetime_.datetime_ import datetime_now

from src.mysql_.repository.ai_claude_session_registry_repository import AiClaudeSessionRegistryRepository
from src.mysql_.repository.project.project_repository import PlanningProjectRepository
from src.mysql_.repository.project.team_repository import ProjectTeamRepository

# Оболочка claude-shell пингует раз в 30 секунд. Порог заметно больше интервала,
# иначе карточка мигает «активна/не активна» на каждом задержавшемся пинге.
TEAM_PROJECT_PING_STALE_SECONDS = 60

# Роли, которые в блоке проекта есть всегда: нет живой сессии — карточка серая.
TEAM_PROJECT_ROLE_BASE = ('manager', 'developer', 'qa')

# Карточки одной роли идут рядом, QA — последней. Роль вне списка попадает
# между developer и qa, чтобы QA осталась в конце ряда.
TEAM_PROJECT_ROLE_ORDER = {'manager': 0, 'developer': 1, 'qa': 3}
TEAM_PROJECT_ROLE_ORDER_OTHER = 2

TEAM_PROJECT_ROLE_TITLE = {
    'manager': 'Менеджер задач',
    'developer': 'Разработчик',
    'qa': 'Тестировщик',
}

# Сессии в этих статусах — живые или закрывающиеся. 'inactive' означает
# завершённую оболочку: такие строки в реестре копятся и на странице не нужны.
TEAM_PROJECT_SESSION_STATUS_SHOWN = ('active', 'closing')


async def team_project_blocks_get() -> list[dict]:
    """Карточки команды в разрезе проектов.

    Один блок — один проект: заголовок это название проекта, внутри карточки ролей.
    Карточка активна, если с ней связана зарегистрированная сессия claude-shell со
    свежим пингом. Связь сессии с проектом — по совпадению ``project.work_dir`` и
    ``ai_claude_session_registry.work_dir``; для сессий, зарегистрированных до
    появления этой колонки, работает запасное совпадение ``project_label`` с
    названием проекта.

    Сессии, не сопоставленные ни одному проекту, собираются в отдельный блок
    «Без проекта» — иначе запущенная оболочка нигде не видна и выглядит потерянной.
    """
    projects = await PlanningProjectRepository().find_by({}, order_by='id ASC')
    members = await ProjectTeamRepository().find_by({}, order_by='id ASC')
    sessions = await AiClaudeSessionRegistryRepository().find_by({}, order_by='id ASC')
    now = await datetime_now()

    member_by_role = {str(row.get('role') or ''): row for row in members}
    # Оболочка без роли — обычная рабочая сессия claude-shell, к команде она
    # отношения не имеет, поэтому карточку для неё не показываем вообще.
    sessions_shown = [row for row in sessions
                      if str(row.get('status') or '') in TEAM_PROJECT_SESSION_STATUS_SHOWN
                      and str(row.get('role') or '').strip()]

    blocks = []
    matched_ids = set()
    for project in projects:
        project_sessions = _project_sessions_select(project, sessions_shown)
        matched_ids.update(row['id'] for row in project_sessions)
        blocks.append({
            'project_id': project.get('id'),
            'title': str(project.get('title') or f"Проект #{project.get('id')}"),
            'work_dir': str(project.get('work_dir') or ''),
            'cards': _cards_build(project_sessions, member_by_role,
                                  str(project.get('work_dir') or ''), now),
        })

    orphans = [row for row in sessions_shown if row['id'] not in matched_ids]
    if orphans:
        blocks.append({
            'project_id': 0,
            'title': 'Без проекта',
            'work_dir': '',
            'cards': _cards_build(orphans, member_by_role, '', now, placeholders=False),
        })

    return blocks


async def team_project_session_work_dir_sync(session_uuid: str, work_dir: str) -> bool:
    """Дозаполнить work_dir у строки реестра по session_uuid.

    Оболочки, зарегистрированные до появления колонки, шлют каталог только в
    /api/team/ping. Без этого их карточки не привязываются к проекту, пока
    оболочку не перезапустят. Заполненное значение не перетираем — каталог
    запуска у сессии не меняется.
    """
    session_uuid = str(session_uuid or '').strip()
    work_dir = str(work_dir or '').strip()
    if not session_uuid or not work_dir:
        return False

    repo = AiClaudeSessionRegistryRepository()
    row = await repo.find_one_by({'session_uuid': session_uuid})
    if not row or row.get('work_dir'):
        return False

    await repo.update(row['id'], {'work_dir': work_dir})

    return True


def _project_sessions_select(project: dict, sessions: list[dict]) -> list[dict]:
    """Сессии оболочек, относящиеся к проекту.

    Основной признак — work_dir. Он же и единственный надёжный: одна и та же
    оболочка на разных проектах отличается именно каталогом запуска.
    """
    work_dir = _path_normalize(project.get('work_dir'))
    title = str(project.get('title') or '').strip().lower()

    selected = []
    for row in sessions:
        session_dir = _path_normalize(row.get('work_dir'))
        if work_dir and session_dir:
            if session_dir == work_dir:
                selected.append(row)
            continue
        # Сессия без work_dir (зарегистрирована до появления колонки) —
        # сопоставляем по project_label, который claude-shell берёт из имени каталога.
        if not session_dir and title and str(row.get('project_label') or '').strip().lower() == title:
            selected.append(row)

    return selected


def _cards_build(sessions: list[dict], member_by_role: dict, work_dir: str,
                 now: datetime, placeholders: bool = True) -> list[dict]:
    """Собрать карточки блока: сессии плюс серые заглушки на роли без сессии."""
    cards = [_card_from_session(row, member_by_role, work_dir, now) for row in sessions]

    if placeholders:
        roles_present = {card['role'] for card in cards}
        for role in TEAM_PROJECT_ROLE_BASE:
            if role not in roles_present:
                cards.append(_card_placeholder(role, member_by_role, work_dir))

    cards.sort(key=lambda card: (
        TEAM_PROJECT_ROLE_ORDER.get(card['role'], TEAM_PROJECT_ROLE_ORDER_OTHER),
        0 if card['active'] else 1,
        -(card['seconds_ago'] if card['seconds_ago'] is not None else 10 ** 9),
    ))

    return cards


def _card_from_session(row: dict, member_by_role: dict, work_dir: str, now: datetime) -> dict:
    """Карточка живой (или недавно живой) сессии реестра.

    Роль здесь всегда заполнена — сессии без роли отфильтрованы выше.
    """
    role = str(row.get('role') or '').strip()
    member = member_by_role.get(role, {})
    seconds_ago = _seconds_ago(row.get('last_seen_at'), now)
    active = seconds_ago is not None and seconds_ago < TEAM_PROJECT_PING_STALE_SECONDS

    return {
        'role': role,
        'role_title': TEAM_PROJECT_ROLE_TITLE.get(role, role),
        'name': str(member.get('name') or TEAM_PROJECT_ROLE_TITLE.get(role, role)),
        'command': _command_build(member.get('command'), work_dir or row.get('work_dir')),
        'session_id': row.get('id'),
        'session_uuid': row.get('session_uuid'),
        'session_status': str(row.get('status') or ''),
        'server_llm': str(row.get('server_llm') or ''),
        'summary': str(row.get('summary') or ''),
        'work_dir': str(row.get('work_dir') or ''),
        'project_label': str(row.get('project_label') or ''),
        'last_seen_at': str(row.get('last_seen_at')) if row.get('last_seen_at') else None,
        'seconds_ago': seconds_ago,
        'active': active,
    }


def _card_placeholder(role: str, member_by_role: dict, work_dir: str) -> dict:
    """Серая карточка роли, у которой нет зарегистрированной сессии."""
    member = member_by_role.get(role, {})

    return {
        'role': role,
        'role_title': TEAM_PROJECT_ROLE_TITLE.get(role, role),
        'name': str(member.get('name') or TEAM_PROJECT_ROLE_TITLE.get(role, role)),
        'command': _command_build(member.get('command'), work_dir),
        'session_id': None,
        'session_uuid': None,
        'session_status': '',
        'server_llm': '',
        'summary': '',
        'work_dir': work_dir,
        'project_label': '',
        'last_seen_at': None,
        'seconds_ago': None,
        'active': False,
    }


def _command_build(command, work_dir) -> str:
    """Команда запуска с переходом в каталог проекта — её копируют кнопкой на карточке."""
    command = str(command or '').strip()
    work_dir = str(work_dir or '').strip()
    if not command:
        return ''
    if not work_dir:
        return command

    return f'cd {work_dir} && {command}'


def _seconds_ago(last_seen_at, now: datetime):
    """Свежесть пинга в секундах.

    ``last_seen_at`` реестра пишется через ``datetime_now()``, поэтому сравнивать
    его можно только со временем оттуда же: время контейнера и NOW() в MySQL дадут
    свои часовые пояса, и сессия окажется либо вечно живой, либо мгновенно мёртвой.
    """
    if not last_seen_at:
        return None

    return int((now - last_seen_at).total_seconds())


def _path_normalize(path) -> str:
    """Путь без хвостового слеша — '/srv/app' и '/srv/app/' это один каталог."""
    value = str(path or '').strip()
    if len(value) > 1:
        value = value.rstrip('/')

    return value

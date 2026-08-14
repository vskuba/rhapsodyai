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
from src.project.team.team_agent import team_agent_by_role
from src.project.team.team_queue import (TEAM_QUEUE_PREVIEW_LIMIT, TEAM_QUEUE_PROJECT_NONE,
                                         team_queue_by_project)
from src.project.task.task_setting_parallel import (
    TASK_SETTING_PARALLEL_DEFAULT,
    task_setting_parallel_all)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_PING_STALE,
    task_setting_timeout_get)

# Порог свежести карточки живёт в настройке `timeout_ping_stale` и правится на
# самой странице — см. `task_setting_timeout`. Читается один раз на сборку блоков и
# дальше передаётся аргументом: карточек на странице десятки, и запрос на каждую
# из них был бы запросом на пустом месте.

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

# Ключ карточек без проекта (`project_team.project_id IS NULL`) — те же строки
# питают блок «Без проекта». В БД это NULL, в словаре по проектам — 0.
TEAM_PROJECT_NO_PROJECT = 0


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

    На карточку кладётся очередь её роли по этому проекту (`team_queue`): сколько
    задач ждёт роль, первые из них списком и что роль делает прямо сейчас.
    """
    projects = await PlanningProjectRepository().find_by({}, order_by='position ASC')
    members = await ProjectTeamRepository().find_by({}, order_by='id ASC')
    sessions = await AiClaudeSessionRegistryRepository().find_by({}, order_by='id ASC')
    queues = await team_queue_by_project()
    agents = await team_agent_by_role()
    now = await datetime_now()
    stale_seconds = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_PING_STALE)
    # Пределы «Parallel LLM» — тоже одним запросом на сборку: селект есть в шапке
    # каждого блока (`task_setting_parallel`).
    parallel = await task_setting_parallel_all()

    members_by_project = _members_by_project(members)
    # Оболочка без роли — обычная рабочая сессия claude-shell, к команде она
    # отношения не имеет, поэтому карточку для неё не показываем вообще.
    sessions_shown = [row for row in sessions
                      if str(row.get('status') or '') in TEAM_PROJECT_SESSION_STATUS_SHOWN
                      and str(row.get('role') or '').strip()]

    blocks = []
    matched_ids = set()

    # Находим позицию для блока «Без проекта» — он имеет implicit position=0,
    # то есть перед первым проектом с position > 0. Проекты уже отсортированы
    # по position ASC, значит достаточно одного линейного прохода.
    insert_index = len(projects)
    for idx, proj in enumerate(projects):
        if int(proj.get('position') or 0) > 0:
            insert_index = idx
            break

    for project in projects:
        project_id = int(project.get('id') or 0)
        project_sessions = _project_sessions_select(project, sessions_shown)
        matched_ids.update(row['id'] for row in project_sessions)
        blocks.append({
            'project_id': project.get('id'),
            'title': str(project.get('title') or f"Проект #{project.get('id')}"),
            'work_dir': str(project.get('work_dir') or ''),
            'parallel': int(parallel.get(project_id, TASK_SETTING_PARALLEL_DEFAULT)),
            'cards': _cards_build(project_sessions, members_by_project.get(project_id, {}),
                                  str(project.get('work_dir') or ''), now, stale_seconds,
                                  queues=queues.get(project_id, {}), agents=agents),
        })

    orphans = [row for row in sessions_shown if row['id'] not in matched_ids]
    if orphans:
        blocks.insert(insert_index, {
            'project_id': 0,
            'title': 'Без проекта',
            'work_dir': '',
            'parallel': int(parallel.get(TEAM_PROJECT_NO_PROJECT, TASK_SETTING_PARALLEL_DEFAULT)),
            'cards': _cards_build(orphans, members_by_project.get(TEAM_PROJECT_NO_PROJECT, {}),
                                  '', now, stale_seconds, placeholders=False,
                                  queues=queues.get(TEAM_QUEUE_PROJECT_NONE, {}), agents=agents),
        })

    return blocks


async def team_project_id_by_work_dir(work_dir: str) -> int | None:
    """Проект, которому принадлежит каталог запуска оболочки.

    Тем же признаком блок проекта отбирает свои сессии: одна и та же оболочка на
    разных проектах отличается именно каталогом. Нужен пингу — по нему пинг
    находит карточку своего проекта, а не первую попавшуюся карточку роли.

    Returns: id проекта либо None, если каталог пуст или ничей.
    """
    work_dir = _path_normalize(work_dir)
    if not work_dir:
        return None

    for project in await PlanningProjectRepository().find_by({}, order_by='position ASC'):
        if _path_normalize(project.get('work_dir')) == work_dir:
            return int(project.get('id') or 0) or None

    return None


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


def _members_by_project(members: list[dict]) -> dict[int, dict]:
    """Карточки команды, разложенные по проекту и роли: {project_id: {role: row}}.

    Две карточки одной роли в одном проекте — данные кривые, а не рабочий случай:
    UNIQUE по (project_id, name) их не ловит, имена-то разные. Берём первую по id,
    как и раньше брала выборка по одной роли.
    """
    by_project: dict[int, dict] = {}
    for row in members:
        project_id = int(row.get('project_id') or TEAM_PROJECT_NO_PROJECT)
        by_project.setdefault(project_id, {}).setdefault(str(row.get('role') or ''), row)

    return by_project


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
                 now: datetime, stale_seconds: int, placeholders: bool = True,
                 queues: dict | None = None, agents: dict | None = None) -> list[dict]:
    """Собрать карточки блока: сессии плюс серые заглушки на роли без сессии."""
    cards = [_card_from_session(row, member_by_role, work_dir, now, stale_seconds)
             for row in sessions]
    cards = _cards_stale_drop(cards)

    if placeholders:
        roles_present = {card['role'] for card in cards}
        for role in TEAM_PROJECT_ROLE_BASE:
            if role not in roles_present:
                cards.append(_card_placeholder(role, member_by_role, work_dir))

    _cards_queue_attach(cards, queues or {})
    _cards_agent_attach(cards, agents or {})

    cards.sort(key=lambda card: (
        TEAM_PROJECT_ROLE_ORDER.get(card['role'], TEAM_PROJECT_ROLE_ORDER_OTHER),
        0 if card['active'] else 1,
        -(card['seconds_ago'] if card['seconds_ago'] is not None else 10 ** 9),
    ))

    return cards


def _cards_queue_attach(cards: list[dict], queues: dict) -> None:
    """Положить на каждую карточку очередь её роли по этому проекту.

    Очередь принадлежит роли, а не сессии: если одну роль держат две оболочки,
    обе карточки покажут одну и ту же очередь — конвейер разбирает её общей.
    Заглушке роли очередь тоже нужна: именно она объясняет, почему задачи стоят.

    «В работе» показываем только тогда, когда работает сама оболочка роли.
    Блокировка в БД принадлежит воркеру конвейера, а не оболочке, и переживает
    его смерть: у погасшей карточки (`active = False`) или у свободного агента
    (`agent_status = 'ready'`) такая строка читалась бы как работа того, кто уже
    ничего не делает. Возвращаем её в начало очереди — роль её всё равно ждёт,
    блокировку снимет `task_claim_locks_reclaim()`.

    Неизвестный статус агента (пустая строка) работой не считаем и не опровергаем:
    у таких карточек остаётся признак по блокировке. Короткий провал в 'ready'
    между захватом и запуском шага покажет задачу первой в очереди — это ближе к
    правде, чем «в работе» у агента, который к ней ещё не приступил.
    """
    for card in cards:
        slot = queues.get(card['role']) or {}
        waiting = list(slot.get('waiting') or [])
        count = int(slot.get('waiting_count') or 0)
        current = slot.get('current')

        idle = not card['active'] or card.get('agent_status') == 'ready'
        if current and idle:
            waiting.insert(0, current)
            count += 1
            current = None

        card['queue_count'] = count
        card['queue'] = waiting[:TEAM_QUEUE_PREVIEW_LIMIT]
        card['queue_current'] = current


def _cards_agent_attach(cards: list[dict], agents: dict) -> None:
    """Положить на карточку агента и workflow её роли (`team_agent`).

    Агент принадлежит роли, а не проекту: карточки менеджеров всех проектов гоняют
    один и тот же `task_plan_manager`, различаясь только оболочкой, в которую он
    ходит. Поэтому словарь общий на страницу.

    Роли без агента получают нули и пустые подписи, а не отсутствие ключей: на
    карточке это две ненарисованные строки, и фронтенду не приходится различать
    «агента нет» и «поле забыли положить».
    """
    for card in cards:
        slot = agents.get(card['role']) or {}
        card['agent_id'] = int(slot.get('agent_id') or 0)
        card['agent_title'] = str(slot.get('agent_title') or '')
        card['workflow_id'] = int(slot.get('workflow_id') or 0)
        card['workflow_title'] = str(slot.get('workflow_title') or '')


def _cards_stale_drop(cards: list[dict]) -> list[dict]:
    """Оставить у роли все живые карточки и не больше одной протухшей.

    Закрытая оболочка остаётся в реестре строкой со статусом 'active' — узнать о
    закрытии терминала можно только по протухшему пингу, и строки копятся: каждый
    запуск роли добавляет свою. Пока роль жива, все они прячутся за живой
    карточкой, но стоит закрыть последнюю оболочку — и в ряду появляется столько
    серых карточек, сколько раз роль когда-либо запускали.

    Поэтому протухшую карточку роли оставляем ровно одну и самую свежую: она
    показывает, что роль когда-то работала, и несёт команду запуска, а остальные
    ничем от неё не отличаются. Живые не трогаем — две живые оболочки одной роли
    это реальная ситуация, и обе должны быть видны.
    """
    roles_active = {card['role'] for card in cards if card['active']}

    kept, stale_seen = [], set()
    for card in sorted(cards, key=_card_freshness):
        if card['active']:
            kept.append(card)
            continue
        if card['role'] in roles_active or card['role'] in stale_seen:
            continue
        stale_seen.add(card['role'])
        kept.append(card)

    return kept


def _card_freshness(card: dict) -> int:
    """Ключ сортировки «сначала свежие»: карточка без пинга уходит в самый конец."""
    seconds_ago = card.get('seconds_ago')

    return seconds_ago if seconds_ago is not None else 10 ** 9


def _card_from_session(row: dict, member_by_role: dict, work_dir: str, now: datetime,
                       stale_seconds: int) -> dict:
    """Карточка живой (или недавно живой) сессии реестра.

    Роль здесь всегда заполнена — сессии без роли отфильтрованы выше.
    """
    role = str(row.get('role') or '').strip()
    member = member_by_role.get(role, {})
    seconds_ago = _seconds_ago(row.get('last_seen_at'), now)
    active = seconds_ago is not None and seconds_ago < stale_seconds

    return {
        'role': role,
        'role_title': TEAM_PROJECT_ROLE_TITLE.get(role, role),
        'name': str(member.get('name') or TEAM_PROJECT_ROLE_TITLE.get(role, role)),
        'command': _command_build(member.get('command'), work_dir or row.get('work_dir')),
        'session_id': row.get('id'),
        'session_uuid': row.get('session_uuid'),
        'session_status': str(row.get('status') or ''),
        # Готовность агента: 'ready' — сообщение уйдёт в дочерний процесс сразу,
        # 'busy' — встанет в очередь. Показываем только у активных карточек: у
        # протухшего пинга это последнее известное значение, а не текущее.
        'agent_status': str(row.get('agent_status') or '') if active else '',
        'agent_status_reason': str(row.get('agent_status_reason') or '') if active else '',
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
        'agent_status': '',
        'agent_status_reason': '',
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

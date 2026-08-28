"""
Команда в разрезе проектов: блоки для `/admin/team`, где каждая карточка — роль
на конкретном проекте, а её активность считается по свежести пинга сессии
claude-shell. Записью статусов членов команды занимается `team_member`.
"""
import re
from datetime import datetime

from datetime_.datetime_ import datetime_now

from src.mysql_.repository.ai_claude_session_registry_repository import AiClaudeSessionRegistryRepository
from src.mysql_.repository.project.project_repository import PlanningProjectRepository
from src.mysql_.repository.project.team_repository import ProjectTeamRepository
from src.project.team.team_setting_autocompact import (
    TEAM_SETTING_AUTOCOMPACT_FLAG, team_setting_autocompact_get)
from src.project.team.team_agent import team_agent_by_role
from src.project.team.team_llm_pool import (team_llm_pool_all, team_llm_pool_locks,
                                            team_llm_pool_sessions)
from src.project.team.team_shell_pool import team_shell_pool_tasks
from src.project.team.team_member import team_member_command_llm_normalize
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
TEAM_PROJECT_ROLE_BASE = ('manager', 'developer', 'qa', 'bugfixer')

# Ряд идёт по конвейеру: менеджер планирует, разработчик делает, QA принимает.
# Багфиксер стоит четвёртым — он вне этой цепочки: у бага нет ни плана, ни подзадач,
# ни круга с QA, и в ряду он читается как отдельная ветка, а не как шаг между
# разработчиком и приёмкой.
#
# Шаг десять, а не единица: роль вне списка встаёт между developer и qa
# (`..._OTHER`), и без зазора её некуда было бы поставить — она слипалась бы с QA
# в одну позицию, и порядок таких карточек решался бы уже свежестью пинга.
TEAM_PROJECT_ROLE_ORDER = {'manager': 0, 'developer': 10, 'qa': 20, 'bugfixer': 30}
TEAM_PROJECT_ROLE_ORDER_OTHER = 15

TEAM_PROJECT_ROLE_TITLE = {
    'manager': 'Менеджер задач',
    'developer': 'Разработчик',
    'bugfixer': 'Багфиксер',
    'qa': 'Тестировщик',
}

# Сессии в этих статусах — живые или закрывающиеся. 'inactive' означает
# завершённую оболочку: такие строки в реестре копятся и на странице не нужны.
TEAM_PROJECT_SESSION_STATUS_SHOWN = ('active', 'closing')

# Ключ карточек без проекта (`project_team.project_id IS NULL`) — те же строки
# питают блок «Без проекта». В БД это NULL, в словаре по проектам — 0.
TEAM_PROJECT_NO_PROJECT = 0


# Каталог рабочих выкладок внутри проекта — в нём поднимают оболочку роли
# (см. `team_member.TEAM_MEMBER_WORKTREES_DIR`).
TEAM_PROJECT_WORKTREES_DIR = '.claude/worktrees'

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
    projects = await PlanningProjectRepository().find_by({}, order_by='position ASC, id ASC')
    members = await ProjectTeamRepository().find_by({}, order_by='id ASC')
    # Порог автосжатия читаем один раз на весь показ: он общий для всех карточек,
    # а запрос на каждую дал бы их столько, сколько ролей во всех проектах.
    autocompact = await team_setting_autocompact_get()
    sessions = await AiClaudeSessionRegistryRepository().find_by({}, order_by='id ASC')
    queues = await team_queue_by_project()
    agents = await team_agent_by_role()
    now = await datetime_now()
    stale_seconds = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_PING_STALE)
    # Предел одновременных прогонов. У проекта с пулом это его длина, у проекта без
    # пула — прежняя настройка (`task_setting_parallel`): он идёт напрямую в облачный
    # Anthropic, и считать там нечего.
    parallel = await task_setting_parallel_all()
    # Пулы и живые захваты — одним чтением на сборку блоков, как и пределы: карточек
    # на странице десятки, и запрос на каждую был бы запросом на пустом месте.
    pools = await team_llm_pool_all()
    # Какая оболочка какую задачу держит: по этому идущие круги ложатся на свои
    # карточки, а не все на первую (`_cards_queue_attach`). Одним чтением на сборку.
    shell_tasks = await team_shell_pool_tasks()
    # Чем какая оболочка занята прямо сейчас. Реестр сессий помнит последнюю модель
    # навсегда, и после круга карточка показывала её как свою — при том, что модель
    # уже отдана соседу. Захват гаснет вместе с кругом, и по нему видно текущее.
    llm_by_session = await team_llm_pool_sessions()
    locks = {}
    for lock in await team_llm_pool_locks():
        locks.setdefault(int(lock.get('project_id') or 0), []).append({
            'llm': lock.get('llm_name'), 'role': lock.get('role'),
            'task_id': lock.get('task_id'),
        })

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
            'parallel': _parallel_of(project_id, parallel, pools),
            # Пул задаёт и чем работать, и сколько работ разом: предел — его длина.
            'llm_pool': pools.get(project_id, []),
            'llm_busy': locks.get(project_id, []),
            'cards': _cards_build(project_sessions, members_by_project.get(project_id, {}),
                                  str(project.get('work_dir') or ''), now, stale_seconds,
                                  queues=queues.get(project_id, {}), agents=agents,
                                  autocompact=autocompact, shell_tasks=shell_tasks,
                                  llm_by_session=llm_by_session, pool=pools.get(project_id, [])),
        })

    orphans = [row for row in sessions_shown if row['id'] not in matched_ids]
    if orphans:
        blocks.insert(insert_index, {
            'project_id': 0,
            'title': 'Без проекта',
            'work_dir': '',
            'parallel': _parallel_of(TEAM_PROJECT_NO_PROJECT, parallel, pools),
            'llm_pool': pools.get(TEAM_PROJECT_NO_PROJECT, []),
            'llm_busy': locks.get(TEAM_PROJECT_NO_PROJECT, []),
            'cards': _cards_build(orphans, members_by_project.get(TEAM_PROJECT_NO_PROJECT, {}),
                                  '', now, stale_seconds, placeholders=False,
                                  queues=queues.get(TEAM_QUEUE_PROJECT_NONE, {}), agents=agents,
                                  autocompact=autocompact, shell_tasks=shell_tasks,
                                  llm_by_session=llm_by_session,
                                  pool=pools.get(TEAM_PROJECT_NO_PROJECT, [])),
        })

    return blocks


async def team_project_id_by_work_dir(work_dir: str) -> int | None:
    """Проект, которому принадлежит каталог запуска оболочки.

    Тем же признаком блок проекта отбирает свои сессии: одна и та же оболочка на
    разных проектах отличается именно каталогом. Нужен пингу — по нему пинг
    находит карточку своего проекта, а не первую попавшуюся карточку роли.

    Returns: id проекта либо None, если каталог пуст или ничей.
    """
    # Оболочку роли поднимают в выкладках проекта (`.claude/worktrees`), а
    # проекты записаны своим корнем: хвост снимаем, иначе пинг не нашёл бы
    # карточку и она осталась бы «не запущена» при живой оболочке.
    work_dir = _team_project_dir(work_dir)
    if not work_dir:
        return None

    for project in await PlanningProjectRepository().find_by({}, order_by='position ASC, id ASC'):
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


def _parallel_of(project_id: int, parallel: dict, pools: dict) -> int:
    """
    Сколько прогонов проект ведёт одновременно.

    Пул есть — его длина: работать разом можно ровно настолько, насколько хватает
    моделей. Пула нет — прежняя настройка: проект идёт напрямую в облачный Anthropic,
    и делить там нечего.

    Правило то же, что у отбора работы (`task_pipeline._parallel_limits`), — разойдись
    они, страница обещала бы одно число, а конвейер работал по другому.
    """
    pool = pools.get(project_id) or []

    return len(pool) or int(parallel.get(project_id, TASK_SETTING_PARALLEL_DEFAULT))


def _members_by_project(members: list[dict]) -> dict[int, dict]:
    """Карточки команды, разложенные по проекту и роли: {project_id: {role: row}}.

    Строка на роль одна: `project_team` описывает роль проекта — её имя и команду
    запуска, — а не запущенную оболочку. Оболочек у роли бывает несколько, и все они
    берут описание из этой строки; сами карточки на странице растут из реестра сессий
    (`_card_from_session`), а не отсюда.

    Две строки одной роли в одном проекте — данные кривые, а не рабочий случай: UNIQUE
    по (project_id, name) их не ловит, имена-то разные. Берём первую по id.
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
                 queues: dict | None = None, agents: dict | None = None,
                 autocompact: str = '', shell_tasks: dict | None = None,
                 llm_by_session: dict | None = None, pool: list | None = None) -> list[dict]:
    """
    Собрать карточки блока: сессии плюс серые заглушки на роли без сессии.

    Карточка растёт из живой оболочки, а не из строки `project_team`: подняли роли
    вторую оболочку — на странице появилась вторая карточка, погасили — исчезла.
    Заглушка нужна ровно для обратного случая: роль есть в заготовке, а оболочки под
    ней нет ни одной, и человеку неоткуда взять команду запуска.
    """
    cards = [_card_from_session(row, member_by_role, work_dir, now, stale_seconds, autocompact,
                                llm_by_session or {}, bool(pool))
             for row in sessions]
    cards = _cards_stale_drop(cards)

    if placeholders:
        roles_present = {card['role'] for card in cards}
        for role in TEAM_PROJECT_ROLE_BASE:
            if role not in roles_present:
                cards.append(_card_placeholder(role, member_by_role, work_dir, autocompact))

    _cards_queue_attach(cards, queues or {}, shell_tasks)
    _cards_agent_attach(cards, agents or {})

    cards.sort(key=lambda card: (
        TEAM_PROJECT_ROLE_ORDER.get(card['role'], TEAM_PROJECT_ROLE_ORDER_OTHER),
        0 if card['active'] else 1,
        -(card['seconds_ago'] if card['seconds_ago'] is not None else 10 ** 9),
    ))

    return cards


def _cards_queue_attach(cards: list[dict], queues: dict, shell_tasks: dict | None = None) -> None:
    """Положить на каждую карточку очередь её роли и её собственный идущий круг.

    Ожидающая очередь принадлежит роли, а не оболочке: конвейер разбирает её общей,
    и все карточки роли показывают одну и ту же. Заглушке роли она тоже нужна —
    именно очередь объясняет, почему задачи стоят.

    А вот **«в работе» у каждой оболочки своё**: их у роли столько, сколько
    терминалов открыл человек, и круги идут в них параллельно. Кто какую задачу
    держит, знает захват (`team_shell_lock`, здесь — `shell_tasks`), по нему круг и
    ложится на свою карточку. Раньше сюда клался общий первый по захвату, и обе
    карточки менеджера показывали одну задачу, хотя работали над разными.

    Круг, чью оболочку сопоставить не вышло (захвата нет — прогон запустили мимо
    конвейера, или строку уже сняли), достаётся первой карточке роли без своего
    круга: показать его надо, а точного адреса у нас нет.

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
    running_by_card = _running_split(cards, queues, shell_tasks or {})
    for index, card in enumerate(cards):
        slot = queues.get(card['role']) or {}
        waiting = list(slot.get('waiting') or [])
        count = int(slot.get('waiting_count') or 0)
        current = running_by_card.get(index)

        idle = not card['active'] or card.get('agent_status') == 'ready'
        if current and idle:
            waiting.insert(0, current)
            count += 1
            current = None

        card['queue_count'] = count
        card['queue'] = waiting[:TEAM_QUEUE_PREVIEW_LIMIT]
        card['queue_current'] = current


def _running_split(cards: list[dict], queues: dict, shell_tasks: dict) -> dict[int, dict]:
    """
    Разложить идущие круги роли по её карточкам: `{индекс карточки: круг}`.

    Сопоставление идёт через захват оболочки: `shell_tasks` — это
    `{session_uuid: task_id}` из `team_shell_lock`, а у карточки есть свой
    `session_uuid`. Совпало — круг её.

    Что не совпало, раздаём по порядку оставшимся карточкам роли: круг мог идти мимо
    конвейера, а показать его всё равно нужно — иначе работающая карточка выглядела
    бы простаивающей.
    """
    out: dict[int, dict] = {}
    by_role: dict[str, list[int]] = {}
    for index, card in enumerate(cards):
        by_role.setdefault(card['role'], []).append(index)

    for role, indexes in by_role.items():
        running = list((queues.get(role) or {}).get('running') or [])
        if not running:
            continue

        # Сперва точные попадания: круг задачи, которую держит оболочка этой карточки.
        free_indexes = []
        for index in indexes:
            session_uuid = str(cards[index].get('session_uuid') or '')
            task_id = shell_tasks.get(session_uuid)
            item = next((r for r in running if task_id and _item_task_id(r) == int(task_id)), None)
            if item is None:
                free_indexes.append(index)
                continue
            running.remove(item)
            out[index] = item

        # Остаток — по порядку: адреса у этих кругов нет, но они идут.
        for index in free_indexes:
            if not running:
                break
            out[index] = running.pop(0)

    return out


def _item_task_id(item: dict) -> int:
    """Номер задачи строки очереди. У подзадачи это её родитель — им и живёт захват."""
    return int(item.get('task_id') or 0)


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


def _card_name(row: dict, member: dict, role: str) -> str:
    """
    Имя карточки с номером оболочки: `Developer`, `Developer 2`, `Developer 3`.

    Номер приходит из реестра (`role_index`) — его назначил сервер при регистрации,
    и ровно он стоит в заголовке терминала. Совпадение обязательно: иначе три
    одинаковые карточки «Developer» не сопоставить с тремя одинаковыми окнами, и
    непонятно, в каком из них идёт та задача, что видна на странице.

    Первая оболочка остаётся без номера: пока роль держит один терминал, номер
    только шумит, а именно так выглядит обычная установка.
    """
    base = str(member.get('name') or TEAM_PROJECT_ROLE_TITLE.get(role, role))
    index = int(row.get('role_index') or 0)

    return f'{base} {index}' if index > 1 else base


def _card_llm(row: dict, llm_by_session: dict, has_pool: bool) -> str:
    """
    Чем оболочка работает **сейчас**. Пусто — ничем, круга нет.

    Реестр сессий помнит последнюю модель навсегда: её записали, отправляя
    `__SWITCH_LLM__`, и после круга значение остаётся. Карточка показывала его как
    текущее — и выходило, что одна модель занята двумя оболочками разом: одна её и
    правда держит, а вторая просто помнит.

    Поэтому у проекта с пулом верим только живому захвату (`team_llm_lock`): он
    гаснет вместе с кругом. Нет захвата — роль между кругами, и честный ответ
    «модель не выбрана», а не имя прошлой.

    Пул пуст — правило не работает: захватывать нечего, оболочка идёт облачным
    бэкендом, и `server_llm` реестра там единственный источник.
    """
    if not has_pool:
        return str(row.get('server_llm') or '')

    return str(llm_by_session.get(str(row.get('session_uuid') or '')) or '')


def _card_freshness(card: dict) -> int:
    """Ключ сортировки «сначала свежие»: карточка без пинга уходит в самый конец."""
    seconds_ago = card.get('seconds_ago')

    return seconds_ago if seconds_ago is not None else 10 ** 9


def _card_from_session(row: dict, member_by_role: dict, work_dir: str, now: datetime,
                       stale_seconds: int, autocompact: str = '',
                       llm_by_session: dict | None = None, has_pool: bool = False) -> dict:
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
        # Имя с номером оболочки: `Developer`, `Developer 2`, `Developer 3`. Номер
        # тот же, что в заголовке терминала (`role_index`), — по нему карточка и
        # окно сопоставляются. Первая остаётся без номера: пока роль держит один
        # терминал, номер только шумит.
        'name': _card_name(row, member, role),
        'role_index': int(row.get('role_index') or 0),
        'command': _command_build(member.get('command'), work_dir or row.get('work_dir'),
                                  autocompact),
        'session_id': row.get('id'),
        'session_uuid': row.get('session_uuid'),
        'session_status': str(row.get('status') or ''),
        # Готовность агента: 'ready' — сообщение уйдёт в дочерний процесс сразу,
        # 'busy' — встанет в очередь. Показываем только у активных карточек: у
        # протухшего пинга это последнее известное значение, а не текущее.
        'agent_status': str(row.get('agent_status') or '') if active else '',
        'agent_status_reason': str(row.get('agent_status_reason') or '') if active else '',
        'server_llm': _card_llm(row, llm_by_session or {}, has_pool),
        'summary': str(row.get('summary') or ''),
        'work_dir': str(row.get('work_dir') or ''),
        'project_label': str(row.get('project_label') or ''),
        'last_seen_at': str(row.get('last_seen_at')) if row.get('last_seen_at') else None,
        'seconds_ago': seconds_ago,
        'active': active,
    }


def _card_placeholder(role: str, member_by_role: dict, work_dir: str,
                      autocompact: str = '') -> dict:
    """Серая карточка роли, у которой нет ни одной запущенной оболочки."""
    member = member_by_role.get(role, {})

    return {
        'role': role,
        'role_title': TEAM_PROJECT_ROLE_TITLE.get(role, role),
        'name': str(member.get('name') or TEAM_PROJECT_ROLE_TITLE.get(role, role)),
        # У заглушки номера нет: она описывает роль, а не запущенную оболочку.
        'role_index': 0,
        'command': _command_build(member.get('command'), work_dir, autocompact),
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


def _command_build(command, work_dir, autocompact: str = '') -> str:
    """
    Команда запуска с переходом в каталог — её копируют кнопкой на карточке.

    Каталог — рабочие выкладки проекта (`.claude/worktrees`), а не его корень.
    Оболочка роли обязана стартовать именно там: тогда корень репозитория
    оказывается выше рабочего каталога, и Claude Code не пишет в чекаут
    человека. Каталоги подзадач лежат внутри подпапками, так что одна оболочка
    по-прежнему обслуживает их все.

    Приводим здесь, а не полагаемся на `project_team.work_dir`: команду строят
    из каталога проекта (`team_project_blocks`), и карточка со своим адресом
    сюда не доходит. Пока приведение в одном месте, команда с кнопки и адрес,
    по которому оболочку потом ищут, не разъедутся.
    """
    command = str(command or '').strip()
    work_dir = _command_work_dir(work_dir)
    if not command:
        return ''

    # Порог автосжатия подставляем здесь, а не при заведении карточки: команда
    # лежит в `project_team.command` и переживает правку настройки. Подставь мы
    # значение один раз — смена настройки не дошла бы до уже созданных карточек,
    # и человек копировал бы кнопкой старое число, не подозревая об этом.
    command = team_member_command_llm_normalize(command)
    if autocompact:
        command = _autocompact_replace(command, autocompact)

    if not work_dir:
        return command

    return f'cd {work_dir} && {command}'


def _autocompact_replace(command: str, value: str) -> str:
    """Подменить значение `--autocompact` в готовой команде. Флага нет — не трогаем."""
    if TEAM_SETTING_AUTOCOMPACT_FLAG not in command:
        return command

    return re.sub(r'--autocompact(?:[= ]\S+)?',
                  f'{TEAM_SETTING_AUTOCOMPACT_FLAG} {value}', command, count=1)


def _command_work_dir(work_dir) -> str:
    """
    Каталог запуска оболочки: рабочие выкладки проекта.

    Адрес, уже указывающий на выкладки, оставляем как есть — иначе получилось бы
    `worktrees/worktrees`, которого нет.
    """
    base = str(work_dir or '').strip().rstrip('/')
    if not base:
        return ''
    if base.endswith('/' + TEAM_PROJECT_WORKTREES_DIR):
        return base

    return f'{base}/{TEAM_PROJECT_WORKTREES_DIR}'


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


def _team_project_dir(work_dir) -> str:
    """Каталог проекта по адресу оболочки: хвост рабочих выкладок отбрасываем."""
    path = _path_normalize(work_dir)
    tail = '/' + TEAM_PROJECT_WORKTREES_DIR

    return path[:-len(tail)] if path.endswith(tail) else path

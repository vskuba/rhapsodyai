"""
Кто планирует задачу: тип задачи → роль карточки команды.

Планирует владелец вкладки, на которой задача живёт: планирование и исследование —
менеджер, разработка — разработчик, баги и тестирование — QA. Раньше планировал
всех менеджер, и на карточку QA не попадало ничего, хотя баги ведёт именно она.

Подзадачи утверждённого плана этому распределению не подчиняются: их всегда делает
Developer, а проверяет QA. План уже разложен, спорить о владельце нечего — поэтому
роль здесь только про корневую задачу.

Роль решает две вещи: в какую живую shell-оболочку уйдёт прогон workflow
планирования (`claude_shell_call` бьёт по роли) и на чьей карточке `/admin/team`
задача видна в очереди.

Одной роли мало: карточки заведены на каждый проект отдельно (`project_team.project_id`),
и менеджер одного проекта не должен уводить задачи чужого. Поэтому живые оболочки
считаются в разрезе проектов (`task_role_shell_live_by_project`), а захват отбирает
задачи условием «свой проект и свой тип» (`task_role_project_type_sql`).

Задача без типа достаётся менеджеру: тип не обязателен (`ON DELETE SET NULL`), и
без владельца задача выпала бы из конвейера совсем.
"""
from datetime_.datetime_ import datetime_now
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_PING_STALE,
    task_setting_timeout_get)

# Роль по умолчанию: ей достаются задачи без типа и с типом, которого нет в карте.
TASK_ROLE_DEFAULT = 'manager'

# Имена типов — ключи `project_task_type.name`, а не id: id зависят от установки,
# имена — часть контракта (их же читает промпт менеджера через `task_type`).
TASK_ROLE_TYPES = {
    'manager':   ('plan', 'research'),
    'developer': ('dev',),
    'qa':        ('bug', 'test'),
}

# Короткие имена для отчётов задачи — не то же самое, что заголовки карточек в
# `team_project`: там подпись под аватаром, здесь подлежащее в строке отчёта.
TASK_ROLE_TITLE = {
    'manager':   'Менеджер',
    'developer': 'Разработчик',
    'qa':        'QA',
}

# Оболочка пингует реестр раз в несколько секунд; порог свежести тот же, что у
# карточки на `/admin/team`, — настройка `timeout_ping_stale` (см. `task_setting_timeout`).
# Ключ «вне проектов»: задача без проекта и оболочка из каталога, который ни одному
# проекту не принадлежит. То же значение, что у блока «Без проекта» в `team_queue`.
TASK_ROLE_PROJECT_NONE = 0

# Сессии в этих статусах — живые или закрывающиеся; 'inactive' — завершённая оболочка.
_TASK_ROLE_SESSION_STATUS_LIVE = ('active', 'closing')


def task_role_by_type(type_name) -> str:
    """Роль, которая планирует задачи такого типа."""
    name = str(type_name or '').strip().lower()
    for role, names in TASK_ROLE_TYPES.items():
        if name in names:
            return role

    return TASK_ROLE_DEFAULT


async def task_role_of_task(task: dict) -> str:
    """Роль-планировщик по строке задачи (нужна только колонка `task_type_id`)."""
    task_type_id = task.get('task_type_id')
    if not task_type_id:
        return TASK_ROLE_DEFAULT

    async with mysql_get_db_async() as db:
        await db.execute('SELECT name FROM project_task_type WHERE id = %s', (task_type_id,))
        row = await db.fetchone()

    return task_role_by_type(row.get('name') if row else '')


def task_role_type_sql(roles, column: str = 'task_type_id') -> tuple[str, list]:
    """
    Условие «тип задачи принадлежит одной из этих ролей» — для отбора в `task_claim`
    и для очереди карточек в `team_queue`.

    Ролей может не быть ни одной (ни одна оболочка не запущена) — тогда условие
    заведомо ложно, и планировать некому. Это не сбой: задачи просто ждут в очереди
    на своих карточках, вместо того чтобы сорваться на мёртвой оболочке.

    Условие по именам через подзапрос, а не по id: id типов зависят от установки.
    Роли по умолчанию достаётся ещё и всё, чего нет в карте — задача без типа и
    задача с типом, который добавили в таблицу, но не в `TASK_ROLE_TYPES`.
    """
    roles = [str(role or '').strip() for role in (roles or [])]
    names = [name for role in roles for name in TASK_ROLE_TYPES.get(role, ())]
    known = [name for names_ in TASK_ROLE_TYPES.values() for name in names_]

    parts, params = [], []
    if names:
        placeholders = ', '.join(['%s'] * len(names))
        parts.append(f'{column} IN (SELECT id FROM project_task_type WHERE name IN ({placeholders}))')
        params.extend(names)
    if TASK_ROLE_DEFAULT in roles:
        placeholders = ', '.join(['%s'] * len(known))
        parts.append(f'{column} IS NULL')
        parts.append(f'{column} NOT IN (SELECT id FROM project_task_type WHERE name IN ({placeholders}))')
        params.extend(known)
    if not parts:
        return '1 = 0', []

    return '(' + ' OR '.join(parts) + ')', params


def task_role_project_type_sql(roles_by_project, column: str = 'task_type_id',
                               project_column: str = 'project_id') -> tuple[str, list]:
    """
    Условие «задачу берёт карточка своего проекта»: проект задачи совпадает с
    проектом живой оболочки, и тип задачи — за её ролью.

    `roles_by_project` — то, что вернул `task_role_shell_live_by_project()`.
    Ключ `TASK_ROLE_PROJECT_NONE` — оболочки из каталога, не принадлежащего ни
    одному проекту; им и достаются задачи без проекта.

    Задача без проекта (`project_id` NULL или 0) — не ничья: её берёт только
    оболочка вне проектов. Раньше такую задачу забирала любая живая роль, и
    менеджер Rhapsody AI планировал чужие задачи, заведённые мимо проекта
    (через API, тестами, до появления колонки). Пусть лучше висят в очереди
    «Без проекта», чем уходят в работу к тому, кто про них ничего не знает.
    """
    parts, params = [], []
    for project_id, roles in (roles_by_project or {}).items():
        project_id = int(project_id or TASK_ROLE_PROJECT_NONE)
        type_sql, type_params = task_role_type_sql(roles, column=column)
        if type_sql == '1 = 0':
            continue
        if project_id:
            parts.append(f'({project_column} = %s AND {type_sql})')
            params.append(project_id)
        else:
            parts.append(f'(({project_column} IS NULL OR {project_column} = 0) AND {type_sql})')
        params.extend(type_params)

    if not parts:
        return '1 = 0', []

    return '(' + ' OR '.join(parts) + ')', params


def task_role_project_sql(roles_by_project, role: str,
                          project_column: str = 'project_id') -> tuple[str, list]:
    """
    Условие «проект строки — за живой оболочкой этой роли», без оглядки на тип.

    Для подзадач утверждённого плана: их всегда делает Developer, а проверяет QA —
    тип задачи здесь ни при чём, и `task_role_project_type_sql` не годится, он
    отбирает ещё и по типу. Остаётся один вопрос: жива ли в проекте строки карточка
    нужной роли. Не жива — подзадачу не берём: прогон всё равно сорвался бы на
    мёртвой оболочке и сжёг бы попытку из отведённых.

    Ключ `TASK_ROLE_PROJECT_NONE` — оболочка из каталога, не принадлежащего ни
    одному проекту; ей достаются подзадачи без проекта, и только ей.
    """
    role = str(role or '').strip()
    ids, project_none = [], False
    for project_id, roles in (roles_by_project or {}).items():
        if role not in [str(item or '').strip() for item in (roles or [])]:
            continue
        project_id = int(project_id or TASK_ROLE_PROJECT_NONE)
        if project_id:
            ids.append(project_id)
        else:
            project_none = True

    parts, params = [], []
    if ids:
        placeholders = ', '.join(['%s'] * len(ids))
        parts.append(f'{project_column} IN ({placeholders})')
        params.extend(ids)
    if project_none:
        parts.append(f'({project_column} IS NULL OR {project_column} = 0)')
    if not parts:
        return '1 = 0', []

    return '(' + ' OR '.join(parts) + ')', params


async def task_role_shell_live_by_project() -> dict[int, list[str]]:
    """
    Живые оболочки claude-shell в разрезе проектов: `{project_id: [role]}`.

    Без живой оболочки шаг workflow всё равно сорвётся, а задача уйдёт в `failed`
    и потребует человека. Поэтому такие задачи лучше не захватывать вовсе — на
    карточке роли они останутся видимой очередью и дождутся запуска.

    Проект оболочки определяется каталогом запуска (`work_dir` реестра сессий) —
    тем же правилом, по которому сессии раскладываются по блокам проектов на
    `/admin/team`. Каталог, не совпавший ни с одним проектом, даёт ключ
    `TASK_ROLE_PROJECT_NONE`: такой оболочке достаются только задачи без проекта.

    Роль без карточки в своём проекте не считается живой: очередь на `/admin/team`
    рисуется по карточкам, и захват работы, которую ни одна карточка не показывает,
    сделал бы происходящее невидимым для человека.

    Свежесть считаем в Python, а не через `NOW()`: `last_seen_at` пишется временем
    приложения, и сравнение с временем MySQL дало бы вечно живую либо мгновенно
    мёртвую оболочку.
    """
    async with mysql_get_db_async() as db:
        placeholders = ', '.join(['%s'] * len(_TASK_ROLE_SESSION_STATUS_LIVE))
        await db.execute(
            'SELECT role, work_dir, last_seen_at FROM ai_claude_session_registry '
            f" WHERE role <> '' AND status IN ({placeholders})",
            list(_TASK_ROLE_SESSION_STATUS_LIVE),
        )
        rows = await db.fetchall()
        await db.execute('SELECT id, work_dir FROM project')
        projects = await db.fetchall()
        await db.execute("SELECT project_id, role FROM project_team WHERE role <> ''")
        cards = await db.fetchall()

    project_by_dir = {}
    for project in (projects or []):
        work_dir = _path_normalize(project.get('work_dir'))
        if work_dir:
            project_by_dir[work_dir] = int(project.get('id') or 0)
    card_roles = {(int(card.get('project_id') or TASK_ROLE_PROJECT_NONE),
                   str(card.get('role') or '').strip()) for card in (cards or [])}

    now = await datetime_now()
    stale_seconds = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_PING_STALE)
    live: dict[int, list[str]] = {}
    for row in (rows or []):
        role = str(row.get('role') or '').strip()
        last_seen_at = row.get('last_seen_at')
        if not role or not last_seen_at:
            continue
        if (now - last_seen_at).total_seconds() >= stale_seconds:
            continue
        project_id = project_by_dir.get(_path_normalize(row.get('work_dir')), TASK_ROLE_PROJECT_NONE)
        if project_id and (project_id, role) not in card_roles:
            continue
        roles = live.setdefault(project_id, [])
        if role not in roles:
            roles.append(role)

    return live


async def task_role_project_work_dir(project_id) -> str:
    """
    Каталог проекта — вторая половина адреса оболочки рядом с ролью.

    Роль отвечает «кто планирует», каталог — «в чьём проекте»: карточки заведены
    на каждый проект отдельно, роли у них одинаковые, и `claude_shell_call` без
    каталога ушёл бы в оболочку соседнего проекта.

    Пустая строка — у задачи нет проекта либо у проекта не задан `work_dir`.
    Это не ошибка: адресация тогда остаётся прежней, только по роли.
    """
    project_id = int(project_id or TASK_ROLE_PROJECT_NONE)
    if not project_id:
        return ''

    async with mysql_get_db_async() as db:
        await db.execute('SELECT work_dir FROM project WHERE id = %s', (project_id,))
        row = await db.fetchone()

    return _path_normalize(row.get('work_dir') if row else '')


def _path_normalize(path) -> str:
    """Путь без хвостового слеша — '/srv/app' и '/srv/app/' это один каталог.

    Копия `team_project._path_normalize`, а не импорт: `team_project` тянет за собой
    очередь и конвейер, и вышел бы круг импортов.
    """
    value = str(path or '').strip()
    if len(value) > 1:
        value = value.rstrip('/')

    return value

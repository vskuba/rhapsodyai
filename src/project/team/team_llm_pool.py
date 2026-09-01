"""
Пул моделей проекта и захват модели ролью на круг работы.

Зачем. Раньше оболочка привязывалась к одной модели флагом при запуске, а сколько
карточек работают разом, задавалось руками («Parallel LLM»). Это две настройки об
одном и том же: работать параллельно можно ровно настолько, насколько хватает
моделей. Теперь у проекта есть **пул** — список моделей из каталога оболочки, — и
предел параллельности выводится из его размера, а не задаётся отдельно.

Как это работает. Роль берёт круг — конвейер захватывает ей свободную модель из пула
проекта. Круг кончился — модель освобождается и её берёт другая работа. Между кругами
она не простаивает, пока человек смотрит результат.

**Прилипание к задаче.** При захвате сначала пробуем ту модель, на которой эта задача
работала прошлый круг. Получилось — оболочке не нужно перезапускать агента, и его
контекст цел; занята — берём любую свободную, но тогда агента перезапустят. Прилипание
это предпочтение, а не закрепление: кончились подзадачи — модель просто уходит другим.

**Атомарность даёт база.** Строка на модель одна (первичный ключ — её имя), а захват
это `UPDATE ... WHERE свободна`: InnoDB держит строку под замком, и `rowcount` честно
говорит, досталась ли она нам. Два тика оркестратора не выдадут одну модель дважды —
второй увидит ноль. Блокировок в коде для этого не нужно.

Строка при освобождении не удаляется, а гасит `locked_at`: в ней остаётся `task_id`
последнего круга, и по нему работает прилипание.

**Окно контекста живёт при модели.** У каждой оно своё: у локального qwen одно, у
чужой модели через маршрутизатор другое. Общее окно на проект врало ровно с того дня,
как моделей стало больше одной, — теперь оно хранится рядом с именем и уезжает в
команду вместе с выбранной моделью.

**Пулы проектов не пересекаются.** Модель, выбранная одним проектом, другому недоступна
(`team_llm_pool_conflicts`): модели общие на машину, и два проекта, взявшие одну,
дрались бы за один прокси. Проверка живёт на сохранении пула, а не на захвате — так
человек узнаёт о столкновении сразу, а не когда работа встала.
"""
from contextlib import suppress

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from setting_.setting_ import setting_get, setting_set
from src.tool.claude_.claude_ import claude_message_user

# Ключ настройки собирается из префикса и id проекта — тем же приёмом, что предел
# параллельности (`task_setting_parallel`): проектов на установке десятки, и колонка
# под список моделей их таблице ни к чему.
TEAM_LLM_POOL_KEY_PREFIX = 'team_llm_pool_'

# Проект «никакой»: оболочка из каталога, не принадлежащего ни одному проекту.
TEAM_LLM_POOL_PROJECT_NONE = 0

# Маркер протокола оболочки: `__SWITCH_LLM__ <модель> <окно>`. Значение — часть
# контракта с уже запущенными оболочками (`shell.py:SWITCH_LLM_MARKER`), менять его
# нельзя, не обновив их.
TEAM_LLM_POOL_SWITCH_MARKER = '__SWITCH_LLM__'

# Окно автосжатия, когда у модели своё не задано. То же значение, что раньше было
# общим на проект (`gx10_autocompact_limit`): окно GX10 — 131072 токена, 115k
# оставляет запас до этой границы.
TEAM_LLM_POOL_CONTEXT_DEFAULT = '115k'

# Сколько живёт захват без подтверждения. Оболочка падает, круг обрывается по
# таймауту — без срока пул опустел бы от мёртвых захватов, снять которые некому.
#
# **Срок короткий, потому что живой круг подтверждает себя сам** — раз в
# `TASK_CLAIM_LOCK_TOUCH_SEC` (`team_llm_pool_touch` из `_lock_hold`). Состарившийся
# захват означает ровно одно: держать его больше некому.
#
# Прежние 7400 секунд опирались на то, что захват снимает `finally` своего job'а. Убитый
# воркер его не выполняет, и живьём мёртвый круг держал единственную модель проекта час:
# конвейер считал её занятой, роль без своей модели голодала, а на странице команды
# «работала» оболочка, в которой давно ничего не происходило.
#
# Значение то же, что у захвата оболочки (`TEAM_SHELL_POOL_STALE_SECONDS`): круг держит
# и то, и другое, и разъехавшиеся сроки дали бы полукруг с моделью без оболочки.
TEAM_LLM_POOL_STALE_SECONDS = 300

# Потолок имени модели в реестре сессий — длина колонки `server_llm`. Режем здесь,
# чтобы MySQL не обрезал молча: имя двухуровневое, и обрезанное посередине оно
# выглядело бы как другая модель. Значение то же, что у
# `telegram_app_claude_session.SESSION_SERVER_LLM_MAX`.
TEAM_LLM_POOL_NAME_MAX = 100

# Оболочка, поднятая **без** `--litellm`: работает родным облачным агентом Claude
# Code. Значение пишет в реестр она сама — при регистрации и каждым пингом
# (`claude-shell/shell.py`, `_llm_mode`), — и другого признака режима у нас нет:
# колонка `server_llm` одна на режим и на имя модели.
#
# Признак держится ровно потому, что модель такой оболочке не выдают
# (`team_llm_pool_shell_cloud` ниже и её проверка в `_llm_assign`): выдай мы её
# однажды, оболочка начала бы слать имя модели, и режим запуска пропал бы навсегда.
TEAM_LLM_POOL_MODE_CLOUD = 'anthropic'

# Как зовётся в пуле запись облачной оболочки. Не имя модели: модели за ней нет, за
# ней стоит родной агент Claude Code, и прокси под неё не поднимается. Имя видно
# человеку на странице команды рядом с именем карточки, которой запись принадлежит.
TEAM_LLM_POOL_CLOUD_NAME = 'Claude Code Agent'


async def team_llm_pool_get(project_id: int) -> list[str]:
    """Имена моделей пула. Пусто — пул не задан, работать через LiteLLM нечем."""
    return [item['name'] for item in await team_llm_pool_items(project_id)]


async def team_llm_pool_items(project_id: int) -> list[dict]:
    """
    Пул с окнами контекста: `[{'name', 'context'}]`.

    Окно живёт при модели, а не при проекте: у каждой оно своё — у локального qwen
    одно, у чужой модели через маршрутизатор другое. Раньше окно было одно на весь
    проект, и это врало ровно с того дня, как моделей стало больше одной.

    В настройке лежит строкой `имя:окно,имя:окно`. Запись без двоеточия читается как
    модель с окном по умолчанию — так пулы, сохранённые до появления окон, не
    ломаются и не требуют миграции.
    """
    return _pool_parse(await setting_get(f'{TEAM_LLM_POOL_KEY_PREFIX}{int(project_id or 0)}', ''))


async def team_llm_pool_all() -> dict[int, list[dict]]:
    """
    Пулы всех проектов разом: `{project_id: [{'name', 'context'}]}`.

    Одним чтением на сборку страницы: проектов десятки, и запрос на каждый был бы
    запросом на пустом месте. Разбор строки тот же, что у `team_llm_pool_items`, —
    вынесен в `_pool_parse`, чтобы форматов не стало два.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT `key`, value FROM setting "
            " WHERE `key` LIKE %s AND user_id IS NULL AND node_id IS NULL",
            (f'{TEAM_LLM_POOL_KEY_PREFIX}%',))
        rows = await db.fetchall() or []

    out = {}
    for row in rows:
        try:
            project_id = int(str(row['key']).removeprefix(TEAM_LLM_POOL_KEY_PREFIX))
        except ValueError:
            continue
        items = _pool_parse(row['value'])
        if items:
            out[project_id] = items

    return out


async def team_llm_pool_conflicts(project_id: int, names: list) -> dict[str, int]:
    """
    Какие из моделей уже заняты пулом другого проекта: `{модель: чей проект}`.

    Модели общие на машину: две роли разных проектов, взявшие одну, поделили бы один
    прокси и мешали друг другу. Проверяем на сохранении, а не при захвате, — так
    человек узнаёт о столкновении сразу, а не когда работа встала без объяснений.
    """
    project_id = int(project_id or 0)
    # Принимаем и голые имена, и пары с окном: страница присылает пары, а вызов из
    # кода может знать только имена. Требовать от него окно значило бы заставлять
    # выдумывать его на пустом месте.
    wanted = {(str(n.get('name')) if isinstance(n, dict) else str(n)).strip()
              for n in (names or [])}
    wanted.discard('')
    if not wanted:
        return {}

    taken = {}
    for other_id, other_items in (await team_llm_pool_all()).items():
        if other_id == project_id:
            continue
        for item in other_items:
            if item['name'] in wanted:
                taken[item['name']] = other_id

    return taken


async def team_llm_pool_set(project_id: int, items: list) -> list[dict]:
    """
    Записать пул проекта. Возвращает сохранённое как `[{'name', 'context'}]`.

    Принимает и голые имена, и пары с окном: страница присылает пары, а вызов из кода
    может знать только имена, и требовать от него окно значило бы заставлять выдумывать
    его на пустом месте.

    Порядок сохраняем как прислали: захват идёт по нему, и человек, поставив первой
    модель побыстрее, вправе ожидать, что её и возьмут первой.

    Здесь же убираются строки захвата выбывших моделей (`_locks_prune`): состав пула
    меняют когда угодно, и без уборки таблица копила бы записи моделей, которых уже
    нет ни в пуле, ни в каталоге оболочки.
    """
    clean, seen = [], set()
    for item in (items or []):
        if isinstance(item, dict):
            name = str(item.get('name') or '').strip()
            context = str(item.get('context') or '').strip()
        else:
            name, context = str(item or '').strip(), ''
        # Дубли молча схлопываем: в списке они значат то же, что и одно вхождение,
        # а в пуле выглядели бы как две модели и завышали предел параллельности.
        if not name or name in seen:
            continue
        seen.add(name)
        clean.append({'name': name, 'context': context or TEAM_LLM_POOL_CONTEXT_DEFAULT})

    await setting_set(f'{TEAM_LLM_POOL_KEY_PREFIX}{int(project_id or 0)}',
                      ','.join(f"{i['name']}:{i['context']}" for i in clean))
    await _locks_prune(project_id, [i['name'] for i in clean])

    return clean


async def team_llm_pool_context(project_id: int, llm_name: str) -> str:
    """Окно контекста модели в пуле проекта. Нет в пуле — значение по умолчанию."""
    for item in await team_llm_pool_items(project_id):
        if item['name'] == llm_name:
            return item['context']

    return TEAM_LLM_POOL_CONTEXT_DEFAULT


async def team_llm_pool_locks(project_id: int | None = None) -> list[dict]:
    """Живые захваты: чем сейчас занята каждая модель. Протухшие не показываем."""
    where = ["locked_at IS NOT NULL", "locked_at > NOW() - INTERVAL %s SECOND"]
    params = [TEAM_LLM_POOL_STALE_SECONDS]
    if project_id is not None:
        where.append("project_id = %s")
        params.append(int(project_id))

    async with mysql_get_db_async() as db:
        await db.execute(
            f"SELECT * FROM team_llm_lock WHERE {' AND '.join(where)} ORDER BY locked_at",
            tuple(params))

        return list(await db.fetchall() or [])


async def team_llm_pool_sessions() -> dict[str, str]:
    """
    Какая оболочка какую модель держит **сейчас**: `{session_uuid: llm_name}`.

    Нужен карточке команды. Реестр сессий помнит последнюю модель, на которую
    оболочку переключали, и после круга это значение врёт: модель уже отдали
    соседней карточке, а прежняя показывает её как свою — выходит, будто две
    оболочки работают на одной модели. Захват же гаснет вместе с кругом, и по нему
    видно, чем роль занята прямо сейчас, а не чем была занята полчаса назад.

    Только живые захваты: протухший ничего не держит, его перехватит следующий круг.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT session_uuid, llm_name FROM team_llm_lock "
            " WHERE locked_at IS NOT NULL AND locked_at > NOW() - INTERVAL %s SECOND "
            "   AND session_uuid <> ''",
            (TEAM_LLM_POOL_STALE_SECONDS,))
        rows = await db.fetchall() or []

    return {str(row['session_uuid']): str(row['llm_name']) for row in rows}


async def team_llm_pool_shell_cloud(session_uuid: str) -> bool:
    """
    Оболочка поднята без `--litellm`? Тогда модель из пула ей не выдают.

    Такую оболочку человек запускает ровно затем, чтобы она работала родным агентом
    Claude Code: выдай ей модель — и `__SWITCH_LLM__` молча переведёт её на пул
    (`shell.py:_switch_llm` режима запуска не спрашивает), перезапустив агента и
    потеряв его контекст. Получилось бы, что флаг ни на что не влияет.

    Заодно это бережёт сам признак: режим и имя модели лежат в одной колонке
    `server_llm`, и первая же выдача затёрла бы «anthropic» именем модели — отличить
    облачную оболочку от пуловой стало бы нечем.

    Пустой адрес — `False`: оболочки у роли не нашлось, и решает это не эта функция, а
    вызывающий (`_shell_assign`). Сбой чтения — тоже `False`: пул как работал, так и
    работает, а тихо лишить круг модели значило бы отправить его на облачные токены
    из-за заминки в базе.
    """
    session_uuid = str(session_uuid or '').strip()
    if not session_uuid:
        return False

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT server_llm FROM ai_claude_session_registry WHERE session_uuid = %s',
                (session_uuid,))
            row = await db.fetchone()
    except Exception as e:
        logger_info(f'[team] режим оболочки {session_uuid[:8]} не прочитан: {e}')

        return False

    return str((row or {}).get('server_llm') or '') == TEAM_LLM_POOL_MODE_CLOUD


async def team_llm_pool_cloud_items(sessions_by_role: dict | None) -> list[dict]:
    """
    Виртуальные записи пула на живые облачные оболочки проекта.

    Зачем. Предел параллельности проекта равен размеру пула: разом работает столько
    кругов, на сколько хватает моделей. Оболочка без `--litellm` модели из пула не
    берёт — у неё свой бэкенд, — и в этом счёте её не было вовсе: открой хоть три
    таких карточки, проект с пулом из одной модели вёл один круг, а карточки стояли.

    Поэтому каждая живая облачная оболочка добавляет к пулу свою запись. Это не модель
    и прокси за ней нет: запись означает «ещё один круг может идти, вот в этой
    оболочке».

    **Запись именная и чужой роли не достаётся.** Она привязана к `session_uuid`
    конкретной оболочки, и взять её может только та же оболочка: пуловая роль ходит за
    моделью в `team_llm_lock`, где облачных строк нет вовсе, а облачная за моделью не
    ходит совсем (`_llm_assign`). Исключительность даёт захват самой оболочки
    (`team_shell_pool`): круг в ней может идти только один, значит и запись занята
    ровно им.

    `sessions_by_role` — живые оболочки проекта, `{role: [session_uuid]}` из
    `task_role_shell_sessions_by_project`. Список приходит снаружи, а не читается
    здесь: правило «какая оболочка живая» уже описано там — свежесть пинга, карточка
    роли, каталог проекта, незапертость на диалоге разрешений, — и вторая его копия
    разошлась бы с первой.

    Returns: `[{'name', 'context', 'session_uuid', 'role', 'role_index', 'cloud'}]`.
    Порядок — по роли и номеру оболочки, чтобы список на странице не прыгал между
    перерисовками.
    """
    wanted = [str(uuid).strip()
              for sessions in (sessions_by_role or {}).values()
              for uuid in (sessions or []) if str(uuid or '').strip()]
    if not wanted:
        return []

    placeholders = ', '.join(['%s'] * len(wanted))
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT session_uuid, role, role_index FROM ai_claude_session_registry '
            f' WHERE session_uuid IN ({placeholders}) AND server_llm = %s '
            ' ORDER BY role, role_index',
            (*wanted, TEAM_LLM_POOL_MODE_CLOUD))
        rows = await db.fetchall() or []

    return [{'name': TEAM_LLM_POOL_CLOUD_NAME,
             'context': TEAM_LLM_POOL_CONTEXT_DEFAULT,
             'session_uuid': str(row['session_uuid']),
             'role': str(row['role'] or ''),
             'role_index': int(row['role_index'] or 0),
             'cloud': True}
            for row in rows]


async def team_llm_pool_free_names(project_id: int) -> list[str]:
    """
    Модели пула, свободные прямо сейчас. Порядок — как в пуле.

    Нужен выбору оболочки на круг (`_shell_assign`): пока свободна локальная модель,
    круг обязан идти в пуловую оболочку, а не в облачную. Иначе гонку выигрывает кто
    успел, и случалось так, что круг уходил за облачные токены, пока локальная модель
    простаивала.

    Ответ мгновенный и устаревает сразу: между «посмотреть» и «захватить» модель может
    уйти соседнему тику. Это не страшно — здесь он служит порядком предпочтения, а не
    обещанием; промахнувшийся круг просто подождёт очереди, как ждал бы и раньше.
    """
    items = await team_llm_pool_items(project_id)
    if not items:
        return []

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT llm_name FROM team_llm_lock '
            ' WHERE project_id = %s AND locked_at IS NOT NULL '
            '   AND locked_at > NOW() - INTERVAL %s SECOND',
            (int(project_id or 0), TEAM_LLM_POOL_STALE_SECONDS))
        busy = {str(row['llm_name']) for row in await db.fetchall() or []}

    return [item['name'] for item in items if item['name'] not in busy]


async def team_llm_pool_acquire(project_id: int, task_id: int, role: str,
                                session_uuid: str = '') -> str | None:
    """
    Захватить свободную модель из пула проекта. Возвращает имя или `None`.

    `None` — не ошибка: свободных нет, работа ждёт очереди. Это штатное поведение,
    ровно то же, что раньше давал предел «Parallel LLM» — только считается он теперь
    сам, по размеру пула.

    Порядок попыток: сначала модель, на которой эта задача работала прошлый круг
    (прилипание — агента не придётся перезапускать), затем остальные по порядку пула.

    **Не отвечающие на пинг пропускаются** (`team_llm_ping_dead`). Модель, отвалившаяся
    у провайдера, продолжала выдаваться ролям: круг уходил в неё, падал, тратил
    попытку — и так каждый тик. Из настройки пула её при этом не убираем: провайдер
    оживёт, и следующий пинг вернёт её в работу сам.

    Пинга нет вовсе (не опрашивали ни разу) — модель выдаётся как прежде: молчание
    значит «не знаем», а не «мертва», иначе на свежей установке пул был бы пуст.

    Мёртвыми оказались все — работаем по полному списку. Пустой пул означал бы, что
    роли не берут работу вовсе; лучше отправить круг в модель, которая может ответить
    вопреки пингу, чем остановить конвейер по данным одной проверки.

    Атомарность даёт `UPDATE ... WHERE свободна`: InnoDB выполняет его под замком
    строки, и `rowcount` честно говорит, досталась ли она нам. Два тика оркестратора
    не могут захватить одну модель — второй увидит `rowcount = 0`.
    """
    pool = await team_llm_pool_get(project_id)
    if not pool:
        return None

    # Импорт внутри функции: `team_llm_ping` читает каталог и пул, и на уровне модуля
    # это дало бы круговую зависимость между двумя файлами.
    from src.project.team.team_llm_ping import team_llm_ping_dead

    dead = await team_llm_ping_dead(pool)
    alive = [name for name in pool if name not in dead]
    if dead and alive:
        logger_info(f"[team] пул проекта {project_id}: пропускаем по пингу "
                    f"{', '.join(sorted(dead))}")

    order = list(alive or pool)
    sticky = await _task_llm_last(task_id)
    if sticky in order:
        order.remove(sticky)
        order.insert(0, sticky)

    # Оболочка просит модель — значит прошлый её круг кончился, чем бы он ни кончился.
    # Гасим всё, что за этой оболочкой ещё числится: агент в ней один, работать двумя
    # моделями разом он не может, и второй захват был бы осиротевшим.
    #
    # Именно за оболочкой, а не за ролью: у роли их бывает несколько, и круги в них
    # идут одновременно (`team_shell_pool`). Гасили по роли — и второй круг отнимал
    # модель у первого; в логе это выглядело как «снято 1 захватов прошлых кругов»
    # ровно в тот момент, когда сосед начинал работу, а дальше оба менеджера делили
    # один прокси.
    #
    # Оболочки нет (захвата не было — старый вызов, ручной прогон) — правило прежнее,
    # по роли: одна оболочка на роль, и путать там нечего.
    #
    # Освобождает круг за собой сам (`_llm_release` в `finally`), но на этот
    # `finally` нельзя закладываться целиком: воркер могут убить по таймауту job'а
    # или перезапуском контейнера — тогда модель выпадает из пула до конца срока
    # протухания, то есть на часы. Живьём так и вышло: за #2437 повисли обе модели
    # проекта, и следующий круг встал ждать при пустом по факту пуле.
    await _holder_locks_clear(project_id, role, session_uuid)

    async with mysql_get_db_async() as db:
        for name in order:
            # Строка на модель заводится один раз и живёт дальше: в ней остаётся
            # `task_id` последнего круга, по которому и работает прилипание. Удаляй
            # мы её при освобождении — память о том, чем задача работала, пропадала
            # бы вместе с ней.
            # `ON DUPLICATE KEY UPDATE llm_name = llm_name` вместо `INSERT IGNORE`:
            # второй на каждом заходе сыпал бы в лог предупреждение о дубле, а дубль
            # здесь — норма, строка заводится один раз и живёт дальше.
            await db.execute(
                "INSERT INTO team_llm_lock (llm_name, project_id, locked_at) "
                "VALUES (%s, %s, NULL) "
                "ON DUPLICATE KEY UPDATE llm_name = llm_name",
                (name, int(project_id or 0)))

            # Свободна — `locked_at IS NULL`; протухла — держат дольше срока: оболочка
            # упала, не освободив, и ждать её больше нечего.
            await db.execute(
                "UPDATE team_llm_lock "
                "   SET project_id = %s, task_id = %s, role = %s, session_uuid = %s, "
                "       locked_at = NOW(), used_at = NOW() "
                " WHERE llm_name = %s "
                "   AND (locked_at IS NULL OR locked_at <= NOW() - INTERVAL %s SECOND)",
                (int(project_id or 0), int(task_id or 0) or None, str(role or ''),
                 str(session_uuid or ''), name, TEAM_LLM_POOL_STALE_SECONDS))
            claimed = db.rowcount
            await db.connection.commit()

            if claimed:
                return name

    return None


async def team_llm_pool_assign(project_id: int, task_id: int, role: str,
                               session_uuid: str = '') -> dict:
    """
    Выдать роли модель на круг: захватить и сказать оболочке переключиться.

    Возвращает `{'llm', 'context', 'switched'}` либо `{'llm': ''}`, если свободных
    моделей нет — тогда работа ждёт очереди, как ждала при прежнем пределе.

    Маркер шлём только когда модель **сменилась**: перезапуск агента стоит ему всего
    накопленного контекста, и платить им за «переключение» на ту же самую нельзя.
    Проверку делает сама оболочка (`_switch_llm`), но не гонять её лишний раз честнее —
    в журнале сессии иначе копились бы пустые переключения.

    Пул пуст — ничего не захватываем и маркера не шлём: оболочка работает штатным
    облачным бэкендом, как до появления пулов.
    """
    llm = await team_llm_pool_acquire(project_id, task_id, role, session_uuid)
    if not llm:
        return {'llm': '', 'context': '', 'switched': False}

    context = await team_llm_pool_context(project_id, llm)
    switched = False
    if session_uuid:
        await claude_message_user(f'{TEAM_LLM_POOL_SWITCH_MARKER} {llm} {context}',
                                  session_uuid, dynamic=1)
        switched = True
        await _session_llm_write(session_uuid, llm)
        logger_info(f'[team] {role} получила {llm} (окно {context}) для задачи #{task_id}')

    return {'llm': llm, 'context': context, 'switched': switched}


async def team_llm_pool_touch(llm_name: str, task_id: int = 0, role: str = '') -> bool:
    """
    Подтвердить захват модели: «круг идёт, модель моя». Returns: подтвердили ли.

    Зовёт работающий job раз в `TASK_CLAIM_LOCK_TOUCH_SEC` (`_lock_hold`) — тем же
    ударом сердца, каким держит строку задачи и захват оболочки. На этом держится
    короткий `TEAM_LLM_POOL_STALE_SECONDS`.

    Подтверждаем ровно свой захват — по тройке «модель + задача + роль», той же, по
    которой его и снимают (`team_llm_pool_release`). Пока круг шёл, модель могла
    протухнуть и уйти другой работе, и подновить её значило бы отобрать чужое.

    `False` — подтверждать нечего: захват уже не наш. Заводить его заново нельзя.
    """
    llm_name = str(llm_name or '').strip()
    if not llm_name:
        return False

    where = ['llm_name = %s', 'locked_at IS NOT NULL']
    params = [llm_name]
    if task_id:
        where.append('task_id = %s')
        params.append(int(task_id))
    if role:
        where.append('role = %s')
        params.append(str(role))

    async with mysql_get_db_async() as db:
        await db.execute(f"UPDATE team_llm_lock SET locked_at = NOW() WHERE {' AND '.join(where)}",
                         tuple(params))
        touched = db.rowcount
        await db.connection.commit()

    return bool(touched)


async def team_llm_pool_release(llm_name: str = '', task_id: int = 0, role: str = '') -> int:
    """
    Освободить модель: по имени, по задаче или по роли. Возвращает число снятых.

    Три способа, потому что круг кончается по-разному. Штатно — знаем имя. По задаче —
    когда её закрыли и держать за ней нечего. По роли — когда оболочку перезапустили и
    что она держала, уже не спросишь.

    Строку не удаляем, а гасим `locked_at`: `task_id` в ней остаётся, и на следующем
    круге та же задача получит ту же модель обратно, если она свободна.
    """
    where, params = ["locked_at IS NOT NULL"], []
    if llm_name:
        where.append("llm_name = %s")
        params.append(str(llm_name))
    if task_id:
        where.append("task_id = %s")
        params.append(int(task_id))
    if role:
        where.append("role = %s")
        params.append(str(role))
    if len(where) == 1:
        return 0

    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE team_llm_lock SET locked_at = NULL, session_uuid = '' "
            f" WHERE {' AND '.join(where)}", tuple(params))
        count = db.rowcount
        await db.connection.commit()

    return count


async def team_llm_pool_forget(task_ids) -> int:
    """
    Забыть удалённые задачи: снять захват и стереть привязку. Returns: снятых строк.

    Отличие от `team_llm_pool_release` — в `task_id`. Освобождение гасит только
    `locked_at`, а номер задачи оставляет намеренно: круг кончился, но задача жива, и
    на следующем ей стараются вернуть ту же модель — тогда агента можно не
    перезапускать, его контекст цел. Здесь возвращать некому: строки больше нет, и
    привязка превращается в мусор, который держится вечно и врёт в панели пула.

    Живьём: захват `gx10/qwen-large` за задачей #2438 провисел три часа после её
    удаления, а `deepseek-...-1` — с `locked_at IS NULL`, то есть не истёк бы никогда.
    Работу они не блокировали (свободной считается и строка с пустым `locked_at`, и
    протухшая), но панель показывала занятыми модели, за которыми никого нет.

    Саму строку не удаляем: она — слот модели в пуле, а не запись о задаче. Захват
    заводит её `INSERT ... ON DUPLICATE KEY`, так что удаление пережилось бы, но
    лишний оборот здесь ни к чему.

    Пустой список — ноль без запроса: `IN ()` синтаксически неверен, а «забыть
    ничего» не должно означать «забыть всё».
    """
    ids = [int(i) for i in (task_ids or []) if int(i or 0)]
    if not ids:
        return 0

    placeholders = ', '.join(['%s'] * len(ids))
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE team_llm_lock SET locked_at = NULL, session_uuid = '', task_id = NULL "
            f" WHERE task_id IN ({placeholders})", tuple(ids))
        count = db.rowcount
        await db.connection.commit()

    if count:
        logger_info(f'[team] пул моделей: снято {count} захват(ов) удалённых задач')
    return count


async def team_llm_pool_parallel(project_id: int) -> int:
    """
    Предел одновременной работы проекта — размер его пула.

    Отдельной настройки больше нет: работать параллельно можно ровно настолько,
    насколько хватает моделей, и держать это вторым числом значило бы позволить им
    разойтись. Пустой пул — единица: проект работает через облачный Anthropic, где
    предел прежний, «по одной».
    """
    return len(await team_llm_pool_get(project_id)) or 1


async def _locks_prune(project_id: int, names: list) -> int:
    """
    Снести строки захвата моделей, которых в пуле проекта больше нет.

    Состав пула меняют когда угодно — переименовали запись в каталоге оболочки, убрали
    модель, развели одну на две с разными портами, — и строки выбывших моделей
    остаются навсегда: захват их не трогает (берутся только имена из пула), прилипание
    тоже (`if sticky in order`). Толку от них нет, а в таблице они копятся и путают
    того, кто в неё заглянет.

    Занятую строку не трогаем: на этой модели прямо сейчас идёт круг, и убрать её
    из-под него значило бы потерять и `task_id` прилипания, и след работы. Она уйдёт
    следующим сохранением пула — к тому времени круг кончится. Протухшую (держат
    дольше `TEAM_LLM_POOL_STALE_SECONDS`) сносим наравне со свободными: её никто уже
    не освободит.

    Пустой список имён — пул очистили целиком, тогда под нож идут все строки проекта.

    Сбой уборки сохранение пула не роняет: пул уже записан, а лишняя строка ничему не
    мешает — за этим её и убирают.
    """
    project_id = int(project_id or 0)
    names = [str(name) for name in (names or [])]

    where = ["project_id = %s",
             "(locked_at IS NULL OR locked_at <= NOW() - INTERVAL %s SECOND)"]
    params = [project_id, TEAM_LLM_POOL_STALE_SECONDS]
    if names:
        where.append(f"llm_name NOT IN ({', '.join(['%s'] * len(names))})")
        params += names

    try:
        async with mysql_get_db_async() as db:
            await db.execute(f"DELETE FROM team_llm_lock WHERE {' AND '.join(where)}",
                             tuple(params))
            count = db.rowcount
            await db.connection.commit()
    except Exception as e:
        logger_info(f'[team] уборка захватов проекта #{project_id} не удалась: {e}')

        return 0

    if count:
        logger_info(f'[team] проект #{project_id}: убрано {count} строк выбывших моделей')

    return count


async def _holder_locks_clear(project_id: int, role: str, session_uuid: str = '') -> int:
    """
    Погасить захваты, оставшиеся за тем же держателем. Возвращает число снятых.

    Держатель — оболочка, если она известна: агент в ней один, и двух моделей у него
    быть не может. Оболочка неизвестна — держателем считаем роль, как было до
    появления захвата оболочек.

    Зовётся перед новым захватом: см. пояснение в `team_llm_pool_acquire`. Пустые роль
    и сессия не гасят ничего — под ними ходят вызовы без адресата, и снимать по ним
    значило бы задеть чужие строки.
    """
    role = str(role or '').strip()
    session_uuid = str(session_uuid or '').strip()

    if session_uuid:
        where, params = 'session_uuid = %s', [session_uuid]
        who = f'оболочка {session_uuid[:8]}'
    elif role:
        where, params = 'role = %s', [role]
        who = role
    else:
        return 0

    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE team_llm_lock SET locked_at = NULL, session_uuid = '' "
            f" WHERE project_id = %s AND {where} AND locked_at IS NOT NULL",
            (int(project_id or 0), *params))
        count = db.rowcount
        await db.connection.commit()

    if count:
        logger_info(f'[team] {who}: снято {count} захватов прошлых кругов проекта #{project_id}')

    return count


async def _session_llm_write(session_uuid: str, llm_name: str) -> None:
    """
    Записать выданную модель в реестр сессии — карточка роли показывает это поле.

    До пула в `server_llm` лежал режим запуска: `anthropic` или `litellm`. С пулом
    режим ничего не говорит — модель у роли меняется от круга к кругу, и карточка,
    показывающая слово «litellm», не отвечает на единственный интересный вопрос: чем
    роль работает **сейчас**.

    Запись опережает факт: маркер `__SWITCH_LLM__` только положен в инбокс, поднять
    прокси и перезапустить агента оболочке ещё предстоит. Пусть так — она же и
    поправит поле своим пингом (`/telegram-app/claude/session/heartbeat`), если
    переключение не удалось и она осталась на прежней модели.

    Сбой записи круг не срывает: это надпись на карточке, а не условие работы.
    """
    with suppress(Exception):
        async with mysql_get_db_async() as db:
            await db.execute(
                "UPDATE ai_claude_session_registry SET server_llm = %s WHERE session_uuid = %s",
                (str(llm_name)[:TEAM_LLM_POOL_NAME_MAX], str(session_uuid)))
            await db.connection.commit()


async def _task_llm_last(task_id: int) -> str:
    """
    Модель, на которой задача работала **последний** круг. Нет — пустая строка.

    Свободную и занятую ищем одинаково: занятая тем же `task_id` — это её же круг,
    который ещё не закрылся, и предпочесть её всё равно правильно.

    Сортировка обязательна. Строк на задачу бывает несколько: строка заводится на
    модель и живёт дальше, `task_id` в ней остаётся после освобождения — это и есть
    память о прошлом круге. Отработала задача на двух моделях подряд, и обе помнят её
    номер. Без `ORDER BY` какую вернуть решал MySQL: живьём задача #4915 числилась
    разом за `gx10/qwen-large` (шёл круг) и за `qwen/qwen3.7-flash` (след прошлого), и
    прилипание срабатывало через раз — а его цена как раз в том, чтобы не
    перезапускать агента и не терять накопленный им контекст.

    По `used_at`, а не по `locked_at`: второй гасится при освобождении, и у свободной
    строки там NULL — «работала час назад» от «работала вчера» по нему не отличить.
    Строки без `used_at` (заведённые до появления колонки) идут последними: про них мы
    не знаем ничего, и ставить их впереди датированных значило бы предпочесть незнание.
    """
    if not task_id:
        return ''

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT llm_name FROM team_llm_lock WHERE task_id = %s "
            " ORDER BY used_at IS NULL, used_at DESC, llm_name LIMIT 1",
            (int(task_id),))
        row = await db.fetchone()

    return str((row or {}).get('llm_name') or '')


def _pool_parse(raw) -> list[dict]:
    """Строка настройки `имя:окно,имя:окно` -> `[{'name', 'context'}]`."""
    out = []
    for chunk in str(raw or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        # `rpartition`, а не `split`: в имени модели двоеточий не бывает, но если
        # однажды появятся, окном должно стать то, что после последнего. Запись без
        # двоеточия — модель с окном по умолчанию: так пулы, сохранённые до появления
        # окон, читаются без миграции.
        name, _, context = chunk.rpartition(':')
        if not name:
            name, context = chunk, ''
        out.append({'name': name.strip(),
                    'context': context.strip() or TEAM_LLM_POOL_CONTEXT_DEFAULT})

    return out

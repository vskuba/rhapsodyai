"""
Захват оболочки ролью на круг работы.

Зачем. У роли бывает несколько живых оболочек: их поднимают одной и той же командой
запуска в новых терминалах, и каждая — свой процесс Claude Code со своим контекстом.
До этого модуля конвейер их не различал: `claude_shell_call` адресовал по паре «роль +
каталог» и брал самую свежую по пингу, поэтому вторая и следующие оболочки простаивали,
а два круга одной роли ушли бы в одну и ту же — второй промпт прилетел бы агенту
посреди чужого хода.

Теперь круг получает конкретную оболочку и держит её до конца: адрес едет в прогон
переменной `task_shell_session`, и все шаги workflow ходят в неё, а не «в роль». Роль
работает столькими кругами, сколько у неё оболочек.

**Атомарность даёт база.** Строка на оболочку одна (первичный ключ — её `session_uuid`),
а захват это `UPDATE ... WHERE свободна`: InnoDB держит строку под замком, и `rowcount`
честно говорит, досталась ли она нам. Два тика оркестратора не выдадут одну оболочку
дважды — второй увидит ноль. Блокировок в коде для этого не нужно.

**Прилипание к задаче.** При захвате сначала пробуем ту оболочку, в которой эта задача
работала прошлый круг: её Claude Code помнит прошлый ход, и вводить агента в курс заново
не придётся. Занята — берём любую свободную. Это предпочтение, а не закрепление.

Строка при освобождении не удаляется, а гасит `locked_at`: в ней остаётся `task_id`
последнего круга, и по нему работает прилипание.

Соседний модуль — `team_llm_pool`: там захват модели, устроенный тем же приёмом. Две
разные сущности и две таблицы: моделей у проекта столько, сколько их в пуле, а оболочек
у роли — сколько терминалов открыл человек, и числа эти не связаны.
"""
from contextlib import suppress

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Сколько живёт захват без подтверждения. Оболочку закрыли посреди круга, воркер убили
# по таймауту job'а — без срока роль осталась бы без оболочек навсегда, а снять захват
# было бы некому.
#
# **Срок короткий, потому что живой круг подтверждает себя сам.** Пока идёт работа, job
# раз в `TASK_CLAIM_LOCK_TOUCH_SEC` подновляет захват (`team_shell_pool_touch` из
# `_lock_hold`) — тем же ударом сердца, каким держит свою строку в `project_task`. Значит
# состарившийся захват означает ровно одно: держать его больше некому.
#
# Раньше здесь стояло 7400 секунд, и это была не осторожность, а цена незнания: захват
# снимал только `finally` своего job'а, а убитый воркер его не выполняет. Живьём круг,
# умерший при перезапуске воркера, держал оболочку и единственную модель проекта целый
# час: на странице команды роль «работала», конвейер считал модель занятой, и соседняя
# роль голодала, не имея чем работать.
#
# Запас — шесть с лишним пропущенных подтверждений: одна заминка круг не отбирает.
TEAM_SHELL_POOL_STALE_SECONDS = 300


async def team_shell_pool_acquire(project_id: int, role: str, task_id: int,
                                  sessions: list, sticky_within: list | None = None) -> str | None:
    """
    Захватить свободную оболочку роли. Возвращает `session_uuid` или `None`.

    `sessions` — живые оболочки этой роли в этом проекте, в порядке предпочтения
    (`task_role_shell_sessions_by_project`). Список приходит снаружи, а не читается
    здесь: правило «какая оболочка считается живой» уже описано в `task_role` —
    свежесть пинга, карточка роли, каталог проекта, незапертость на диалоге, — и
    вторая его копия разошлась бы с первой.

    `None` — не ошибка: все оболочки роли заняты, работа ждёт очереди. Столько кругов
    роль и ведёт разом, сколько у неё терминалов.

    Порядок попыток: сначала оболочка, в которой эта задача работала прошлый круг
    (прилипание — её агент помнит ход), затем остальные по порядку списка.

    `sticky_within` ограничивает прилипание: продвинуть вперёд можно только оболочку из
    этого списка. Нужно там, где порядок задан не предпочтением, а правилом, и ломать
    его прилипанием нельзя. Так с локальными моделями против облачного агента: пока
    свободна модель пула, круг обязан идти в пуловую оболочку, и «задача прошлый раз
    работала в облачной» этого не отменяет — иначе прилипание раз за разом уводило бы
    работу за облачные токены мимо простаивающей локальной модели.

    `None` (умолчание) — прилипание работает по всему списку, как и раньше.
    """
    sessions = [str(s).strip() for s in (sessions or []) if str(s).strip()]
    if not sessions:
        return None

    order = list(sessions)
    allowed = order if sticky_within is None else [str(s).strip() for s in sticky_within]
    sticky = await _task_shell_last(task_id)
    if sticky in order and sticky in allowed:
        order.remove(sticky)
        order.insert(0, sticky)

    async with mysql_get_db_async() as db:
        for session_uuid in order:
            # Строка на оболочку заводится один раз и живёт дальше: в ней остаётся
            # `task_id` последнего круга, по которому и работает прилипание. Удаляй
            # мы её при освобождении — память о том, где задача работала, пропадала
            # бы вместе с ней.
            await db.execute(
                'INSERT INTO team_shell_lock (session_uuid, project_id, role, locked_at) '
                'VALUES (%s, %s, %s, NULL) '
                'ON DUPLICATE KEY UPDATE project_id = VALUES(project_id), role = VALUES(role)',
                (session_uuid, int(project_id or 0), str(role or '')))

            # Свободна — `locked_at IS NULL`; протухла — держат дольше срока: оболочку
            # закрыли, не освободив, и ждать её больше нечего.
            await db.execute(
                'UPDATE team_shell_lock '
                '   SET project_id = %s, role = %s, task_id = %s, locked_at = NOW() '
                ' WHERE session_uuid = %s '
                '   AND (locked_at IS NULL OR locked_at <= NOW() - INTERVAL %s SECOND)',
                (int(project_id or 0), str(role or ''), int(task_id or 0) or None,
                 session_uuid, TEAM_SHELL_POOL_STALE_SECONDS))
            claimed = db.rowcount
            await db.connection.commit()

            if claimed:
                logger_info(f'[team] {role}: круг задачи #{task_id} идёт в оболочку '
                            f'{session_uuid[:8]}')
                return session_uuid

    return None


async def team_shell_pool_touch(session_uuid: str) -> bool:
    """
    Подтвердить захват оболочки: «круг идёт, оболочка моя». Returns: подтвердили ли.

    Зовёт сам работающий job раз в `TASK_CLAIM_LOCK_TOUCH_SEC` (`_lock_hold`), тем же
    ударом сердца, каким держит свою строку задачи. На этом и держится короткий срок
    протухания (`TEAM_SHELL_POOL_STALE_SECONDS`): захват, который никто не подтверждает,
    свободен — держать его больше некому.

    `False` — подтверждать нечего: захват уже сняли (освобождение, протухание, уборка).
    Для зовущего это сигнал прекратить, а не повод завести строку заново: оболочка
    больше не его, и ставить на неё свежую метку значило бы отнять её у нового круга.
    """
    session_uuid = str(session_uuid or '').strip()
    if not session_uuid:
        return False

    async with mysql_get_db_async() as db:
        await db.execute(
            'UPDATE team_shell_lock SET locked_at = NOW() '
            ' WHERE session_uuid = %s AND locked_at IS NOT NULL',
            (session_uuid,))
        touched = db.rowcount
        await db.connection.commit()

    return bool(touched)


async def team_shell_pool_release(session_uuid: str = '', task_id: int = 0,
                                  role: str = '') -> int:
    """
    Освободить оболочку: по сессии, по задаче или по роли. Возвращает число снятых.

    Три способа, потому что круг кончается по-разному. Штатно — знаем сессию. По
    задаче — когда её закрыли и держать за ней нечего. По роли — когда оболочки
    перезапустили и что они держали, уже не спросишь.

    Хотя бы один признак обязателен: без него запрос снял бы все захваты установки.

    Строку не удаляем, а гасим `locked_at`: `task_id` в ней остаётся, и на следующем
    круге та же задача вернётся в ту же оболочку, если она свободна.
    """
    where, params = ['locked_at IS NOT NULL'], []
    if session_uuid:
        where.append('session_uuid = %s')
        params.append(str(session_uuid))
    if task_id:
        where.append('task_id = %s')
        params.append(int(task_id))
    if role:
        where.append('role = %s')
        params.append(str(role))
    if len(where) == 1:
        return 0

    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE team_shell_lock SET locked_at = NULL WHERE {' AND '.join(where)}",
            tuple(params))
        count = db.rowcount
        await db.connection.commit()

    return count


async def team_shell_pool_forget(task_ids) -> int:
    """
    Забыть удалённые задачи: снять захват и стереть привязку. Returns: снятых строк.

    Зеркало `team_llm_pool_forget` и по той же причине. Освобождение
    (`team_shell_pool_release`) номер задачи оставляет намеренно — на следующем круге
    та же задача вернётся в ту же оболочку, где уже прогрет её контекст. Удалённой
    задаче возвращаться некуда, и привязка остаётся мусором.

    Пустой список — ноль без запроса: `IN ()` синтаксически неверен, а «забыть ничего»
    не должно означать «забыть всё».
    """
    ids = [int(i) for i in (task_ids or []) if int(i or 0)]
    if not ids:
        return 0

    placeholders = ', '.join(['%s'] * len(ids))
    async with mysql_get_db_async() as db:
        await db.execute(
            f'UPDATE team_shell_lock SET locked_at = NULL, task_id = NULL '
            f' WHERE task_id IN ({placeholders})', tuple(ids))
        count = db.rowcount
        await db.connection.commit()

    if count:
        logger_info(f'[team] пул оболочек: снято {count} захват(ов) удалённых задач')
    return count


async def team_shell_pool_busy(project_id: int | None = None) -> dict[int, dict[str, int]]:
    """
    Сколько оболочек занято прямо сейчас: `{project_id: {role: число}}`.

    Нужен отбору работы: роль выпадает из него, когда заняты все её оболочки, а не
    когда занята одна (`task_pipeline._roles_by_project_free`). Протухшие захваты не
    в счёт — их всё равно перехватит следующий `acquire`.
    """
    where = ['locked_at IS NOT NULL', 'locked_at > NOW() - INTERVAL %s SECOND']
    params = [TEAM_SHELL_POOL_STALE_SECONDS]
    if project_id is not None:
        where.append('project_id = %s')
        params.append(int(project_id))

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT project_id, role, COUNT(*) AS cnt FROM team_shell_lock '
            f" WHERE {' AND '.join(where)} GROUP BY project_id, role",
            tuple(params))
        rows = await db.fetchall() or []

    busy: dict[int, dict[str, int]] = {}
    for row in rows:
        busy.setdefault(int(row['project_id']), {})[str(row['role'] or '')] = int(row['cnt'])

    return busy


async def team_shell_pool_tasks(project_id: int | None = None) -> dict[str, int]:
    """
    Какая оболочка какую задачу держит: `{session_uuid: task_id}`.

    Нужен странице команды: по нему идущий круг ложится на свою карточку, а не все
    круги роли на первую (`team_project._cards_queue_attach`). Только живые захваты —
    протухшие ничего уже не держат.
    """
    where = ['locked_at IS NOT NULL', 'locked_at > NOW() - INTERVAL %s SECOND',
             'task_id IS NOT NULL']
    params = [TEAM_SHELL_POOL_STALE_SECONDS]
    if project_id is not None:
        where.append('project_id = %s')
        params.append(int(project_id))

    async with mysql_get_db_async() as db:
        await db.execute(
            f"SELECT session_uuid, task_id FROM team_shell_lock WHERE {' AND '.join(where)}",
            tuple(params))
        rows = await db.fetchall() or []

    return {str(row['session_uuid']): int(row['task_id']) for row in rows}


async def team_shell_pool_prune(alive: set) -> int:
    """
    Снести строки оболочек, которых больше нет в реестре живых.

    Терминалы закрывают и открывают заново, и каждый запуск заводит новую сессию —
    строки закрытых копились бы навсегда. Держать их незачем: прилипание ищет по
    `task_id` среди живых, а мёртвая сессия ни одному кругу не достанется.

    `alive` — `session_uuid` всех живых оболочек установки. Пустое множество ничего не
    сносит: живых нет вовсе — скорее всего, реестр не прочитался, и чистить по такому
    ответу значило бы стереть таблицу на ровном месте.

    **Идущий круг не сносим, кем бы ни был назван список живых.** Раньше уборка верила
    вызывающему на слово: дали множество — всё остальное под нож. Этого хватило, чтобы
    один неверный вызов обнулял захваты всего конвейера: тест пула зовёт `prune` со
    своими выдуманными сессиями, то есть заявляет «живых больше никого», и живые круги
    оставались без строк. Живьём — круг разработчика по #5238 шёл, агент работал, а
    оболочка числилась свободной: следующий тик вправе был послать в неё второй круг
    посреди чужого хода.

    Свежий захват (`locked_at` моложе `TEAM_SHELL_POOL_STALE_SECONDS`) — это работа,
    идущая прямо сейчас, и знать о ней уборке достаточно из самой таблицы: спрашивать
    об этом вызывающего незачем, а верить ему в этом — опасно. Мёртвые и свободные
    строки, ради которых уборку и заводили, условие не задевает.

    Сбой уборки ничего не роняет: лишняя строка ничему не мешает — за этим её и
    убирают.
    """
    alive = {str(s).strip() for s in (alive or []) if str(s).strip()}
    if not alive:
        return 0

    count = 0
    with suppress(Exception):
        async with mysql_get_db_async() as db:
            placeholders = ', '.join(['%s'] * len(alive))
            await db.execute(
                f'DELETE FROM team_shell_lock WHERE session_uuid NOT IN ({placeholders}) '
                '   AND (locked_at IS NULL OR locked_at <= NOW() - INTERVAL %s SECOND)',
                (*sorted(alive), TEAM_SHELL_POOL_STALE_SECONDS))
            count = db.rowcount
            await db.connection.commit()

    if count:
        logger_info(f'[team] убрано {count} строк закрытых оболочек')

    return count


async def _task_shell_last(task_id: int) -> str:
    """Оболочка, в которой задача работала прошлый круг. Нет — пустая строка."""
    if not task_id:
        return ''

    async with mysql_get_db_async() as db:
        # Свободную и занятую ищем одинаково: занятая тем же `task_id` — это её же
        # круг, который ещё не закрылся, и предпочесть её всё равно правильно.
        await db.execute(
            'SELECT session_uuid FROM team_shell_lock WHERE task_id = %s LIMIT 1',
            (int(task_id),))
        row = await db.fetchone()

    return str((row or {}).get('session_uuid') or '')

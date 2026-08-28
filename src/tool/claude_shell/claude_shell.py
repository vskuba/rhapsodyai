"""
Отправка сообщения живому агенту claude-shell и ожидание его ответа.

Оболочка claude-shell (ноутбук разработчика) держит дочерний процесс Claude Code
и опрашивает очередь `ai_claude_session`. Инструмент кладёт в эту очередь строку,
дожидается фазы 'delivered' (оболочка действительно ввела текст в Claude Code) и
затем фазы 'answered' с текстом ответа. Так задача попадает не к LLM-агенту, а к
настоящему Claude Code, запущенному в каталоге проекта.

Headless-вызова здесь больше нет: сообщение идёт в уже запущенную сессию с нужной
ролью ('manager', 'developer', 'qa'), которая видна на `/admin/team`.
"""
import asyncio
import json
import time
from datetime import timedelta

from datetime_.datetime_ import datetime_now
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

from src.project.task.task_metric_gx10 import (task_metric_gx10_delta,
                                                task_metric_gx10_snapshot)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_SHELL_ACK,
    TASK_SETTING_TIMEOUT_SHELL_BUSY,
    TASK_SETTING_TIMEOUT_SHELL_CALL,
    TASK_SETTING_TIMEOUT_SHELL_STALE,
    task_setting_timeout_get)
from src.tool.claude_.claude_ import (
    CLAUDE_MESSAGE_STATUS_ANSWERED,
    CLAUDE_MESSAGE_STATUS_DELIVERED,
    CLAUDE_MESSAGE_STATUS_FAILED,
    claude_message_user,
)

CLAUDE_SHELL_ROLE_DEFAULT = 'manager'

# Сами лимиты ожидания живут в настройках и правятся на `/admin/team` — см.
# `task_setting_timeout`: полный лимит ответа (`timeout_shell_call`), подтверждение
# доставки (`timeout_shell_ack`), ожидание занятого агента (`timeout_shell_busy`)
# и свежесть пинга реестра (`timeout_shell_stale`). Здесь остаётся только шаг
# опроса: он не настройка, а частота обращений к базе внутри ожидания.
# Каталог рабочих выкладок внутри проекта: в нём поднимают оболочку роли, чтобы
# корень репозитория остался выше рабочего каталога агента. Значение то же, что
# у `task_worktree.TASK_WORKTREE_BASE_DIR`; своя копия — потому что импорт
# оттуда замкнул бы кольцо: `task_worktree` тянет этот модуль.
CLAUDE_SHELL_WORKTREES_DIR = '.claude/worktrees'

CLAUDE_SHELL_POLL_SECONDS = 2

# Как часто, ожидая ответа, переспрашивать реестр — жива ли ещё та сессия, в
# которую ушло сообщение. Реже опроса очереди намеренно: ожидание тянется
# десятками минут, и проверка на каждом опросе стоила бы тысячи запросов.
CLAUDE_SHELL_SESSION_CHECK_SECONDS = 20

# Ответ, которым помечается сообщение осиротевшей сессии. Дословно тот же, что
# пишет сама оболочка при перезапуске из конвейера: для читающего журнал это
# одно и то же событие, и разными словами звать его незачем.
CLAUDE_SHELL_ERROR_RESTARTED = 'Оболочка перезапущена, ответ на сообщение потерян'

CLAUDE_SHELL_SESSION_STATUS_SHOWN = ('active', 'closing')

# Готовность агента из реестра. 'busy' означает, что сообщение встанет в очередь
# оболочки и подтверждения доставки в разумный срок не будет.
CLAUDE_SHELL_AGENT_STATUS_READY = 'ready'
CLAUDE_SHELL_AGENT_STATUS_BUSY = 'busy'

# Первая строка сообщения. По ней оболочка отличает запрос от агента и не шлёт
# «Принял», не пушит ответ в Telegram и проставляет фазу доставки.
CLAUDE_SHELL_AGENT_MARKER = '[[agent]]'

# Ключи ответа инструмента: их нельзя перетереть полями payload.
CLAUDE_SHELL_RESULT_KEYS = ('status', 'response', 'payload_json', 'error',
                            'session_uuid', 'inbox_id', 'elapsed',
                            'tokens_out', 'tokens_prompt', 'tokens_sec')

CLAUDE_SHELL_STATUS_ANSWERED = 'answered'
CLAUDE_SHELL_STATUS_NO_SESSION = 'no_session'
CLAUDE_SHELL_STATUS_BUSY = 'busy'
CLAUDE_SHELL_STATUS_ACK_TIMEOUT = 'ack_timeout'
CLAUDE_SHELL_STATUS_TIMEOUT = 'timeout'
CLAUDE_SHELL_STATUS_FAILED = 'failed'


async def claude_shell_call(prompt: str, role: str = CLAUDE_SHELL_ROLE_DEFAULT,
                            timeout: int = 0,
                            work_dir: str = '',
                            session: str = '') -> dict:
    """
    Отправляет сообщение агенту claude-shell с указанной ролью и ждёт ответа.

    Сообщение кладётся в очередь сессии, оболочка вводит его в Claude Code и
    возвращает ответ. Если агент занят предыдущим ходом, инструмент ждёт его
    освобождения внутри своего таймаута. Если живой сессии с такой ролью нет
    вовсе - сразу возвращает ошибку, не ставя задачу в очередь.

    Args:
        prompt:  Текст задания агенту. Если нужен машинно-читаемый ответ, прямо
                 в тексте просите ответить одним JSON-объектом.
        role:    Роль агента в команде проекта: manager, developer, qa.
        timeout: Сколько секунд ждать ответ агента, считая от доставки задания.
                 0 - взять значение из настроек. Ожидание освобождения занятого
                 агента и подтверждения доставки в этот срок не входят: у них
                 свои настройки (timeout_shell_busy, timeout_shell_ack).
        work_dir: Каталог проекта. Роли в командах разных проектов одинаковые,
                 поэтому одной роли мало: без каталога сообщение уйдёт в любую
                 живую оболочку с этой ролью, в том числе чужого проекта.
                 Пустая строка - адресация только по роли.
        session: UUID конкретной оболочки. У роли их бывает несколько - по одной
                 на открытый терминал, - и круг конвейера держит свою на всё
                 время работы: её Claude Code помнит предыдущие шаги того же
                 круга. Пустая строка - взять самую свежую по пингу оболочку
                 роли, как было до появления захвата (`team_shell_pool`).

    Returns:
        dict:
            status (str): answered - ответ получен; no_session - нет живой
                оболочки с такой ролью; busy - агент так и не освободился;
                ack_timeout -
                оболочка не подтвердила доставку; timeout - ответа не дождались;
                failed - оболочка сообщила об ошибке.
            response (str): текст ответа агента.
            payload_json (str): JSON из ответа, если агент ответил JSON-ом:
                объект или массив. Конверт из одного ключа ({"имя": {...}})
                разворачивается до самого значения.
            error (str): описание проблемы. При status = answered заполняется
                только если агент ответил, но не JSON-ом.
            session_uuid (str): сессия, которой ушло сообщение.
            inbox_id (int): строка очереди ai_claude_session.
            elapsed (int): сколько секунд заняли доставка и ответ.
        Скалярные поля JSON-ответа дополнительно кладутся в результат верхним
        уровнем - чтобы workflow мог обращаться к ним как к обычным переменным.
    """
    started = time.monotonic()
    prompt = str(prompt or '').strip()
    role = str(role or CLAUDE_SHELL_ROLE_DEFAULT).strip() or CLAUDE_SHELL_ROLE_DEFAULT
    # Шаг workflow своё значение обычно задаёт сам; ноль означает «взять общее»,
    # и тогда читаем настройку — потолок правится без перезапуска контейнеров.
    timeout = int(timeout or await task_setting_timeout_get(TASK_SETTING_TIMEOUT_SHELL_CALL))
    ack_timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_SHELL_ACK)
    busy_timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_SHELL_BUSY)
    work_dir = _path_normalize(work_dir)
    if not prompt:
        return _result_build(CLAUDE_SHELL_STATUS_FAILED, error='prompt пустой', elapsed=0)

    # Три ожидания идут подряд, но бюджеты у них раздельные, и `timeout` — бюджет
    # только последнего, ответа. Общий бюджет на всё выглядел экономнее, но врал:
    # занятый агент съедал минуты ожиданием освобождения, до ответа их не
    # оставалось, и шаг сдавался с «не ответил за 600с» — при том, что агент как
    # раз отвечал, просто на минуту позже. Потолок всему прогону ставит не этот
    # инструмент, а таймаут роли (`timeout_developer_run` и соседние).
    # Адрес круга приезжает переменной прогона: захват оболочки живёт весь круг, и
    # все его шаги обязаны идти в один и тот же Claude Code — иначе шаг плана не
    # увидит того, что нашла разведка. Пусто — берём свежайшую оболочку роли.
    session_wanted = str(session or '').strip()
    session, problem = await _session_ready_wait(role, busy_timeout, work_dir,
                                                 session_wanted)
    if problem == CLAUDE_SHELL_STATUS_NO_SESSION:
        return _result_build(
            CLAUDE_SHELL_STATUS_NO_SESSION,
            error=f'Нет живой shell-оболочки с ролью {role}'
                  f'{f" в каталоге {work_dir}" if work_dir else ""}: агент не запущен',
            elapsed=_elapsed(started))
    if problem == CLAUDE_SHELL_STATUS_BUSY:
        return _result_build(
            CLAUDE_SHELL_STATUS_BUSY,
            error=f'Агент {role} занят ({session.get("agent_status_reason") or "busy"}) '
                  f'и не освободился за {_elapsed(started)}с',
            session_uuid=str(session['session_uuid']), elapsed=_elapsed(started))

    session_uuid = str(session['session_uuid'])
    # Счётчики модели снимаем здесь, а не в начале функции: до этой строки шло
    # ожидание освобождения агента, и токены за это время потратил предыдущий ход,
    # а не наш. Замер вспомогательный — недоступные счётчики дают пустой снимок,
    # и в ответ уйдут нули (см. `task_metric_gx10`).
    tokens_before = task_metric_gx10_snapshot()
    inbox = await claude_message_user(
        prompt_user=f'{CLAUDE_SHELL_AGENT_MARKER}\n{prompt}',
        session_uuid=session_uuid,
        dynamic=1,
    )
    inbox_id = int(inbox['id'])

    # Фаза 1: оболочка подтверждает, что ввела текст в Claude Code. Без неё
    # ждать ответ бессмысленно - сообщение может лежать в очереди оболочки.
    row = await _row_wait(inbox_id, (CLAUDE_MESSAGE_STATUS_DELIVERED,
                                     CLAUDE_MESSAGE_STATUS_ANSWERED,
                                     CLAUDE_MESSAGE_STATUS_FAILED),
                          ack_timeout, role, work_dir, session_uuid)
    if row is None:
        return _result_build(
            CLAUDE_SHELL_STATUS_ACK_TIMEOUT,
            error=f'Оболочка {role} не подтвердила доставку за {ack_timeout}с',
            session_uuid=session_uuid, inbox_id=inbox_id, elapsed=_elapsed(started),
            tokens=_tokens_since(tokens_before))

    # Фаза 2: ответ агента. Отсчёт — от доставки: агент начинает думать над
    # заданием только сейчас, и время, потраченное на ожидание его освобождения,
    # к сроку ответа отношения не имеет.
    if row['status'] == CLAUDE_MESSAGE_STATUS_DELIVERED:
        row = await _row_wait(inbox_id, (CLAUDE_MESSAGE_STATUS_ANSWERED,
                                         CLAUDE_MESSAGE_STATUS_FAILED),
                              timeout, role, work_dir, session_uuid)
    if row is None:
        return _result_build(
            CLAUDE_SHELL_STATUS_TIMEOUT,
            error=f'Агент {role} не ответил за {timeout}с',
            session_uuid=session_uuid, inbox_id=inbox_id, elapsed=_elapsed(started),
            tokens=_tokens_since(tokens_before))

    response = str(row.get('response') or '')
    if row['status'] == CLAUDE_MESSAGE_STATUS_FAILED:
        return _result_build(
            CLAUDE_SHELL_STATUS_FAILED, response=response,
            error=response or f'Оболочка {role} сообщила об ошибке',
            session_uuid=session_uuid, inbox_id=inbox_id, elapsed=_elapsed(started),
            tokens=_tokens_since(tokens_before))

    payload = _payload_parse(response)
    return _result_build(
        CLAUDE_SHELL_STATUS_ANSWERED, response=response, payload=payload,
        error='' if payload else _error_no_payload(response),
        session_uuid=session_uuid, inbox_id=inbox_id, elapsed=_elapsed(started),
        tokens=_tokens_since(tokens_before))


async def claude_shell_session_status(role: str = CLAUDE_SHELL_ROLE_DEFAULT,
                                      work_dir: str = '',
                                      session_uuid: str = '') -> dict:
    """
    Готов ли агент claude-shell с указанной ролью принять сообщение.

    Проверяет две вещи: свежий пинг сессии (оболочка жива) и готовность агента
    (терминал свободен, сообщение уйдёт в Claude Code сразу).

    Args:
        role: Роль агента в команде проекта: manager, developer, qa.
        work_dir: Каталог проекта; пустая строка - любая оболочка с этой ролью.
        session_uuid: Конкретная оболочка. У роли их бывает несколько - по одной на
                 открытый терминал, - и спрашивать «готова ли роль» бессмысленно:
                 ответит свободная соседка, а работать будет не она. Пустая
                 строка - самая свежая по пингу, прежний путь.

    Returns:
        dict:
            ready (int): 1 - можно слать сообщение, 0 - нельзя.
            agent_status (str): ready, busy или unknown.
            agent_status_reason (str): чем занят агент.
            session_uuid (str): сессия агента, пустая строка если сессии нет.
            seconds_ago (int): сколько секунд назад был пинг, -1 если сессии нет.
    """
    session = await _session_find(str(role or CLAUDE_SHELL_ROLE_DEFAULT).strip(),
                                  _path_normalize(work_dir),
                                  str(session_uuid or '').strip())
    if not session:
        return {'ready': 0, 'agent_status': '', 'agent_status_reason': '',
                'session_uuid': '', 'seconds_ago': -1}

    agent_status = str(session.get('agent_status') or '')
    now = await datetime_now()
    last_seen_at = session.get('last_seen_at')

    return {
        'ready': 1 if agent_status != CLAUDE_SHELL_AGENT_STATUS_BUSY else 0,
        'agent_status': agent_status,
        'agent_status_reason': str(session.get('agent_status_reason') or ''),
        'session_uuid': str(session['session_uuid']),
        'seconds_ago': int((now - last_seen_at).total_seconds()) if last_seen_at else -1,
    }


async def _session_ready_wait(role: str, timeout: float,
                              work_dir: str = '',
                              session_uuid: str = '') -> tuple[dict | None, str]:
    """Живая сессия с ролью, готовая принять сообщение.

    Возвращает (сессия, проблема). Проблема пустая — можно слать; no_session —
    живой оболочки нет и ждать нечего; busy — агент за отведённое время так и не
    освободился, вызов нужно повторить позже.

    `session_uuid` задан — ждём именно её: круг захватил эту оболочку, и уйти в
    соседнюю нельзя, там другой контекст. Она умерла — это `no_session`, и подменять
    её живой соседкой тем более нельзя: круг продолжился бы с чистого листа, молча.

    Ждём именно занятость: соседние шаги workflow шлют сообщения одному и тому же
    менеджеру подряд, и на следующем шаге он ещё дописывает предыдущий ход. Отказ
    без ожидания возвращал `busy` с elapsed = 0, и шаг молча терял ответ.
    """
    deadline = time.monotonic() + max(float(timeout), 0.0)
    while True:
        session = await _session_find(role, work_dir, session_uuid)
        if not session:
            return None, CLAUDE_SHELL_STATUS_NO_SESSION
        if str(session.get('agent_status') or '') != CLAUDE_SHELL_AGENT_STATUS_BUSY:
            return session, ''
        if time.monotonic() >= deadline:
            return session, CLAUDE_SHELL_STATUS_BUSY

        await asyncio.sleep(CLAUDE_SHELL_POLL_SECONDS)


async def _session_find(role: str, work_dir: str = '',
                        session_uuid: str = '') -> dict | None:
    """Живая сессия реестра с нужной ролью — самая свежая по пингу.

    `session_uuid` сужает поиск до одной оболочки: её выдал захват круга
    (`team_shell_pool`), и остальные условия — роль, каталог, свежесть — остаются в
    силе. Умерла или сменила роль — здесь `None`, то есть `no_session`.

    Каталог сужает поиск до одного проекта: роли в командах разных проектов
    называются одинаково, и без каталога «самая свежая по пингу» отдала бы
    менеджера соседнего проекта. Хвостовой слеш у обеих сторон снимаем —
    '/srv/app' и '/srv/app/' это один каталог.

    Порог свежести считаем через datetime_now(): last_seen_at пишется в поясе из
    настройки timezone, а NOW() отдал бы пояс MySQL — сессия оказалась бы либо
    вечно живой, либо мгновенно мёртвой.
    """
    stale_seconds = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_SHELL_STALE)
    stale_before = await datetime_now() - timedelta(seconds=stale_seconds)
    placeholders = ','.join(['%s'] * len(CLAUDE_SHELL_SESSION_STATUS_SHOWN))
    session_sql, session_params = '', []
    if session_uuid:
        session_sql = 'AND session_uuid = %s '
        session_params = [str(session_uuid)]
    work_dir_sql, work_dir_params = '', []
    if work_dir:
        # Оболочка роли поднимается не в корне проекта, а в каталоге его рабочих
        # выкладок (`.claude/worktrees`): так корень репозитория оказывается выше
        # рабочего каталога, и Claude Code не пишет в чекаут человека. Спрашивают
        # же её по каталогу проекта — конвейер знает проект, а не выкладки.
        # Поэтому оба адреса считаем одной оболочкой.
        variants = _work_dir_variants(work_dir)
        placeholders_dir = ','.join(['%s'] * len(variants))
        work_dir_sql = f"AND TRIM(TRAILING '/' FROM work_dir) IN ({placeholders_dir}) "
        work_dir_params = variants

    async with mysql_get_db_async() as db:
        await db.execute(
            f"""
            SELECT * FROM `ai_claude_session_registry`
            WHERE role = %s AND status IN ({placeholders}) AND last_seen_at >= %s
            {session_sql}{work_dir_sql}
            ORDER BY last_seen_at DESC
            LIMIT 1
            """,
            (role, *CLAUDE_SHELL_SESSION_STATUS_SHOWN, stale_before,
             *session_params, *work_dir_params)
        )
        rows = await db.fetchall()

    return rows[0] if rows else None


async def _row_wait(inbox_id: int, statuses: tuple, timeout: float,
                    role: str = '', work_dir: str = '', session_uuid: str = '') -> dict | None:
    """
    Опрос строки очереди до одной из целевых фаз. None — не дождались.

    Заодно следим, жив ли адресат. Оболочку перезапускают и мимо конвейера — руками
    в терминале, — и тогда у роли появляется новая сессия, а наше сообщение остаётся
    висеть в старой: отвечать на него уже некому. Без этой проверки прогон досиживал
    до своего таймаута: сорок шесть минут ожидания при свободной роли, которая всё
    это время простаивала.

    Смена сессии возвращается как сбой доставки — той же строкой, что пишет сама
    оболочка, когда её перезапускает конвейер. Дальше по общему пути: круг считается
    несостоявшимся, попытка не жжётся, вход отдаётся заново.

    Сессию проверяем не каждый опрос, а раз в `CLAUDE_SHELL_SESSION_CHECK_SECONDS`:
    опрос идёт каждые две секунды, и лишний запрос в реестр на каждом из них за
    сорок минут ожидания вылился бы в тысячу с лишним походов в базу впустую.
    """
    deadline = time.monotonic() + max(float(timeout), 0.0)
    checked_at = time.monotonic()
    while True:
        async with mysql_get_db_async() as db:
            await db.execute(
                "SELECT id, status, response, handled FROM ai_claude_session WHERE id = %s",
                (inbox_id,)
            )
            rows = await db.fetchall()

        row = rows[0] if rows else None
        if row and str(row.get('status') or '') in statuses:
            return row
        if time.monotonic() >= deadline:
            return None

        if session_uuid and time.monotonic() - checked_at >= CLAUDE_SHELL_SESSION_CHECK_SECONDS:
            checked_at = time.monotonic()
            if await _session_replaced(role, work_dir, session_uuid):
                logger_info(f'claude_shell: сессия роли {role} сменилась, ждать ответа больше некому')
                return {'id': inbox_id, 'status': CLAUDE_MESSAGE_STATUS_FAILED,
                        'response': CLAUDE_SHELL_ERROR_RESTARTED, 'handled': 0}

        await asyncio.sleep(CLAUDE_SHELL_POLL_SECONDS)


async def _session_replaced(role: str, work_dir: str, session_uuid: str) -> bool:
    """
    Нашу оболочку сменила новая: терминал перезапустили, ждать ответа некому.

    Проверяем именно нашу сессию, а не «самую свежую у роли»: оболочек у роли бывает
    несколько, и соседняя, пингующая чаще, оказывалась бы «самой свежей» постоянно —
    круг срывался бы сразу после первого же вопроса агенту.

    Пропавшая сессия сменой не считается сама по себе: оболочка молчит несколько
    секунд на каждом перезапуске дочернего Claude Code, и объявлять прогон сорванным
    из-за этого рано — на то есть таймаут.

    Смена — это когда нашей сессии нет, а у роли появилась **новее нашей**: только
    так выглядит перезапущенный человеком терминал. Сравнение по `created_at`
    обязательно: без него соседняя оболочка, поднятая раньше нашей и всё это время
    мирно простаивавшая, засчитывалась бы за замену — и круг срывался бы каждый раз,
    когда наша молчит дольше порога свежести.
    """
    if await _session_find(role, work_dir, session_uuid):
        return False

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT created_at FROM ai_claude_session_registry WHERE session_uuid = %s',
            (session_uuid,))
        ours = await db.fetchone()

    newer = await _session_find(role, work_dir)
    if not newer or not ours:
        return False

    return bool(newer.get('created_at') and ours.get('created_at')
                and newer['created_at'] > ours['created_at'])


def _payload_parse(response: str) -> dict | list:
    """JSON из ответа агента.

    Claude Code почти всегда оборачивает JSON в ```-блок или дописывает пару слов
    вокруг («Готово, бла-бла. {…}»), поэтому кроме прямого разбора ищем первое
    самостоятельное значение внутри текста. Не разобрали — не беда, текст ответа
    остаётся на месте.
    """
    text = str(response or '').strip()
    if not text:
        return {}

    if '```' in text:
        parts = text.split('```')
        for part in parts[1::2]:
            part = part.split('\n', 1)[-1] if part[:20].lower().startswith('json') else part
            payload = _json_loads(part)
            if payload:
                return _payload_unwrap(payload)

    payload = _json_loads(text)
    if payload:
        return _payload_unwrap(payload)

    # Оборванный ответ разбираем раньше поиска первого значения: у обрыва целое
    # снаружи не читается, и поиск подхватил бы вложенный объект, потеряв
    # соседние ключи. Здесь же хвост достраивается (`_json_balance`) целиком.
    for opening in ('{', '['):
        start = text.find(opening)
        if start >= 0:
            payload = _json_loads(text[start:])
            if payload:
                return _payload_unwrap(payload)

    payload = _json_first_value(text)
    if payload:
        return _payload_unwrap(payload)

    return {}


def _payload_unwrap(payload: dict | list) -> dict | list:
    """Снимает конверт вида {"task_plan_json": {...}} до самого значения.

    Промпты просят агента завернуть ответ в объект с одним ключом-именем
    переменной, но агент нередко отвечает сразу содержимым. Разворачивая
    одноключевой конверт, получаем один и тот же результат в обоих случаях.
    Плоские ответы судьи (plan_ok + plan_critique_new) не трогаем: там ключей
    больше одного, а одноключевой ответ со скаляром — это уже само значение.
    """
    if not isinstance(payload, dict) or len(payload) != 1:
        return payload

    value = next(iter(payload.values()))
    return value if isinstance(value, (dict, list)) else payload


def _json_loads(text: str) -> dict | list:
    """Разбор JSON: объект или массив; всё остальное считаем неудачей.

    Не разобрали с первого раза — пробуем достроить скобки: живой агент иногда
    обрывает ответ на одну закрывающую скобку раньше, и без починки разбор
    сползал на фоллбэк «вырезать первый массив», а тот возвращал кусок ответа
    (например, только `subtasks`) вместо всего объекта.
    """
    text = str(text).strip()
    value = _json_loads_strict(text)
    return value if value else _json_loads_strict(_json_balance(text))


def _json_loads_strict(text: str) -> dict | list:
    """Разбор без починки: объект или массив; всё остальное считаем неудачей."""
    try:
        value = json.loads(str(text).strip())
    except (ValueError, TypeError):
        return {}

    return value if isinstance(value, (dict, list)) else {}


def _json_first_value(text: str) -> dict | list:
    """Первое полноценное JSON-значение внутри текста, остальное отбрасываем.

    Агент отвечает и текстом, и JSON-ом: «Готово, бла-бла. {…}», а следом ещё
    дописывает пояснение. Резать по первой '{' и последней '}' на таком ответе
    нельзя — фигурная скобка попадается и в прозе, и в примерах кода, и границы
    уезжают. `raw_decode` разбирает значение от указанной позиции и молча
    игнорирует хвост, поэтому идём по всем кандидатам-скобкам слева направо и
    берём первую, от которой значение разобралось целиком.
    """
    decoder = json.JSONDecoder()
    for position, char in enumerate(text):
        if char not in '{[':
            continue
        try:
            value, _ = decoder.raw_decode(text, position)
        except ValueError:
            continue
        if isinstance(value, (dict, list)):
            return value

    return {}


def _json_balance(text: str) -> str:
    """Достраивает недостающий хвост оборванного JSON: кавычка и скобки.

    Чиним только обрыв — незакрытые скобки в конце. Лишняя закрывающая скобка
    или скобка не того вида означают, что текст испорчен по-настоящему: тогда
    возвращаем пустую строку, и разбор честно проваливается.
    """
    stack     = []
    in_string = False
    escaped   = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack or stack[-1] != ('{' if char == '}' else '['):
                return ''
            stack.pop()

    if not stack:
        return ''

    tail = '"' if in_string else ''
    return text + tail + ''.join('}' if char == '{' else ']' for char in reversed(stack))


def _result_build(status: str, response: str = '', payload: dict | list | None = None,
                  error: str = '', session_uuid: str = '', inbox_id: int = 0,
                  elapsed: int = 0, tokens: dict | None = None) -> dict:
    """Ответ инструмента: служебные поля плюс поля разобранного JSON.

    Вложенные объекты и массивы тоже поднимаем наверх: движок workflow сам
    сериализует их в JSON-строку, и шаг умеет подставить её в следующий промпт.
    Ответ-массив наверх раскладывать нечего — он целиком лежит в payload_json.

    `tokens` — что модель сделала за этот ход (`task_metric_gx10`). Кладём в ответ,
    а не считаем потом: только здесь известны обе границы хода, а после него
    счётчики уже уехали на чужую работу. Нули означают «замер не состоялся» —
    модель недоступна или счётчики не читаются.
    """
    payload = payload if payload else {}
    tokens = tokens or {}
    result = {
        'status': status,
        'response': response,
        'payload_json': json.dumps(payload, ensure_ascii=False) if payload else '',
        'error': error,
        'session_uuid': session_uuid,
        'inbox_id': inbox_id,
        'elapsed': elapsed,
        'tokens_out': int(tokens.get('tokens_output') or 0),
        'tokens_prompt': int(tokens.get('tokens_prompt') or 0),
        'tokens_sec': float(tokens.get('tokens_per_sec') or 0.0),
    }

    if isinstance(payload, dict):
        for key, value in payload.items():
            key = str(key)
            if key in CLAUDE_SHELL_RESULT_KEYS:
                continue
            result[key] = value

    return result


def _tokens_since(before: dict) -> dict:
    """Что модель сделала с момента снимка `before` до сейчас.

    Второй снимок берём здесь, а не заранее: ход только что кончился, и позже
    счётчики уже уедут на чужую работу.
    """
    return task_metric_gx10_delta(before, task_metric_gx10_snapshot())


def _error_no_payload(response: str) -> str:
    """Диагностика на ответ без JSON: сам ответ, урезанный до безопасной строки.

    Шаги workflow подставляют `%..._error%` внутрь JSON-шаблона, поэтому кавычки,
    слэши и переводы строк из ответа агента ломали бы разбор результата — их
    вычищаем. Без этого провал выглядел как «менеджер не ответил», хотя ответ был,
    просто не в том формате.
    """
    text = ' '.join(str(response or '').split())
    text = text.replace('"', "'").replace('\\', '/')
    if not text:
        return 'Агент ответил пустой строкой'
    if len(text) > 200:
        text = text[:200] + '...'
    return f'Агент ответил не JSON-ом: {text}'


def _elapsed(started: float) -> int:
    """Секунды с начала вызова — их видно в трейсе workflow."""
    return int(time.monotonic() - started)


def _work_dir_variants(work_dir: str) -> list:
    """
    Адреса, под которыми может быть зарегистрирована оболочка проекта.

    Их два: сам каталог проекта и его `.claude/worktrees`. Роль запускают во
    втором — чтобы корень репозитория остался выше рабочего каталога и
    правки агента не уходили в чекаут человека, — а спрашивают по первому:
    конвейер оперирует проектом, про выкладки он не знает.

    Оба конца делаем понятными друг другу здесь, а не в вызывающих: адрес
    сверяется в нескольких местах, и разъехавшиеся правила означали бы, что
    роль видна одному и не видна другому.

    Переданный адрес уже с выкладками — второй вариант не добавляем: он бы
    указывал на `worktrees/worktrees`, которого нет.
    """
    base = _path_normalize(work_dir)
    if not base:
        return []
    if base.endswith('/' + CLAUDE_SHELL_WORKTREES_DIR):
        return [base]

    return [base, f'{base}/{CLAUDE_SHELL_WORKTREES_DIR}']


def _path_normalize(path) -> str:
    """Путь без хвостового слеша — '/srv/app' и '/srv/app/' это один каталог.

    Каталог приходит и из настройки проекта, и из реестра сессий, где его пишет
    оболочка, — записаны они бывают по-разному, а сравнение должно совпасть.
    """
    value = str(path or '').strip()
    if len(value) > 1:
        value = value.rstrip('/')

    return value

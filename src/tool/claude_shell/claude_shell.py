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
from mysql_.mysql_ import mysql_get_db_async

from src.tool.claude_.claude_ import (
    CLAUDE_MESSAGE_STATUS_ANSWERED,
    CLAUDE_MESSAGE_STATUS_DELIVERED,
    CLAUDE_MESSAGE_STATUS_FAILED,
    claude_message_user,
)

CLAUDE_SHELL_ROLE_DEFAULT = 'manager'

# Полный лимит ожидания ответа: агент читает задачу, ходит по коду и отвечает.
CLAUDE_SHELL_TIMEOUT = 300
# Лимит на подтверждение доставки. Оболочка вводит текст, только когда терминал
# свободен, поэтому запас больше обычного цикла опроса очереди (5с).
CLAUDE_SHELL_ACK_TIMEOUT = 120
CLAUDE_SHELL_POLL_SECONDS = 2

# Лимит ожидания освобождения агента. Шаги workflow бьют в одну оболочку подряд,
# и на следующем шаге агент почти всегда ещё дописывает предыдущий ход — это
# секунды. Отказ без ожидания терял бы шаги судьи и целей.
# 300с, а не 180: если предыдущий шаг отвалился по своему таймауту, ход агента
# при этом продолжается, и следующий шаг обязан его дождаться, иначе конвейер
# ловит `busy` на живом агенте и выбрасывает уже готовый результат.
CLAUDE_SHELL_BUSY_TIMEOUT = 300

# Свежесть пинга реестра: столько же, сколько на карточках `/admin/team`.
# Оболочка пингует раз в несколько секунд, 30с — это уже закрытый терминал.
CLAUDE_SHELL_STALE_SECONDS = 30
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
                            'session_uuid', 'inbox_id', 'elapsed')

CLAUDE_SHELL_STATUS_ANSWERED = 'answered'
CLAUDE_SHELL_STATUS_NO_SESSION = 'no_session'
CLAUDE_SHELL_STATUS_BUSY = 'busy'
CLAUDE_SHELL_STATUS_ACK_TIMEOUT = 'ack_timeout'
CLAUDE_SHELL_STATUS_TIMEOUT = 'timeout'
CLAUDE_SHELL_STATUS_FAILED = 'failed'


async def claude_shell_call(prompt: str, role: str = CLAUDE_SHELL_ROLE_DEFAULT,
                            timeout: int = CLAUDE_SHELL_TIMEOUT) -> dict:
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
        timeout: Сколько секунд ждать ответ.

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
    timeout = int(timeout or CLAUDE_SHELL_TIMEOUT)
    if not prompt:
        return _result_build(CLAUDE_SHELL_STATUS_FAILED, error='prompt пустой', elapsed=0)

    session, problem = await _session_ready_wait(role, min(CLAUDE_SHELL_BUSY_TIMEOUT, timeout))
    if problem == CLAUDE_SHELL_STATUS_NO_SESSION:
        return _result_build(
            CLAUDE_SHELL_STATUS_NO_SESSION,
            error=f'Нет живой shell-оболочки с ролью {role}: агент не запущен',
            elapsed=_elapsed(started))
    if problem == CLAUDE_SHELL_STATUS_BUSY:
        return _result_build(
            CLAUDE_SHELL_STATUS_BUSY,
            error=f'Агент {role} занят ({session.get("agent_status_reason") or "busy"}) '
                  f'и не освободился за {_elapsed(started)}с',
            session_uuid=str(session['session_uuid']), elapsed=_elapsed(started))

    session_uuid = str(session['session_uuid'])
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
                          min(CLAUDE_SHELL_ACK_TIMEOUT, timeout - _elapsed(started)))
    if row is None:
        return _result_build(
            CLAUDE_SHELL_STATUS_ACK_TIMEOUT,
            error=f'Оболочка {role} не подтвердила доставку за {CLAUDE_SHELL_ACK_TIMEOUT}с',
            session_uuid=session_uuid, inbox_id=inbox_id, elapsed=_elapsed(started))

    # Фаза 2: ответ агента.
    if row['status'] == CLAUDE_MESSAGE_STATUS_DELIVERED:
        row = await _row_wait(inbox_id, (CLAUDE_MESSAGE_STATUS_ANSWERED,
                                         CLAUDE_MESSAGE_STATUS_FAILED),
                              timeout - _elapsed(started))
    if row is None:
        return _result_build(
            CLAUDE_SHELL_STATUS_TIMEOUT,
            error=f'Агент {role} не ответил за {timeout}с',
            session_uuid=session_uuid, inbox_id=inbox_id, elapsed=_elapsed(started))

    response = str(row.get('response') or '')
    if row['status'] == CLAUDE_MESSAGE_STATUS_FAILED:
        return _result_build(
            CLAUDE_SHELL_STATUS_FAILED, response=response,
            error=response or f'Оболочка {role} сообщила об ошибке',
            session_uuid=session_uuid, inbox_id=inbox_id, elapsed=_elapsed(started))

    payload = _payload_parse(response)
    return _result_build(
        CLAUDE_SHELL_STATUS_ANSWERED, response=response, payload=payload,
        error='' if payload else _error_no_payload(response),
        session_uuid=session_uuid, inbox_id=inbox_id, elapsed=_elapsed(started))


async def claude_shell_session_status(role: str = CLAUDE_SHELL_ROLE_DEFAULT) -> dict:
    """
    Готов ли агент claude-shell с указанной ролью принять сообщение.

    Проверяет две вещи: свежий пинг сессии (оболочка жива) и готовность агента
    (терминал свободен, сообщение уйдёт в Claude Code сразу).

    Args:
        role: Роль агента в команде проекта: manager, developer, qa.

    Returns:
        dict:
            ready (int): 1 - можно слать сообщение, 0 - нельзя.
            agent_status (str): ready, busy или unknown.
            agent_status_reason (str): чем занят агент.
            session_uuid (str): сессия агента, пустая строка если сессии нет.
            seconds_ago (int): сколько секунд назад был пинг, -1 если сессии нет.
    """
    session = await _session_find(str(role or CLAUDE_SHELL_ROLE_DEFAULT).strip())
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


async def _session_ready_wait(role: str, timeout: float) -> tuple[dict | None, str]:
    """Живая сессия с ролью, готовая принять сообщение.

    Возвращает (сессия, проблема). Проблема пустая — можно слать; no_session —
    живой оболочки нет и ждать нечего; busy — агент за отведённое время так и не
    освободился, вызов нужно повторить позже.

    Ждём именно занятость: соседние шаги workflow шлют сообщения одному и тому же
    менеджеру подряд, и на следующем шаге он ещё дописывает предыдущий ход. Отказ
    без ожидания возвращал `busy` с elapsed = 0, и шаг молча терял ответ.
    """
    deadline = time.monotonic() + max(float(timeout), 0.0)
    while True:
        session = await _session_find(role)
        if not session:
            return None, CLAUDE_SHELL_STATUS_NO_SESSION
        if str(session.get('agent_status') or '') != CLAUDE_SHELL_AGENT_STATUS_BUSY:
            return session, ''
        if time.monotonic() >= deadline:
            return session, CLAUDE_SHELL_STATUS_BUSY

        await asyncio.sleep(CLAUDE_SHELL_POLL_SECONDS)


async def _session_find(role: str) -> dict | None:
    """Живая сессия реестра с нужной ролью — самая свежая по пингу.

    Порог свежести считаем через datetime_now(): last_seen_at пишется в поясе из
    настройки timezone, а NOW() отдал бы пояс MySQL — сессия оказалась бы либо
    вечно живой, либо мгновенно мёртвой.
    """
    stale_before = await datetime_now() - timedelta(seconds=CLAUDE_SHELL_STALE_SECONDS)
    placeholders = ','.join(['%s'] * len(CLAUDE_SHELL_SESSION_STATUS_SHOWN))

    async with mysql_get_db_async() as db:
        await db.execute(
            f"""
            SELECT * FROM `ai_claude_session_registry`
            WHERE role = %s AND status IN ({placeholders}) AND last_seen_at >= %s
            ORDER BY last_seen_at DESC
            LIMIT 1
            """,
            (role, *CLAUDE_SHELL_SESSION_STATUS_SHOWN, stale_before)
        )
        rows = await db.fetchall()

    return rows[0] if rows else None


async def _row_wait(inbox_id: int, statuses: tuple, timeout: float) -> dict | None:
    """Опрос строки очереди до одной из целевых фаз. None — не дождались."""
    deadline = time.monotonic() + max(float(timeout), 0.0)
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

        await asyncio.sleep(CLAUDE_SHELL_POLL_SECONDS)


def _payload_parse(response: str) -> dict | list:
    """JSON из ответа агента.

    Claude Code почти всегда оборачивает JSON в ```-блок или дописывает пару слов
    вокруг, поэтому кроме прямого разбора пробуем вырезать первый объект по
    границам скобок. Не разобрали — не беда, текст ответа остаётся на месте.
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

    for opening, closing in (('{', '}'), ('[', ']')):
        start = text.find(opening)
        end = text.rfind(closing)
        if 0 <= start < end:
            payload = _json_loads(text[start:end + 1])
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
                  elapsed: int = 0) -> dict:
    """Ответ инструмента: служебные поля плюс поля разобранного JSON.

    Вложенные объекты и массивы тоже поднимаем наверх: движок workflow сам
    сериализует их в JSON-строку, и шаг умеет подставить её в следующий промпт.
    Ответ-массив наверх раскладывать нечего — он целиком лежит в payload_json.
    """
    payload = payload if payload else {}
    result = {
        'status': status,
        'response': response,
        'payload_json': json.dumps(payload, ensure_ascii=False) if payload else '',
        'error': error,
        'session_uuid': session_uuid,
        'inbox_id': inbox_id,
        'elapsed': elapsed,
    }

    if isinstance(payload, dict):
        for key, value in payload.items():
            key = str(key)
            if key in CLAUDE_SHELL_RESULT_KEYS:
                continue
            result[key] = value

    return result


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

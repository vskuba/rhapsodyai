"""
Управление живой оболочкой claude-shell: карточка команды на `/admin/team` и
перезапуск агента перед новой задачей конвейера.

Снаружи оболочкой командуют только через очередь `ai_claude_session`: она сама
опрашивает свой inbox и выполняет служебные маркеры (`dynamic=1` — такие записи
в истории чата не показываются). Здесь лежит перезапуск watch-процесса — тот же
механизм, которым пользуется кнопка статуса в Telegram Mini App.

Перезапуск не «оживляет зависшую оболочку», а гасит и поднимает заново дочерний
Claude Code, то есть обнуляет его контекст. Поэтому он же обязателен перед тем,
как карточка возьмёт в работу новую задачу: иначе разговор предыдущей задачи
остаётся в контексте и мешается в следующей.

Состав карточек и их активность — в `team_project`; здесь только действия над
конкретной сессией.
"""
import asyncio
import time
from datetime import datetime

from datetime_.datetime_ import datetime_now
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

from src.mysql_.repository.ai_claude_session_registry_repository import AiClaudeSessionRegistryRepository
from src.telegram_.telegram_notify import telegram_send_owner
from src.tool.claude_.claude_ import claude_message_user
from src.tool.claude_shell.claude_shell import (CLAUDE_SHELL_AGENT_STATUS_READY,
                                                claude_shell_session_status)

# Маркер протокола оболочки: увидев его в inbox, `/loop` перезапускает watch.
# Значение — часть контракта с уже запущенными оболочками, менять его нельзя.
TEAM_SESSION_RESTART_MARKER = '__RESTART_WATCH__'

# Живым watch считаем пинг не старше 15 секунд — это 3× интервал heartbeat.
# Порог свежести карточки (`TEAM_PROJECT_PING_STALE_SECONDS`) больше: там речь
# про «оболочка вообще работает», а тут — про «ответит ли она прямо сейчас».
TEAM_SESSION_WATCH_ALIVE_SECONDS = 15

TEAM_SESSION_RESTART_POLL_SECONDS = 2
# Оболочка помечает маркер `handled=1` сразу, как прочитала его из inbox: цикл
# опроса — 2–5 секунд, минуты здесь взяться неоткуда. Не дождались за минуту —
# watch не читает очередь, и ждать готовности бессмысленно.
TEAM_SESSION_RESTART_ACK_TIMEOUT = 60
# Пауза между подтверждением и опросом готовности. Пока старый дочерний процесс
# не убит, heartbeat продолжает отдавать `ready` — без паузы мы бы приняли этот
# ответ уходящего процесса за готовность нового. Убийство и повторный запуск
# занимают у оболочки около двух секунд, берём с запасом.
TEAM_SESSION_RESTART_SETTLE_SECONDS = 10
# Сколько ждём, пока поднявшийся Claude Code дочитает свой запуск и освободится.
# Холодный старт с большим CLAUDE.md — это десятки секунд, изредка больше минуты.
TEAM_SESSION_RESTART_READY_TIMEOUT = 180

# Причины, по которым перезапуск не состоялся — уходят в лог и в результат.
TEAM_SESSION_RESTART_NO_SESSION = 'no_session'
TEAM_SESSION_RESTART_NO_ACK = 'no_ack'
TEAM_SESSION_RESTART_NOT_READY = 'not_ready'


async def team_session_restart(session_uuid: str) -> dict | None:
    """
    Попросить оболочку перезапустить watch-процесс.

    Returns: статус сессии на момент запроса либо None, если сессии нет в реестре.
    Статус возвращается прежний, до перезапуска: новый heartbeat придёт секундами
    позже, и страница увидит его следующим опросом `/api/team/projects`.
    """
    session_uuid = str(session_uuid or '').strip()
    if not session_uuid:
        return None

    row = await AiClaudeSessionRegistryRepository().find_one_by({'session_uuid': session_uuid})
    if not row:
        return None

    await claude_message_user(TEAM_SESSION_RESTART_MARKER, session_uuid, dynamic=1)

    status = _status_build(row, await datetime_now())
    status['restart_sent'] = True
    await _telegram_notify(row, status)

    return status


async def team_session_restart_role(role: str, work_dir: str = '') -> dict:
    """
    Перезапустить агента в оболочке с указанной ролью и дождаться готовности.

    Зовётся перед тем, как роль возьмёт в работу новую задачу: дочерний Claude
    Code гасится и поднимается заново, то есть контекст предыдущей задачи не
    протекает в следующую. Внутри одного прогона звать нельзя — шаги workflow
    бьют в ту же оболочку подряд, и перезапуск посреди прогона снёс бы её ход.

    Ничего не бросает: живой оболочки может не быть вовсе, и это не повод
    ронять задачу — шаг `claude_shell_call` сам вернёт `no_session`, а конвейер
    разберётся по своим правилам.

    Args:
        role: роль карточки — manager, developer, qa.
        work_dir: каталог проекта. Роли в командах разных проектов называются
            одинаково, и без каталога перезапуск снёс бы контекст менеджера
            соседнего проекта — того самого, что сейчас работает над своей
            задачей. Пустая строка — адресация только по роли.

    Returns:
        role, session_uuid: кого перезапускали (session_uuid пуст, если сессии нет).
        restarted (bool): оболочка подтвердила приём маркера.
        ready (bool): агент снова принимает сообщения.
        reason (str): пусто при успехе, иначе no_session / no_ack / not_ready.
        elapsed (int): секунды, потраченные на ожидание.
    """
    role = str(role or '').strip()
    started = time.monotonic()

    session = await claude_shell_session_status(role, work_dir)
    session_uuid = str(session.get('session_uuid') or '')
    if not session_uuid:
        logger_info(f'[team] restart {role}: живой оболочки нет, перезапуск пропущен')
        return _restart_result(role, '', False, False, TEAM_SESSION_RESTART_NO_SESSION, started)

    inbox = await claude_message_user(TEAM_SESSION_RESTART_MARKER, session_uuid, dynamic=1)
    if not await _inbox_handled_wait(int(inbox['id']), TEAM_SESSION_RESTART_ACK_TIMEOUT):
        logger_info(f'[team] restart {role}: оболочка не подтвердила маркер за '
                    f'{TEAM_SESSION_RESTART_ACK_TIMEOUT}s')
        return _restart_result(role, session_uuid, False, False, TEAM_SESSION_RESTART_NO_ACK, started)

    await asyncio.sleep(TEAM_SESSION_RESTART_SETTLE_SECONDS)
    ready = await _agent_ready_wait(role, TEAM_SESSION_RESTART_READY_TIMEOUT, work_dir)

    result = _restart_result(role, session_uuid, True, ready,
                             '' if ready else TEAM_SESSION_RESTART_NOT_READY, started)
    logger_info(f'[team] restart {role}: перезапущен, готов={ready}, {result["elapsed"]}s')

    return result


def _status_build(row: dict, now: datetime) -> dict:
    """
    Свежесть пинга сессии. `now` берётся из `datetime_now()`: `last_seen_at`
    записан в том же поясе, и сравнивать его с временем контейнера нельзя.
    """
    last_seen_at = row.get('last_seen_at')
    seconds_ago = int((now - last_seen_at).total_seconds()) if last_seen_at else None

    return {
        'session_uuid': row.get('session_uuid'),
        'role': str(row.get('role') or ''),
        'project_label': str(row.get('project_label') or ''),
        'last_seen_at': str(last_seen_at) if last_seen_at else None,
        'seconds_ago': seconds_ago,
        'watch_alive': seconds_ago is not None and seconds_ago <= TEAM_SESSION_WATCH_ALIVE_SECONDS,
    }


def _restart_result(role: str, session_uuid: str, restarted: bool, ready: bool,
                    reason: str, started: float) -> dict:
    return {'role': role, 'session_uuid': session_uuid, 'restarted': restarted,
            'ready': ready, 'reason': reason, 'elapsed': int(time.monotonic() - started)}


async def _inbox_handled_wait(inbox_id: int, timeout: float) -> bool:
    """
    Дождаться, пока оболочка пометит служебный маркер обработанным.

    Ответа на такую строку не будет: маркер не доходит до агента, оболочка сама
    его подтверждает (`inbox-ack`) и уходит в перезапуск. Значит, `handled=1` —
    единственное подтверждение, что перезапуск точно состоится.
    """
    deadline = time.monotonic() + max(float(timeout), 0.0)
    while True:
        async with mysql_get_db_async() as db:
            await db.execute('SELECT handled FROM ai_claude_session WHERE id = %s', (inbox_id,))
            row = await db.fetchone()

        if row and int(row.get('handled') or 0) == 1:
            return True
        if time.monotonic() >= deadline:
            return False

        await asyncio.sleep(TEAM_SESSION_RESTART_POLL_SECONDS)


async def _agent_ready_wait(role: str, timeout: float, work_dir: str = '') -> bool:
    """
    Дождаться поднявшегося агента: свежий пинг сессии плюс статус `ready`.

    Пока новый дочерний процесс печатает свой запуск, оболочка отдаёт `busy`.
    Не дождались — не страшно: сообщение всё равно встанет в очередь оболочки,
    просто время доставки перестаёт быть предсказуемым.
    """
    deadline = time.monotonic() + max(float(timeout), 0.0)
    while True:
        session = await claude_shell_session_status(role, work_dir)
        if str(session.get('agent_status') or '') == CLAUDE_SHELL_AGENT_STATUS_READY:
            return True
        if time.monotonic() >= deadline:
            return False

        await asyncio.sleep(TEAM_SESSION_RESTART_POLL_SECONDS)


async def _telegram_notify(row: dict, status: dict) -> None:
    """
    Запасной канал на случай мёртвого watch: inbox тогда никто не читает, и
    маркер до оболочки не дойдёт. Telegram-плагин в терминале сообщение получит
    и разбудит агента, который поднимет watch руками.

    Сбой уведомления не должен ронять запрос — перезапуск уже поставлен в очередь.
    """
    try:
        await telegram_send_owner(
            f"🔄 Перезапуск процессов сессии со страницы «Команда»\n"
            f"Сессия: {row.get('project_label')} / {row.get('role')}\n"
            f"watch alive: {'да' if status['watch_alive'] else 'нет'}"
        )
    except Exception as error:
        logger_info(f'[team] team_session_restart: telegram notify failed: {error}')

#!/usr/bin/env python3
"""
CLI-обертка над эндпоинтами реестра сессий Claude Code
(src/uvicorn/routers/telegram_app/telegram_app.py) - не хук, вызывается вручную
из /loop-промпта или самим агентом через Bash, чтобы не собирать curl вручную
на каждой итерации. Секрет и base_url читаются тем же способом, что и в
session_start.py. См. .claude/docs/claude_session_registry.md §4.

Использование:
  session_client.py register --role ROLE --project-label LABEL
  session_client.py resume --session-uuid UUID
  session_client.py heartbeat --session-uuid UUID
  session_client.py inbox --session-uuid UUID
  session_client.py respond --session-uuid UUID --response TEXT [--inbox-id N] [--no-notify]
  session_client.py finalize --session-uuid UUID [--summary TEXT]
  session_client.py watch --session-uuid UUID [--interval SECONDS] [--terminal-pid PID]
  session_client.py status --session-uuid UUID

Общие вспомогательные инструменты (не завязанные на конкретную сессию) - в
соседнем `session_tool.py`.

`watch` - бесресурсный (без LLM) фоновый процесс, запускается ОДИН раз при
регистрации/резюме сессии и живёт, пока жив терминал (умирает вместе с
процессом при закрытии окна - см. claude_session_registry.md §4). На каждом
тике (по умолчанию 5с - дёшево, это просто HTTP+SQL, не LLM): 1) пингует
heartbeat - обновляет last_seen_at независимо от того, думает ли сейчас LLM
(решает staleness для Mini App, порог 15с - 3x интервала); 2) проверяет
inbox и печатает маркерную строку в stdout, только если там сообщение с id
больше последнего уже увиденного (дедуп по id - без этого маркер печатался
бы на каждом тике, пока сообщение остаётся необработанным, а не один раз
при появлении). При обнаружении новых сообщений сам (без участия LLM,
гарантированно - не завязано на то, вспомнит ли агент) шлёт короткий push
"получено, разбираюсь" - агенту не нужно помнить об этом вручную. Сам по
себе не тратит токены - предназначен для Monitor, который слушает stdout
этого процесса и будит агента только по реальному новому событию.

Все исходящие запросы (heartbeat, auto-ack, respond, finalize) идут через
`api_call_retry` - если сервер недоступен (например, идёт передеплой),
не проваливаются сразу, а повторяют попытку с паузой до ~1 минуты, чтобы
сообщения не терялись в окне недоступности.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error

from session_tool import PROJECT_ROOT, api_call, load_config

SESSION_UUID_PATH = os.path.join(PROJECT_ROOT, ".claude", "session_uuid")

# Спец-контент, которым Mini App (кнопка "Удалить") просит терминал
# самоочиститься - watch распознаёт и обрабатывает его сам, без LLM (см.
# cleanup_session ниже и SESSION_CLEANUP_MARKER в telegram_app.py)
CLEANUP_MARKER = "__SESSION_CLEANUP__"

# Кнопка «Статус» в Mini App - просит watch перезапустить себя.
RESTART_WATCH_MARKER = "__RESTART_WATCH__"


def api_call_retry(method: str, path: str, secret: str, base_url: str, params: dict = None,
                    body: dict = None, retries: int = 12, delay: int = 5) -> dict:
    # Повторяет запрос при недоступности сервера (например, идёт передеплой
    # - в наблюдении контейнер поднимался за 10-20с, 12x5с=60с даёт запас) -
    # чтобы heartbeat/ack/respond/finalize не терялись молча в этом окне.
    last_error = None
    for attempt in range(retries):
        try:
            return api_call(method, path, secret, base_url, params=params, body=body)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise  # 4xx - постоянная ошибка, ретраить бессмысленно
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_error


def is_watch_running(session_uuid: str) -> bool:
    try:
        result = subprocess.run(["pgrep", "-f", f"session_client.py watch --session-uuid {session_uuid}"],
                                 capture_output=True, timeout=3)
        return result.returncode == 0
    except Exception:
        return False


def find_terminal_pid(start_pid: int):
    # Ищем реального "владельца" терминала - процесс, который одновременно
    # 1) лидер своей сессии (SID == его собственный PID) и 2) имеет
    # настоящий TTY. Наивно проверять os.getsid(0) не работает: харнесс
    # заводит каждый вызов инструмента Bash в СВОЕЙ изолированной сессии
    # (SID == PID процесса-обёртки), но без TTY - это не терминал, а сам
    # `claude` хоть и видит настоящий TTY, но не лидер сессии (сессией
    # владеет запустивший его шелл). Только шелл терминала одновременно
    # удовлетворяет обоим условиям.
    pid = start_pid
    for _ in range(20):
        try:
            out = subprocess.run(["ps", "-o", "pid=,ppid=,sid=,tty=", "-p", str(pid)],
                                  capture_output=True, text=True, timeout=3).stdout.strip()
        except Exception:
            return None
        if not out:
            return None
        parts = out.split()
        cur_pid, ppid, sid, tty = int(parts[0]), int(parts[1]), int(parts[2]), parts[3]
        if tty != "?" and sid == cur_pid:
            return cur_pid
        if ppid <= 1:
            return None
        pid = ppid
    return None


def _spawn_watch(session_uuid: str, terminal_pid: int = None):
    log_path = f"/tmp/claude_watch_{os.path.basename(PROJECT_ROOT)}.log"
    log_file = open(log_path, "a")
    cmd = [sys.executable, "-u", os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_client.py"),
           "watch", "--session-uuid", session_uuid]
    if terminal_pid:
        cmd += ["--terminal-pid", str(terminal_pid)]
    subprocess.Popen(
        cmd, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True, cwd=PROJECT_ROOT,
    )


def start_watch_detached(session_uuid: str):
    # setsid (start_new_session=True) - без него фоновый watch привязан к
    # жизни самого процесса Claude Code, а не терминала: если Claude Code
    # перезапустится/упадёт, watch молча умирает вместе с ним, даже если
    # окно терминала осталось открыто (обнаружено на живом тесте). Побочный
    # эффект register/resume - гарантированно, не завязано на то, вспомнит
    # ли агент запустить его вручную через инструкцию.
    #
    # Но полная отвязка через setsid - тоже перебор: теперь watch не умирает
    # и при реальном закрытии окна терминала (второй живой тест это подтвердил
    # - last_seen_at продолжал обновляться часами после закрытия окна). Поэтому
    # передаём watch PID процесса-шелла терминала (find_terminal_pid), пока мы
    # ещё в обычном дереве процессов - watch сам проверяет его на каждом тике и
    # завершается, если тот пропал (терминал реально закрыт), но переживает
    # перезапуск самого Claude Code (шелл остаётся тем же).
    if is_watch_running(session_uuid):
        return
    terminal_pid = find_terminal_pid(os.getpid())
    _spawn_watch(session_uuid, terminal_pid)


def save_session_uuid(session_uuid: str):
    os.makedirs(os.path.dirname(SESSION_UUID_PATH), exist_ok=True)
    with open(SESSION_UUID_PATH, "w", encoding="utf-8") as f:
        f.write(session_uuid)


def activate_session(session_uuid: str):
    # Общая точка входа для register/resume - и хук, и агент дёргают её
    # косвенно через CLI, поэтому "сессия стала активной" всегда значит
    # одно и то же: файл сохранён, watch поднят, дублировать эти два шага
    # по всем вызывающим местам не нужно
    save_session_uuid(session_uuid)
    start_watch_detached(session_uuid)


def cleanup_session(session_uuid: str, secret: str, base_url: str):
    # Реакция на CLEANUP_MARKER - полностью механическая (удалить файл,
    # почистить очередь), LLM тут решать нечего, поэтому обрабатывается
    # прямо в watch, не пробрасывается агенту через NEW_MESSAGES
    try:
        api_call_retry("POST", "/telegram-app/claude/session/cleanup-confirm", secret, base_url,
                        body={"session_uuid": session_uuid})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass
    if os.path.isfile(SESSION_UUID_PATH):
        os.remove(SESSION_UUID_PATH)


def watch(session_uuid: str, secret: str, base_url: str, interval: int, terminal_pid: int = None):
    # last_seen_max_id дедуплицирует маркер: без него watch печатал бы
    # NEW_MESSAGES на каждом тике, пока сообщение остаётся необработанным
    # (handled=0), а не один раз при появлении. id - глобальный
    # auto-increment (ai_claude_session), монотонный и надёжнее хэша
    # контента (не путает два разных сообщения с одинаковым текстом).
    last_seen_max_id = 0
    while True:
        # terminal_pid - PID шелла терминала, захваченный до setsid-отвязки
        # (см. find_terminal_pid/start_watch_detached). Если его больше нет
        # в /proc - терминал реально закрыт, а не просто перезапустился
        # Claude Code (тогда шелл остаётся тем же, PID не меняется) - самое
        # время завершиться самому, раз больше некому это сделать за нас.
        if terminal_pid and not os.path.exists(f"/proc/{terminal_pid}"):
            print(f"TERMINAL_CLOSED terminal_pid={terminal_pid}", flush=True)
            return
        try:
            api_call_retry("POST", "/telegram-app/claude/session/heartbeat", secret, base_url,
                            body={"session_uuid": session_uuid})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        try:
            result = api_call("GET", "/telegram-app/claude/session/inbox", secret, base_url,
                               params={"session_uuid": session_uuid})
            rows = result.get("result") or []
            new_rows = [r for r in rows if r["id"] > last_seen_max_id]
            if new_rows:
                last_seen_max_id = new_rows[-1]["id"]
                if any(r["content"] == CLEANUP_MARKER for r in new_rows):
                    cleanup_session(session_uuid, secret, base_url)
                    print("SESSION_CLEANED_UP", flush=True)
                    return
                restart_rows = [r for r in new_rows if r["content"] == RESTART_WATCH_MARKER]
                if restart_rows:
                    # Помечаем маркер обработанным, чтобы новый watch-процесс
                    # его не увидел и не зациклил перезапуски.
                    try:
                        api_call_retry("POST", "/telegram-app/claude/session/inbox-ack", secret, base_url, body={
                            "session_uuid": session_uuid,
                            "ids": [r["id"] for r in restart_rows],
                        })
                    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                        pass
                    # Запускаем новый watch с тем же terminal_pid - old watch выходит после return.
                    # terminal_pid передаём чтобы новый watch тоже корректно отслеживал закрытие
                    # терминала (find_terminal_pid уже не сработает из detached-процесса).
                    _spawn_watch(session_uuid, terminal_pid)
                    print("WATCH_RESTARTING", flush=True)
                    return
                user_rows = [r for r in new_rows if r["content"] != RESTART_WATCH_MARKER]
                if user_rows:
                    try:
                        api_call_retry("POST", "/telegram-app/claude/respond", secret, base_url, body={
                            "session_uuid": session_uuid,
                            "response": "Получено, разбираюсь…",
                            "notify": True,
                        })
                    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                        pass
                    # Сырой текст сообщения в самой строке лога - Monitor матчит
                    # по "NEW_MESSAGES" и отдаёт всю строку как есть в событие,
                    # так сразу видно, что именно пришло, без отдельного inbox.
                    # Одна строка на сообщение (не одна строка на батч) - если
                    # пришло сразу несколько, каждое видно по отдельности.
                    # Переносы строк в контенте схлопываются в пробел, чтобы не
                    # разорвать строку лога на части, которые grep не заметит.
                    for r in user_rows:
                        content_flat = " ".join(str(r["content"]).split())
                        print(f"NEW_MESSAGES Message: {content_flat!r}", flush=True)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(interval)


def session_status(session_uuid: str, secret: str, base_url: str) -> dict:
    # Проверяет только то, что реально проверяемо снаружи (процесс watch,
    # доступность сервера, файл session_uuid) - "Monitor: armed" сюда не
    # входит принципиально: это состояние самой сессии Claude Code, знает
    # о нём только сам агент (он его вызывал), не внешний процесс. Агент
    # обязан дописать эту строку сам после вызова этой команды - см.
    # session_start.py.
    watch_ok = is_watch_running(session_uuid)
    try:
        # api_call_retry, не голый api_call - если сервер сейчас недоступен
        # (например, идёт передеплой), статус не должен сразу показывать
        # 🔴 и заставлять пользователя вручную просить повторить - тихо
        # пробуем до ~60с (12x5с), прежде чем реально признать недоступность
        api_call_retry("POST", "/telegram-app/claude/session/heartbeat", secret, base_url,
                        body={"session_uuid": session_uuid})
        server_ok = True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        server_ok = False
    file_ok = os.path.isfile(SESSION_UUID_PATH) and open(SESSION_UUID_PATH).read().strip() == session_uuid

    return {"watch": watch_ok, "server": server_ok, "session_uuid_file": file_ok}


def format_status_checklist(status: dict) -> str:
    # Общий формат чек-листа (🍏/🔴, не текстовые галочки) - использует и
    # хук (встраивает уже готовый текст с реальными данными прямо в
    # additionalContext, гарантированно, до всякого решения агента), и
    # агент, если вызывает `status` вручную сам. Строку "Monitor" сюда не
    # добавляет - см. session_status(). 🟢 (зелёный кружок) заменён на 🍏
    # (зелёное яблоко) - у пользователя 🟢 рендерился серым из-за проблем
    # со шрифтом эмодзи в его терминале, 🍏 показывает реальный зелёный.
    icon = lambda ok: "🍏" if ok else "🔴"
    return (
        f"{icon(status['watch'])} watch\n"
        f"{icon(status['server'])} server\n"
        f"{icon(status['session_uuid_file'])} session_uuid_file"
    )


def main():
    secret, base_url = load_config()

    if not secret:
        print(json.dumps({"error": "TELEGRAM_TOKEN_RHAPSODY not found in .env/.env.local"}), file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_register = sub.add_parser("register")
    p_register.add_argument("--role", default="developer")
    p_register.add_argument("--project-label", required=True)

    p_resume = sub.add_parser("resume")
    p_resume.add_argument("--session-uuid", required=True)

    p_heartbeat = sub.add_parser("heartbeat")
    p_heartbeat.add_argument("--session-uuid", required=True)

    p_inbox = sub.add_parser("inbox")
    p_inbox.add_argument("--session-uuid", required=True)

    p_respond = sub.add_parser("respond")
    p_respond.add_argument("--session-uuid", required=True)
    p_respond.add_argument("--response", required=True)
    p_respond.add_argument("--inbox-id", type=int, default=None)
    p_respond.add_argument("--no-notify", action="store_true")

    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("--session-uuid", required=True)
    p_finalize.add_argument("--summary", default=None)

    p_watch = sub.add_parser("watch")
    p_watch.add_argument("--session-uuid", required=True)
    p_watch.add_argument("--interval", type=int, default=5)
    p_watch.add_argument("--terminal-pid", type=int, default=None)

    p_status = sub.add_parser("status")
    p_status.add_argument("--session-uuid", required=True)

    args = parser.parse_args()

    if args.command == "watch":
        watch(args.session_uuid, secret, base_url, args.interval, args.terminal_pid)
        return

    try:
        if args.command == "status":
            result = {"result": session_status(args.session_uuid, secret, base_url)}
        elif args.command == "register":
            body = {"role": args.role, "project_label": args.project_label}
            result = api_call("POST", "/telegram-app/claude/session/register", secret, base_url, body=body)
            activate_session(result["result"]["session_uuid"])
        elif args.command == "resume":
            result = api_call("POST", "/telegram-app/claude/session/resume", secret, base_url,
                               body={"session_uuid": args.session_uuid})
            activate_session(args.session_uuid)
        elif args.command == "heartbeat":
            result = api_call("POST", "/telegram-app/claude/session/heartbeat", secret, base_url,
                               body={"session_uuid": args.session_uuid})
        elif args.command == "inbox":
            result = api_call("GET", "/telegram-app/claude/session/inbox", secret, base_url,
                               params={"session_uuid": args.session_uuid})
        elif args.command == "respond":
            body = {"session_uuid": args.session_uuid, "response": args.response, "notify": not args.no_notify}
            if args.inbox_id is not None:
                body["inbox_id"] = args.inbox_id
            result = api_call_retry("POST", "/telegram-app/claude/respond", secret, base_url, body=body)
        elif args.command == "finalize":
            body = {"session_uuid": args.session_uuid}
            if args.summary:
                body["summary"] = args.summary
            result = api_call_retry("POST", "/telegram-app/claude/session/finalize", secret, base_url, body=body)
        else:
            raise ValueError(f"unknown command: {args.command}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

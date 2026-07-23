#!/usr/bin/env python3
"""
CLI-обертка над эндпоинтами реестра сессий Claude Code
(src/uvicorn/routers/telegram_app/telegram_app.py) - не хук, вызывается вручную
из /loop-промпта или самим агентом через Bash, чтобы не собирать curl вручную
на каждой итерации. Секрет и base_url читаются тем же способом, что и в
session_start.py. См. .claude/docs/claude_session_registry.md §4.

Использование:
  session_client.py heartbeat --session-uuid UUID
  session_client.py inbox --session-uuid UUID
  session_client.py respond --session-uuid UUID --response TEXT [--inbox-id N] [--no-notify]
  session_client.py finalize --session-uuid UUID [--summary TEXT]
  session_client.py watch --session-uuid UUID [--interval SECONDS]

`watch` - бесресурсный (без LLM) фоновый процесс, запускается ОДИН раз при
регистрации/резюме сессии и живёт, пока жив терминал (умирает вместе с
процессом при закрытии окна - см. claude_session_registry.md §4). На каждом
тике (по умолчанию 5с - дёшево, это просто HTTP+SQL, не LLM): 1) пингует
heartbeat - обновляет last_seen_at независимо от того, думает ли сейчас LLM
(решает staleness для Mini App, порог 15с - 3x интервала); 2) проверяет
inbox и печатает маркерную строку в stdout, только если там сообщение с id
больше последнего уже увиденного (дедуп по id - без этого маркер печатался
бы на каждом тике, пока сообщение остаётся необработанным, а не один раз
при появлении). Сам по себе не тратит токены - предназначен для Monitor,
который слушает stdout этого процесса и будит агента только по реальному
новому событию.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def env_file_load(path: str) -> dict:
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return values


def api_call(method: str, path: str, secret: str, base_url: str, params: dict = None, body: dict = None) -> dict:
    url = f"{base_url}{path}"
    if params:
        query = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        url = f"{url}?{query}"

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "X-Claude-Secret": secret,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def watch(session_uuid: str, secret: str, base_url: str, interval: int):
    # last_seen_max_id дедуплицирует маркер: без него watch печатал бы
    # NEW_MESSAGES на каждом тике, пока сообщение остаётся необработанным
    # (handled=0), а не один раз при появлении. id - глобальный
    # auto-increment (ai_claude_session), монотонный и надёжнее хэша
    # контента (не путает два разных сообщения с одинаковым текстом).
    last_seen_max_id = 0
    while True:
        try:
            api_call("POST", "/telegram-app/claude/session/heartbeat", secret, base_url,
                      body={"session_uuid": session_uuid})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        try:
            result = api_call("GET", "/telegram-app/claude/session/inbox", secret, base_url,
                               params={"session_uuid": session_uuid})
            rows = result.get("result") or []
            if rows and rows[-1]["id"] > last_seen_max_id:
                new_count = sum(1 for r in rows if r["id"] > last_seen_max_id)
                last_seen_max_id = rows[-1]["id"]
                print(f"NEW_MESSAGES count={new_count}", flush=True)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(interval)


def main():
    env = env_file_load(os.path.join(PROJECT_ROOT, ".env"))
    secret = os.environ.get("TELEGRAM_TOKEN_RHAPSODY") or env.get("TELEGRAM_TOKEN_RHAPSODY", "")
    mini_app_url = os.environ.get("TELEGRAM_MINI_APP_URL") or env.get("TELEGRAM_MINI_APP_URL", "")
    base_url = mini_app_url.rsplit("/telegram-app", 1)[0] if mini_app_url else "http://localhost:8011"

    if not secret:
        print(json.dumps({"error": "TELEGRAM_TOKEN_RHAPSODY not found in .env"}), file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

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

    args = parser.parse_args()

    if args.command == "watch":
        watch(args.session_uuid, secret, base_url, args.interval)
        return

    try:
        if args.command == "heartbeat":
            result = api_call("POST", "/telegram-app/claude/session/heartbeat", secret, base_url,
                               body={"session_uuid": args.session_uuid})
        elif args.command == "inbox":
            result = api_call("GET", "/telegram-app/claude/session/inbox", secret, base_url,
                               params={"session_uuid": args.session_uuid})
        elif args.command == "respond":
            body = {"session_uuid": args.session_uuid, "response": args.response, "notify": not args.no_notify}
            if args.inbox_id is not None:
                body["inbox_id"] = args.inbox_id
            result = api_call("POST", "/telegram-app/claude/respond", secret, base_url, body=body)
        elif args.command == "finalize":
            body = {"session_uuid": args.session_uuid}
            if args.summary:
                body["summary"] = args.summary
            result = api_call("POST", "/telegram-app/claude/session/finalize", secret, base_url, body=body)
        else:
            raise ValueError(f"unknown command: {args.command}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

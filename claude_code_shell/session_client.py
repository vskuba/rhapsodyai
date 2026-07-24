#!/usr/bin/env python3
"""
CLI-обертка над эндпоинтами реестра сессий Claude Code.

  session_client.py register --role ROLE --project-label LABEL
  session_client.py resume --session-uuid UUID
  session_client.py heartbeat --session-uuid UUID
  session_client.py inbox --session-uuid UUID
  session_client.py respond --session-uuid UUID --response TEXT [--inbox-id N] [--no-notify]
  session_client.py finalize --session-uuid UUID [--summary TEXT]
  session_client.py status --session-uuid UUID

Инъекция сообщений из inbox в PTY обрабатывается claude_code_shell.py.
"""

import argparse
import json
import os
import sys
import time
import urllib.error

from session_tool import PROJECT_ROOT, api_call, load_config

SESSION_UUID_PATH = os.path.join(PROJECT_ROOT, "claude_code_shell", "session_uuid")


def api_call_retry(method, path, secret, base_url, params=None, body=None, retries=12, delay=5):
    last_error = None
    for attempt in range(retries):
        try:
            return api_call(method, path, secret, base_url, params=params, body=body)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_error


def save_session_uuid(session_uuid):
    os.makedirs(os.path.dirname(SESSION_UUID_PATH), exist_ok=True)
    with open(SESSION_UUID_PATH, "w", encoding="utf-8") as f:
        f.write(session_uuid)


def session_status(session_uuid, secret, base_url):
    try:
        api_call_retry("POST", "/telegram-app/claude/session/heartbeat", secret, base_url,
                       body={"session_uuid": session_uuid})
        server_ok = True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        server_ok = False
    file_ok = os.path.isfile(SESSION_UUID_PATH) and open(SESSION_UUID_PATH).read().strip() == session_uuid
    return {"server": server_ok, "session_uuid_file": file_ok}


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

    p_status = sub.add_parser("status")
    p_status.add_argument("--session-uuid", required=True)

    args = parser.parse_args()

    try:
        if args.command == "status":
            result = {"result": session_status(args.session_uuid, secret, base_url)}
        elif args.command == "register":
            result = api_call("POST", "/telegram-app/claude/session/register", secret, base_url,
                              body={"role": args.role, "project_label": args.project_label})
            save_session_uuid(result["result"]["session_uuid"])
        elif args.command == "resume":
            result = api_call("POST", "/telegram-app/claude/session/resume", secret, base_url,
                              body={"session_uuid": args.session_uuid})
            save_session_uuid(args.session_uuid)
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

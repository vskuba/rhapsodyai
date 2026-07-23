#!/usr/bin/env python3
"""
Session Tools - вспомогательные CLI-инструменты общего назначения,
не завязанные на конкретную сессию (в отличие от session_client.py). Цель -
не переписывать заново boilerplate (чтение .env, авторизация, HTTP-запрос)
через inline-python каждый раз, когда нужно что-то быстро проверить на
проде. Новые инструменты добавляются сюда же, сгруппированные по секциям
ниже - см. заголовки "=== ... ===".

Использование:
  session_tool.py call METHOD PATH [--params k=v,k2=v2] [--body JSON]
"""

import argparse
import json
import os
import sys

from session_client import PROJECT_ROOT, api_call, env_file_load


# === HTTP API (X-Claude-Secret) ===
# Универсальный авторизованный запрос к любому /telegram-app/... эндпоинту -
# без переписывания boilerplate вручную через inline-python. Работает только
# для _require_claude_secret эндпоинтов - owner-only (_require_telegram_owner)
# не обходит, это осознанно не поддерживается (владельческую сессию Mini App
# не подделываем).

def call(method: str, path: str, secret: str, base_url: str, params_arg: str, body_arg: str):
    params = dict(kv.split("=", 1) for kv in params_arg.split(",")) if params_arg else None
    body = json.loads(body_arg) if body_arg else None
    return api_call(method.upper(), path, secret, base_url, params=params, body=body)


def main():
    env = env_file_load(f"{PROJECT_ROOT}/.env")
    secret = os.environ.get("TELEGRAM_TOKEN_RHAPSODY") or env.get("TELEGRAM_TOKEN_RHAPSODY", "")
    mini_app_url = os.environ.get("TELEGRAM_MINI_APP_URL") or env.get("TELEGRAM_MINI_APP_URL", "")
    base_url = mini_app_url.rsplit("/telegram-app", 1)[0] if mini_app_url else "http://localhost:8011"

    if not secret:
        print(json.dumps({"error": "TELEGRAM_TOKEN_RHAPSODY not found in .env"}), file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_call = sub.add_parser("call")
    p_call.add_argument("method")
    p_call.add_argument("path")
    p_call.add_argument("--params", default=None, help="k=v,k2=v2")
    p_call.add_argument("--body", default=None, help="raw JSON")

    args = parser.parse_args()

    try:
        if args.command == "call":
            result = call(args.method, args.path, secret, base_url, args.params, args.body)
        else:
            raise ValueError(f"unknown command: {args.command}")
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

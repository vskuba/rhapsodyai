#!/usr/bin/env python3
"""
Session Tools - базовый модуль общих утилит + CLI-инструменты общего
назначения, не завязанные на конкретную сессию (в отличие от
session_client.py, который его импортирует, а не наоборот - здесь ноль
зависимостей от соседних файлов, чтобы не было циклического импорта).
Портируется в другой проект вместе с session_client.py/session_start.py
без правок - project_label и .env/.env.local определяются на месте.

Цель - не переписывать заново boilerplate (чтение .env, авторизация,
HTTP-запрос) через inline-python каждый раз, когда нужно что-то быстро
проверить на проде. Новые инструменты добавляются сюда же, сгруппированные
по секциям ниже - см. заголовки "=== ... ===".

Использование:
  session_tool.py call METHOD PATH [--params k=v,k2=v2] [--body JSON]
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WRAPPER_PID_FILE = os.path.join(PROJECT_ROOT, "claude_code_shell", "wrapper.pid")


def is_wrapper_running() -> bool:
    try:
        with open(WRAPPER_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


# === Загрузка .env ===

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


def env_file_find(project_root: str) -> dict:
    # .env.local первым - частый паттерн, где .env закоммичен (шаблон/
    # дефолты), а локальные значения живут в незакоммиченном .env.local
    for name in (".env.local", ".env"):
        path = os.path.join(project_root, name)
        if os.path.isfile(path):
            return env_file_load(path)
    return {}


def load_config() -> tuple[str, str]:
    # Единственное место, где собираются secret/base_url - session_start.py,
    # session_client.py и main() ниже импортируют это отсюда, не дублируют
    env = env_file_find(PROJECT_ROOT)
    secret = os.environ.get("TELEGRAM_TOKEN_RHAPSODY") or env.get("TELEGRAM_TOKEN_RHAPSODY", "")
    mini_app_url = os.environ.get("TELEGRAM_MINI_APP_URL") or env.get("TELEGRAM_MINI_APP_URL", "")
    base_url = mini_app_url.rsplit("/telegram-app", 1)[0] if mini_app_url else "http://localhost:8011"
    return secret, base_url


# === HTTP API (X-Claude-Secret) ===
# Универсальный авторизованный запрос к любому /telegram-app/... эндпоинту -
# без переписывания boilerplate вручную через inline-python. Работает только
# для _require_claude_secret эндпоинтов - owner-only (_require_telegram_owner)
# не обходит, это осознанно не поддерживается (владельческую сессию Mini App
# не подделываем).

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


def call(method: str, path: str, secret: str, base_url: str, params_arg: str, body_arg: str):
    params = dict(kv.split("=", 1) for kv in params_arg.split(",")) if params_arg else None
    body = json.loads(body_arg) if body_arg else None
    return api_call(method.upper(), path, secret, base_url, params=params, body=body)


# === Claude Quota ===

def get_oauth_token() -> str:
    cred_path = os.path.expanduser("~/.claude/.credentials.json")
    if not os.path.exists(cred_path):
        raise FileNotFoundError(f"Файл авторизации не найден: {cred_path}")
    with open(cred_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    token = data.get("claudeAiOauth", {}).get("accessToken")
    if not token:
        raise KeyError("Поле claudeAiOauth.accessToken отсутствует в файле авторизации")
    return token


def _parse_tz_offset_hours(tz_str: str) -> float:
    tz_str = tz_str.strip()
    if ":" in tz_str:
        sign = -1 if tz_str.startswith("-") else 1
        tz_str = tz_str.lstrip("+-")
        parts = tz_str.split(":")
        return sign * (int(parts[0]) + int(parts[1]) / 60)
    return float(tz_str)


def check_quota_data(secret: str = "", base_url: str = "") -> dict:
    """
    Запрашивает данные квоты у Anthropic API.
    Возвращает dict с полями: five_hour, seven_day (None если нет), reset_time, error (None если успех).
    """
    try:
        token = get_oauth_token()
    except Exception as e:
        return {"quota": True, "five_hour": None, "seven_day": None, "reset_time": None, "error": str(e)}

    url = "https://api.anthropic.com/api/oauth/usage"
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-code/1.0.85",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))

        five_hour = res_data.get("five_hour") or {}
        utilization = five_hour.get("utilization")
        resets_at_raw = five_hour.get("resets_at")

        reset_time = None
        if resets_at_raw:
            try:
                from datetime import timedelta
                dt = datetime.fromisoformat(resets_at_raw.replace("Z", "+00:00"))
                tz_offset_hours = 0.0
                if secret and base_url:
                    try:
                        tz_resp = api_call("GET", "/telegram-app/claude/timezone", secret, base_url)
                        tz_str = (tz_resp.get("result") or {}).get("timezone", "+0")
                        tz_offset_hours = _parse_tz_offset_hours(tz_str)
                    except Exception:
                        pass
                dt_local = dt + timedelta(hours=tz_offset_hours)
                reset_time = dt_local.strftime("%H:%M")
            except Exception:
                reset_time = resets_at_raw

        seven_day = res_data.get("seven_day") or {}
        seven_day_pct = seven_day.get("utilization")

        return {
            "quota": True,
            "five_hour": utilization,
            "seven_day": seven_day_pct,
            "reset_time": reset_time,
            "error": None,
        }

    except urllib.error.HTTPError as e:
        if e.code == 401:
            msg = "Токен устарел. Напишите любое сообщение в чат Claude Code для его обновления."
        elif e.code == 429:
            msg = "Слишком частые запросы (≥1 раза в 3 мин)."
        else:
            msg = f"HTTP {e.code}: {e.read().decode(errors='ignore')}"
        return {"quota": True, "five_hour": None, "seven_day": None, "reset_time": None, "error": msg}
    except Exception as e:
        return {"quota": True, "five_hour": None, "seven_day": None, "reset_time": None, "error": str(e)}


# === Event Log ===

def event_log_add(event_type: str, payload: dict | None, secret: str, base_url: str) -> dict:
    body = {"type": event_type}
    if payload is not None:
        body["payload"] = payload
    return api_call("POST", "/event-log", secret, base_url, body=body)


def main():
    secret, base_url = load_config()

    if not secret:
        print(json.dumps({"error": "TELEGRAM_TOKEN_RHAPSODY not found in .env/.env.local"}), file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_call = sub.add_parser("call")
    p_call.add_argument("method")
    p_call.add_argument("path")
    p_call.add_argument("--params", default=None, help="k=v,k2=v2")
    p_call.add_argument("--body", default=None, help="raw JSON")

    p_event_log = sub.add_parser("event-log")
    p_event_log.add_argument("--type", required=True, dest="event_type")
    p_event_log.add_argument("--payload", default=None, help="raw JSON object")

    sub.add_parser("quota")

    args = parser.parse_args()

    try:
        if args.command == "call":
            result = call(args.method, args.path, secret, base_url, args.params, args.body)
        elif args.command == "event-log":
            payload = json.loads(args.payload) if args.payload else None
            result = event_log_add(args.event_type, payload, secret, base_url)
        elif args.command == "quota":
            result = check_quota_data(secret, base_url)
        else:
            raise ValueError(f"unknown command: {args.command}")
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

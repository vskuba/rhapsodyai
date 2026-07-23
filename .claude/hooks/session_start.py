#!/usr/bin/env python3
"""
SessionStart hook - при старте новой (не resume/clear/compact) сессии Claude
Code достает из реестра ai_claude_session_registry список сессий для текущего
проекта. Вся механика оживления сессии (файл session_uuid, фоновый watch)
инкапсулирована здесь и в session_client.py.

Если .claude/session_uuid уже есть с прошлого запуска - хук резюмирует
сессию и поднимает watch сам, без участия LLM.
"""

import json
import os
import sys
import urllib.error

from session_client import (SESSION_UUID_PATH, activate_session, api_call_retry,
                             format_status_checklist, session_status)
from session_tool import load_config


def emit(context_lines: list[str]):
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(context_lines),
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


def main():
    hook_input = json.load(sys.stdin)
    cwd = hook_input.get("cwd") or os.getcwd()
    project_label = os.path.basename(os.path.normpath(cwd))

    secret, base_url = load_config()
    context_lines = [f"[session-registry] project_label: {project_label}"]

    if not secret:
        context_lines.append("(TELEGRAM_TOKEN_RHAPSODY не найден - реестр сессий недоступен)")
        emit(context_lines)
        return

    watch_log = f"/tmp/claude_watch_{project_label}.log"

    if os.path.isfile(watch_log):
        os.remove(watch_log)

    if os.path.isfile(SESSION_UUID_PATH):
        with open(SESSION_UUID_PATH, "r", encoding="utf-8") as f:
            session_uuid = f.read().strip()
        try:
            api_call_retry("POST", "/telegram-app/claude/session/resume", secret, base_url,
                           body={"session_uuid": session_uuid})
            activate_session(session_uuid)
            checklist = format_status_checklist(session_status(session_uuid, secret, base_url))
            context_lines.append(
                f"Сессия session_uuid={session_uuid} автоматически возобновлена, "
                f"фоновый watch (heartbeat+inbox) уже поднят и пишет в {watch_log}.\n\n"
                f"Статус:\n{checklist}\n\n"
                "Сообщения из чата Mini App вставляются в терминал с префиксом [await_respond]. "
                "После ответа на каждое такое сообщение обязательно вызови: "
                f"`python3 .claude/hooks/session_client.py respond --session-uuid {session_uuid} "
                "--response '<твой ответ>' --notify`."
            )
            emit(context_lines)
            return
        except urllib.error.HTTPError as e:
            if e.code == 404:
                os.remove(SESSION_UUID_PATH)
                context_lines.append(
                    f"(сохранённая сессия {session_uuid} не найдена в реестре - "
                    "файл session_uuid удалён, ниже предложены варианты для нового старта)"
                )
            else:
                context_lines.append(
                    f"⚠️ ОШИБКА РЕЕСТРА СЕССИЙ: не удалось возобновить сессию {session_uuid} "
                    f"после 60 секунд ожиданий: {e}\n"
                    "ИНСТРУКЦИЯ АГЕНТУ: сразу сообщи пользователю об этой ошибке — сессия не стартовала. "
                    "Предложи перезапустить Claude Code, когда сервер будет доступен."
                )
                emit(context_lines)
                return
        except Exception as e:
            context_lines.append(
                f"⚠️ ОШИБКА РЕЕСТРА СЕССИЙ: не удалось возобновить сессию {session_uuid} "
                f"после 60 секунд ожиданий: {e}\n"
                "ИНСТРУКЦИЯ АГЕНТУ: сразу сообщи пользователю об этой ошибке — сессия не стартовала. "
                "Предложи перезапустить Claude Code, когда сервер будет доступен."
            )
            emit(context_lines)
            return

    try:
        result = api_call_retry("GET", "/telegram-app/claude/sessions", secret, base_url,
                                params={"project_label": project_label})
        sessions = result.get("result", [])
    except Exception as e:
        context_lines.append(f"(не удалось получить список зарегистрированных сессий: {e})")
        emit(context_lines)
        return

    if sessions:
        context_lines.append("Найдены ранее зарегистрированные сессии для этого проекта:")
        for s in sessions:
            context_lines.append(
                f"- id={s['id']} role={s['role']} status={s['status']} "
                f"closed_at={s.get('closed_at')} summary={s.get('summary') or '(нет)'} "
                f"session_uuid={s['session_uuid']}"
            )
        context_lines.append(
            "\nИНСТРУКЦИЯ АГЕНТУ: спроси пользователя через AskUserQuestion, какую из этих сессий "
            "продолжить (кратко покажи роль/дату закрытия/summary по каждой), либо создать новую. "
            "При выборе существующей - вызови `python3 .claude/hooks/session_client.py resume "
            "--session-uuid <session_uuid>`. При выборе 'создать новую' - уточни роль (пока только "
            "'developer') и вызови `python3 .claude/hooks/session_client.py register --role <роль> "
            f"--project-label {project_label}`. Обе команды сами сохраняют session_uuid и "
            f"поднимают фоновый watch, пишущий в /tmp/claude_watch_{project_label}.log.\n"
            "После регистрации/резюме: сообщения из чата Mini App будут вставляться в терминал "
            "с префиксом [await_respond] — после ответа вызывай "
            "`python3 .claude/hooks/session_client.py respond --session-uuid <uuid> "
            "--response '<ответ>' --notify`."
        )
    else:
        context_lines.append(
            "Зарегистрированных сессий для этого проекта нет.\n"
            "ИНСТРУКЦИЯ АГЕНТУ: спроси пользователя через AskUserQuestion, под какой ролью создать "
            "новую сессию (пока только 'developer'), затем вызови "
            "`python3 .claude/hooks/session_client.py register --role <роль> "
            f"--project-label {project_label}` - сама сохранит session_uuid и поднимет watch, "
            f"пишущий в /tmp/claude_watch_{project_label}.log.\n"
            "После регистрации: сообщения из чата Mini App будут вставляться в терминал "
            "с префиксом [await_respond] — после ответа вызывай "
            "`python3 .claude/hooks/session_client.py respond --session-uuid <uuid> "
            "--response '<ответ>' --notify`."
        )

    emit(context_lines)


if __name__ == "__main__":
    main()

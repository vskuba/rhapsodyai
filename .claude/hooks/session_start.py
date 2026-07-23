#!/usr/bin/env python3
"""
SessionStart hook - при старте новой (не resume/clear/compact) сессии Claude
Code достает из реестра ai_claude_session_registry список сессий для текущего
проекта и инжектит их в контекст. Сам интерактивный выбор ("резюмировать
такую-то" или "создать новую под ролью X") делает уже агент через
AskUserQuestion, следуя инструкции в additionalContext - хук сам ничего не
выбирает, только гарантированно доставляет данные. См.
.claude/docs/claude_session_registry.md
"""

import json
import os
import sys
import urllib.error
import urllib.request

from session_tool import load_config


def main():
    hook_input = json.load(sys.stdin)
    cwd = hook_input.get("cwd") or os.getcwd()
    project_label = os.path.basename(os.path.normpath(cwd))

    secret, base_url = load_config()

    context_lines = [f"[session-registry] project_label: {project_label}"]

    sessions = None
    if secret:
        try:
            req = urllib.request.Request(
                f"{base_url}/telegram-app/claude/sessions?project_label={project_label}",
                headers={"X-Claude-Secret": secret},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                sessions = json.load(resp).get("result", [])
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            context_lines.append(f"(не удалось получить список зарегистрированных сессий: {e})")
    else:
        context_lines.append("(TELEGRAM_TOKEN_RHAPSODY не найден - реестр сессий недоступен)")

    if sessions is not None:
        if sessions:
            context_lines.append("Найдены ранее зарегистрированные сессии для этого проекта:")
            for s in sessions:
                context_lines.append(
                    f"- id={s['id']} role={s['role']} status={s['status']} "
                    f"closed_at={s.get('closed_at')} summary={s.get('summary') or '(нет)'} "
                    f"session_uuid={s['session_uuid']}"
                )
            context_lines.append(
                "\nИНСТРУКЦИЯ АГЕНТУ: спроси пользователя через AskUserQuestion, какую из этих "
                "сессий продолжить (кратко покажи роль/дату закрытия/summary по каждой), либо "
                "создать новую. При выборе существующей - вызови "
                "`python3 .claude/hooks/session_client.py resume --session-uuid <session_uuid>` "
                "(секрет и URL берёт из .env/.env.local сам, ничего передавать не нужно), подтяни "
                "вернувшуюся историю сообщений как контекст своей работы. При выборе 'создать "
                "новую' - уточни роль (пока только 'developer') и вызови "
                "`python3 .claude/hooks/session_client.py register --role <роль> "
                f"--project-label {project_label}`."
            )
        else:
            context_lines.append(
                "Зарегистрированных сессий для этого проекта нет.\n"
                "ИНСТРУКЦИЯ АГЕНТУ: спроси пользователя через AskUserQuestion, под какой ролью "
                "создать новую сессию (пока только 'developer'), затем вызови "
                "`python3 .claude/hooks/session_client.py register --role <роль> "
                f"--project-label {project_label}` (секрет и URL берёт из .env/.env.local сам)."
            )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(context_lines),
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()

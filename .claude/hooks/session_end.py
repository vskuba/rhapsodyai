#!/usr/bin/env python3
"""
SessionEnd hook - срабатывает на осознанное завершение сессии Claude Code
(exit, /exit, clear и т.п. - см. поле "reason" в hook_input), в отличие от
краша/убийства процесса, на которые сработать физически нечему. Это и есть
разница с find_terminal_pid-защитой в session_client.py: та переживает
краш/перезапуск Claude Code (сознательное решение, см.
claude_session_registry.md §4), а этот хук - наоборот, реагирует именно на
осознанный выход, который find_terminal_pid не отличает от простого
перезапуска (шелл терминала остаётся жив в обоих случаях).

Останавливает фоновый watch для сессии этого проекта - не удаляет
.claude/session_uuid, чтобы следующий `claude` в этом же терминале
подхватил её через auto-resume (см. session_start.py) и поднял watch
заново.
"""

import json
import os
import subprocess
import sys

from session_client import SESSION_UUID_PATH


def main():
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass

    if os.path.isfile(SESSION_UUID_PATH):
        with open(SESSION_UUID_PATH, "r", encoding="utf-8") as f:
            session_uuid = f.read().strip()
        if session_uuid:
            subprocess.run(["pkill", "-f", f"session_client.py watch --session-uuid {session_uuid}"],
                            capture_output=True, timeout=3)

    sys.exit(0)


if __name__ == "__main__":
    main()

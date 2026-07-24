#!/usr/bin/env python3
"""
Stop hook — срабатывает после каждого завершённого turn-а Claude Code.

Если .claude/inbox_pending.json существует (оболочка положила его перед
инъекцией сообщения из Mini App inbox), читает последнее ассистентское
сообщение из transcript и отправляет в /telegram-app/claude/respond.
Файл inbox_pending.json удаляется сразу, чтобы повторный Stop не отправил
тот же ответ дважды.
"""

import json
import os
import sys

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(HOOK_DIR))
CLAUDE_SHELL_DIR = os.path.join(PROJECT_ROOT, "claude_code_shell")
sys.path.insert(0, CLAUDE_SHELL_DIR)
sys.path.insert(0, PROJECT_ROOT)

from claude_code_shell.session_client import api_call_retry
from claude_code_shell.session_tool import load_config

INBOX_PENDING_PATH = os.path.join(PROJECT_ROOT, "claude_code_shell", "inbox_pending.json")


def _extract_text(content) -> str | None:
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts) or None
    return None


def _last_assistant_text(transcript_path: str) -> str | None:
    if not transcript_path or not os.path.isfile(transcript_path):
        return None
    last_text = None
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Два возможных формата transcript:
            #   1. {"role": "assistant", "content": ...}
            #   2. {"type": "assistant", "message": {"role": "assistant", "content": ...}}
            role = entry.get("role") or entry.get("type")
            if role != "assistant":
                continue
            content = entry.get("content") or entry.get("message", {}).get("content")
            text = _extract_text(content)
            if text:
                last_text = text
    return last_text


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    if not os.path.isfile(INBOX_PENDING_PATH):
        sys.exit(0)

    try:
        with open(INBOX_PENDING_PATH, "r", encoding="utf-8") as f:
            pending = json.load(f)
    except Exception:
        sys.exit(0)

    os.remove(INBOX_PENDING_PATH)

    session_uuid = pending.get("session_uuid")
    inbox_id = pending.get("inbox_id")
    if not session_uuid:
        sys.exit(0)

    secret, base_url = load_config()
    if not secret:
        sys.exit(0)

    transcript_path = hook_input.get("transcript_path")
    response_text = _last_assistant_text(transcript_path) or "(ответ не найден в transcript)"

    try:
        body: dict = {
            "session_uuid": session_uuid,
            "response": response_text,
            "notify": True,
        }
        if inbox_id is not None:
            body["inbox_id"] = inbox_id
        api_call_retry("POST", "/telegram-app/claude/respond", secret, base_url, body=body)
    except Exception as e:
        sys.stderr.write(f"session_stop: respond failed: {e}\n")

    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Stop hook — срабатывает после каждого завершённого turn-а Claude Code.

Если .claude/inbox_pending.json существует (оболочка положила его перед
инъекцией сообщения из Mini App inbox), берёт ответ из hook_input
last_assistant_message и отправляет в /telegram-app/claude/respond.
Файл inbox_pending.json удаляется сразу, чтобы повторный Stop не отправил
тот же ответ дважды.
"""

import json
import os
import sys
import time

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(HOOK_DIR))
CLAUDE_SHELL_DIR = os.path.join(PROJECT_ROOT, "claude_code_shell")
sys.path.insert(0, CLAUDE_SHELL_DIR)
sys.path.insert(0, PROJECT_ROOT)

from claude_code_shell.session_client import api_call_retry
from claude_code_shell.session_tool import load_config

INBOX_PENDING_PATH = os.path.join(PROJECT_ROOT, "claude_code_shell", "inbox_pending.json")
LOG_PATH = os.path.join(PROJECT_ROOT, "claude_code_shell", "logs", "session_stop.log")


def _log(msg: str):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


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


def _last_assistant_text_from_transcript(transcript_path: str) -> str | None:
    if not transcript_path or not os.path.isfile(transcript_path):
        _log(f"  transcript not found: {transcript_path!r}")
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
            msg = entry.get("message") or entry
            if msg.get("role") != "assistant":
                continue
            text = _extract_text(msg.get("content"))
            if text:
                last_text = text
    _log(f"  transcript fallback result: {last_text is not None}")
    return last_text


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    _log(f"hook fired, inbox_pending exists={os.path.isfile(INBOX_PENDING_PATH)}")

    # Только при наличии inbox_pending.json отправляем ответ в Mini App
    if not os.path.isfile(INBOX_PENDING_PATH):
        _log("  no inbox_pending.json — skipping")
        sys.exit(0)

    try:
        with open(INBOX_PENDING_PATH, "r", encoding="utf-8") as f:
            pending = json.load(f)
        session_uuid = pending.get("session_uuid")
        inbox_id = pending.get("inbox_id")
        os.remove(INBOX_PENDING_PATH)
        _log(f"  loaded inbox_pending: session_uuid={session_uuid}, inbox_id={inbox_id}")
    except Exception as e:
        _log(f"  inbox_pending read error: {e}")
        sys.exit(0)

    if not session_uuid:
        _log("  no session_uuid in inbox_pending, exiting")
        sys.exit(0)

    secret, base_url = load_config()
    if not secret:
        _log("  no secret, exiting")
        sys.exit(0)

    # Берём ответ из hook_input напрямую, без парсинга transcript
    last_msg = hook_input.get("last_assistant_message", "")
    if isinstance(last_msg, str):
        response_text = last_msg.strip()
    else:
        response_text = _extract_text(last_msg) or ""

    if not response_text:
        _log("  last_assistant_message empty, falling back to transcript")
        transcript_path = hook_input.get("transcript_path")
        response_text = _last_assistant_text_from_transcript(transcript_path) or "(ответ не найден)"

    _log(f"  response_text preview: {response_text[:200]!r}")

    try:
        body: dict = {
            "session_uuid": session_uuid,
            "response": response_text,
            "notify": True,
        }
        if inbox_id is not None:
            body["inbox_id"] = inbox_id
        api_call_retry("POST", "/telegram-app/claude/respond", secret, base_url, body=body)
        _log("  respond API call OK")
    except Exception as e:
        _log(f"  respond API call FAILED: {e}")
        sys.stderr.write(f"session_stop: respond failed: {e}\n")

    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
claude_shell tool — DB-инструмент для вызова Claude Code из контейнера.

В контейнере uvicorn (без Claude CLI) этот инструмент отправляет промпт на
ноутбук, где крутится claude_shell.py --workflow-tool, и возвращает результат.

Используется Manager-агентом для получения детального контекста проекта
(страницы, блоки, wireframes, токены и т.д.) при составлении планов.

Использование из агента:
    claude_shell_call(
        prompt="Опиши структуру страниц проекта #{project_id}",
        use_gx10=True,
    )

Ответ — структурированный текст от Claude в headless режиме (-p).
"""

import asyncio
import json
import urllib.error
import urllib.request

# Адрес workflow-tool на ноутбуке.
# host.docker.internal работает в Docker Compose благодаря extra_hosts.
CLAUDE_SHELL_URL = "http://host.docker.internal:8999/run"
CLAUDE_SHELL_HEALTH = "http://host.docker.internal:8999/health"
CLAUDE_SHELL_SECRET = "claude-shell-workflow"
CLAUDE_SHELL_TIMEOUT = 720  # 12 минут


def _strip_ansi(text: str) -> str:
    """Убирает ANSI-коды из строки."""
    return "".join(
        c for c in text if not (ord(c) == 0x1b or  # ESC
                                (ord(c) >= 0x30 and ord(c) <= 0x3F) or
                                (ord(c) >= 0x40 and ord(c) <= 0x5F) or
                                (ord(c) >= 0x60 and ord(c) <= 0x7E)))


def claude_shell_is_available() -> bool:
    """
    Проверяет, доступен ли workflow-tool на ноутбуке.

    Returns:
        True если HTTP-сервер отвечает на /health.
    """
    try:
        req = urllib.request.Request(CLAUDE_SHELL_HEALTH, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def claude_shell_call(prompt: str, use_gx10: bool = True) -> str:
    """
    Отправляет промпт на ноутбук, запускает Claude Code в headless режиме
    (--print / -p) и возвращает результат.

    Args:
        prompt:   Промпт для Claude (может содержать контекст проекта).
        use_gx10: Использовать LiteLLM proxy (gx10) как LLM-бэкенд.

    Returns:
        Ответ Claude — структурированный текст.

    Raises:
        RuntimeError: если HTTP-запрос не удался или timeout.
    """
    payload = json.dumps({
        "prompt": prompt,
        "use_gx10": use_gx10,
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        CLAUDE_SHELL_URL,
        data=payload,
        method="POST",
        headers={
            "X-Claude-Secret": CLAUDE_SHELL_SECRET,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=CLAUDE_SHELL_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"claude_shell HTTP {e.code}: {body[:500]}")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"claude_shell недоступен по {CLAUDE_SHELL_URL}: "
            f"ноутбук или workflow-tool не запущен"
        ) from e
    except TimeoutError:
        raise RuntimeError(
            f"claude_shell timeout после {CLAUDE_SHELL_TIMEOUT}s"
        )

    status = raw.get("status", "error")
    message = raw.get("message", "")

    if status == "error":
        return f"claude_shell error: {message}"

    return message


# ── Async wrapper для вызова внутри event loop ──────────────────────────────

def claude_shell_call_async(prompt: str, use_gx10: bool = True) -> str:
    """
    Асинхронная обёртка над claude_shell_call для использования
    внутри async-контекста (run_in_executor).

    Args:
        prompt:   Промпт для Claude.
        use_gx10: Использовать LiteLLM proxy (gx10).

    Returns:
        Ответ Claude.

    Raises:
        RuntimeError: при ошибке.
    """
    return asyncio.get_event_loop().run_in_executor(
        None, claude_shell_call, prompt, use_gx10,
    )

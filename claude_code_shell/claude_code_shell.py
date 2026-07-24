#!/usr/bin/env python3
"""
claude_cli_shell.py — оболочка для запуска Claude Code с инъекцией сообщений
из inbox Mini App.

Запускает `claude` как дочерний процесс в PTY. Фоновый поток поллит inbox и
вставляет сообщения напрямую в PTY (без X11/xdotool). Умеет перезапускать
дочерний процесс при получении маркера RESTART.

Запуск:
  python3 ai_cli_shell.py
  python3 ai_cli_shell.py --register
  python3 ai_cli_shell.py --session-uuid UUID -- --resume
"""

import argparse
import json
import os
import queue
import select
import signal
import sys
import termios
import threading
import time
import tty
import urllib.error
import urllib.request

import pexpect

# ─── Константы ───────────────────────────────────────────────────────────────

SHELL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SHELL_DIR)

WRAPPER_PID_FILE = os.path.join(SHELL_DIR, "wrapper.pid")
SESSION_UUID_PATH = os.path.join(SHELL_DIR, "session_uuid")

CLEANUP_MARKER = "__SESSION_CLEANUP__"
RESTART_WATCH_MARKER = "__RESTART_WATCH__"

_WRITE_LOCK = threading.Lock()


# ─── Конфиг / HTTP ───────────────────────────────────────────────────────────

def _env_file_load(path: str) -> dict:
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


def _load_config() -> tuple[str, str]:
    for name in (".env.local", ".env"):
        path = os.path.join(PROJECT_ROOT, name)
        if os.path.isfile(path):
            env = _env_file_load(path)
            break
    else:
        env = {}
    secret = os.environ.get("TELEGRAM_TOKEN_RHAPSODY") or env.get("TELEGRAM_TOKEN_RHAPSODY", "")
    mini_app_url = os.environ.get("TELEGRAM_MINI_APP_URL") or env.get("TELEGRAM_MINI_APP_URL", "")
    base_url = mini_app_url.rsplit("/telegram-app", 1)[0] if mini_app_url else "http://localhost:8011"
    return secret, base_url


def _api_call(method: str, path: str, secret: str, base_url: str,
              params: dict = None, body: dict = None) -> dict:
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


def _api_call_retry(method, path, secret, base_url, params=None, body=None,
                    retries=12, delay=5):
    last_error = None
    for attempt in range(retries):
        try:
            return _api_call(method, path, secret, base_url, params=params, body=body)
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


# ─── Сессия ──────────────────────────────────────────────────────────────────

def _is_wrapper_running() -> bool:
    try:
        with open(WRAPPER_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def _save_session_uuid(session_uuid: str):
    os.makedirs(os.path.dirname(SESSION_UUID_PATH), exist_ok=True)
    with open(SESSION_UUID_PATH, "w", encoding="utf-8") as f:
        f.write(session_uuid)


def _cleanup_session(session_uuid: str, secret: str, base_url: str):
    try:
        _api_call_retry("POST", "/telegram-app/claude/session/cleanup-confirm",
                        secret, base_url, body={"session_uuid": session_uuid})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass
    if os.path.isfile(SESSION_UUID_PATH):
        os.remove(SESSION_UUID_PATH)


# ─── PID файл ────────────────────────────────────────────────────────────────

def _write_pid():
    os.makedirs(os.path.dirname(WRAPPER_PID_FILE), exist_ok=True)
    with open(WRAPPER_PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid():
    try:
        os.remove(WRAPPER_PID_FILE)
    except FileNotFoundError:
        pass


# ─── Оболочка ────────────────────────────────────────────────────────────────

class ClaudeShell:
    def __init__(self, session_uuid, secret, base_url, claude_args, log):
        self.session_uuid = session_uuid
        self.secret = secret
        self.base_url = base_url
        self.claude_args = claude_args
        self.log = log

        self._cmd_queue = queue.Queue()
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._child = None
        self._old_tc = None
        self._last_id = 0

    # ─── Terminal ────────────────────────────────────────────────────────────

    def _term_size(self):
        try:
            cols, rows = os.get_terminal_size()
        except OSError:
            rows, cols = 24, 80
        return rows, cols

    def _set_child_size(self):
        if self._child and self._child.isalive():
            rows, cols = self._term_size()
            self._child.setwinsize(rows, cols)

    def _raw(self):
        if sys.stdin.isatty():
            self._old_tc = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin)

    def _restore(self):
        if self._old_tc is not None:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_tc)
            except Exception:
                pass
            self._old_tc = None

    # ─── Inbox поток ─────────────────────────────────────────────────────────

    def _inbox_loop(self):
        interval = 5
        while not self._stop.is_set():
            try:
                _api_call_retry("POST", "/telegram-app/claude/session/heartbeat",
                                self.secret, self.base_url,
                                body={"session_uuid": self.session_uuid})
            except Exception:
                pass

            try:
                result = _api_call("GET", "/telegram-app/claude/session/inbox",
                                   self.secret, self.base_url,
                                   params={"session_uuid": self.session_uuid})
                rows = result.get("result") or []
                new_rows = [r for r in rows if r["id"] > self._last_id]
                if new_rows:
                    self._last_id = new_rows[-1]["id"]
                    self._process_rows(new_rows)
            except Exception as e:
                self._log(f"inbox error: {e}")

            self._stop.wait(interval)

    def _process_rows(self, rows):
        cleanup = [r for r in rows if r["content"] == CLEANUP_MARKER]
        if cleanup:
            _cleanup_session(self.session_uuid, self.secret, self.base_url)
            self._stop.set()
            return

        restart = [r for r in rows if r["content"] == RESTART_WATCH_MARKER]
        if restart:
            self._ack([r["id"] for r in restart])
            self._restart.set()

        user_rows = [r for r in rows
                     if r["content"] not in (CLEANUP_MARKER, RESTART_WATCH_MARKER)]
        if not user_rows:
            return

        for r in user_rows:
            try:
                _api_call_retry("POST", "/telegram-app/claude/respond",
                                self.secret, self.base_url,
                                body={"session_uuid": self.session_uuid,
                                      "response": "Принял",
                                      "inbox_id": r["id"],
                                      "notify": False})
            except Exception:
                pass

        if len(user_rows) == 1:
            combined = " ".join(str(user_rows[0]["content"]).split())
            last_inbox_id = user_rows[0]["id"]
        else:
            parts = [f"[{i+1}] {' '.join(str(r['content']).split())}"
                     for i, r in enumerate(user_rows)]
            combined = "Несколько сообщений:\n" + "\n".join(parts)
            last_inbox_id = user_rows[-1]["id"]

        self._write_inbox_pending(last_inbox_id)
        self._cmd_queue.put(combined)
        self._ack([r["id"] for r in user_rows])

    def _write_inbox_pending(self, inbox_id: int):
        pending_path = os.path.join(SHELL_DIR, "inbox_pending.json")
        try:
            with open(pending_path, "w", encoding="utf-8") as f:
                json.dump({"session_uuid": self.session_uuid, "inbox_id": inbox_id}, f)
        except Exception as e:
            self._log(f"inbox_pending write error: {e}")

    def _ack(self, ids):
        try:
            _api_call_retry("POST", "/telegram-app/claude/session/inbox-ack",
                            self.secret, self.base_url,
                            body={"session_uuid": self.session_uuid, "ids": ids})
        except Exception:
            pass

    # ─── Инъекция / I/O цикл ─────────────────────────────────────────────────

    def _inject(self, text: str):
        if self._child and self._child.isalive():
            data = (text + "\r").encode("utf-8")
            with _WRITE_LOCK:
                try:
                    os.write(self._child.child_fd, data)
                except OSError as e:
                    self._log(f"inject error: {e}")
            self._log(f"injected: {text[:80]!r}")

    def _spawn(self):
        rows, cols = self._term_size()
        args = self.claude_args
        if "--permission-mode" not in args:
            args = ["--permission-mode", "auto"] + args
        child = pexpect.spawn(
            "claude", args,
            dimensions=(rows, cols),
            encoding=None,
        )
        self._child = child
        self._log(f"spawned claude pid={child.pid}")
        return child

    def _io_loop(self, child):
        child_fd = child.child_fd
        stdin_fd = sys.stdin.fileno() if sys.stdin.isatty() else -1

        while not self._stop.is_set() and not self._restart.is_set():
            if not child.isalive():
                self._log("child exited")
                self._stop.set()
                break

            try:
                msg = self._cmd_queue.get_nowait()
                self._inject(msg)
            except queue.Empty:
                pass

            fds = [child_fd] + ([stdin_fd] if stdin_fd >= 0 else [])
            try:
                r, _, _ = select.select(fds, [], [], 0.05)
            except (select.error, ValueError):
                break

            if child_fd in r:
                try:
                    data = os.read(child_fd, 4096)
                    if data:
                        os.write(sys.stdout.fileno(), data)
                except OSError:
                    break

            if stdin_fd in r:
                try:
                    data = os.read(stdin_fd, 4096)
                    if data:
                        with _WRITE_LOCK:
                            os.write(child_fd, data)
                except OSError:
                    break

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        try:
            self.log.write(f"[{ts}] {msg}\n")
            self.log.flush()
        except Exception:
            pass

    # ─── Запуск ──────────────────────────────────────────────────────────────

    def run(self):
        _write_pid()

        inbox_thread = threading.Thread(target=self._inbox_loop, daemon=True)
        inbox_thread.start()

        signal.signal(signal.SIGWINCH, lambda s, f: self._set_child_size())
        signal.signal(signal.SIGTERM, lambda s, f: self._stop.set())
        signal.signal(signal.SIGHUP, lambda s, f: self._stop.set())

        self._raw()
        try:
            while not self._stop.is_set():
                self._restart.clear()
                child = self._spawn()
                self._io_loop(child)

                if child.isalive():
                    try:
                        child.terminate(force=True)
                    except Exception:
                        pass
                else:
                    child.close()

                if self._restart.is_set():
                    self._log("restarting claude...")
                    time.sleep(1.0)
                else:
                    break
        finally:
            self._restore()
            self._stop.set()
            _remove_pid()
            self._log("wrapper exited")


# ─── Инфо о сессии ───────────────────────────────────────────────────────────

def _session_info_print(session_uuid: str, mini_app_url: str):
    line = "─" * 60
    print(f"\n{line}")
    print(f"  Запущена сессия Mini App:")
    print(f"  UUID: {session_uuid}")
    print(f"  URL:  {mini_app_url}")
    print(f"{line}\n", flush=True)
    time.sleep(2)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Claude Code shell wrapper")
    parser.add_argument("--session-uuid", default=None)
    parser.add_argument("--register", action="store_true", help="Force new session")
    parser.add_argument("--project-label", default=None)
    parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    claude_args = list(args.claude_args)
    if claude_args and claude_args[0] == "--":
        claude_args = claude_args[1:]

    secret, base_url = _load_config()
    if not secret:
        sys.exit("ERROR: TELEGRAM_TOKEN_RHAPSODY not found in .env/.env.local")

    project_label = args.project_label or os.path.basename(os.path.normpath(PROJECT_ROOT))
    logs_dir = os.path.join(SHELL_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, f"claude_code_shell_{project_label}.log")
    log = open(log_path, "a")

    def _log(msg):
        log.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        log.flush()

    _log(f"wrapper started pid={os.getpid()}")

    session_uuid = args.session_uuid

    if not session_uuid and not args.register:
        if os.path.isfile(SESSION_UUID_PATH):
            with open(SESSION_UUID_PATH) as f:
                session_uuid = f.read().strip()
            try:
                _api_call_retry("POST", "/telegram-app/claude/session/resume",
                                secret, base_url,
                                body={"session_uuid": session_uuid})
                _log(f"resumed session {session_uuid}")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    session_uuid = None
                    os.remove(SESSION_UUID_PATH)
                    _log("saved session not found, registering new")
                else:
                    _log(f"resume error: {e}")
                    session_uuid = None
            except Exception as e:
                _log(f"resume error: {e}")
                session_uuid = None

    if not session_uuid:
        try:
            result = _api_call_retry("POST", "/telegram-app/claude/session/register",
                                     secret, base_url,
                                     body={"role": "developer",
                                           "project_label": project_label})
            session_uuid = result["result"]["session_uuid"]
            _save_session_uuid(session_uuid)
            _log(f"registered session {session_uuid}")
        except Exception as e:
            _log(f"register failed: {e}, running without session management")
            session_uuid = "no-session"

    mini_app_session_url = base_url + "/telegram-app"
    _session_info_print(session_uuid, mini_app_session_url)

    shell = ClaudeShell(session_uuid, secret, base_url, claude_args, log)
    shell.run()


if __name__ == "__main__":
    main()

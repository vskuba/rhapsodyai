#!/usr/bin/env python3
"""
CLI-обертка над эндпоинтами реестра сессий Claude Code.

  session_client.py register --role ROLE --project-label LABEL
  session_client.py resume --session-uuid UUID
  session_client.py heartbeat --session-uuid UUID
  session_client.py inbox --session-uuid UUID
  session_client.py respond --session-uuid UUID --response TEXT [--inbox-id N] [--no-notify]
  session_client.py finalize --session-uuid UUID [--summary TEXT]
  session_client.py watch --session-uuid UUID [--interval SECONDS] [--terminal-pid PID]
  session_client.py status --session-uuid UUID
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error

from session_tool import PROJECT_ROOT, api_call, load_config

SESSION_UUID_PATH = os.path.join(PROJECT_ROOT, ".claude", "session_uuid")

CLEANUP_MARKER = "__SESSION_CLEANUP__"
RESTART_WATCH_MARKER = "__RESTART_WATCH__"


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


def is_watch_running(session_uuid):
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"session_client.py watch --session-uuid {session_uuid}"],
            capture_output=True, timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def find_terminal_pid(start_pid):
    # Ищем шелл терминала: лидер сессии (SID == PID) с настоящим TTY.
    # Харнесс Bash создаёт изолированные сессии без TTY, поэтому начинаем
    # с текущего PID и идём вверх по дереву.
    pid = start_pid
    for _ in range(20):
        try:
            out = subprocess.run(
                ["ps", "-o", "pid=,ppid=,sid=,tty=", "-p", str(pid)],
                capture_output=True, text=True, timeout=3,
            ).stdout.strip()
        except Exception:
            return None
        if not out:
            return None
        parts = out.split()
        cur_pid, ppid, sid, tty = int(parts[0]), int(parts[1]), int(parts[2]), parts[3]
        if tty != "?" and sid == cur_pid:
            return cur_pid
        if ppid <= 1:
            return None
        pid = ppid
    return None


def _spawn_watch(session_uuid, terminal_pid=None):
    log_path = f"/tmp/claude_watch_{os.path.basename(PROJECT_ROOT)}.log"
    log_file = open(log_path, "a")
    cmd = [
        sys.executable, "-u",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_client.py"),
        "watch", "--session-uuid", session_uuid,
    ]
    if terminal_pid:
        cmd += ["--terminal-pid", str(terminal_pid)]
    subprocess.Popen(
        cmd, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True, cwd=PROJECT_ROOT,
    )


def start_watch_detached(session_uuid):
    # start_new_session=True отвязывает watch от Claude Code, но не от терминала:
    # terminal_pid позволяет watch завершиться при реальном закрытии окна.
    if is_watch_running(session_uuid):
        return
    terminal_pid = find_terminal_pid(os.getpid())
    _spawn_watch(session_uuid, terminal_pid)


def save_session_uuid(session_uuid):
    os.makedirs(os.path.dirname(SESSION_UUID_PATH), exist_ok=True)
    with open(SESSION_UUID_PATH, "w", encoding="utf-8") as f:
        f.write(session_uuid)


def activate_session(session_uuid):
    save_session_uuid(session_uuid)
    start_watch_detached(session_uuid)


def cleanup_session(session_uuid, secret, base_url):
    try:
        api_call_retry("POST", "/telegram-app/claude/session/cleanup-confirm", secret, base_url,
                       body={"session_uuid": session_uuid})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass
    if os.path.isfile(SESSION_UUID_PATH):
        os.remove(SESSION_UUID_PATH)


def _paste_to_terminal(content, terminal_pid):
    # Вставка через clipboard + xdotool. TIOCSTI отключён (legacy_tiocsti=0).
    # xdotool search --pid не находит окна PyCharm/Java, поэтому строим карту
    # pid→window_id через xprop -root _NET_CLIENT_LIST и идём вверх по дереву.
    try:
        with open(f"/proc/{terminal_pid}/environ", "rb") as ef:
            proc_env = {}
            for pair in ef.read().split(b"\x00"):
                if b"=" in pair:
                    k, v = pair.split(b"=", 1)
                    proc_env[k.decode(errors="replace")] = v.decode(errors="replace")
        display = proc_env.get("DISPLAY") or os.environ.get("DISPLAY") or ":0"
        xenv = {**os.environ, "DISPLAY": display}

        wlist_r = subprocess.run(
            ["xprop", "-root", "_NET_CLIENT_LIST"],
            capture_output=True, text=True, timeout=3, env=xenv,
        )
        pid_to_wid = {}
        for wid in re.findall(r"0x[0-9a-f]+", wlist_r.stdout):
            wp = subprocess.run(
                ["xprop", "-id", wid, "_NET_WM_PID"],
                capture_output=True, text=True, timeout=2, env=xenv,
            )
            m = re.search(r"= (\d+)", wp.stdout)
            if m:
                pid_to_wid[int(m.group(1))] = wid

        target_wid = None
        pid = terminal_pid
        for _ in range(10):
            if pid in pid_to_wid:
                target_wid = pid_to_wid[pid]
                break
            ppid_r = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(pid)],
                capture_output=True, text=True, timeout=3,
            )
            ppid = ppid_r.stdout.strip()
            if not ppid or int(ppid) <= 1:
                break
            pid = int(ppid)

        # xclip форкается: capture_output держит pipes и блокирует fork,
        # поэтому stdout/stderr → DEVNULL.
        xclip = subprocess.Popen(
            ["xclip", "-selection", "clipboard"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=xenv,
        )
        if xclip.stdin:
            xclip.stdin.write(content.encode())
            xclip.stdin.close()
        xclip.wait(timeout=3)

        if target_wid:
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", target_wid],
                env=xenv, capture_output=True, timeout=3,
            )
        subprocess.run(["xdotool", "key", "ctrl+v"], env=xenv, capture_output=True, timeout=3)
        subprocess.run(["xdotool", "key", "Return"], env=xenv, capture_output=True, timeout=3)
    except Exception:
        pass


def watch(session_uuid, secret, base_url, interval, terminal_pid=None):
    last_seen_max_id = 0
    while True:
        if terminal_pid and not os.path.exists(f"/proc/{terminal_pid}"):
            print(f"TERMINAL_CLOSED terminal_pid={terminal_pid}", flush=True)
            return
        try:
            api_call_retry("POST", "/telegram-app/claude/session/heartbeat", secret, base_url,
                           body={"session_uuid": session_uuid})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        try:
            result = api_call("GET", "/telegram-app/claude/session/inbox", secret, base_url,
                              params={"session_uuid": session_uuid})
            rows = result.get("result") or []
            new_rows = [r for r in rows if r["id"] > last_seen_max_id]
            if new_rows:
                last_seen_max_id = new_rows[-1]["id"]
                if any(r["content"] == CLEANUP_MARKER for r in new_rows):
                    cleanup_session(session_uuid, secret, base_url)
                    print("SESSION_CLEANED_UP", flush=True)
                    return
                restart_rows = [r for r in new_rows if r["content"] == RESTART_WATCH_MARKER]
                if restart_rows:
                    try:
                        api_call_retry("POST", "/telegram-app/claude/session/inbox-ack", secret, base_url,
                                       body={"session_uuid": session_uuid,
                                             "ids": [r["id"] for r in restart_rows]})
                    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                        pass
                    _spawn_watch(session_uuid, terminal_pid)
                    print("WATCH_RESTARTING", flush=True)
                    return
                user_rows = [r for r in new_rows if r["content"] != RESTART_WATCH_MARKER]
                if user_rows:
                    for r in user_rows:
                        content_flat = " ".join(str(r["content"]).split())
                        print(f"NEW_MESSAGES Message: {content_flat!r}", flush=True)
                        try:
                            api_call_retry("POST", "/telegram-app/claude/respond", secret, base_url,
                                           body={"session_uuid": session_uuid,
                                                 "response": "Принял",
                                                 "inbox_id": r["id"],
                                                 "notify": True})
                        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                            pass
                    if terminal_pid:
                        if len(user_rows) == 1:
                            message = " ".join(str(user_rows[0]["content"]).split())
                            if message.startswith('/'):
                                combined = message
                            else :
                                combined = "[await_respond] " + message
                        else:
                            parts = [f"[{i+1}] {' '.join(str(r['content']).split())}"
                                     for i, r in enumerate(user_rows)]
                            combined = "[await_respond] Несколько сообщений:\n" + "\n".join(parts)
                        _paste_to_terminal(combined, terminal_pid)
                    try:
                        api_call_retry("POST", "/telegram-app/claude/session/inbox-ack", secret, base_url,
                                       body={"session_uuid": session_uuid,
                                             "ids": [r["id"] for r in user_rows]})
                    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                        pass
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(interval)


def session_status(session_uuid, secret, base_url):
    watch_ok = is_watch_running(session_uuid)
    try:
        api_call_retry("POST", "/telegram-app/claude/session/heartbeat", secret, base_url,
                       body={"session_uuid": session_uuid})
        server_ok = True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        server_ok = False
    file_ok = os.path.isfile(SESSION_UUID_PATH) and open(SESSION_UUID_PATH).read().strip() == session_uuid
    return {"watch": watch_ok, "server": server_ok, "session_uuid_file": file_ok}


def format_status_checklist(status):
    icon = lambda ok: "🍏" if ok else "🔴"
    return (
        f"{icon(status['watch'])} watch\n"
        f"{icon(status['server'])} server\n"
        f"{icon(status['session_uuid_file'])} session_uuid_file"
    )


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

    p_watch = sub.add_parser("watch")
    p_watch.add_argument("--session-uuid", required=True)
    p_watch.add_argument("--interval", type=int, default=5)
    p_watch.add_argument("--terminal-pid", type=int, default=None)

    p_status = sub.add_parser("status")
    p_status.add_argument("--session-uuid", required=True)

    args = parser.parse_args()

    if args.command == "watch":
        watch(args.session_uuid, secret, base_url, args.interval, args.terminal_pid)
        return

    try:
        if args.command == "status":
            result = {"result": session_status(args.session_uuid, secret, base_url)}
        elif args.command == "register":
            result = api_call("POST", "/telegram-app/claude/session/register", secret, base_url,
                              body={"role": args.role, "project_label": args.project_label})
            activate_session(result["result"]["session_uuid"])
        elif args.command == "resume":
            result = api_call("POST", "/telegram-app/claude/session/resume", secret, base_url,
                              body={"session_uuid": args.session_uuid})
            activate_session(args.session_uuid)
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

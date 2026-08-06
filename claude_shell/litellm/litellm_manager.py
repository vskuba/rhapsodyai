import os
import subprocess
import sys
import time

LITELLM_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(LITELLM_DIR))
PID_FILE     = os.path.join(LITELLM_DIR, "litellm.pid")
LOG_FILE     = os.path.join(LITELLM_DIR, "litellm.log")
CONFIG_FILE  = os.path.join(LITELLM_DIR, "litellm_config.yaml")
PORT         = 4000

# Предпочитаем venv-python, где гарантированно установлен litellm
_VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python3")
PYTHON       = _VENV_PYTHON if os.path.isfile(_VENV_PYTHON) else sys.executable


def litellm_is_running() -> bool:
    import socket
    import subprocess

    # Пытаемся прочитать PID из файла
    file_pid = None
    try:
        with open(PID_FILE) as f:
            file_pid = int(f.read().strip())
        os.kill(file_pid, 0)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        file_pid = None

    # Ищем реальный PID процесса на порту
    try:
        result = subprocess.run(["ss", "-tlnp", "sport = :4000"],
                                capture_output=True, text=True, timeout=5)
        port_pid = None
        for line in result.stdout.splitlines():
            if ":4000" in line and "users:" in line:
                # Формат: pid=1234,cmd="..."
                for part in line.split("users:"):
                    for u in part.split("("):
                        if "pid=" in u:
                            port_pid = int(u.split("pid=")[1].split(",")[0])
    except Exception:
        port_pid = None

    # Если порт занят — обновляем PID-файл реальным PID и проверяем коннект
    if port_pid is not None:
        with open(PID_FILE, "w") as f:
            f.write(str(port_pid))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", PORT)) == 0

    # Порт пуст, но PID в файале жив — проверяем коннект
    if file_pid is not None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", PORT)) == 0

    return False


def litellm_start() -> None:
    if not os.path.isfile(CONFIG_FILE):
        raise FileNotFoundError(f"LiteLLM config not found: {CONFIG_FILE}")

    log = open(LOG_FILE, "a")
    proc = subprocess.Popen(
        [PYTHON, "-c",
         "from litellm.proxy.proxy_cli import run_server; import sys; "
         f"sys.argv=['litellm','--config','{CONFIG_FILE}','--port','{PORT}']; run_server()"],
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    time.sleep(2)


def litellm_ensure_running() -> int:
    if not litellm_is_running():
        litellm_start()
    return PORT

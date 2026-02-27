import os
import subprocess
import sys
from typing import Any


def os_get_service_status(service_name: str):
    """
    Проверяет статус сервиса в системе и возращает его.
    """
    try:
        # Check if the service is active
        subprocess.check_call(["systemctl", "is-active", "--quiet", service_name])
        return "active"
    except subprocess.CalledProcessError:
        try:
            # Check if the service is inactive (stopped)
            subprocess.check_call(["systemctl", "is-failed", "--quiet", service_name])
            return "failed"
        except subprocess.CalledProcessError:
            # If neither active nor failed, it might be inactive or not found
            return "inactive or not found"
    except FileNotFoundError:
        return "systemctl not found (might not be a systemd system)"


def os_current_script_close():
    """
    Завершает работу скрипта и агента.
    """
    sys.exit()


def os_env_set(key: str, value: Any):
    """
    Ложим переменные в os env
    """
    os.environ[key] = value

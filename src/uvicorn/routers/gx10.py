"""
Вкладка GX10 — мониторинг и управление локальными LLM на машине GX10.

GX10 — отдельная машина с systemd-сервисами llama.cpp и ComfyUI. uvicorn ходит
на неё по SSH (sshpass; пароль — через переменную SSHPASS, не аргументами
команды) и за один вызов снимает снапшот: статус всех юнитов и память хоста.
Статус кэшируется на GX10_STATUS_TTL секунд: фронтенд поллит каждые 3 сек,
а SSH-снапшот делается не чаще одного за TTL на весь процесс.
"""
import asyncio
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config.config import config_get
from logging_.logging_ import logger_info
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# Управляемые юниты. Новый сервис — одна строка здесь: фронтенд рисует список
# из ответа GET /api/gx10/status, хардкода во вкладке нет.
GX10_SERVICES = (
    "llama-qwen-large.service",
    "llama-qwen-medium.service",
    "llama-qwen-small.service",
    "llama-qwen-vl.service",
    "comfyui.service",
)

GX10_CONTROL_ACTIONS = ("start", "stop", "restart", "enable", "disable")

GX10_STATUS_TTL = 3
GX10_SSH_TIMEOUT = 15


class Gx10SshError(Exception):
    """Команда по SSH на GX10 завершилась ошибкой (связь, авторизация, юнит)."""


class Gx10ControlBody(BaseModel):
    unit: str
    action: str


# ── Публичный API модуля ──


@router.get("/api/gx10/status")
async def gx10_status(user=Depends(AuthChecker([AuthPermission.GX10_VIEW]))):
    """Снапшот GX10: настроенность, память хоста, статус/enable/память/адрес юнитов."""
    cfg = _gx10_config()
    if not cfg:
        return {"gx10": {"configured": False, "memory": None, "services": [], "fetched_at": None}}

    now = time.monotonic()
    if _gx10_cache_fresh(now):
        return {"gx10": _STATUS_CACHE["data"]}

    async with _STATUS_LOCK:
        # Двойная проверка: пока ждали лок, другой запрос уже снял снапшот.
        if _gx10_cache_fresh(time.monotonic()):
            return {"gx10": _STATUS_CACHE["data"]}
        try:
            snapshot = await _gx10_ssh_run(_gx10_status_command())
        except Gx10SshError as e:
            # 502 — сбой вышестоящего сервиса (как LlmProviderError): фронтенд
            # держит последние значения и показывает причину.
            raise HTTPException(status_code=502, detail=f"GX10: {e}") from e
        data = _gx10_snapshot_parse(snapshot, cfg["host"])
        data["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _STATUS_CACHE["data"] = data
        _STATUS_CACHE["at"] = time.monotonic()
        return {"gx10": data}


@router.post("/api/gx10/control")
async def gx10_control(body: Gx10ControlBody, user=Depends(AuthChecker([AuthPermission.GX10_CONTROL]))):
    """start/stop/restart/enable/disable юнита GX10. Кэш статуса сбрасывается."""
    if body.unit not in GX10_SERVICES:
        raise HTTPException(status_code=400, detail=f"unit: допустимые значения {GX10_SERVICES}")
    if body.action not in GX10_CONTROL_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action: допустимые значения {GX10_CONTROL_ACTIONS}")

    if not _gx10_config():
        missing = ", ".join(k for k in ("GX10_HOST", "GX10_USERNAME", "GX10_PASSWORD")
                            if not gx10_config_get(k))
        raise HTTPException(status_code=503, detail=f"GX10 не настроен: не заданы {missing}")

    # sudo: пользователь GX10_USERNAME не root — polkit для manage-units требует
    # аутентификации, а sudoers-правило NOPASSWD: /bin/systemctl её заменяет.
    command = f"sudo systemctl {body.action} {body.unit}"
    try:
        await _gx10_ssh_run(command)
    except Gx10SshError as e:
        raise HTTPException(status_code=502, detail=f"GX10: {e}") from e

    logger_info(f"🖥️ GX10: {command} (пользователь {user.username})")
    _STATUS_CACHE["data"] = None
    _STATUS_CACHE["at"] = 0.0
    return {"gx10": {"unit": body.unit, "action": body.action, "ok": True}}


def gx10_config_get(key: str, default: str = '') -> str:
    """GX10_* из окружения. Отдельная точка — её мокают тесты."""
    return config_get(key, default)


def gx10_status_cache_reset() -> None:
    """Сброс кэша статуса (тесты, ручные проверки)."""
    _STATUS_CACHE["data"] = None
    _STATUS_CACHE["at"] = 0.0


# ── Детали реализации ──

_STATUS_CACHE = {"data": None, "at": 0.0}
_STATUS_LOCK = asyncio.Lock()


def _gx10_config() -> dict:
    """Набор GX10_* из окружения. Нехватка любого ключа — конфигурация не задана."""
    cfg = {
        "host": _gx10_host_clean(gx10_config_get("GX10_HOST")),
        "port": gx10_config_get("GX10_PORT", "22"),
        "username": gx10_config_get("GX10_USERNAME"),
        "password": gx10_config_get("GX10_PASSWORD"),
    }
    if not cfg["host"] or not cfg["username"] or not cfg["password"]:
        return {}
    return cfg


def _gx10_host_clean(raw: str) -> str:
    """GX10_HOST могут задать как URL (http://192.168.1.2/) — обрезаем схему и путь.

    Иначе ssh получает хост «http://192.168.1.2» и падает с «Could not resolve
    hostname» — а на вкладке это выглядит как бессмысленный 502.
    """
    host = raw.strip()
    if "://" in host:
        host = host.split("://", 1)[1]
    return host.split("/", 1)[0]


def _gx10_cache_fresh(now: float) -> bool:
    return _STATUS_CACHE["data"] is not None and (now - _STATUS_CACHE["at"]) < GX10_STATUS_TTL


def _gx10_status_command() -> str:
    """Один shell-сниппет на снапшот: все юниты + память хоста.

    Формат ответа: по каждому юниту строка «S <unit> <state> <enabled> <mem|n/a|->»
    и строка «P <unit> <port>» с портом из ExecStart, дальше сырой вывод free -b
    (строка Mem: — total/used/free).

    Порт отдельной строкой, а не шестым полем «S»: MemoryCurrent у остановленного
    юнита пустой, и порт уехал бы на место памяти. ExecStart в строку не кладём
    вовсе — там пробелы и кавычки, парсить его на этой стороне нечего.

    Кавычки внутри есть только у grep-шаблона: значения systemctl пробелов и
    globs не содержат.
    """
    units = " ".join(GX10_SERVICES)
    return (
        "for u in " + units + "; do " +
        "st=$(systemctl is-active $u 2>/dev/null); " +
        "en=$(systemctl is-enabled $u 2>/dev/null); " +
        "mem=$(systemctl show -p MemoryCurrent --value $u 2>/dev/null); " +
        "echo S $u $st $en $mem; " +
        "port=$(systemctl show -p ExecStart --value $u 2>/dev/null | "
        "grep -oE '[-]{1,2}port[ =][0-9]+' | head -1 | grep -oE '[0-9]+'); " +
        "echo P $u $port; " +
        "done; " +
        "LC_ALL=C free -b"
    )


def _gx10_snapshot_parse(snapshot: str, host: str) -> dict:
    services = {unit: None for unit in GX10_SERVICES}
    ports = {}
    memory = None
    for line in snapshot.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "S" and len(parts) >= 4:
            unit, state, enabled = parts[1], parts[2], parts[3]
            raw_mem = parts[4] if len(parts) > 4 else ""
            services[unit] = {
                "unit": unit,
                "state": state or "unknown",
                "enabled": enabled or "unknown",
                "memory": int(raw_mem) if raw_mem.isdigit() else None,
            }
        elif parts[0] == "P" and len(parts) >= 3 and parts[2].isdigit():
            ports[parts[1]] = parts[2]
        elif parts[0] == "Mem:" and len(parts) >= 4:
            memory = {"total": int(parts[1]), "used": int(parts[2]), "free": int(parts[3])}
    # Юнит, которого снимок не отдал, — unknown: фронтенд покажет статус честно.
    ordered = []
    for unit in GX10_SERVICES:
        info = services[unit]
        if info is None:
            info = {"unit": unit, "state": "unknown", "enabled": "unknown", "memory": None}
        # Адрес подключения: хост берём свой (в ExecStart стоит --host 0.0.0.0,
        # показывать его человеку незачем), порт — из ExecStart юнита. Порта нет
        # (юнит без --port или его вовсе нет на машине) — адреса тоже нет.
        port = ports.get(unit)
        info["address"] = f"{host}:{port}" if port else None
        ordered.append(info)
    return {"configured": True, "memory": memory, "services": ordered}


async def _gx10_ssh_run(remote_command: str) -> str:
    """Команда на GX10 по SSH. Пароль — в SSHPASS, не в argv (правило про секреты).

    Возвращает stdout. Ненулевой код — Gx10SshError со stderr («Permission
    denied», «Unit not found» и т.п.) — она же текст ошибки для фронтенда.
    """
    cfg = _gx10_config()
    if not cfg:
        raise Gx10SshError("GX10 не настроен (GX10_HOST/GX10_USERNAME/GX10_PASSWORD)")

    env = {**os.environ, "SSHPASS": cfg["password"]}
    argv = [
        "sshpass", "-e",
        "ssh",
        "-o", "BatchMode=no",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        "-p", cfg["port"],
        cfg["username"] + "@" + cfg["host"],
        remote_command,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=GX10_SSH_TIMEOUT)
    except (asyncio.TimeoutError, OSError) as e:
        logger_info(f"❌ GX10 SSH не удалась: {type(e).__name__}: {e}")
        raise Gx10SshError(f"SSH на GX10 не удался: {type(e).__name__}") from e

    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="ignore").strip()
        if not detail:
            detail = stdout.decode("utf-8", errors="ignore").strip()
        logger_info(f"❌ GX10 SSH ({remote_command[:80]}): rc={proc.returncode} {detail[:300]}")
        raise Gx10SshError(detail or f"код {proc.returncode}")
    return stdout.decode("utf-8", errors="ignore")
"""
Юнит-тесты вкладки GX10 (src/uvicorn/routers/gx10.py).

SSH на GX10 мокнуется на уровне транспорта (gx10._gx10_ssh_run) — остальное
(парсинг systemctl/free, кэш статуса, валидация команд, права) — реальный код
роутера. Живой сервер тут не нужен: интеграционный дым-тест идёт отдельно
(прогон против :8011 после .env.local и пересборки образа).
"""
import asyncio as aio

import pytest
import httpx
from fastapi import FastAPI

from src.uvicorn.routers import gx10
from src.auth.auth_session import AuthSession

# Формат одного снапшота, который shell-сниппет отдаёт с GX10:
#   S <unit> <state> <enabled> <memory_bytes|->  (printf на каждый юнит)
#   + сырой вывод `free -b`, строка `Mem:` — total/used/free
SNAPSHOT_OK = (
    "S llama-qwen-large.service active enabled 10737418240\n"
    "S llama-qwen-small.service inactive disabled -\n"
    "S llama-qwen-vl.service failed enabled -\n"
    "S comfyui.service active disabled 5368709120\n"
    "              total        used        free      shared  buff/cache   available\n"
    "Mem:        68719476736 21474836480 47244640256 0 2000000000 40000000000\n"
    "Swap:              0           0           0\n"
)

SNAPSHOT_NO_MEMORY = (
    "S llama-qwen-large.service active enabled n/a\n"
    "              total        used        free      shared  buff/cache   available\n"
    "Mem:        68719476736 100 68719476636 0 0 68000000000\n"
)


async def _fake_user(request):
    """QA-роль — полный набор прав: и view, и control проходят AuthChecker."""
    return AuthSession(user_id=1, username="unit_test", role="qa")


@pytest.fixture
def monkey_ssh(monkeypatch):
    """Заменяет SSH-транспорт на фикстуру; отдаёт снапшот и записывает команды."""
    calls = []
    state = {"snapshot": SNAPSHOT_OK, "fail": None}

    async def fake_ssh_run(remote_command):
        calls.append(remote_command)
        if state["fail"]:
            raise gx10.Gx10SshError(state["fail"])
        return state["snapshot"]

    monkeypatch.setattr(gx10, "_gx10_ssh_run", fake_ssh_run)
    monkeypatch.setattr(gx10, "gx10_config_get", lambda key, default="": {
        "GX10_HOST": "10.0.0.42",
        "GX10_PORT": "22",
        "GX10_USERNAME": "rhapsody",
        "GX10_PASSWORD": "secret",
    }.get(key, default))
    monkeypatch.setattr("src.auth.auth.get_current_user", _fake_user)
    gx10.gx10_status_cache_reset()
    return {"calls": calls, "state": state}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr("src.auth.auth.get_current_user", _fake_user)
    application = FastAPI()
    application.include_router(gx10.router)
    return application


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gx10.test") as c:
        yield c


# ============================ GET /api/gx10/status ============================


@pytest.mark.asyncio
async def test_status_returns_all_services(client, monkey_ssh):
    r = await client.get("/api/gx10/status")
    assert r.status_code == 200
    result = r.json()["gx10"]
    assert result["configured"] is True
    units = [s["unit"] for s in result["services"]]
    assert units == list(gx10.GX10_SERVICES)
    by_unit = {s["unit"]: s for s in result["services"]}
    assert by_unit["llama-qwen-large.service"]["state"] == "active"
    assert by_unit["llama-qwen-large.service"]["enabled"] == "enabled"
    assert by_unit["llama-qwen-large.service"]["memory"] == 10737418240
    assert by_unit["llama-qwen-small.service"]["state"] == "inactive"
    assert by_unit["llama-qwen-small.service"]["memory"] is None
    assert by_unit["llama-qwen-vl.service"]["state"] == "failed"


@pytest.mark.asyncio
async def test_status_returns_host_memory(client, monkey_ssh):
    result = (await client.get("/api/gx10/status")).json()["gx10"]
    assert result["memory"] == {
        "total": 68719476736,
        "used": 21474836480,
        "free": 47244640256,
    }


@pytest.mark.asyncio
async def test_status_na_memory_is_none(client, monkey_ssh):
    monkey_ssh["state"]["snapshot"] = SNAPSHOT_NO_MEMORY
    gx10.gx10_status_cache_reset()
    result = (await client.get("/api/gx10/status")).json()["gx10"]
    assert result["services"][0]["memory"] is None


@pytest.mark.asyncio
async def test_status_caches_within_ttl(client, monkey_ssh):
    await client.get("/api/gx10/status")
    await client.get("/api/gx10/status")
    # Один SSH-снапшот на два поллинга — кэш TTL 3 сек работает.
    assert len(monkey_ssh["calls"]) == 1


@pytest.mark.asyncio
async def test_status_refetches_after_ttl(monkeypatch, client, monkey_ssh):
    monkeypatch.setattr(gx10, "GX10_STATUS_TTL", 0)
    await client.get("/api/gx10/status")
    await client.get("/api/gx10/status")
    assert len(monkey_ssh["calls"]) == 2


@pytest.mark.asyncio
async def test_status_without_config_is_not_configured(client, monkeypatch, monkey_ssh):
    monkeypatch.setattr(gx10, "gx10_config_get", lambda key, default="": default)
    gx10.gx10_status_cache_reset()
    r = await client.get("/api/gx10/status")
    assert r.status_code == 200
    assert r.json()["gx10"]["configured"] is False
    # Без конфигурации в SSH не ходим.
    assert monkey_ssh["calls"] == []


@pytest.mark.asyncio
async def test_status_ssh_failure_returns_502(client, monkey_ssh):
    monkey_ssh["state"]["fail"] = "Permission denied (publickey,password)"
    gx10.gx10_status_cache_reset()
    r = await client.get("/api/gx10/status")
    assert r.status_code == 502
    assert "Permission denied" in r.json()["detail"]


# ============================ POST /api/gx10/control ============================


@pytest.mark.asyncio
async def test_control_start_sends_systemctl(client, monkey_ssh):
    r = await client.post("/api/gx10/control", json={"unit": "comfyui.service", "action": "start"})
    assert r.status_code == 200
    assert r.json()["gx10"]["ok"] is True
    # sudo: пользователь GX10_USERNAME не root — polkit требует аутентификации,
    # а sudoers-правило <USER> ALL=(root) NOPASSWD: /bin/systemctl её заменяет.
    assert monkey_ssh["calls"][-1] == "sudo systemctl start comfyui.service"
    # После управления кэш сброшен: следующий статус пойдёт в SSH.
    await client.get("/api/gx10/status")
    assert any(c.startswith("for u in") for c in monkey_ssh["calls"])


@pytest.mark.asyncio
async def test_control_rejects_unknown_unit(client, monkey_ssh):
    r = await client.post("/api/gx10/control", json={"unit": "nginx.service", "action": "start"})
    assert r.status_code == 400
    assert monkey_ssh["calls"] == []


@pytest.mark.asyncio
async def test_control_rejects_unknown_action(client, monkey_ssh):
    r = await client.post("/api/gx10/control", json={"unit": "comfyui.service", "action": "cat"})
    assert r.status_code == 400
    assert monkey_ssh["calls"] == []


@pytest.mark.asyncio
async def test_control_ssh_failure_returns_502(client, monkey_ssh):
    monkey_ssh["state"]["fail"] = "Unit not found"
    r = await client.post("/api/gx10/control", json={"unit": "comfyui.service", "action": "start"})
    assert r.status_code == 502
    assert "Unit not found" in r.json()["detail"]


@pytest.mark.asyncio
async def test_control_without_config_returns_503(client, monkeypatch, monkey_ssh):
    monkeypatch.setattr(gx10, "gx10_config_get", lambda key, default="": default)
    r = await client.post("/api/gx10/control", json={"unit": "comfyui.service", "action": "start"})
    assert r.status_code == 503
    assert "GX10_HOST" in r.json()["detail"]


# ============================ права и транспорт ============================


def test_permissions_exist():
    from src.auth.auth_permission import AuthPermission
    assert AuthPermission.GX10_VIEW.value == "gx10:view"
    assert AuthPermission.GX10_CONTROL.value == "gx10:control"


def test_router_uses_auth_checker():
    """Оба эндпоинта прикрыты AuthChecker: без сессии/токена их не достать."""
    from src.auth.auth import AuthChecker
    protected = 0
    for route in gx10.router.routes:
        deps = [d.call for d in route.dependant.dependencies if d.call is not None]
        if any(isinstance(d, AuthChecker) for d in deps):
            protected += 1
    assert protected == 2


def test_ssh_password_not_in_argv(monkeypatch):
    """Пароль уходит в SSHPASS, а не в аргументы команды (правило про секреты)."""
    captured = {}

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"M 1 1 1\n", b"")

        async def wait(self):
            return 0

    async def fake_exec(*argv, env=None, **kwargs):
        captured["argv"] = argv
        captured["env"] = env
        return FakeProc()

    monkeypatch.setattr(gx10, "gx10_config_get", lambda key, default="": {
        "GX10_HOST": "h", "GX10_PORT": "22", "GX10_USERNAME": "u", "GX10_PASSWORD": "secret",
    }.get(key, default))
    monkeypatch.setattr(gx10.asyncio, "create_subprocess_exec", fake_exec)

    async def run():
        return await gx10._gx10_ssh_run("true")

    aio.run(run())
    argv = [str(a) for a in captured["argv"]]
    assert "secret" not in " ".join(argv)
    assert captured["env"]["SSHPASS"] == "secret"
    assert "sshpass" in argv[0]
    assert "ssh" in argv
    assert "u@h" in argv

def test_config_host_url_scheme_stripped(monkeypatch):
    """GX10_HOST могут задать как URL (http://192.168.1.2/) — схема и путь обрезаются.

    Без очистки ssh получает хост «http://192.168.1.2» и падает с
    «Could not resolve hostname» (502 на вкладке).
    """
    env = {"GX10_HOST": "http://192.168.1.2/", "GX10_PORT": "22", "GX10_USERNAME": "u", "GX10_PASSWORD": "secret"}
    monkeypatch.setattr(gx10, "gx10_config_get", lambda key, default="": env.get(key, default))
    assert gx10._gx10_config()["host"] == "192.168.1.2"


def test_config_host_plain_unchanged(monkeypatch):
    env = {"GX10_HOST": "gx10.lan", "GX10_USERNAME": "u", "GX10_PASSWORD": "secret"}
    monkeypatch.setattr(gx10, "gx10_config_get", lambda key, default="": env.get(key, default))
    assert gx10._gx10_config()["host"] == "gx10.lan"

def test_status_command_forces_c_locale_for_free():
    """На GX10 `free` печатает заголовки по локали («Память:») — без
    LC_ALL=C парсер не найдёт строку Mem: и память хоста покажет «—».
    """
    cmd = gx10._gx10_status_command()
    assert "LC_ALL=C free -b" in cmd
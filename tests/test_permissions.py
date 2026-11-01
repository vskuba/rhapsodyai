import os
import uuid

from tests.constants import TEST_AUTH
"""Permission boundary tests — non-admin users must get 403 on write operations."""
import pytest
import httpx
from typing import AsyncGenerator

pytestmark = pytest.mark.auth

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
TEST_PERM_PREFIX = "test_perm_"


@pytest.fixture
async def admin() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Полноправный клиент. ⚠ На уровне модуля: им убирают за собой оба класса."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        await client.post("/auth/login", json=TEST_AUTH)
        yield client


class TestPermissions:
    """Роль, не названная в коде, не может **ничего** — ни писать, ни читать.

    ⚠⚠ До 2026-11-01 класс назывался иначе и проверял обратное: «все не-админы
    получают view-набор». Набор доставался роли, которой нет в
    `AUTH_ROLE_PERMISSIONS`, — то есть любой, включая строку `guest` из
    публичной гостевой сессии. Теперь по умолчанию не достаётся ничего, а
    view-набор выдаётся роли поимённо (`auth_role.py`).

    Фикстура заводит роль со случайным именем, в коде не упомянутую, — то есть
    ровно тот случай. Что видит роль **из** списка, проверяет
    `TestNamedRoleCanRead` ниже: без него этот класс зеленел бы и на коде,
    который запретил всё всем.
    """

    @pytest.fixture
    async def non_admin(self, admin: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Creates a non-admin user via admin, logs in, yields client, cleans up."""
        # Create role
        role_resp = await admin.post("/role", json={"name": f"{TEST_PERM_PREFIX}role", "node_ids": []})
        assert role_resp.status_code == 200
        role_id = role_resp.json()["result"]["id"]
        # ⚠ Скелет людей знает роли **по именам**: номер остаётся только
        # для уборки роли в конце.
        role_name = f"{TEST_PERM_PREFIX}role"

        # Create user with that role
        username = f"{TEST_PERM_PREFIX}user"
        password = "TestPerm123!"
        # Pre-cleanup: remove leftover from a failed previous run
        try:
            users = ((await admin.get("/api/users")).json().get("result") or {}).get("users", [])
            for u in users:
                if u.get("username") == username:
                    await admin.delete(f"/api/users/{u['id']}")
        except Exception:
            pass

        user_resp = await admin.post("/api/users", json={
            "username": username,
            "email": f"{username}@test.local",
            "password": password,
            "role": role_name,
            "node_ids": [],
        })
        # ⚠ 201, а не 200: скелет отвечает «создано».
        assert user_resp.status_code == 201, user_resp.text
        user_id = user_resp.json()["result"]["id"]

        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
            login = await client.post("/auth/login", json={"username": username, "password": password})
            assert login.status_code == 200
            yield client

        await admin.delete(f"/api/users/{user_id}")
        await admin.delete(f"/role/{role_id}")

    # --- User write operations ---

    async def test_non_admin_cannot_create_user(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/api/users", json={
            "username": "hacked_user", "email": "h@x.com", "password": "pass1234"
        })
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_user(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/api/users/1")
        assert resp.status_code == 403

    async def test_non_admin_cannot_update_user(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.put("/api/users/1", json={"email": "h@x.com"})
        assert resp.status_code == 403

    # --- Agent write operations ---

    async def test_non_admin_cannot_create_agent(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/agent", json={"title": "Hacked", "node_id": 2})
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_agent(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/agent/1")
        assert resp.status_code == 403

    async def test_non_admin_cannot_update_agent(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.put("/agent/1", json={"title": "Hacked"})
        assert resp.status_code == 403

    # --- Node write operations ---

    async def test_non_admin_cannot_create_node(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/node", json={"name": "hacked_node"})
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_node(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/node/1")
        assert resp.status_code == 403

    # --- Workflow write operations ---

    async def test_non_admin_cannot_create_workflow(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/workflow", json={"name": "hacked", "title": "Hacked"})
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_workflow(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/workflow/1")
        assert resp.status_code == 403

    # --- Role write operations ---

    async def test_non_admin_cannot_create_role(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/role", json={"name": "hacked_role"})
        assert resp.status_code == 403

    async def test_non_admin_cannot_delete_role(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/role/1")
        assert resp.status_code == 403

    # --- Fact write operations ---

    async def test_non_admin_cannot_delete_fact(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.delete("/fact/1")
        assert resp.status_code == 403

    async def test_non_admin_cannot_update_fact(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.put("/fact/1", json={"document": "hacked"})
        assert resp.status_code == 403

    # --- Setting write operations ---

    async def test_non_admin_cannot_save_setting(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/api/setting", json={"key": "hacked_key", "value": "hacked"})
        assert resp.status_code == 403

    # --- Планирование и переменные: писать нельзя ---
    #
    # ⚠⚠ В AUTH_PERMISSIONS_DEFAULT лежали два права на ЗАПИСЬ —
    # `planning:update` и `workflow_variable:update`. Набор достаётся роли,
    # которой нет в AUTH_ROLE_PERMISSIONS, то есть **любой**, и через него
    # анонимная гостевая сессия получала 71 пишущую точку: конвейер задач,
    # слияние веток, удаление блоков дизайна. Проверок на эту пару не было
    # вовсе — файл проверял только то, чего в наборе и так нет.

    async def test_non_admin_cannot_update_planning_project(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.put("/planning/project/1", json={"title": "hacked"})
        assert resp.status_code == 403

    async def test_non_admin_cannot_start_task_pipeline(self, non_admin: httpx.AsyncClient):
        """Самое дорогое за `planning:update`: запуск конвейера и слияние ветки."""
        resp = await non_admin.post("/task/1/pipeline/start", json={})
        assert resp.status_code == 403

    async def test_non_admin_cannot_merge_task_worktree(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/task/1/worktree/merge", json={})
        assert resp.status_code == 403

    async def test_non_admin_cannot_set_team_timeout(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.post("/api/team/timeout", json={"key": "x", "value": 60})
        assert resp.status_code == 403

    async def test_non_admin_cannot_update_workflow_variable(self, non_admin: httpx.AsyncClient):
        resp = await non_admin.put("/workflow_variable/public/1", json={"value": "hacked"})
        assert resp.status_code == 403

    # --- Неназванная роль не читает тоже ---
    #
    # ⚠⚠ Раньше эти пять проверок стояли с `== 200` и назывались
    # `test_non_admin_can_*`: роль получала view-набор из пустого места. Это и
    # была дыра — тем же путём его получал анонимный гость. Чтение роли,
    # которую никто не наделял правами, теперь закрыто.

    @pytest.mark.parametrize("path", [
        "/agent/list", "/node/list", "/workflow/list", "/llm/list", "/llm/status",
    ])
    async def test_unnamed_role_cannot_read(self, non_admin: httpx.AsyncClient, path: str):
        resp = await non_admin.get(path)
        assert resp.status_code == 403, f'{path}: {resp.status_code} {resp.text[:120]}'

    async def test_unnamed_role_has_no_panel(self, non_admin: httpx.AsyncClient):
        """И в панель не входит: `panel:view` выдаётся вместе с view-набором."""
        resp = await non_admin.get("/admin/setting")
        assert resp.status_code == 403, resp.text[:120]


class TestNamedRoleCanRead:
    """Роль **из** `AUTH_ROLE_PERMISSIONS` читает и входит в панель.

    ⚠⚠ Пара к `TestPermissions`. Тот проверяет, что незнакомой роли нельзя
    ничего, — и в одиночку он зеленел бы на коде, который запретил всё и всем,
    включая живых людей панели (`nelya`, `olga`, `alena`). Здесь проверяется,
    что им по-прежнему можно: роль берём настоящую, `manager_dating`.
    """

    ROLE_NAMED = 'manager_dating'

    @pytest.fixture
    async def named(self, admin: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
        username = f'{TEST_PERM_PREFIX}named'
        password = 'TestNamed123!'

        users = ((await admin.get('/api/users')).json().get('result') or {}).get('users', [])
        for one in users:
            if one.get('username') == username:
                await admin.delete(f"/api/users/{one['id']}")

        made = await admin.post('/api/users', json={
            'username': username, 'email': f'{username}@test.local',
            'password': password, 'role': self.ROLE_NAMED, 'node_ids': [],
        })
        assert made.status_code == 201, made.text
        user_id = made.json()['result']['id']

        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=10.0) as client:
            login = await client.post('/auth/login',
                                      json={'username': username, 'password': password})
            assert login.status_code == 200, login.text
            yield client

        await admin.delete(f'/api/users/{user_id}')

    @pytest.mark.parametrize("path", [
        "/agent/list", "/node/list", "/workflow/list", "/llm/list", "/llm/status",
    ])
    async def test_named_role_reads(self, named: httpx.AsyncClient, path: str):
        resp = await named.get(path)
        assert resp.status_code == 200, f'{path}: {resp.status_code} {resp.text[:120]}'

    async def test_named_role_opens_panel(self, named: httpx.AsyncClient):
        resp = await named.get('/admin/setting')
        assert resp.status_code == 200, resp.text[:120]

    async def test_named_role_still_cannot_write(self, named: httpx.AsyncClient):
        """View-набор остаётся view: право на запись в нём по-прежнему не лежит."""
        resp = await named.post('/api/users', json={
            'username': 'hacked', 'email': 'h@x.com', 'password': 'pass1234'})
        assert resp.status_code == 403, resp.text[:120]


class TestGuestCannotWrite:
    """Анонимная гостевая сессия не пишет ничего.

    `POST /auth/guest` публичен и заводит сессию без всяких доказательств — это
    нужно публичным PWA (`/play/detective`). Роль он кладёт строкой `guest`,
    которой в таблице `role` нет, и права ей достаются из
    AUTH_PERMISSIONS_DEFAULT. Пока в том наборе лежали `planning:update` и
    `workflow_variable:update`, любой прохожий двумя запросами получал право
    слить ветку задачи и удалить блок дизайна.

    ⚠ Класс проверяет **запись**. Чтение гостю пока открыто намеренно (тот же
    набор, view-права) — сужение гостевого чтения отдельное решение, и его
    здесь не проверяют, чтобы тест не врал про то, чего нет.
    """

    @pytest.fixture
    async def guest(self, admin: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Анонимный вход — и уборка за ним.

        ⚠⚠ Учётку сносим: `/auth/guest` заводит строку в `user` на каждый зов,
        а случаев в классе восемь. Без уборки сюита копила бы по восемь мёртвых
        `guest_*` за прогон — сам себе сор, который потом ищут глазами.
        ⚠ Сносит админ: гость себя удалить не может, прав нет — ровно это класс
        и проверяет.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=10.0) as client:
            resp = await client.post("/auth/guest", json={})
            assert resp.status_code == 200, resp.text
            guest_id = resp.json()["user"]["id"]

            yield client

        await admin.delete(f"/api/users/{guest_id}")

    @pytest.mark.parametrize("method,path", [
        ("POST", "/task/1/pipeline/start"),
        ("POST", "/task/1/worktree/merge"),
        ("DELETE", "/task/1/plan/reset"),
        ("POST", "/api/team/timeout"),
        ("POST", "/api/team/parallel"),
        ("PUT", "/planning/project/1"),
        ("DELETE", "/design/widget/1"),
        ("PUT", "/workflow_variable/public/1"),
    ])
    async def test_guest_write_is_forbidden(self, guest: httpx.AsyncClient,
                                            method: str, path: str):
        """⚠ 403, а не 422: отказ обязан случиться **до** разбора тела.

        Признак дыры был ровно такой — `POST /api/team/parallel` отвечал гостю
        422 «не хватает поля project_id», то есть право уже прошло и запрос
        споткнулся лишь о пустое тело.
        """
        response = await guest.request(method, path, json={})
        assert response.status_code == 403, f'{method} {path}: {response.text}'

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/users"),
        ("GET", "/api/setting"),
        ("GET", "/api/team"),
        ("GET", "/workflow/list"),
        ("GET", "/api/backup/file"),
        ("GET", "/companion/list"),
        ("GET", "/admin/setting"),
        ("GET", "/admin/team"),
        ("POST", "/translate"),
        ("POST", "/agent/list"),
        ("POST", "/chat/message/put"),
    ])
    async def test_guest_read_is_forbidden(self, guest: httpx.AsyncClient,
                                           method: str, path: str):
        """Гость не читает и служебного.

        ⚠⚠ Всё перечисленное отдавалось ему 200. Список людей с почтой,
        настройки установки, `work_dir` и `pid` команды, перечень бэкапов,
        справочник собеседников и 36 страниц панели. Плюс `POST /translate` —
        поход в модель за наши деньги, сколько угодно раз.
        """
        response = await guest.request(method, path, json={})
        assert response.status_code == 403, f'{method} {path}: {response.text[:120]}'


class TestGuestCanPlay:
    """А вот игре гость по-прежнему нужен — и она работает.

    ⚠⚠ Пара к `TestGuestCannotWrite`, и без неё та зеленела бы на коде, где
    гостю запрещено вообще всё, — то есть на сломанном `/play/detective`.
    Пять адресов ниже — это весь список, по которым ходит
    `apps/detective/js/app.js`.

    ⚠ Коды разные и не все 200: важно, что ответ **не 403**. `422` значит
    «право прошло, не хватило тела», `404` — «право прошло, нет такого
    агента». Проверять точное тело здесь незачем: это тест доступа.
    """

    @pytest.fixture
    async def guest(self, admin: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=30.0) as client:
            resp = await client.post("/auth/guest", json={})
            assert resp.status_code == 200, resp.text
            guest_id = resp.json()["user"]["id"]

            yield client

        await admin.delete(f"/api/users/{guest_id}")

    async def test_guest_opens_case_agents(self, guest: httpx.AsyncClient):
        resp = await guest.get(f'/detective/case_agents?session_uuid={uuid.uuid4()}')
        assert resp.status_code == 200, resp.text[:120]

    async def test_guest_reads_own_history(self, guest: httpx.AsyncClient):
        resp = await guest.post('/chat/messages',
                                json={'session_uuid': str(uuid.uuid4()), 'limit': 5})
        assert resp.status_code == 200, resp.text[:120]

    async def test_guest_may_ask_agent(self, guest: httpx.AsyncClient):
        """404 «нет такого агента» — значит право прошло и дело дошло до тела."""
        resp = await guest.post('/chat/ask', json={
            'agent_id': 10 ** 7, 'question': 'проба', 'session_uuid': str(uuid.uuid4())})
        assert resp.status_code == 404, f'{resp.status_code}: {resp.text[:120]}'

    async def test_guest_may_send_voice(self, guest: httpx.AsyncClient):
        """422 «нет файла» — право прошло, споткнулась только валидация тела."""
        resp = await guest.post('/chat/voice')
        assert resp.status_code == 422, f'{resp.status_code}: {resp.text[:120]}'

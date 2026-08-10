"""
Тесты presence-пинга команды (`/api/team/*`).

Оболочка claude-shell, пока жива, раз в 30 секунд шлёт `POST /api/team/ping`
и обновляет `project_team.last_ping_at`. Страница `/admin/team` опрашивает
`GET /api/team` и красит карточки по свежести этого времени — признак «живой»
именно оно, а не колонка `status`: процесс, убитый `-9`, deactivate не пришлёт.

Оболочка знает свою роль (`--manager/--developer/--qa`), а не числовой id строки,
поэтому пинг идентифицируется ролью; `member_id` остаётся для кнопок в админке.

Тесты требуют запущенного сервера на BASE_URL и живой БД (маркер `integration`).
"""

import os
import uuid

import httpx
import pytest
from dotenv import load_dotenv

from tests.constants import TEST_AUTH

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = pytest.mark.integration


@pytest.fixture
async def client():
    """Авторизованный клиент.

    `GET /api/team` и `/api/team/types` отдают work_dir, pid и session_uuid,
    поэтому закрыты AuthChecker. Публичны только POST-ы /ping, /activate,
    /deactivate — их дёргает внешняя claude-shell без cookie.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as http_client:
        response = await http_client.post('/auth/login', json=TEST_AUTH)
        assert response.status_code == 200, f'Логин не прошёл: {response.text}'
        yield http_client


async def team_list_get(client: httpx.AsyncClient) -> list:
    response = await client.get('/api/team')
    assert response.status_code == 200, response.text
    return response.json()


async def team_member_get(client: httpx.AsyncClient, role: str) -> dict:
    members = await team_list_get(client)
    member = next((m for m in members if m['role'] == role), None)
    assert member is not None, f'В project_team нет роли {role!r}: {members}'
    return member


@pytest.fixture
async def qa_member(client):
    """Роль qa как подопытная: тесты меняют ей статус и в конце возвращают его.

    last_ping_at не восстанавливается — это отметка времени последнего пинга,
    её значение и должно двигаться.
    """
    member = await team_member_get(client, 'qa')
    yield member
    endpoint = '/api/team/activate' if member['status'] == 'active' else '/api/team/deactivate'
    await client.post(endpoint, json={'role': 'qa'})


class TestTeamList:
    """GET /api/team — то, что читает /admin/team."""

    async def test_roles_present(self, client):
        roles = {m['role'] for m in await team_list_get(client)}
        assert {'manager', 'developer', 'qa'} <= roles

    async def test_presence_fields_exposed(self, client):
        """Карточке нужны свежесть пинга и данные запущенного процесса."""
        member = await team_member_get(client, 'manager')
        for field in ('id', 'role', 'status', 'last_ping_at', 'pid',
                      'session_uuid', 'work_dir'):
            assert field in member


class TestTeamPing:
    """POST /api/team/ping — сам heartbeat."""

    async def test_ping_by_role_moves_last_ping_at(self, client, qa_member):
        """Идентификация ролью: числового id оболочка не знает."""
        before = qa_member['last_ping_at']

        response = await client.post('/api/team/ping', json={'role': 'qa'})
        assert response.status_code == 200, response.text
        assert response.json() == {'success': True, 'member_id': qa_member['id']}

        after = (await team_member_get(client, 'qa'))['last_ping_at']
        assert after is not None
        assert after != before

    async def test_ping_by_member_id(self, client, qa_member):
        """Кнопки на /admin/team шлют member_id."""
        response = await client.post('/api/team/ping',
                                     json={'member_id': qa_member['id']})
        assert response.status_code == 200, response.text
        assert response.json()['member_id'] == qa_member['id']

    async def test_session_fields_are_persisted(self, client, qa_member):
        """pid/session_uuid/work_dir из пинга видны на карточке."""
        session_uuid = str(uuid.uuid4())
        response = await client.post('/api/team/ping', json={
            'role': 'qa',
            'pid': 424242,
            'session_uuid': session_uuid,
            'work_dir': '/tmp/claude-shell-test',
        })
        assert response.status_code == 200, response.text

        member = await team_member_get(client, 'qa')
        assert member['pid'] == 424242
        assert member['session_uuid'] == session_uuid
        assert member['work_dir'] == '/tmp/claude-shell-test'

    async def test_ping_marks_active(self, client, qa_member):
        """Пинг сам по себе означает «оболочка запущена»."""
        await client.post('/api/team/deactivate', json={'role': 'qa'})
        await client.post('/api/team/ping', json={'role': 'qa'})
        assert (await team_member_get(client, 'qa'))['status'] == 'active'

    async def test_unknown_role_is_404(self, client):
        response = await client.post('/api/team/ping', json={'role': 'designer'})
        assert response.status_code == 404

    async def test_unknown_member_id_is_404(self, client):
        response = await client.post('/api/team/ping', json={'member_id': 10 ** 7})
        assert response.status_code == 404

    async def test_identity_is_required(self, client):
        """Без member_id и без role пинг некому засчитать."""
        response = await client.post('/api/team/ping', json={})
        assert response.status_code == 422


class TestActivateDeactivate:
    """Границы сессии оболочки: первый пинг и штатное завершение."""

    async def test_activate_sets_status_and_session(self, client, qa_member):
        session_uuid = str(uuid.uuid4())
        response = await client.post('/api/team/activate', json={
            'role': 'qa', 'pid': 4321, 'session_uuid': session_uuid,
        })
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'active'

        member = await team_member_get(client, 'qa')
        assert member['status'] == 'active'
        assert member['pid'] == 4321
        assert member['session_uuid'] == session_uuid
        assert member['last_ping_at'] is not None

    async def test_deactivate_clears_dead_process_data(self, client, qa_member):
        """Процесса больше нет: pid и session_uuid на карточке врали бы."""
        await client.post('/api/team/activate', json={
            'role': 'qa', 'pid': 4321, 'session_uuid': str(uuid.uuid4()),
        })

        response = await client.post('/api/team/deactivate', json={'role': 'qa'})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'inactive'

        member = await team_member_get(client, 'qa')
        assert member['status'] == 'inactive'
        assert member['pid'] is None
        assert member['session_uuid'] is None

    async def test_deactivate_keeps_work_dir(self, client, qa_member):
        """work_dir — настройка члена команды, а не след процесса."""
        await client.post('/api/team/activate', json={
            'role': 'qa', 'work_dir': '/tmp/claude-shell-test',
        })
        await client.post('/api/team/deactivate', json={'role': 'qa'})
        assert (await team_member_get(client, 'qa'))['work_dir'] == '/tmp/claude-shell-test'

    async def test_deactivate_unknown_role_is_404(self, client):
        response = await client.post('/api/team/deactivate', json={'role': 'designer'})
        assert response.status_code == 404

"""Reveal переменной сайта: `GET /api/browser/variable/{id}/reveal` — отдельное право.

Список переменных показывает секрет замазанным **всегда и для всех** — страница
опрашивает его на каждой смене сайта, и пачка паролей в ответе осела бы в журнале
прокси. Сырое значение выдаёт только эта отдельная ручка и по отдельному праву
(`browser:secret`): знать, что пароль есть, и знать сам пароль — разные вещи.
Именно эта HTTP-половина раньше не проверялась: соседний
`test_browser_site_variable.py` работает со слоем функций, а `AuthChecker` живёт
в зависимости маршрута и в таком вызове не участвует — отказ на двери проходил бы
незамеченным.

Что проверяется:
* анониму reveal закрыт, роль без прав получает 403 и на список, и на reveal;
* роль только на чтение (`manager_dating`) список видит — с маской, — а reveal ей
  запрещён: это и есть граница между `browser:view` и `browser:secret`;
* reveal полноправного возвращает значение целиком (шифрование обратимое, не хэш);
* список не отдаёт секрет открытым даже полноправному;
* переменная, заведённая через HTTP, лежит в базе шифротекстом, а не паролем.

Сайт заводится напрямую в базу и сносится в конце — переменные уходят каскадом
(`fk_bsv_site`). Модули импортируются внутри тестов: они тянут `mysql_`, который
читает `MYSQL_HOST` на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""
import os
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = [pytest.mark.browser, pytest.mark.integration]

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

TEST_SITE_NAME = '__pytest_reveal_site'
SECRET_NAME = 'password'
SECRET_VALUE = 's3cr3t-pytest-reveal'
PLAIN_NAME = 'stand'
PLAIN_VALUE = 'https://stand.example'
_DENIAL_ROLE = 'test_reveal_role'
_DENIAL_USER = 'test_reveal_user'
_DENIAL_PASSWORD = 'TestReveal123!'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def qa() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        login = await client.post('/auth/login', json=TEST_AUTH)
        assert login.status_code == 200, login.text
        yield client


@pytest.fixture
async def anon() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        yield client


@pytest.fixture
async def site_id() -> AsyncGenerator[int, None]:
    """Сайт-закладка, которому принадлежат переменные; за собой сносит всё каскадом."""
    await _drop_site()
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('INSERT INTO browser_site (name, url) VALUES (%s, %s)',
                         (TEST_SITE_NAME, 'https://stand.example'))
        site = db.lastrowid
        await db.connection.commit()

    yield site

    await _drop_site()


@pytest.fixture
async def secret_id(site_id: int) -> int:
    """Секретная переменная: ложится в базу шифротекстом, как это делает сохранение."""
    return await _seed_variable(site_id, SECRET_NAME, SECRET_VALUE, is_secret=True)


@pytest.fixture
async def plain_id(site_id: int) -> int:
    """Обычная переменная — для сравнения: её список отдаёт открытым всегда."""
    return await _seed_variable(site_id, PLAIN_NAME, PLAIN_VALUE, is_secret=False)


@pytest.fixture
async def no_right(qa: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Роль, в коде не названная, — без единого права (`auth_role.py`)."""
    await _drop_denial_users(qa)
    role_resp = await qa.post('/role', json={'name': _DENIAL_ROLE, 'node_ids': []})
    assert role_resp.status_code == 200, role_resp.text
    role_id = role_resp.json()['result']['id']

    user_resp = await qa.post('/api/users', json={
        'username': _DENIAL_USER,
        'email': f'{_DENIAL_USER}@test.local',
        'password': _DENIAL_PASSWORD,
        'role': _DENIAL_ROLE,
        'node_ids': [],
    })
    assert user_resp.status_code == 201, user_resp.text
    user_id = user_resp.json()['result']['id']

    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        login = await client.post('/auth/login',
                                 json={'username': _DENIAL_USER, 'password': _DENIAL_PASSWORD})
        assert login.status_code == 200, login.text
        yield client

    await qa.delete(f'/api/users/{user_id}')
    await qa.delete(f'/role/{role_id}')


@pytest.fixture
async def view_role(qa: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Роль с view-набором: `browser:view` есть, `browser:secret` — нет."""
    username, password = 'test_reveal_viewer', 'TestReveal123!'
    await _drop_users_named(qa, username)

    user_resp = await qa.post('/api/users', json={
        'username': username,
        'email': f'{username}@test.local',
        'password': password,
        'role': 'manager_dating',
        'node_ids': [],
    })
    assert user_resp.status_code == 201, user_resp.text
    user_id = user_resp.json()['result']['id']

    created = next((one for one in (await qa.get('/api/users')).json()['result']['users']
                    if one['id'] == user_id), None)
    if not created or created.get('role') != 'manager_dating':
        await qa.delete(f'/api/users/{user_id}')
        pytest.skip('роль manager_dating не заведена в этой установке')

    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        login = await client.post('/auth/login', json={'username': username, 'password': password})
        assert login.status_code == 200, login.text
        yield client

    await qa.delete(f'/api/users/{user_id}')


class TestRevealAuthorization:
    """Дверь reveal: право на список не даёт права на значение."""

    async def test_anonymous_cannot_reveal(self, anon: httpx.AsyncClient, secret_id: int):
        response = await anon.get(f'/api/browser/variable/{secret_id}/reveal')
        assert response.status_code in (401, 403)

    async def test_anonymous_cannot_list_variables(self, anon: httpx.AsyncClient, site_id: int):
        response = await anon.get(f'/api/browser/variable?site_id={site_id}')
        assert response.status_code in (401, 403)

    async def test_role_without_rights_denied(self, no_right: httpx.AsyncClient,
                                             site_id: int, secret_id: int):
        assert (await no_right.get(f'/api/browser/variable?site_id={site_id}')).status_code == 403
        assert (await no_right.get(f'/api/browser/variable/{secret_id}/reveal')).status_code == 403

    async def test_view_role_lists_masked_but_reveal_denied(
            self, view_role: httpx.AsyncClient, site_id: int, secret_id: int):
        # Граница двух прав: список — 200, но с маской; значение — 403.
        listing = await view_role.get(f'/api/browser/variable?site_id={site_id}')
        assert listing.status_code == 200
        assert SECRET_VALUE not in listing.text
        assert (await view_role.get(f'/api/browser/variable/{secret_id}/reveal')).status_code == 403


class TestRevealContract:
    """Сырое значение — поштучно, по отдельному праву и целиком."""

    async def test_reveal_returns_plaintext(self, qa: httpx.AsyncClient, secret_id: int):
        response = await qa.get(f'/api/browser/variable/{secret_id}/reveal')
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['id'] == secret_id
        assert body['name'] == SECRET_NAME
        assert body['value'] == SECRET_VALUE

    async def test_list_masks_secret_and_shows_plain(
            self, qa: httpx.AsyncClient, site_id: int, secret_id: int, plain_id: int):
        # Маска стоит и полноправному: список рисуется пачкой и оседает в журналах,
        # сырое значение — только reveal.
        response = await qa.get(f'/api/browser/variable?site_id={site_id}')
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['secret_ready'] is True

        by_id = {one['id']: one for one in body['items']}
        assert by_id[secret_id]['is_secret'] is True
        assert by_id[secret_id]['value'] != SECRET_VALUE
        assert SECRET_VALUE not in response.text
        assert by_id[plain_id]['value'] == PLAIN_VALUE

    async def test_reveal_unknown_variable_is_404(self, qa: httpx.AsyncClient):
        response = await qa.get('/api/browser/variable/99999999/reveal')
        assert response.status_code == 404


class TestRevealRoundTrip:
    """Заведённая через HTTP переменная: в базе шифротекст, из reveal — пароль."""

    async def test_secret_created_via_http_is_stored_encrypted(
            self, qa: httpx.AsyncClient, site_id: int):
        new_password = 'api-key-pytest-57'
        response = await qa.post('/api/browser/variable', json={
            'site_id': site_id, 'name': 'api_key', 'value': new_password, 'is_secret': True,
        })
        assert response.status_code == 200, response.text
        variable_id = response.json()['id']

        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute('SELECT value FROM browser_site_variable WHERE id = %s',
                             (variable_id,))
            stored = (await db.fetchone())['value']

        from browser_.browser_secret import BROWSER_SECRET_PREFIX

        # Дамп базы не должен содержать пароль: только шифротекст под версионной
        # меткой — по ней читающий отличает зашифрованное от открытого.
        assert stored.startswith(BROWSER_SECRET_PREFIX)
        assert new_password not in stored

        revealed = await qa.get(f'/api/browser/variable/{variable_id}/reveal')
        assert revealed.status_code == 200
        assert revealed.json()['value'] == new_password


async def _seed_variable(site_id: int, name: str, value: str, is_secret: bool) -> int:
    """Переменная сразу в базе: секрет шифруется тем же модулем, что и сохранение."""
    from browser_.browser_secret import browser_secret_encrypt
    from mysql_.mysql_ import mysql_get_db_async

    stored = browser_secret_encrypt(value) if is_secret else value
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO browser_site_variable (site_id, name, value, is_secret) '
            'VALUES (%s, %s, %s, %s)',
            (site_id, name, stored, int(is_secret)))
        variable_id = db.lastrowid
        await db.connection.commit()

    return variable_id


async def _drop_site() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM browser_site WHERE name = %s', (TEST_SITE_NAME,))
        await db.connection.commit()


async def _drop_denial_users(qa: httpx.AsyncClient) -> None:
    await _drop_users_named(qa, _DENIAL_USER)
    for one in (await qa.get('/role/list')).json()['result']:
        if one['name'] == _DENIAL_ROLE:
            await qa.delete(f"/role/{one['id']}")


async def _drop_users_named(qa: httpx.AsyncClient, username: str) -> None:
    # Предуборка остатков от предыдущего упавшего прогона.
    users = ((await qa.get('/api/users')).json().get('result') or {}).get('users', [])
    for one in users:
        if one.get('username') == username:
            await qa.delete(f"/api/users/{one['id']}")

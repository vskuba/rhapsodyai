"""Реестр сетевых прокси: `GET/POST/PUT/DELETE /api/browser/proxy` — права и пароль.

Страница реестра показывает выходы **с замазанным паролем**, а настоящий адрес с
паролем отдаёт только `GET /address` и по отдельному праву (`browser:proxy`):
знать, что выход есть, и знать, чем к нему подключаться, — разные вещи. Правка
адреса обязана сбрасывать итог проверки, иначе строка со старым `check_ip`
уезжала бы к потребителю, ведя в другое место. HTTP-половины у реестра не было
вовсе — весь контроль `AuthChecker` на этих точках оставался непроверенным.

Что проверяется:
* все шесть точек без входа — 401/403; роль без прав — 403 на любую;
* роль на чтение: список — 200, `/address` и запись — 403 (граница трёх прав);
* список не отдаёт пароль даже полноправному, `/address` — отдаёт;
* `ready` по умолчанию не выдаёт непроверенные выходы — тестовые заведены
  выключенными и непроверенными, живым потребителям они не достанутся;
* правка адреса без пароля сохраняет прежний пароль и сбрасывает `check_ok`;
* удаление: строка исчезает, повтор — 404; дубль имени — 409; неразбираемый
  адрес — 422 человеческой фразой.

Проверка выхода (`POST /{id}/check`) трогается только на мёртвом локальном
порту: соединение рвётся на рукопожатии, наружу никто не ходит. Список же согревает
кэш своего внешнего адреса (тот зовёт ipinfo.io **на сервере**, раз в полчаса) —
это поведение страницы, а не сюиты, и сторож сети сюиты его не ловит.
"""
import os
import uuid
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = [pytest.mark.browser, pytest.mark.integration]

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

PROXY_PREFIX = '__pytest_proxy_'
PROXY_USER = 'ptuser'
PROXY_PASSWORD = 'pytestsecret42'
# Порт 9 (discard) на localhost: соединение отказывает мгновенно, наружу не уходит.
DEAD_PORT = 9
_DENIAL_ROLE = 'test_proxy_role'
_DENIAL_USER = 'test_proxy_user'
_DENIAL_PASSWORD = 'TestProxy123!'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def qa() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=30.0) as client:
        login = await client.post('/auth/login', json=TEST_AUTH)
        assert login.status_code == 200, login.text
        yield client


@pytest.fixture
async def anon() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=30.0) as client:
        yield client


@pytest.fixture
async def proxy(qa: httpx.AsyncClient) -> AsyncGenerator[dict, None]:
    """Выключенный выход с мёртвым адресом: в раздачу живым он не попадёт.

    ⚠ `is_enabled=False` обязателен: база стенда общая, и включённый непроверенный
    выход мог бы попасться настоящему потребителю раньше, чем дойдёт уборка.
    """
    await _sweep(qa)
    name = f'{PROXY_PREFIX}{uuid.uuid4().hex[:8]}'
    response = await qa.post('/api/browser/proxy', json={
        'address': f'http://{PROXY_USER}:{PROXY_PASSWORD}@127.0.0.1:{DEAD_PORT}',
        'name': name, 'note': 'pytest', 'is_enabled': False,
    })
    assert response.status_code == 201, response.text
    proxy_id = response.json()['result']['id']

    yield {'id': proxy_id, 'name': name}

    await qa.delete(f'/api/browser/proxy/{proxy_id}')


@pytest.fixture
async def no_right(qa: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Роль, в коде не названная, — без единого права (`auth_role.py`)."""
    await _drop_denial(qa)
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

    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=30.0) as client:
        login = await client.post('/auth/login',
                                 json={'username': _DENIAL_USER, 'password': _DENIAL_PASSWORD})
        assert login.status_code == 200, login.text
        yield client

    await qa.delete(f'/api/users/{user_id}')
    await qa.delete(f'/role/{role_id}')


@pytest.fixture
async def view_role(qa: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Роль с view-набором: `browser:view` есть, записи и раздачи пароля — нет."""
    username, password = 'test_proxy_viewer', 'TestProxy123!'
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

    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=30.0) as client:
        login = await client.post('/auth/login', json={'username': username, 'password': password})
        assert login.status_code == 200, login.text
        yield client

    await qa.delete(f'/api/users/{user_id}')


class TestProxyAuthorization:
    """Все шесть точек реестра под входом и под правом."""

    async def test_anonymous_denied_everywhere(self, qa: httpx.AsyncClient,
                                               anon: httpx.AsyncClient, proxy: dict):
        # Тело заведомо разборабельное: до валидации не должно быть дела —
        # проверяем только дверь.
        body = {'address': f'127.0.0.1:{DEAD_PORT}', 'name': f'{PROXY_PREFIX}anon',
                'is_enabled': False}
        responses = [
            await anon.get('/api/browser/proxy'),
            await anon.get('/api/browser/proxy/address?ready=false'),
            await anon.post('/api/browser/proxy', json=body),
            await anon.put(f"/api/browser/proxy/{proxy['id']}", json=body),
            await anon.delete(f"/api/browser/proxy/{proxy['id']}"),
            await anon.post(f"/api/browser/proxy/{proxy['id']}/check"),
        ]
        for response in responses:
            assert response.status_code in (401, 403), response.request.url
        # Если какая-то точка всё же пустила анонима — её строку из базы убираем.
        await _sweep(qa)

    async def test_role_without_rights_denied(self, no_right: httpx.AsyncClient, proxy: dict):
        assert (await no_right.get('/api/browser/proxy')).status_code == 403
        assert (await no_right.get('/api/browser/proxy/address?ready=false')).status_code == 403
        create = await no_right.post('/api/browser/proxy', json={
            'address': f'127.0.0.1:{DEAD_PORT}', 'name': f'{PROXY_PREFIX}denied',
            'is_enabled': False})
        assert create.status_code == 403
        put = await no_right.put(f"/api/browser/proxy/{proxy['id']}", json={
            'address': f'127.0.0.1:{DEAD_PORT}', 'name': proxy['name'], 'is_enabled': False})
        assert put.status_code == 403
        assert (await no_right.delete(f"/api/browser/proxy/{proxy['id']}")).status_code == 403
        assert (await no_right.post(f"/api/browser/proxy/{proxy['id']}/check")).status_code == 403


class TestProxyRightsSplit:
    """Граница трёх прав у одной таблицы: смотреть, брать адрес, править."""

    async def test_view_role_lists_but_cannot_take_or_write(
            self, view_role: httpx.AsyncClient, proxy: dict):
        listing = await view_role.get('/api/browser/proxy')
        assert listing.status_code == 200
        row = _find(listing, proxy['id'])
        # Тот же список, что видит полноправный, — но пароль в нём замазан и
        # права на сырой адрес нет: `browser:proxy` и `browser:create` отдельны.
        assert PROXY_PASSWORD not in listing.text
        assert row['has_password'] is True
        assert (await view_role.get('/api/browser/proxy/address?ready=false')).status_code == 403
        write = await view_role.post('/api/browser/proxy', json={
            'address': f'127.0.0.1:{DEAD_PORT}', 'name': f'{PROXY_PREFIX}viewer_write',
            'is_enabled': False})
        assert write.status_code == 403
        erase = await view_role.delete(f"/api/browser/proxy/{proxy['id']}")
        assert erase.status_code == 403


class TestProxyMasking:
    """Пароль выходит из хранилища ровно в одну сторону — в `/address`."""

    async def test_list_hides_password(self, qa: httpx.AsyncClient, proxy: dict):
        response = await qa.get('/api/browser/proxy')
        assert response.status_code == 200, response.text
        row = _find(response, proxy['id'])
        assert row['has_password'] is True
        assert '•••' in row['url']
        assert PROXY_PASSWORD not in response.text

    async def test_address_ready_false_carries_password(self, qa: httpx.AsyncClient, proxy: dict):
        response = await qa.get('/api/browser/proxy/address?ready=false')
        assert response.status_code == 200, response.text
        row = _find(response, proxy['id'])
        # Адрес собирает сервер, экранируя логин и пароль: для наших символов
        # строка каноническая.
        assert row['url'] == f'http://{PROXY_USER}:{PROXY_PASSWORD}@127.0.0.1:{DEAD_PORT}'

    async def test_address_ready_by_default_excludes_unverified(
            self, qa: httpx.AsyncClient, proxy: dict):
        # Непроверенный выход потребителю не отдаётся: неизвестно, каким адресом
        # там увидят, а считают занятость именно по нему.
        response = await qa.get('/api/browser/proxy/address')
        assert response.status_code == 200
        assert proxy['id'] not in [one['id'] for one in response.json()['result']]


class TestProxyWrite:
    """Жизненный цикл строки: правка, удаление и отказ на неизвестном номере."""

    async def test_update_moved_address_keeps_password_and_resets_check(
            self, qa: httpx.AsyncClient, proxy: dict):
        # Строке заранее подкрашен успешный итог проверки — так видно, что правка
        # адреса его **сбрасывает**, а не оставляет годную строку, ведущую в
        # другое место.
        await _fake_checked(proxy['id'])

        response = await qa.put(f"/api/browser/proxy/{proxy['id']}", json={
            'address': f'http://{PROXY_USER}@127.0.0.1:{DEAD_PORT + 10}',
            'name': proxy['name'], 'is_enabled': False,
        })
        assert response.status_code == 200, response.text
        assert response.json()['result']['recheck'] is True

        listing = await qa.get('/api/browser/proxy')
        row = _find(listing, proxy['id'])
        assert row['check_ok'] is False
        assert row['check_ip'] == ''

        # Адрес без пароля — «не трогал»: страница показать прежний не может и
        # присылает строку без него, затирать было бы молчаливой порчей.
        address = await qa.get('/api/browser/proxy/address?ready=false')
        assert PROXY_PASSWORD in _find(address, proxy['id'])['url']

    async def test_delete_removes_then_missing(self, qa: httpx.AsyncClient, proxy: dict):
        response = await qa.delete(f"/api/browser/proxy/{proxy['id']}")
        assert response.status_code == 200, response.text
        rows = (await qa.get('/api/browser/proxy')).json()['result']
        assert proxy['id'] not in [one['id'] for one in rows]
        assert (await qa.delete(f"/api/browser/proxy/{proxy['id']}")).status_code == 404

    async def test_update_unknown_is_404(self, qa: httpx.AsyncClient):
        response = await qa.put('/api/browser/proxy/99999999', json={
            'address': f'127.0.0.1:{DEAD_PORT}', 'name': f'{PROXY_PREFIX}unknown'})
        assert response.status_code == 404

    async def test_check_unknown_is_404(self, qa: httpx.AsyncClient):
        response = await qa.post('/api/browser/proxy/99999999/check')
        assert response.status_code == 404

    async def test_unparsable_address_is_422_with_phrase(self, qa: httpx.AsyncClient):
        response = await qa.post('/api/browser/proxy', json={
            'address': 'не прокси', 'name': f'{PROXY_PREFIX}garbage', 'is_enabled': False})
        assert response.status_code == 422
        # Отказ — человеческая фраза, а не список объектов pydantic: человек
        # вставлял строку из письма провайдера.
        assert isinstance(response.json()['detail'], str)

    async def test_duplicate_name_conflicts(self, qa: httpx.AsyncClient, proxy: dict):
        response = await qa.post('/api/browser/proxy', json={
            'address': f'127.0.0.1:{DEAD_PORT + 20}', 'name': proxy['name'], 'is_enabled': False})
        assert response.status_code == 409

    async def test_check_dead_proxy_reports_not_raises(self, qa: httpx.AsyncClient, proxy: dict):
        # Проверка обязана вернуть итог, а не упасть: страница показывает серый
        # выход, а не ошибку страницы.
        response = await qa.post(f"/api/browser/proxy/{proxy['id']}/check")
        assert response.status_code == 200, response.text
        result = response.json()['result']
        assert result['id'] == proxy['id']
        assert result['ok'] is False
        assert result['error']


def _find(response, proxy_id: int) -> dict:
    """Строка реестра по номеру; нет — видимый провал, а не `StopIteration`."""
    for row in response.json()['result']:
        if row['id'] == proxy_id:
            return row
    raise AssertionError(f'выхода #{proxy_id} нет в ответе реестра')


async def _fake_checked(proxy_id: int) -> None:
    """Подкрашивает итог проверки: TEST-NET адрес заведомо чужой."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'UPDATE browser_proxy SET check_ok = 1, check_ip = %s, check_error = %s '
            'WHERE id = %s', ('203.0.113.9', '', proxy_id))
        await db.connection.commit()


async def _sweep(qa: httpx.AsyncClient) -> None:
    """Убирает выходы прошлых прогонов: имя в таблице уникально, мусор помешает."""
    for row in (await qa.get('/api/browser/proxy')).json()['result']:
        if row['name'].startswith(PROXY_PREFIX):
            await qa.delete(f"/api/browser/proxy/{row['id']}")


async def _drop_denial(qa: httpx.AsyncClient) -> None:
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

"""Люди панели: заведение, чтение, правка, удаление.

Ручки живут в общем скелете (`py_modules/panel_/panel_user_api.py`, страница
`.claude/docs-common/panel.md`), а столбцы этой установки — почта и связи с
узлами — приезжают туда швом `extra_fields`.

## ⚠ Что сменилось вместе с переездом

* путь `/user*` → `/api/users*`, список лежит под `result.users`;
* роль задаётся **именем**, а не `role_id`: правами ведает каталог, и он знает
  роли по именам (номер остаётся внутри хранилища);
* заведение отвечает **201**, а не 200;
* **пароль обязателен** — учётка без него не может войти, и заводить такую
  незачем;
* роль обязана существовать: прежде человек заводился и без роли.

## ⚠⚠ Тесты убирают за собой

Прежде не убирали, и повторный прогон падал «такое имя уже занято»: учётки с
прошлого раза оставались в базе. Фикстура `made` помнит заведённых и сносит их в
конце — в том числе когда тест упал на середине.
"""
import os
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = pytest.mark.auth

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

# Роль для подопытных. ⚠ Именем: номер остаётся делом хранилища.
TEST_ROLE = 'manager_dating'
TEST_ROLE_FULL = 'admin'

# Пароль подопытных. ⚠ Не короче восьми знаков — скелет короче не принимает.
TEST_PASSWORD = 'TestCrud123!'


class TestUserCRUD:
    """Полный круг работы с учёткой."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=10.0) as client:
            await client.post('/auth/login', json=TEST_AUTH)
            yield client

    @pytest.fixture
    async def made(self, client: httpx.AsyncClient) -> AsyncGenerator[list, None]:
        """Заводилка учёток, которая прибирает за собой.

        ⚠ Убирает **и при падении теста**: иначе следующий прогон спотыкается о
        занятое имя, и красным становится не то, что сломалось.
        """
        ids: list = []

        async def make(username: str, **fields) -> dict:
            payload = {'username': username, 'password': TEST_PASSWORD,
                       'role': TEST_ROLE, 'email': f'{username}@example.com'}
            payload.update(fields)

            # Хвост прошлого прогона мешает заведению — убираем его молча.
            listed = (await client.get('/api/users')).json()['result']['users']
            for one in listed:
                if one['username'] == username:
                    await client.delete(f'/api/users/{one["id"]}')

            got = await client.post('/api/users', json=payload)
            assert got.status_code == 201, got.text
            user = got.json()['result']
            ids.append(user['id'])

            return user

        yield make

        for user_id in ids:
            await client.delete(f'/api/users/{user_id}')

    async def test_get_user_list(self, client: httpx.AsyncClient):
        """Список людей. ⚠ Лежит под `users`: форма общего скелета."""
        response = await client.get('/api/users')

        assert response.status_code == 200
        assert isinstance(response.json()['result']['users'], list)

    async def test_create_user(self, made):
        user = await made('test_user_crud')

        assert user['username'] == 'test_user_crud'
        assert user['email'] == 'test_user_crud@example.com'
        assert user['role'] == TEST_ROLE
        assert 'id' in user

    async def test_create_user_with_admin_role(self, made):
        user = await made('test_admin_crud', role=TEST_ROLE_FULL)

        assert user['role'] == TEST_ROLE_FULL

    async def test_create_user_without_password_is_rejected(
            self, client: httpx.AsyncClient):
        """⚠ Учётка без пароля не заводится: войти ею нельзя, и смысла в ней нет."""
        response = await client.post('/api/users', json={
            'username': 'test_user_nopass', 'role': TEST_ROLE})

        assert response.status_code == 422, response.text
        assert 'пароль' in response.json()['detail']

    async def test_create_user_without_role_is_rejected(
            self, client: httpx.AsyncClient):
        """⚠ Роль обязана существовать.

        Прежде человек заводился и без роли — и попадал в список с пустым
        полем, не умея ничего. Скелет такого не делает: опечатка в имени роли
        завела бы учётку, которая выглядит рабочей и не может ни одной страницы.
        """
        response = await client.post('/api/users', json={
            'username': 'test_user_norole', 'password': TEST_PASSWORD})

        assert response.status_code == 422, response.text
        assert 'роли' in response.json()['detail']

    async def test_get_user_by_id(self, client: httpx.AsyncClient, made):
        created = await made('test_user_get')

        response = await client.get(f'/api/users/{created["id"]}')

        assert response.status_code == 200
        user = response.json()['result']
        assert user['id'] == created['id']
        assert user['username'] == 'test_user_get'
        assert user['role'] == TEST_ROLE

    async def test_update_user(self, client: httpx.AsyncClient, made):
        created = await made('test_user_update')

        response = await client.put(f'/api/users/{created["id"]}', json={
            'role': TEST_ROLE_FULL, 'email': 'test_updated@example.com'})

        assert response.status_code == 200, response.text
        user = response.json()['result']
        assert user['role'] == TEST_ROLE_FULL
        assert user['email'] == 'test_updated@example.com'

    async def test_update_user_partial(self, client: httpx.AsyncClient, made):
        """Правка одной роли не трогает прочие поля."""
        created = await made('test_user_partial')

        response = await client.put(f'/api/users/{created["id"]}',
                                    json={'role': TEST_ROLE_FULL})

        assert response.status_code == 200, response.text
        user = response.json()['result']
        assert user['role'] == TEST_ROLE_FULL
        assert user['username'] == 'test_user_partial'
        assert user['email'] == 'test_user_partial@example.com'

    async def test_delete_user(self, client: httpx.AsyncClient, made):
        created = await made('test_user_delete')

        assert (await client.delete(f'/api/users/{created["id"]}')).status_code == 200
        assert (await client.get(f'/api/users/{created["id"]}')).status_code == 404

    async def test_user_node_associations(self, client: httpx.AsyncClient, made):
        """⚠ Связи с узлами — столбец **этой** установки, и он доезжает швом
        `extra_fields`: скелет про узлы не знает, а карточка их не теряет."""
        created = await made('test_user_nodes', node_ids=[2, 4])

        assert created['node_ids'] == [2, 4]

        updated = await client.put(f'/api/users/{created["id"]}',
                                   json={'node_ids': [4, 6]})
        assert updated.status_code == 200, updated.text
        assert updated.json()['result']['node_ids'] == [4, 6]

        fetched = await client.get(f'/api/users/{created["id"]}')
        assert fetched.json()['result']['node_ids'] == [4, 6]

        listed = (await client.get('/api/users')).json()['result']['users']
        found = next((one for one in listed if one['id'] == created['id']), None)
        assert found is not None
        assert found['node_ids'] == [4, 6]

    async def test_delete_nonexistent_user(self, client: httpx.AsyncClient):
        """⚠ Удаление того, чего нет, — 404 со словами, а не молчаливое «ок»."""
        response = await client.delete('/api/users/999999')

        assert response.status_code == 404

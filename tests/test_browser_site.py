"""
Сайты контейнера-браузера: закладки «имя + адрес» (`/api/browser/site`).

Проверяется контракт ручек, а не страница: карточку заводят руками один раз,
а открывают потом сотни, и молчаливо принятый адрес без схемы («example.com»)
превратился бы в сессию, которая никуда не пошла.

Требуется запущенный сервер на BASE_URL и живая БД (маркер `integration`).
"""

import os
from typing import AsyncGenerator

import httpx
import pytest
from dotenv import load_dotenv

from tests.constants import TEST_AUTH

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = pytest.mark.integration

# Имя уникально в базе, поэтому тестовое берём заведомо своё.
SITE_NAME = 'test_browser_site'
SITE_URL = 'https://example.com/login'


class TestBrowserSite:

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            await client.post('/auth/login', json=TEST_AUTH)
            yield client

    @pytest.fixture
    async def site_id(self, client: httpx.AsyncClient) -> AsyncGenerator[int, None]:
        # Хвост прошлого прогона, оборванного на середине, иначе займёт имя.
        await _cleanup(client)
        resp = await client.post('/api/browser/site', json={'name': SITE_NAME, 'url': SITE_URL})
        assert resp.status_code == 201, resp.text
        yield resp.json()['result']
        await _cleanup(client)

    async def test_created_site_is_listed(self, client: httpx.AsyncClient, site_id: int):
        rows = (await client.get('/api/browser/site')).json()['result']
        site = next((row for row in rows if row['id'] == site_id), None)

        assert site, f'сайта {site_id} нет в списке'
        assert site['name'] == SITE_NAME
        assert site['url'] == SITE_URL

    async def test_list_is_ordered_by_position(self, client: httpx.AsyncClient, site_id: int):
        """Список идёт в порядке раскладки: по нему рисуются карточки и селекты."""
        rows = (await client.get('/api/browser/site')).json()['result']
        positions = [row['position'] for row in rows]

        assert positions == sorted(positions), positions

    async def test_new_site_goes_last(self, client: httpx.AsyncClient, site_id: int):
        """Новая карточка встаёт в конец — заведение сайта не меняет выбор в селектах."""
        rows = (await client.get('/api/browser/site')).json()['result']

        assert rows[-1]['id'] == site_id, [row['name'] for row in rows]

    async def test_order_rewrites_positions(self, client: httpx.AsyncClient, site_id: int):
        """Раскладка мышью: список id сверху вниз переписывает позиции целиком."""
        rows = (await client.get('/api/browser/site')).json()['result']
        ids = [row['id'] for row in rows]
        if len(ids) < 2:
            pytest.skip('для проверки порядка нужны хотя бы два сайта')

        # Наш (последний) уезжает в начало — самый заметный сдвиг.
        moved = [site_id] + [i for i in ids if i != site_id]
        assert (await client.post('/api/browser/site/order', json={'ids': moved})).status_code == 200

        rows = (await client.get('/api/browser/site')).json()['result']
        assert [row['id'] for row in rows] == moved
        assert [row['position'] for row in rows] == list(range(1, len(moved) + 1))

        # Возвращаем прежний порядок: тест не вправе перекладывать чужие карточки.
        await client.post('/api/browser/site/order', json={'ids': ids})

    async def test_order_ignores_unknown_ids(self, client: httpx.AsyncClient, site_id: int):
        """Исчезнувший id ничего не ломает: соседняя вкладка могла удалить сайт."""
        resp = await client.post('/api/browser/site/order',
                                 json={'ids': [99999999, site_id]})

        assert resp.status_code == 200, resp.text

    async def test_url_without_scheme_rejected(self, client: httpx.AsyncClient):
        """Адрес без схемы — 422: угаданный `https://` скрыл бы опечатку."""
        resp = await client.post('/api/browser/site',
                                 json={'name': SITE_NAME + '_bad', 'url': 'example.com'})

        assert resp.status_code == 422, resp.text

    async def test_duplicate_name_conflicts(self, client: httpx.AsyncClient, site_id: int):
        """Имя уникально: карточки различают по нему.

        Текст отказа читает человек в окне правки, поэтому в нём имя, а не
        `Duplicate entry … for key` из драйвера.
        """
        resp = await client.post('/api/browser/site',
                                 json={'name': SITE_NAME, 'url': 'https://example.org'})

        assert resp.status_code == 409, resp.text
        detail = resp.json()['detail']
        assert SITE_NAME in detail and 'Duplicate' not in detail, detail

    async def test_update_rewrites_url(self, client: httpx.AsyncClient, site_id: int):
        resp = await client.put(f'/api/browser/site/{site_id}',
                                json={'name': SITE_NAME, 'url': 'https://example.org/admin'})
        assert resp.status_code == 200, resp.text

        rows = (await client.get('/api/browser/site')).json()['result']
        site = next(row for row in rows if row['id'] == site_id)
        assert site['url'] == 'https://example.org/admin'

    async def test_tags_are_normalized(self, client: httpx.AsyncClient, site_id: int):
        """Метки ложатся строчными, без пробелов и повторов.

        Отбор сравнивает строки, и `Dating`, ` dating ` и `dating` обязаны стать
        одной меткой ещё при записи — иначе сосед спросит `?tag=dating` и не найдёт
        сайт, который человек пометил с заглавной.
        """
        resp = await client.put(f'/api/browser/site/{site_id}',
                                json={'name': SITE_NAME, 'url': SITE_URL,
                                      'tags': ' Dating , VIP ,dating,'})
        assert resp.status_code == 200, resp.text

        rows = (await client.get('/api/browser/site')).json()['result']
        site = next(row for row in rows if row['id'] == site_id)
        assert site['tags'] == 'dating,vip', site['tags']

    async def test_tag_filters_the_list(self, client: httpx.AsyncClient, site_id: int):
        """`?tag=` отбирает по метке: этим DatingAi берёт себе только сайты знакомств."""
        await client.put(f'/api/browser/site/{site_id}',
                         json={'name': SITE_NAME, 'url': SITE_URL, 'tags': 'test_tag'})

        rows = (await client.get('/api/browser/site?tag=test_tag')).json()['result']

        assert [row['id'] for row in rows] == [site_id], [row['name'] for row in rows]

    async def test_untagged_site_is_out_of_tag_list(self, client: httpx.AsyncClient, site_id: int):
        """Закладка без меток не попадает ни в один `?tag=` — отбор строгий."""
        rows = (await client.get('/api/browser/site?tag=test_tag')).json()['result']

        assert all(row['id'] != site_id for row in rows), 'непомеченный сайт попал в отбор'

    async def test_unknown_tag_gives_empty_list(self, client: httpx.AsyncClient, site_id: int):
        """Незнакомая метка — пустой список, а не весь набор закладок."""
        rows = (await client.get('/api/browser/site?tag=нетакой')).json()['result']

        assert rows == [], rows

    async def test_tag_list_is_rejected(self, client: httpx.AsyncClient):
        """Несколько меток разом — 422.

        `FIND_IN_SET` с запятой внутри иглы не совпал бы ни с чем, и человек читал
        бы пустой ответ как «сайтов нет», а не как «так спрашивать нельзя».
        """
        assert (await client.get('/api/browser/site?tag=dating,vip')).status_code == 422

    async def test_update_of_missing_site_not_found(self, client: httpx.AsyncClient):
        resp = await client.put('/api/browser/site/99999999',
                                json={'name': 'нет такого', 'url': 'https://example.com'})

        assert resp.status_code == 404, resp.text

    async def test_delete_removes_site(self, client: httpx.AsyncClient, site_id: int):
        assert (await client.delete(f'/api/browser/site/{site_id}')).status_code == 200

        rows = (await client.get('/api/browser/site')).json()['result']
        assert all(row['id'] != site_id for row in rows), 'сайт остался в списке'

    async def test_list_requires_auth(self):
        """Закладки видны только вошедшему: там адреса внутренних стендов."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as guest:
            assert (await guest.get('/api/browser/site')).status_code == 401


async def _cleanup(client: httpx.AsyncClient) -> None:
    """Снести тестовые карточки — и свою, и оставшуюся от оборванного прогона."""
    rows = (await client.get('/api/browser/site')).json().get('result') or []
    for row in rows:
        if str(row.get('name', '')).startswith(SITE_NAME):
            await client.delete(f"/api/browser/site/{row['id']}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

"""Раздача файлов превью: `GET /planning/preview/{project_id}/{path}` — права и путь.

Маршрут отдаёт статику прототипов прямо с диска, а HTTP-половины у него не было
вовсе: ни проверки прав на двери, ни проверки, что путём нельзя выйти за каталог
проекта. Защита здесь — две строки в обработчике (`normpath` плюс поиск `..`), а
не файловая система; стоит их убрать — маршрутизатор становится читателем любого
файла, до которого дотянется процесс контейнера.

Что проверяется:
* на всех точках раздачи нужен вход: анониму — 401/403;
* роль без прав получает отказ даже на существующий файл; роль только на чтение
  (`manager_dating`) файлы читает, но версию прототипа удалить не может — чтение
  не должно выдавать запись;
* containment: `..` в кодировках, доходящих до сервера (открытый сворачивает сам
  клиент), и путь от корня — не отдают содержимое за пределами каталога проекта.

Файлы заводятся прямо на диске под `data/planning/<project_id>/`: в compose репозиторий
смонтирован `./:/app`, так что для сервера это тот же каталог, что `/app/data/planning`
(тот же приём, что `JS_ROOTS` в `test_workflow_dice_spec_var.py`). Всё созданное
сносится в уборке; номер проекта взят заведомо дальше реальных, чтобы уборка
случайно не снесла чужую работу.
"""
import os
import shutil
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = [pytest.mark.core, pytest.mark.integration]

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

# Номер проекта для превью произвольный: маршрутизатор видит в нём только имя
# каталога и в базу не заглядывает. Огромный — чтобы не пересечься с настоящим.
PREVIEW_PROJECT_ID = 99999999
MARKER = 'pytest_preview_marker'
_DENIAL_ROLE = 'test_preview_role'
_DENIAL_USER = 'test_preview_user'
_DENIAL_PASSWORD = 'TestPreview123!'


@pytest.fixture
async def qa() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Полноправная тестовая учётка: файлы отдаются по `planning:view`."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        login = await client.post('/auth/login', json=TEST_AUTH)
        assert login.status_code == 200, login.text
        yield client


@pytest.fixture
async def anon() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0) as client:
        yield client


@pytest.fixture
async def no_right(qa: httpx.AsyncClient) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Роль, в коде не названная, а значит без единого права (`auth_role.py`)."""
    # Предуборка остатков от предыдущего упавшего прогона.
    users = ((await qa.get('/api/users')).json().get('result') or {}).get('users', [])
    for one in users:
        if one.get('username') == _DENIAL_USER:
            await qa.delete(f"/api/users/{one['id']}")
    for one in (await qa.get('/role/list')).json()['result']:
        if one['name'] == _DENIAL_ROLE:
            await qa.delete(f"/role/{one['id']}")

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
    """Человек с правами только на чтение: видит превью, но не трогает его.

    Роль из заводского каталога, не выдуманная фикстурой: граница «чтение есть,
    записи нет» существует именно у именованных ролей. Роли нет в установке —
    тест пропускается, а не проходит молча отказом: без роли учётка была бы
    пуста, и отказывала бы не граница, а отсутствие всего.
    """
    username, password = 'test_preview_viewer', 'TestPreview123!'
    users = ((await qa.get('/api/users')).json().get('result') or {}).get('users', [])
    for one in users:
        if one.get('username') == username:
            await qa.delete(f"/api/users/{one['id']}")

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


@pytest.fixture(autouse=True)
def prototype_files():
    """Заводит файлы прототипа на диске и сносит их после теста."""
    root = _preview_root()
    os.makedirs(os.path.join(root, 'styles'), exist_ok=True)
    with open(os.path.join(root, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(f'<!DOCTYPE html><html><body><h1>{MARKER}</h1></body></html>')
    with open(os.path.join(root, 'styles', 'site.css'), 'w', encoding='utf-8') as f:
        f.write(f'/* {MARKER} */\nbody {{ color: #123456; }}\n')

    yield

    shutil.rmtree(root, ignore_errors=True)


class TestPreviewAuthorization:
    """Дверь раздачи: анониму нельзя, роль без прав — отказ, чтение ≠ запись."""

    async def test_anonymous_cannot_open_preview(self, anon: httpx.AsyncClient):
        response = await anon.get(f'/planning/preview/{PREVIEW_PROJECT_ID}/index.html')
        assert response.status_code in (401, 403)

    async def test_anonymous_cannot_download_document(self, anon: httpx.AsyncClient):
        # Тот же читательский контур: файлы и выгрузки документов — по `planning:view`.
        for url in ('/planning/document/1/download', '/planning/document/1/download/pdf'):
            assert (await anon.get(url)).status_code in (401, 403), url

    async def test_role_without_rights_denied(self, no_right: httpx.AsyncClient):
        # Файл на диске есть — значит отказывает именно право, а не 404.
        response = await no_right.get(f'/planning/preview/{PREVIEW_PROJECT_ID}/index.html')
        assert response.status_code == 403

    async def test_view_role_reads_preview(self, view_role: httpx.AsyncClient):
        # Право на чтение — полноценный доступ к раздаче: иначе зелёным выглядело
        # бы любое чрезмерное закрытие, и подмена прав прошла бы незамеченной.
        response = await view_role.get(f'/planning/preview/{PREVIEW_PROJECT_ID}/index.html')
        assert response.status_code == 200
        assert MARKER in response.text

    async def test_view_role_cannot_delete_version(self, view_role: httpx.AsyncClient):
        # Удаление версии сносит каталог с файлами — это запись, право на неё
        # отдельное (`planning:update`): читающий превью не должен уметь стирать.
        response = await view_role.delete(f'/planning/project/{PREVIEW_PROJECT_ID}/prototype/7')
        assert response.status_code == 403


class TestPreviewServing:
    """Что раздаётся своим: содержимое, тип, вживление виджета."""

    async def test_serves_index_with_widget(self, qa: httpx.AsyncClient):
        response = await qa.get(f'/planning/preview/{PREVIEW_PROJECT_ID}/index.html')
        assert response.status_code == 200
        assert MARKER in response.text
        # В html вживляется скрипт редактора с номером проекта — признак, что
        # отдаёт именно обработчик превью, а не, скажем, статика напрямую.
        assert '__PROTO_WIDGET__' in response.text
        assert str(PREVIEW_PROJECT_ID) in response.text
        assert response.headers['content-type'].startswith('text/html')

    async def test_empty_path_serves_index(self, qa: httpx.AsyncClient):
        response = await qa.get(f'/planning/preview/{PREVIEW_PROJECT_ID}/')
        assert response.status_code == 200
        assert MARKER in response.text

    async def test_serves_css_with_own_type_and_no_widget(self, qa: httpx.AsyncClient):
        response = await qa.get(f'/planning/preview/{PREVIEW_PROJECT_ID}/styles/site.css')
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/css')
        assert MARKER in response.text
        assert '__PROTO_WIDGET__' not in response.text

    async def test_missing_file_is_not_found(self, qa: httpx.AsyncClient):
        response = await qa.get(f'/planning/preview/{PREVIEW_PROJECT_ID}/no_such_page.html')
        assert response.status_code == 404


class TestPreviewPathContainment:
    """Путь не выводит за каталог проекта — ни в одной кодировке, доходящей до сервера.

    ⚠ Кодовый фильтр (`normpath` + подстрока `..`) закрывает вопрос только для
    этого обработчика, и держится он на двух строках. Тесты ловят регрессию по
    факту: содержимое `/etc/passwd` не должно приехать в ответе ни в одном виде.
    """

    async def test_encoded_traversal_blocked(self, qa: httpx.AsyncClient):
        response = await qa.get(
            f'/planning/preview/{PREVIEW_PROJECT_ID}/%2e%2e%2f%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd')
        assert response.status_code in (400, 404)
        assert b'root:' not in response.content

    async def test_dotted_slash_traversal_blocked(self, qa: httpx.AsyncClient):
        # Открытый `../` сворачивает в адресе сам клиент (и httpx, и браузер),
        # так что до сервера он доходит только в таких кодировках — дешифрует
        # их uvicorn уже в маршрутизатор, мимо `normpath` не пройти.
        response = await qa.get(
            f'/planning/preview/{PREVIEW_PROJECT_ID}/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd')
        assert response.status_code in (400, 404)
        assert b'root:' not in response.content

    async def test_deep_traversal_blocked(self, qa: httpx.AsyncClient):
        # Глубина заведомо больше вложенности каталога: иначе цепочка `../`
        # дотягивалась бы до корня контейнера, оставаясь без `..` внутри одного
        # нормализованного шага.
        response = await qa.get(f'/planning/preview/{PREVIEW_PROJECT_ID}/a/'
                                '%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd')
        assert response.status_code in (400, 404)
        assert b'root:' not in response.content

    async def test_absolute_path_stays_inside(self, qa: httpx.AsyncClient):
        # Ведущий слэш срезается (`lstrip`), и путь становится относительным
        # каталога проекта — до диска снаружи он не дотягивается.
        response = await qa.get(f'/planning/preview/{PREVIEW_PROJECT_ID}//etc/passwd')
        assert response.status_code in (400, 404)
        assert b'root:' not in response.content


def _preview_root() -> str:
    """Каталог превью на стороне сюиты: в compose он же, что `/app/data/planning`."""
    return os.path.join(os.getcwd(), 'data', 'planning', str(PREVIEW_PROJECT_ID))

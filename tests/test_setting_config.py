"""`GET /api/setting/config` — конфиг фронтенда этой установки: кого пускает и что отдаёт.

Двери у ручки две: `auth_middleware` (`main_uvicorn.py`) пропускает к роутеру только
сессию или настоящий токен доступа, а на самом роутере стоит
`AuthChecker([SETTING_VIEW])`. Состав ответа задаёт белый список
`SETTING_CONFIG_PUBLIC_KEYS` — всё, чего нет в нём, наружу не выходит: здесь сторожится
правило «секретам тут не место, всё возвращённое видно в DevTools» (`setting_config.py`).

Что проверяется:
* аноним — 401 от заставы; вошедший с правом — 200; вошедший без `setting:view` — 403
  (роль, в коде не названная, прав не имеет: `AUTH_PERMISSIONS_DEFAULT` пуст,
  `auth_role.py`);
* под `result` — ровно ключи белого списка, без дампа окружения и без ячеек
  таблицы `setting`;
* имена ключей наружу — с отрезанным префиксом `TELEGRAM_`, а читаются значения
  из переменных с полным именем;
* секреты `.env` не утекают — ни именами, ни значениями.
"""
import uuid

import pytest

from http_.http_pool import http_pool_client
from src.setting.setting_config import SETTING_CONFIG_PUBLIC_KEYS, setting_config_public
from src.uvicorn.routers.setting import setting
from tests.conftest import BASE_URL
from uvicorn_.uvicorn_panel import uvicorn_panel_client

pytestmark = [pytest.mark.core, pytest.mark.integration]

_DENIAL_PASSWORD = 'TestCfg123!'


@pytest.fixture
async def anon():
    """Посетитель без сессии и без токена — тот, кому застава отвечает на входе."""
    async with http_pool_client(base_url=BASE_URL, follow_redirects=False,
                                timeout=10) as client:
        yield client


@pytest.fixture
async def no_right(client):
    """Вошедший без единого права: роль нигде в коде не названа.

    Тот же приём, что в `test_browser_proxy_net`: неназванная роль получает
    `AUTH_PERMISSIONS_DEFAULT` — пустой (`auth_role.py`), — и `setting:view` в ней
    нет. Это ровно та разница, которую надо отличить: «точку прикрывает право»
    против «точку прикрывает любой вход».

    Имена с суффиксом: прогоны соседних выкладок делят эту базу, фиксированное
    имя столкнулось бы с чужим прогоном на создании роли.
    """
    suffix = uuid.uuid4().hex[:8]
    role_name = f'test_cfg_role_{suffix}'
    username = f'test_cfg_user_{suffix}'

    await _sweep_denials(client)

    role = await client.post('/role', json={'name': role_name, 'node_ids': []})
    assert role.status_code == 200, role.text
    role_id = role.json()['result']['id']

    user = await client.post('/api/users', json={
        'username': username,
        'email': f'{username}@test.local',
        'password': _DENIAL_PASSWORD,
        'role': role_name,
        'node_ids': [],
    })
    assert user.status_code == 201, user.text
    user_id = user.json()['result']['id']

    yield await uvicorn_panel_client(base=BASE_URL, user=username,
                                     password=_DENIAL_PASSWORD)

    # Порядок обязателен: на роль ссылается учётка, её раньше.
    await client.delete(f'/api/users/{user_id}')
    await client.delete(f'/role/{role_id}')


async def _sweep_denials(client) -> None:
    """Остатки роли и учётки от прогонов, упавших до уборки, — снять по префиксу."""
    users = ((await client.get('/api/users')).json().get('result') or {}).get('users', [])
    for one in users:
        if str(one.get('username', '')).startswith('test_cfg_user_'):
            await client.delete(f"/api/users/{one['id']}")
    for one in (await client.get('/role/list')).json().get('result') or []:
        if str(one.get('name', '')).startswith('test_cfg_role_'):
            await client.delete(f"/role/{one['id']}")


class TestAccess:
    """Кого ручка пускает: заставу и право на роутере."""

    async def test_anonymous_gets_401(self, anon):
        """Без входа — отказ заставы, а не пустой конфиг: ключи `.env` не для гостей."""
        response = await anon.get('/api/setting/config')
        assert response.status_code == 401, response.text
        # Формат отказа — `{status, message}` от заставы; `result` здесь быть не должно.
        body = response.json()
        assert body.get('status') == 'error'
        assert 'result' not in body

    async def test_logged_in_gets_config(self, client):
        """Вошедший с правом — 200 и под `result` ровно белый список ключей.

        ⚠ Сравнивается **множество**, а не «наши ключи есть»: лишняя строка здесь —
        это уже или дамп `.env`, или ячейки таблицы `setting`, чего отдавать нельзя.
        """
        response = await client.get('/api/setting/config')
        assert response.status_code == 200, response.text
        result = response.json()['result']
        assert set(result) == set(SETTING_CONFIG_PUBLIC_KEYS)
        assert all(isinstance(value, str) for value in result.values())

    async def test_role_without_setting_view_gets_403(self, no_right):
        """Вход есть, права `setting:view` нет — 403, а не 200.

        Ровно этот случай краснеет, если с роута снять `AuthChecker` или заменить
        его «просто входом»: с пустым `AUTH_PERMISSIONS_DEFAULT` неназванная роль —
        первый же проверяемый, кому конфиг показывать нельзя.
        """
        assert (await no_right.get('/api/setting/config')).status_code == 403


def test_route_holds_setting_view_dependency():
    """На роутере стоит `AuthChecker` именно с `SETTING_VIEW`.

    403 выше ловит снятую зависимость; эта строка ловит подмену права — например
    `AuthChecker([])`, который пускает всякого вошедшего.
    """
    from src.auth.auth import AuthChecker
    from src.auth.auth_permission import AuthPermission

    routes = [one for one in setting.router.routes
              if getattr(one, 'path', None) == '/api/setting/config']
    assert len(routes) == 1
    checkers = [dep.call for dep in routes[0].dependant.dependencies
                if isinstance(dep.call, AuthChecker)]
    assert len(checkers) == 1
    assert checkers[0].required_permissions == [AuthPermission.SETTING_VIEW]


# ============================ белый список и секретный фильтр ============================


def _fill_public_env(monkeypatch):
    """Публичные переменные — заданы, значения узнаваемы."""
    monkeypatch.setenv('TELEGRAM_SITE_LOGIN_REMOTE_URL', 'remote')
    monkeypatch.setenv('TELEGRAM_SITE_LOGIN_LOCAL_URL', 'local')
    monkeypatch.setenv('DEEPSEEK_HARNESS_GX10', 'gx10')


def test_all_keys_present(monkeypatch):
    _fill_public_env(monkeypatch)

    result = setting_config_public()

    assert set(result.keys()) == set(SETTING_CONFIG_PUBLIC_KEYS.keys())
    assert result["SITE_LOGIN_REMOTE_URL"] == "remote"
    assert result["SITE_LOGIN_LOCAL_URL"] == "local"
    assert result["DEEPSEEK_HARNESS_GX10"] == "gx10"


def test_unset_variable_returns_empty_string(monkeypatch):
    monkeypatch.delenv("TELEGRAM_SITE_LOGIN_REMOTE_URL", raising=False)
    monkeypatch.delenv("TELEGRAM_SITE_LOGIN_LOCAL_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_HARNESS_GX10", raising=False)

    result = setting_config_public()

    assert result["SITE_LOGIN_REMOTE_URL"] == ""
    assert result["SITE_LOGIN_LOCAL_URL"] == ""
    assert result["DEEPSEEK_HARNESS_GX10"] == ""


def test_telegram_prefix_stripped_in_key_name(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SITE_LOGIN_REMOTE_URL", "val1")
    monkeypatch.setenv("TELEGRAM_SITE_LOGIN_LOCAL_URL", "val2")
    monkeypatch.setenv("DEEPSEEK_HARNESS_GX10", "val3")

    result = setting_config_public()

    assert "SITE_LOGIN_REMOTE_URL" in result
    assert "SITE_LOGIN_LOCAL_URL" in result
    assert "DEEPSEEK_HARNESS_GX10" in result
    assert "TELEGRAM_SITE_LOGIN_REMOTE_URL" not in result
    assert "TELEGRAM_SITE_LOGIN_LOCAL_URL" not in result


def test_key_name_is_not_env_name(monkeypatch):
    """Значение читается из `TELEGRAM_…`, а не из переменной, названной по ключу.

    Имена расходятся именно из-за отрезанного префикса, и перепутать их — молча
    отдать фронту пустоту (или чужую переменную тем же именем). Заведём обе,
    с разными значениями, — и посмотрим, какую функция прочитала.
    """
    monkeypatch.setenv('TELEGRAM_SITE_LOGIN_REMOTE_URL', 'from-env')
    monkeypatch.setenv('SITE_LOGIN_REMOTE_URL', 'from-key-name')

    assert setting_config_public()['SITE_LOGIN_REMOTE_URL'] == 'from-env'


def test_no_secrets_in_public_config(monkeypatch):
    """Белый список — фильтр: всё остальное окружение в ответ не попадает.

    Один-единственный путь, которым секрет доезжает до DevTools, — регрессия
    «отдать весь `os.environ`» вместо словаря ключей. Проверяем и имена, и
    значения: подсовываем настоящие секретные переменные установки с меткой
    и требуем, чтобы ни имени, ни метки в ответе не было.
    """
    for secret in ('TELEGRAM_TOKEN_RHAPSODY', 'MYSQL_PASSWORD', 'ANTHROPIC_API_KEY'):
        monkeypatch.setenv(secret, 'do-not-leak')
    _fill_public_env(monkeypatch)

    result = setting_config_public()

    assert set(result) == set(SETTING_CONFIG_PUBLIC_KEYS)
    assert 'do-not-leak' not in str(result)

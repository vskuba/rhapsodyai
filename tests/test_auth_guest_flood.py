"""`/auth/guest`: против флуда — потолок по адресу и хеш-маркер (находка #3).

Публичная точка заводит учётку без доказательств; пентест 2026-11-02 показал,
что один клиент плодил гостей без счёта. Две оси:

* **рост таблицы** — поадресный потолок `_auth_guest_rate_ok` (скользящее окно
  в памяти процесса). Лимитируются только публичные адреса (`_auth_ip_is_public`):
  на проде внешний клиент за Caddy приходит публичным IP, а docker-мост и петля
  (и сюита) — приватные, их потолок не трогает.
* **CPU** — пароль гостя теперь короткий маркер, не bcrypt. Войти под гостя по
  паролю невозможно: `checkpw` на не-bcrypt строке даёт отказ.

⚠ Логику потолка проверяем **юнитом** на самой функции: HTTP-клиент приходит с
приватного docker-адреса, который по замыслу не лимитируется, — через него
потолок не воспроизвести. Маркер пароля — интеграционно: заводим гостя ручкой и
пробуем войти.
"""
import os
import sys

import httpx
import pytest
from dotenv import load_dotenv

sys.path.insert(0, 'py_modules')
from mysql_.mysql_query import mysql_query_run  # noqa: E402

from tests.constants import TEST_AUTH  # noqa: E402
from src.uvicorn.routers.auth import auth as auth_module  # noqa: E402

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = [pytest.mark.auth, pytest.mark.integration]


class TestRateUnit:
    """Потолок и его забор — на самой функции, без HTTP."""

    @pytest.fixture(autouse=True)
    def clean_counter(self):
        """Счётчик — глобальный словарь процесса; очищаем до и после."""
        auth_module._auth_guest_hits.clear()
        yield
        auth_module._auth_guest_hits.clear()

    def test_public_ip_is_capped(self):
        """Публичный адрес: первые MAX проходят, следующий — отказ."""
        ip = '8.8.8.8'  # реально глобальный адрес
        cap = auth_module.AUTH_GUEST_MAX_PER_IP
        allowed = [auth_module._auth_guest_rate_ok(ip) for _ in range(cap)]
        assert all(allowed), 'честные входы в пределах потолка отбиты'
        assert auth_module._auth_guest_rate_ok(ip) is False, 'потолок не сработал'

    def test_other_ip_is_independent(self):
        """Потолок одного адреса не задевает другой."""
        a, b = '8.8.8.8', '1.1.1.1'
        for _ in range(auth_module.AUTH_GUEST_MAX_PER_IP):
            auth_module._auth_guest_rate_ok(a)
        assert auth_module._auth_guest_rate_ok(a) is False
        assert auth_module._auth_guest_rate_ok(b) is True, 'чужой адрес заперт заодно'

    @pytest.mark.parametrize('ip,public', [
        ('8.8.8.8', True),
        ('1.1.1.1', True),
        # ⚠ TEST-NET (203.0.113/24) по RFC не глобальный — ipaddress это знает.
        ('203.0.113.7', False),
        ('192.168.160.1', False),   # docker gateway
        ('10.0.0.5', False),
        ('172.17.0.1', False),
        ('127.0.0.1', False),
        ('::1', False),
        ('', False),
        ('not-an-ip', False),
    ])
    def test_public_classification(self, ip, public):
        assert auth_module._auth_ip_is_public(ip) is public, ip


class TestGuestPasswordMarker:
    """Гость не входит по паролю: хранится маркер, а не bcrypt."""

    @pytest.fixture
    async def admin(self):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=10.0) as client:
            await client.post('/auth/login', json=TEST_AUTH)
            yield client

    async def test_fresh_guest_stores_marker_and_cannot_login(self, admin):
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=10.0) as client:
            resp = await client.post('/auth/guest', json={})
            assert resp.status_code == 200, resp.text
            guest = resp.json()['user']
        try:
            row = mysql_query_run('SELECT password_hash FROM user WHERE id = %s',
                                  (guest['id'],))['rows'][0]
            # ⚠ Маркер, не bcrypt: bcrypt всегда начинается с `$2`.
            assert row['password_hash'] == auth_module.AUTH_GUEST_PASSWORD_MARKER
            assert not row['password_hash'].startswith('$2'), 'в поле bcrypt-хеш'

            # Войти под гостя по паролю-маркеру нельзя.
            async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                         timeout=10.0) as anon:
                login = await anon.post('/auth/login', json={
                    'username': guest['username'],
                    'password': auth_module.AUTH_GUEST_PASSWORD_MARKER})
                assert login.status_code == 401, login.text
        finally:
            await admin.delete(f"/api/users/{guest['id']}")

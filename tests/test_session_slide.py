"""Скользящее окно сессии админки: срок считается от последнего запроса.

Проверяется то, ради чего окно и сделано:

* работающего человека сессия не выбрасывает — каждый запрос продлевает срок;
* анонимный запрос куки не заводит;
* кука обновляется **не на каждый ответ**, а не чаще раза в шаг: иначе
  `Set-Cookie` уезжал бы с каждой картинкой и каждым файлом статики;
* вход и выход работают как прежде.

⚠ Логика вынесена в `auth_session_slide_touch` с подменяемым временем именно
ради этих тестов: иначе проверка скольжения ждала бы целый шаг (минуту) на
каждый случай.
"""
import os
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = pytest.mark.auth

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


class TestSlideDecision:
    """Решение «пора ли продлевать» — без сети и без ожидания."""

    def test_activity_extends_the_session(self):
        """Запрос в новом шаге продлевает срок: кука уедет свежей."""
        from src.auth.auth_session_slide import (AUTH_SESSION_SLIDE_STEP,
                                                 auth_session_slide_touch)

        session = {'user_id': 7}
        start = 1_000_000 * AUTH_SESSION_SLIDE_STEP

        assert auth_session_slide_touch(session, now=start) is True
        assert auth_session_slide_touch(session, now=start + AUTH_SESSION_SLIDE_STEP) is True

    def test_repeat_within_step_does_not_touch_the_cookie(self):
        """
        ⚠ Внутри шага кука не трогается. Присваивание помечает сессию изменённой
        всегда, даже тем же значением, — а `Set-Cookie` на каждый ответ это
        лишние сотни байт с каждой картинкой и каждым файлом статики.

        ⚠ Отсчёт идёт по **абсолютной сетке** (`время // шаг`), а не от первого
        касания: граница ячейки проходит по кратным шагу, поэтому запрос может
        попасть в новую ячейку и через секунду после предыдущего. Отсюда `start`
        кратен шагу — иначе тест проверял бы не то, что думает. На деле это
        значит, что окно «дребезжит» на величину шага, и при сроке в часы
        роли не играет.
        """
        from src.auth.auth_session_slide import (AUTH_SESSION_SLIDE_STEP,
                                                 auth_session_slide_touch)

        session = {'user_id': 7}
        start = 1_000_000 * AUTH_SESSION_SLIDE_STEP
        auth_session_slide_touch(session, now=start)

        assert auth_session_slide_touch(session, now=start + 1) is False
        assert auth_session_slide_touch(session,
                                        now=start + AUTH_SESSION_SLIDE_STEP - 1) is False

    def test_anonymous_session_is_left_alone(self):
        """
        ⚠ Пустая сессия не трогается: запись завела бы куку каждому, кто просто
        открыл страницу входа.
        """
        from src.auth.auth_session_slide import auth_session_slide_touch

        empty: dict = {}

        assert auth_session_slide_touch(empty, now=1_000_000) is False
        assert empty == {}, 'в сессию анонима что-то записали'

    def test_session_without_login_is_left_alone(self):
        """Признак входа — `user_id`, а не непустой словарь: служебное не в счёт."""
        from src.auth.auth_session_slide import auth_session_slide_touch

        session = {'something': 'служебное'}

        assert auth_session_slide_touch(session, now=1_000_000) is False

    def test_broken_input_does_not_raise(self):
        """Зовут из middleware на каждом ответе — падать здесь нельзя."""
        from src.auth.auth_session_slide import auth_session_slide_touch

        assert auth_session_slide_touch(None) is False
        assert auth_session_slide_touch('не словарь') is False


class TestSlideOverHttp:
    """То же самое, но как это видит браузер."""

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                     timeout=20.0) as session:
            yield session

    async def test_login_sets_the_full_window(self, client):
        """Вход отдаёт куку со сроком, объявленным приложением."""
        from main_uvicorn import SESSION_MAX_AGE

        got = await client.post('/auth/login', json=TEST_AUTH)

        assert got.status_code == 200
        assert f'Max-Age={SESSION_MAX_AGE}' in got.headers.get('set-cookie', '')

    async def test_anonymous_request_gets_no_cookie(self, client):
        """
        Анониму куки не выдаём ни на странице входа, ни на закрытой ручке, ни на
        статике — иначе каждый заход заводил бы сессию.
        """
        for path in ('/login', '/setting/list', '/static/js/api.js'):
            got = await client.get(path)

            assert 'set-cookie' not in got.headers, f'кука уехала анониму на {path}'

    async def test_logout_still_clears_the_session(self, client):
        """
        ⚠ Продление не должно мешать выходу: после `/auth/logout` кука гасится, а
        закрытая ручка снова отвечает 401.
        """
        await client.post('/auth/login', json=TEST_AUTH)
        got = await client.post('/auth/logout')

        assert got.status_code == 200
        assert 'expires=Thu, 01 Jan 1970' in got.headers.get('set-cookie', ''), \
            'кука не погашена'

        after = await client.get('/setting/list')
        assert after.status_code == 401, 'сессия пережила выход'

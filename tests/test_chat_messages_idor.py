"""`/chat/messages`: своё — своим, чужое — только инспектору (находка #1 пентеста).

Точка отдавала переписку **кому угодно по одному `session_uuid`**, без проверки
владельца. Пентест 2026-11-02 вытащил гостём чужой диалог дейтинга: защищала
только неугадываемость UUID, а он уезжает в URL
(`/detective/case_agents?session_uuid=…`) — в логи и `Referer`.

Владение держится на `agent_session.user_id` (у него FK на `user`, у сессии он
один). Правило: `session:view` (админы, менеджеры, QA) читают любую сессию —
этим живёт инспектор `/admin/chat`; остальные — только свои, чужая отвечает
пустым списком.

⚠ Тест сеет строки `agent_session` напрямую (`mysql_query_run`, как
`test_browser_site_variable`) — HTTP-ручки записать историю под чужим владельцем
нет. `user_id` берём настоящий: FK не пустит выдуманный. Всё посеянное
убирается в `finally`.
"""
import os
import sys
import uuid

import httpx
import pytest
from dotenv import load_dotenv

sys.path.insert(0, 'py_modules')
from mysql_.mysql_query import mysql_query_run  # noqa: E402

from tests.constants import TEST_AUTH  # noqa: E402

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = [pytest.mark.auth, pytest.mark.integration]


def _seed(session_uuid: str, owner_id: int) -> None:
    """Обмен из двух строк под указанным владельцем."""
    for role, kind, content in (
            ('user', 'user-prompt', 'мой вопрос'),
            ('assistant', 'response-final', 'мой ответ')):
        mysql_query_run(
            "INSERT INTO agent_session"
            " (session_uuid, request_uuid, user_id, role, kind_type, content)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (session_uuid, 'rq1', owner_id, role, kind, content))


def _wipe(session_uuid: str) -> None:
    mysql_query_run("DELETE FROM agent_session WHERE session_uuid = %s",
                    (session_uuid,))


async def _messages(client: httpx.AsyncClient, session_uuid: str) -> list:
    resp = await client.post('/chat/messages',
                             json={'session_uuid': session_uuid, 'limit': 10})
    assert resp.status_code == 200, resp.text
    return resp.json()['result']


@pytest.fixture
async def admin():
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=10.0) as client:
        resp = await client.post('/auth/login', json=TEST_AUTH)
        assert resp.status_code == 200, resp.text
        yield client


@pytest.fixture
async def guest(admin: httpx.AsyncClient):
    """Гостевая сессия и её числовой id — и уборка учётки."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=10.0) as client:
        resp = await client.post('/auth/guest', json={})
        assert resp.status_code == 200, resp.text
        guest_id = resp.json()['user']['id']
        client.guest_id = guest_id

        yield client

    await admin.delete(f'/api/users/{guest_id}')


class TestMessagesOwnership:

    async def test_guest_cannot_read_foreign_session(self, guest, admin):
        """⚠⚠ Главное: чужая сессия гостю — пустой список, а не чужая переписка.

        Владельцем ставим `admin` (id=1): он гостю заведомо чужой.
        """
        sid = f'idor-foreign-{uuid.uuid4().hex[:8]}'
        _seed(sid, owner_id=1)
        try:
            assert await _messages(guest, sid) == [], 'гость прочитал чужую сессию'
            # А инспектор (session:view) — видит: это его работа.
            assert len(await _messages(admin, sid)) == 2, 'инспектор потерял доступ'
        finally:
            _wipe(sid)

    async def test_guest_reads_own_session(self, guest):
        """Свою историю гость видит — игра детектива не сломана."""
        sid = f'idor-own-{uuid.uuid4().hex[:8]}'
        _seed(sid, owner_id=guest.guest_id)
        try:
            rows = await _messages(guest, sid)
            assert [r['content'] for r in rows] == ['мой вопрос', 'мой ответ'], rows
        finally:
            _wipe(sid)

    async def test_unknown_session_is_empty_not_error(self, guest):
        """Несуществующая сессия — пустой список, без утечки факта её отсутствия."""
        assert await _messages(guest, f'nope-{uuid.uuid4().hex}') == []

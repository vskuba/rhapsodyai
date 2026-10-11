"""Список инструментов отсортирован: сперва группа, внутри имя.

## ⚠⚠ Что стережётся и какой ценой узнано

Без `ORDER BY` база отдаёт строки как ей удобно, и список в селекте шага
`tool_invoke` выстраивался случайно: `Weather`, `List`, `Claude_`,
`Datetime_`, … Человек, заведя инструмент в новой группе, не находил его
глазами — и решал, что выкладка его не довезла.

Замерено 11.10.2026: после деплоя `chat_intention_add` лежал в реестре прода
(id 41635, группа «Chat»), а в селекте оказался в хвосте списка. Разбор ушёл
на проверку контейнера, таблицы `tool` и журнала синка; попутно был удалён шаг
workflow, который на самом деле был исправен.

⚠ Беда тихая: список **полон**, порядок лишь неудобен, и ни ошибки, ни
предупреждения тут быть не может — только глаза человека.

⚠ Клиент заводится здесь, как у соседних сюит: общий пул слоя
(`http_pool_transport`) — про живые выходы в бою, а тесту нужна своя сессия с
логином и коротким сроком ожидания.
"""
import os

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


@pytest.fixture
async def client():
    logged = httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=15.0)
    response = await logged.post("/auth/login", json=TEST_AUTH)
    assert response.status_code == 200, response.text
    try:
        yield logged
    finally:
        await logged.aclose()


class TestToolListOrder:
    """Порядок задаёт ручка, а не тот, кто показывает."""

    async def test_groups_come_alphabetically(self, client: httpx.AsyncClient):
        """⚠⚠ Главный случай: группы по алфавиту, новая не теряется в хвосте."""
        rows = await _listed(client)

        seen = []
        for row in rows:
            group = str(row.get('group_name') or '')
            if group and group not in seen:
                seen.append(group)

        assert len(seen) > 1, 'групп меньше двух — порядок проверять не на чем'
        assert seen == sorted(seen, key=_as_mysql), \
            f'группы идут не по алфавиту: {seen}'

    async def test_tools_inside_a_group_come_alphabetically(
            self, client: httpx.AsyncClient):
        """⚠ Внутри группы — тоже по имени: в больших группах их по десятку."""
        rows = await _listed(client)

        by_group: dict = {}
        for row in rows:
            by_group.setdefault(str(row.get('group_name') or ''), []).append(
                str(row.get('name') or ''))

        crooked = {group: names for group, names in by_group.items()
                   if group and names != sorted(names, key=_as_mysql)}

        assert not crooked, f'внутри группы имена не по алфавиту: {crooked}'

    async def test_the_nameless_group_goes_last(self, client: httpx.AsyncClient):
        """⚠⚠ Инструменты без группы — **вниз**, а не наверх.

        В MySQL `NULL` при `ASC` идёт первым, и без отдельного ключа сортировки
        безымянные возглавили бы список — то есть ровно то место, куда смотрят
        в первую очередь.
        """
        rows = await _listed(client)
        nameless = [number for number, row in enumerate(rows)
                    if not row.get('group_name')]

        if not nameless:
            pytest.skip('на этой установке нет инструментов без группы')

        assert min(nameless) > max(
            number for number, row in enumerate(rows) if row.get('group_name')), \
            'инструменты без группы оказались выше именованных'


# ---------------------------------------------------------------------------
# Приватное
# ---------------------------------------------------------------------------

def _as_mysql(value: str) -> str:
    """Ключ сортировки, повторяющий коллацию базы (`utf8mb4_general_ci`).

    ## ⚠⚠ Почему верхний регистр, а не нижний

    `general_ci` сравнивает, приведя буквы к **верхнему** регистру, и на именах
    с подчёркиванием это меняет порядок: `S` (0x53) меньше `_` (0x5F), а `s`
    (0x73) — больше. Отсюда `session_messages` раньше `session_message_add` —
    и это верно, так их и показывают человеку.

    ⚠ Сортируй тест по `str.lower`, и он объявил бы исправный порядок
    сломанным: проверял бы правила Python, а не те, по которым список вправду
    построен.
    """
    return str(value or '').upper()


async def _listed(client: httpx.AsyncClient) -> list:
    """Список инструментов как его отдаёт ручка — в её порядке."""
    response = await client.get('/tool/list')
    assert response.status_code == 200, response.text

    rows = response.json().get('result') or []
    assert rows, 'реестр инструментов пуст — проверять нечего'

    return rows


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

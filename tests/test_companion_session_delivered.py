"""Отметка доставки: строка помечается один раз, повтор время не двигает.

⚠⚠ Что здесь стережётся. `companion_session` пишется **внутри прогона
workflow** — до того, как DatingAi попробует отправить реплику. Отметка
`delivered_at` отделяет «мы это сочинили» от «собеседник это получил», и лента
для агента показывает только второе.

⚠ Тесты зовут инструмент напрямую, а не через прогон workflow: прогон стоит
вызова модели, общей с продом, а проверяется здесь запись в таблицу.

⚠ `asyncio_mode = "auto"` в `pyproject.toml` — своей метки `pytest.mark.asyncio`
тестам не нужно.

⚠ В базу ходим драйвером, а не `docker exec`: образец —
`tests/test_workflow_variables_node.py`, оттуда же фикстура `db_pool_release`.
"""
import uuid

import pytest

from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

from src.tool.companion.companion_session import (companion_session_add,
                                                   companion_session_delivered)

pytestmark = pytest.mark.core


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого свой.

    ⚠ Тот же приём, что у `test_workflow_variables_node.py`. Без него второй
    ходящий в базу тест падает «Future attached to a different loop».
    """
    yield
    await mysql_pool_close()


async def _delivered_at(row_id: int):
    """Отметка доставки у строки — `None`, если её нет."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT `delivered_at` FROM `companion_session`'
                         ' WHERE `id` = %s', (int(row_id),))
        row = await db.fetchone()

    return (row or {}).get('delivered_at')


@pytest.fixture
async def pair():
    """Пара ключей, по которой заводится разговор. Убирается за собой."""
    mark = uuid.uuid4().hex[:8]
    keys = (f'comp_own_{mark}', f'comp_him_{mark}')

    yield keys

    async with mysql_get_db_async() as db:
        await db.execute(
            'DELETE s FROM `companion_session` s'
            ' JOIN `companion` c ON c.`id` = s.`owner_id`'
            ' WHERE c.`unique_id` = %s', (keys[0],))
        await db.execute('DELETE FROM `companion` WHERE `unique_id` IN (%s, %s)',
                         keys)
        await db.connection.commit()


class TestDeliveredMark:
    async def test_new_row_is_not_delivered(self, pair):
        """Записанный обмен доставленным не считается: отправки ещё не было."""
        made = await companion_session_add(pair[0], pair[1],
                                           question='hi', answer='hello')

        assert await _delivered_at(made['id']) is None

    async def test_mark_sets_time(self, pair):
        """Отметка проставляет время."""
        made = await companion_session_add(pair[0], pair[1],
                                           question='hi', answer='hello')

        got = await companion_session_delivered(int(made['id']))

        assert got['marked'] == 1
        assert await _delivered_at(made['id']) is not None

    async def test_second_mark_does_not_move_time(self, pair):
        """⚠ Повтор времени не двигает: «когда дошло» обязано остаться первым."""
        made = await companion_session_add(pair[0], pair[1],
                                           question='hi', answer='hello')
        await companion_session_delivered(int(made['id']))
        first = await _delivered_at(made['id'])

        got = await companion_session_delivered(int(made['id']))

        assert got['marked'] == 0, 'повтор не должен считаться отметкой'
        assert await _delivered_at(made['id']) == first

    async def test_unknown_id_is_not_an_error(self):
        """⚠ Неизвестный номер — не отказ сервера: панели нечего повторять."""
        got = await companion_session_delivered(999999999)

        assert got['marked'] == 0
        assert got['why']

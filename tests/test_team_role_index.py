"""
Номер оболочки внутри роли — `telegram_app_claude_session._role_index_next`.

Зачем это проверять. По номеру карточка на `/admin/team` сопоставляется с окном
терминала: три окна «Developer» и три одинаковые карточки различить больше нечем.
Совпади номера — на странице появляются две неотличимые карточки, и понять, в каком
окне идёт видимая задача, нельзя.

Дефект был живой. Между «посмотреть занятые номера» и «записать свой» есть окно, и в
него влезает соседний терминал: человек перезапускает команду одной командой,
оболочки стартуют разом, обе читают тот же список занятых и обе берут единицу. Две
сессии QA, зарегистрированные в одну секунду, получили `role_index = 1`.

Поэтому главный тест здесь — гонка, а не арифметика: последовательную выдачу «первый
свободный» ломает не логика, а одновременность.

Тесты идут на живой базе и убирают за собой: сессии заводятся в вымышленном каталоге,
и удаляются по нему же.
"""

import asyncio
import uuid

import pytest

# Каталог, которого не существует: по нему выдача номеров изолирована от настоящих
# оболочек установки — номера считаются в пределах каталога.
TEST_WORK_DIR = '/tmp/role-index-test'

# Сколько оболочек стартует разом в проверке гонки. Четырёх достаточно — команда это
# менеджер, разработчик, QA и багфиксер, ровно они и запускаются одной командой.
#
# Больше брать нельзя: каждая задача держит соединение всё время удержания замка, а
# пул отдаёт десять на процесс, часть из которых уже занята фикстурами. Прошлая
# версия просила десять и вешала прогон на `acquire` — не проверив ничего.
RACE_SHELLS = 4


@pytest.fixture(autouse=True)
async def registry_cleanup():
    """Снести тестовые сессии — до теста и после."""
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestRoleIndexRace:
    """Одновременные запуски получают разные номера."""

    async def test_concurrent_registrations_get_unique_numbers(self):
        """
        Десять оболочек стартуют разом — десять разных номеров.

        Пауза внутри замка растягивает то самое окно, в которое влезала гонка: без
        замка все десять прочитали бы пустой список занятых и взяли единицу.
        """
        numbers = await asyncio.gather(*[_register() for _ in range(RACE_SHELLS)])

        assert sorted(numbers) == list(range(1, RACE_SHELLS + 1))

    async def test_numbers_fill_gaps(self):
        """
        Освободившийся номер достаётся следующей оболочке.

        Терминалы закрывают и открывают заново, и сквозная нумерация довела бы до
        «Developer 14» при двух открытых окнах.
        """
        from src.uvicorn.routers.telegram_app.telegram_app_claude_session import _role_index_next

        await _session_write(1)
        await _session_write(3)

        assert await _role_index_next('developer', TEST_WORK_DIR) == 2

    async def test_other_directory_does_not_take_numbers(self):
        """
        Номера считаются в пределах каталога: роли в командах разных проектов зовутся
        одинаково, и менеджер соседнего проекта не должен отбирать номер.
        """
        from src.uvicorn.routers.telegram_app.telegram_app_claude_session import _role_index_next

        await _session_write(1, work_dir=TEST_WORK_DIR + '-other')

        assert await _role_index_next('developer', TEST_WORK_DIR) == 1


class TestRoleIndexLock:
    """Замок не должен ронять регистрацию — она важнее номера."""

    async def test_lock_releases_on_error(self):
        """
        Исключение внутри замка его отпускает. Иначе первая же ошибка регистрации
        заперла бы роль до перезапуска MySQL, и оболочки перестали бы заводиться
        вовсе — цена куда выше, чем у повторяющегося номера.
        """
        from src.uvicorn.routers.telegram_app.telegram_app_claude_session import _role_index_lock

        with pytest.raises(RuntimeError):
            async with _role_index_lock('developer', TEST_WORK_DIR):
                raise RuntimeError('падение внутри замка')

        # Замок свободен — второй вход проходит и не виснет на ожидании.
        async with _role_index_lock('developer', TEST_WORK_DIR):
            pass


async def _register() -> int:
    """Выдать номер и записать строку — как это делает регистрация оболочки."""
    from src.uvicorn.routers.telegram_app.telegram_app_claude_session import (
        _role_index_lock, _role_index_next)

    async with _role_index_lock('developer', TEST_WORK_DIR):
        number = await _role_index_next('developer', TEST_WORK_DIR)
        # Пауза внутри замка: без неё гонка может не воспроизвестись даже на сломанном
        # коде — запросы успевают выстроиться в очередь сами.
        await asyncio.sleep(0.05)
        await _session_write(number)

    return number


async def _session_write(number: int, work_dir: str = TEST_WORK_DIR) -> None:
    from datetime_.datetime_ import datetime_utc_now
    from mysql_.mysql_ import mysql_get_db_async

    now = datetime_utc_now()
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO ai_claude_session_registry '
            '       (session_uuid, role, role_index, project_label, status, '
            '        server_llm, work_dir, created_at, last_seen_at) '
            "VALUES (%s, 'developer', %s, 'role-index-test', 'active', 'test', %s, %s, %s)",
            (str(uuid.uuid4()), number, work_dir, now, now))
        await db.connection.commit()


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM ai_claude_session_registry WHERE work_dir LIKE %s',
                         (f'{TEST_WORK_DIR}%',))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

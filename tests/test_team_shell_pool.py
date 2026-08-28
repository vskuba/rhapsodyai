"""
Захват оболочки ролью на круг (`src/project/team/team_shell_pool.py`).

Главное, что здесь проверяется: **одна оболочка достаётся ровно одному кругу**. Захват
это `UPDATE ... WHERE свободна`, и вся его надёжность держится на том, что второй
претендент видит `rowcount = 0`. Ошибка в условии проявится не отказом, а двумя кругами
в одном Claude Code: второй промпт прилетит агенту посреди чужого хода, и оба ответа
окажутся мусором.

Рядом — прилипание к задаче: следующий круг той же задачи стараются вернуть в ту же
оболочку, её агент помнит прошлый ход.

Тесты работают на живой базе и убирают за собой: строки заводятся под проектом
`TEST_PROJECT_ID`, которого в базе нет.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST` на
импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

# Проект, которого в базе нет: под ним заводятся захваты тестов, и уборка сносит ровно
# их, не задевая работающий конвейер.
TEST_PROJECT_ID = 987657

# Сессии тестовые: попади сюда настоящий uuid — тест отнял бы оболочку у живой роли.
TEST_SHELL_A = 'test-shell-aaaa-0001'
TEST_SHELL_B = 'test-shell-bbbb-0002'


@pytest.fixture(autouse=True)
async def locks_cleanup():
    """Снести захваты тестового проекта — до теста и после."""
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestAcquire:
    """Кому досталась оболочка и что видит второй."""

    async def test_no_shells_gives_nothing(self):
        """Оболочек нет — захватывать нечего, шаг сорвётся сам с `no_session`."""
        from src.project.team.team_shell_pool import team_shell_pool_acquire

        assert await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, []) is None

    async def test_two_rounds_get_two_shells(self):
        from src.project.team.team_shell_pool import team_shell_pool_acquire

        first = await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1,
                                              [TEST_SHELL_A, TEST_SHELL_B])
        second = await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 2,
                                               [TEST_SHELL_A, TEST_SHELL_B])

        assert {first, second} == {TEST_SHELL_A, TEST_SHELL_B}, \
            'Два круга попали в одну оболочку — они дерутся за одного агента'

    async def test_exhausted_shells_return_none(self):
        """
        Свободных нет — `None`, а не чужая оболочка.

        Это и есть предел роли: сколько терминалов открыл человек, столько кругов она
        и ведёт. Работа ждёт очереди.
        """
        from src.project.team.team_shell_pool import team_shell_pool_acquire

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])

        assert await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 2, [TEST_SHELL_A]) is None

    async def test_release_returns_shell(self):
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_release)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        released = await team_shell_pool_release(session_uuid=TEST_SHELL_A)

        assert released == 1
        assert await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 2,
                                             [TEST_SHELL_A]) == TEST_SHELL_A

    async def test_release_without_criteria_does_nothing(self):
        """
        Без признака не снимаем ничего: такой запрос снёс бы все захваты установки.
        """
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_release)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])

        assert await team_shell_pool_release() == 0

    async def test_sticky_shell_preferred_for_same_task(self):
        """
        Задачу возвращают в ту оболочку, где она работала прошлый круг.

        Её Claude Code помнит прошлый ход, и вводить агента в курс заново не придётся.
        Проверяем именно предпочтение: первой в списке стоит другая, и без прилипания
        задача получила бы её.
        """
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_release)

        shells = [TEST_SHELL_A, TEST_SHELL_B]
        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, shells)
        assert await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 2, shells) == TEST_SHELL_B
        await team_shell_pool_release(task_id=1)
        await team_shell_pool_release(task_id=2)

        assert await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 2, shells) == TEST_SHELL_B


class TestBusyCount:
    """Счётчик занятых — по нему отбор решает, осталась ли роли свободная оболочка."""

    async def test_busy_counts_by_role(self):
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_busy)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await team_shell_pool_acquire(TEST_PROJECT_ID, 'qa', 2, [TEST_SHELL_B])

        busy = await team_shell_pool_busy(TEST_PROJECT_ID)

        assert busy[TEST_PROJECT_ID] == {'manager': 1, 'qa': 1}

    async def test_released_shell_leaves_the_count(self):
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_busy,
                                                      team_shell_pool_release)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await team_shell_pool_release(session_uuid=TEST_SHELL_A)

        assert await team_shell_pool_busy(TEST_PROJECT_ID) == {}


class TestPrune:
    """Строки закрытых оболочек не копятся."""

    async def test_dead_shell_row_is_removed(self):
        """Терминал закрыли — сессия больше не появится, и строка ни к чему."""
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_prune)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await team_shell_pool_prune({TEST_SHELL_B})

        assert await _lock_sessions() == []

    async def test_alive_shell_row_survives(self):
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_prune)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await team_shell_pool_prune({TEST_SHELL_A, TEST_SHELL_B})

        assert await _lock_sessions() == [TEST_SHELL_A]

    async def test_empty_alive_set_clears_nothing(self):
        """
        Живых нет вовсе — скорее всего, реестр не прочитался.

        Чистить по такому ответу значило бы стереть таблицу на ровном месте и отобрать
        оболочки у идущих кругов.
        """
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_prune)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])

        assert await team_shell_pool_prune(set()) == 0
        assert await _lock_sessions() == [TEST_SHELL_A]


async def _lock_sessions() -> list:
    """Сессии в строках захвата тестового проекта."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('SELECT session_uuid FROM team_shell_lock WHERE project_id = %s '
                         ' ORDER BY session_uuid', (TEST_PROJECT_ID,))

        return [row['session_uuid'] for row in await db.fetchall() or []]


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM team_shell_lock WHERE project_id = %s', (TEST_PROJECT_ID,))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

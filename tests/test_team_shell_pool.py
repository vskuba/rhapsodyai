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

**Множество живых для `prune` собирается из самой таблицы, а не из тестовых сессий.**
`prune` сносит всё, чего в этом множестве нет, — а рядом лежат захваты работающих
ролей. Собранное из одних тестовых имён, оно снесло бы их все: `pytest -m team` по
рабочей базе оставлял идущие круги без строки захвата, и страница команды теряла
работающую оболочку — круг прыгал по карточкам роли, а занятая выглядела свободной.
Поэтому в `prune` идёт `_alive_except(...)`: живые как есть, минус те, чью гибель
тест и проверяет.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST` на
импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

pytestmark = pytest.mark.team

# Проект, которого в базе нет: под ним заводятся захваты тестов, и уборка сносит ровно
# их, не задевая работающий конвейер.
TEST_PROJECT_ID = 987657

# Второй такой же — им играет «сосед, круг которого сносить нельзя». Отдельный проект,
# а не отдельная роль: `prune` смотрит только на сессию, и сосед обязан отличаться от
# проверяемого всем, чем отличается живой конвейер.
TEST_PROJECT_ID_NEIGHBOUR = TEST_PROJECT_ID + 1

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


class TestTouch:
    """
    Захват живёт, пока круг его подтверждает.

    На этом держится короткий срок протухания. Раньше он был два часа, потому что снять
    захват мог только `finally` своего job'а, а убитый воркер его не выполняет: круг,
    погибший при перезапуске, час держал оболочку и единственную модель проекта — на
    странице команды роль «работала», а соседняя роль голодала, не имея чем работать.
    """

    async def test_touch_refreshes_the_lock(self):
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_touch)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await _lock_age(TEST_SHELL_A, seconds=1000)

        assert await team_shell_pool_touch(TEST_SHELL_A) is True
        assert (await _lock_row(TEST_SHELL_A))['locked_at'] is not None
        assert await _lock_age_seconds(TEST_SHELL_A) < 60, 'отметка не обновилась'

    async def test_free_lock_is_not_revived(self):
        """
        Освобождённый захват подтверждением не поднимается.

        Иначе опоздавший удар сердца отобрал бы оболочку у круга, который взял её
        следом: строка одна на оболочку, и свежая метка на ней означала бы чужую работу.
        """
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_release,
                                                      team_shell_pool_touch)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await team_shell_pool_release(session_uuid=TEST_SHELL_A)

        assert await team_shell_pool_touch(TEST_SHELL_A) is False
        assert (await _lock_row(TEST_SHELL_A))['locked_at'] is None

    async def test_unknown_shell_is_not_an_error(self):
        from src.project.team.team_shell_pool import team_shell_pool_touch

        assert await team_shell_pool_touch('no-such-shell') is False
        assert await team_shell_pool_touch('') is False

    async def test_stale_lock_is_free_for_the_next_round(self):
        """
        Круг умер и подтверждать перестал — оболочка достаётся следующему.

        Это и есть замена `finally`, которого у убитого job'а не бывает.
        """
        from src.project.team.team_shell_pool import (TEAM_SHELL_POOL_STALE_SECONDS,
                                                      team_shell_pool_acquire)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await _lock_age(TEST_SHELL_A, seconds=TEAM_SHELL_POOL_STALE_SECONDS + 60)

        assert await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 2,
                                             [TEST_SHELL_A]) == TEST_SHELL_A


class TestPrune:
    """Строки закрытых оболочек не копятся."""

    async def test_dead_shell_row_is_removed(self):
        """
        Терминал закрыли — сессия больше не появится, и строка ни к чему.

        Сосед в захвате обязателен: без него множество живых окажется пустым, а на
        пустое `prune` по своему же правилу не трогает ничего — проверять было бы
        нечего. Заодно это ровно та обстановка, в которой он и работает: рядом всегда
        есть чужие живые оболочки.
        """
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_prune)

        await team_shell_pool_acquire(TEST_PROJECT_ID_NEIGHBOUR, 'developer', 1, [TEST_SHELL_B])
        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await team_shell_pool_prune(await _alive_except(TEST_SHELL_A))

        assert await _lock_sessions() == []

    async def test_alive_shell_row_survives(self):
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_prune)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await team_shell_pool_prune(await _alive_except())

        assert await _lock_sessions() == [TEST_SHELL_A]

    async def test_live_rounds_are_not_touched(self):
        """
        Захваты соседей `prune` не трогает — ни живого конвейера, ни чужих тестов.

        Сторож на ту самую ошибку, ради которой множество живых собирается из
        таблицы: назови тест живыми только свои сессии, и этот захват исчез бы
        вместе с кругами работающих ролей.
        """
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_prune)

        await team_shell_pool_acquire(TEST_PROJECT_ID_NEIGHBOUR, 'developer', 1, [TEST_SHELL_B])
        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 1, [TEST_SHELL_A])
        await team_shell_pool_prune(await _alive_except(TEST_SHELL_A))

        assert await _lock_row(TEST_SHELL_B), 'prune снёс захват соседнего круга'

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


class TestForget:
    """Удалённая задача не должна числиться за оболочкой."""

    async def test_forget_clears_lock_and_binding(self):
        """
        Освобождение оставляет номер задачи ради прилипания — на следующем круге она
        вернётся в ту же оболочку с прогретым контекстом. Удалённой возвращаться
        некуда, и номер уходит вместе с ней.
        """
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_forget)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 4242, [TEST_SHELL_A])

        assert await team_shell_pool_forget([4242]) == 1

        row = await _lock_row(TEST_SHELL_A)
        assert row['locked_at'] is None
        assert row['task_id'] is None, 'номер удалённой задачи остался за оболочкой'

    async def test_empty_list_touches_nothing(self):
        """«Забыть ничего» не должно означать «забыть всё»."""
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_forget)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 4242, [TEST_SHELL_A])

        assert await team_shell_pool_forget([]) == 0
        assert (await _lock_row(TEST_SHELL_A))['task_id'] == 4242

    async def test_other_tasks_untouched(self):
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_forget)

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 4242, [TEST_SHELL_A])
        await team_shell_pool_acquire(TEST_PROJECT_ID, 'manager', 4243,
                                      [TEST_SHELL_A, TEST_SHELL_B])

        assert await team_shell_pool_forget([4242]) == 1
        assert (await _lock_row(TEST_SHELL_B))['task_id'] == 4243


async def _lock_row(session_uuid: str) -> dict:
    """Строка захвата целиком — по ней видно и замок, и привязку."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('SELECT * FROM team_shell_lock WHERE session_uuid = %s',
                         (session_uuid,))

        return await db.fetchone() or {}


async def _lock_sessions() -> list:
    """Сессии в строках захвата тестового проекта."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('SELECT session_uuid FROM team_shell_lock WHERE project_id = %s '
                         ' ORDER BY session_uuid', (TEST_PROJECT_ID,))

        return [row['session_uuid'] for row in await db.fetchall() or []]


async def _lock_age(session_uuid: str, seconds: int) -> None:
    """Состарить захват: отодвинуть его отметку назад на столько секунд."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'UPDATE team_shell_lock SET locked_at = NOW() - INTERVAL %s SECOND '
            ' WHERE session_uuid = %s', (int(seconds), session_uuid))
        await db.connection.commit()


async def _lock_age_seconds(session_uuid: str) -> int:
    """Сколько секунд назад захват подтверждали."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT TIMESTAMPDIFF(SECOND, locked_at, NOW()) AS age FROM team_shell_lock '
            ' WHERE session_uuid = %s', (session_uuid,))
        row = await db.fetchone() or {}

    return int(row.get('age') or 0)


async def _alive_except(*dead: str) -> set:
    """
    Живые оболочки установки, кроме названных: множество для `team_shell_pool_prune`.

    Живые берём из самой таблицы, а не из тестовых имён. `prune` сносит всё, чего в
    множестве нет, и множество из одних тестовых сессий означало бы «живых больше
    никого» — под нож ушли бы захваты работающих ролей. Так и было: после
    `pytest -m team` идущий круг оставался без строки, и страница команды показывала
    работающую оболочку свободной.

    Названные исключаются — это и есть «оболочку закрыли», гибель которой проверяет
    тест.
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('SELECT session_uuid FROM team_shell_lock')
        rows = await db.fetchall() or []

    return {row['session_uuid'] for row in rows} - set(dead)


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM team_shell_lock WHERE project_id IN (%s, %s)',
                         (TEST_PROJECT_ID, TEST_PROJECT_ID_NEIGHBOUR))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

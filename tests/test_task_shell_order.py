"""
Приоритет локальной модели над облачным агентом — `task_pipeline._shell_order`.

Зачем это проверять. У роли рядом стоят две карточки: одна поднята под пул и работает
локальной моделью, вторая — без `--litellm`, родным агентом Claude Code за облачные
токены. Освободилась локальная модель, и за круг берутся обе; кто выиграет, решал
порядок захвата — то есть случай. Живьём это значит счёт за облачный прогон при
простаивающей оплаченной модели.

Правило: **пока свободна модель пула, круг идёт в пуловую оболочку.** Обратное тоже
важно и проверяется здесь же: свободных моделей нет — вперёд выходит облачная, иначе
пуловая упрётся в «ждёт свободной модели» и потратит на это захват, а облачная
простоит.

Отдельно проверяется прилипание. Оно предпочитает оболочку прошлого круга ради
прогретого контекста, но правило старше предпочтения: липнуть можно только внутри
ведущей группы, иначе «прошлый раз работали в облачной» раз за разом уводило бы работу
мимо свободной локальной модели.

Тесты идут на живой базе и убирают за собой: пул, захваты и сессии заводятся под
проектом `TEST_PROJECT_ID`, которого в базе нет.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST` на
импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import uuid

import pytest

pytestmark = pytest.mark.pipeline

# Проект, которого в базе нет: под ним живут пул, захваты и сессии тестов.
TEST_PROJECT_ID = 987655

# Каталог тестовых сессий — по нему их и сносит уборка.
TEST_WORK_DIR = '/tmp/shell-order-test'

# Модель тестовая: попади сюда настоящая из каталога — тест отнял бы её у конвейера.
TEST_LLM = 'test_order/model-a'


@pytest.fixture(autouse=True)
async def order_cleanup():
    """Снести пул, захваты и сессии тестового проекта — до теста и после."""
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestLocalFirst:
    """Свободна локальная модель — круг идёт к ней."""

    async def test_pool_shell_leads_when_model_free(self):
        from src.project.task.task_pipeline import _shell_order
        from src.project.team.team_llm_pool import team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM])
        pool_shell = await _session_write('litellm')
        cloud_shell = await _session_write('anthropic')
        by_role = {'developer': [cloud_shell, pool_shell]}

        order, sticky = await _shell_order(TEST_PROJECT_ID, by_role, by_role['developer'])

        assert order == [pool_shell, cloud_shell], 'круг ушёл в облако мимо свободной модели'
        assert sticky == [pool_shell], 'прилипание разрешено вне ведущей группы'

    async def test_cloud_leads_when_no_model_free(self):
        """
        Все модели заняты — вперёд облачная: пуловой идти не с чем.

        Иначе круг захватит пуловую оболочку, упрётся в «ждёт свободной модели» и
        вернёт её обратно, потратив тик, — а облачная всё это время простоит.
        """
        from src.project.task.task_pipeline import _shell_order
        from src.project.team.team_llm_pool import team_llm_pool_acquire, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM])
        pool_shell = await _session_write('litellm')
        cloud_shell = await _session_write('anthropic')
        assert await team_llm_pool_acquire(TEST_PROJECT_ID, 1, 'developer') == TEST_LLM
        by_role = {'developer': [pool_shell, cloud_shell]}

        order, sticky = await _shell_order(TEST_PROJECT_ID, by_role, by_role['developer'])

        assert order == [cloud_shell, pool_shell]
        assert sticky == [cloud_shell]


class TestStickyDoesNotBreakPriority:
    """Прилипание к прошлой оболочке правило не отменяет."""

    async def test_sticky_cloud_does_not_jump_free_model(self):
        """
        Задача прошлый круг работала в облачной, локальная модель свободна.

        Прилипание тянет её обратно в облако, и без ограничения оно бы выиграло: захват
        двигает липкую оболочку в начало списка. Ограничение (`sticky_within`) держит
        его внутри ведущей группы, и круг всё равно уходит к локальной модели.
        """
        from src.project.task.task_pipeline import _shell_order
        from src.project.team.team_llm_pool import team_llm_pool_set
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_release)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM])
        pool_shell = await _session_write('litellm')
        cloud_shell = await _session_write('anthropic')

        # Прошлый круг задачи #77 отработал в облачной и освободил её: строка захвата
        # осталась с её номером — это и есть прилипание.
        await team_shell_pool_acquire(TEST_PROJECT_ID, 'developer', 77, [cloud_shell])
        await team_shell_pool_release(task_id=77)

        by_role = {'developer': [cloud_shell, pool_shell]}
        order, sticky = await _shell_order(TEST_PROJECT_ID, by_role, by_role['developer'])
        taken = await team_shell_pool_acquire(TEST_PROJECT_ID, 'developer', 77, order,
                                              sticky_within=sticky)

        assert taken == pool_shell, 'прилипание увело круг в облако мимо свободной модели'

    async def test_sticky_works_inside_leading_group(self):
        """
        Внутри ведущей группы прилипание работает как прежде: контекст дороже порядка.

        Две пуловые оболочки, задача прошлый круг была во второй — туда и вернётся,
        хотя в списке она стоит второй.
        """
        from src.project.task.task_pipeline import _shell_order
        from src.project.team.team_llm_pool import team_llm_pool_set
        from src.project.team.team_shell_pool import (team_shell_pool_acquire,
                                                      team_shell_pool_release)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM])
        first = await _session_write('litellm')
        second = await _session_write('litellm')
        cloud_shell = await _session_write('anthropic')

        await team_shell_pool_acquire(TEST_PROJECT_ID, 'developer', 78, [second])
        await team_shell_pool_release(task_id=78)

        by_role = {'developer': [first, second, cloud_shell]}
        order, sticky = await _shell_order(TEST_PROJECT_ID, by_role, by_role['developer'])
        taken = await team_shell_pool_acquire(TEST_PROJECT_ID, 'developer', 78, order,
                                              sticky_within=sticky)

        assert taken == second, 'прилипание внутри группы не сработало'


class TestNothingToSplit:
    """Где делить нечего, порядок остаётся прежним."""

    async def test_no_pool_keeps_order(self):
        """Пул пуст — модель никому не выдаётся, и предпочитать некого."""
        from src.project.task.task_pipeline import _shell_order

        cloud_shell = await _session_write('anthropic')
        pool_shell = await _session_write('litellm')
        by_role = {'developer': [cloud_shell, pool_shell]}

        order, sticky = await _shell_order(TEST_PROJECT_ID, by_role, by_role['developer'])

        assert order == [cloud_shell, pool_shell]
        assert sticky == order, 'прилипание сузили там, где групп нет'

    async def test_only_pool_shells_keep_order(self):
        """Облачных оболочек нет — делить не на что, порядок по свежести пинга."""
        from src.project.task.task_pipeline import _shell_order
        from src.project.team.team_llm_pool import team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM])
        first = await _session_write('litellm')
        second = await _session_write('litellm')
        by_role = {'developer': [first, second]}

        order, sticky = await _shell_order(TEST_PROJECT_ID, by_role, by_role['developer'])

        assert order == [first, second]
        assert sticky == order


async def _session_write(server_llm: str) -> str:
    """Строка реестра с заданным режимом. Возвращает `session_uuid`."""
    from datetime_.datetime_ import datetime_utc_now
    from mysql_.mysql_ import mysql_get_db_async

    session_uuid = str(uuid.uuid4())
    now = datetime_utc_now()
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO ai_claude_session_registry '
            '       (session_uuid, role, role_index, project_label, status, '
            '        server_llm, work_dir, created_at, last_seen_at) '
            "VALUES (%s, 'developer', 1, 'shell-order-test', 'active', %s, %s, %s, %s)",
            (session_uuid, server_llm, TEST_WORK_DIR, now, now))
        await db.connection.commit()

    return session_uuid


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async
    from src.project.team.team_llm_pool import team_llm_pool_set

    await team_llm_pool_set(TEST_PROJECT_ID, [])
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM ai_claude_session_registry WHERE work_dir LIKE %s',
                         (f'{TEST_WORK_DIR}%',))
        await db.execute('DELETE FROM team_shell_lock WHERE project_id = %s', (TEST_PROJECT_ID,))
        await db.execute('DELETE FROM team_llm_lock WHERE project_id = %s', (TEST_PROJECT_ID,))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

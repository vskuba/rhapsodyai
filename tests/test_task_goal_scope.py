"""
Дробление подзадачи по целям — `src/project/task/task_goal_scope.py`.

Здесь проверяется не разделение списка целей (это делает `_goals_partition`, и оно
покрыто в `test_task_question.py`), а **что получается в базе**: продолжение работы
обязано ждать свою исходную и встать сразу за ней.

Почему это важнее самого разделения. Обе половины — одна работа в одних файлах.
Пущенные разом, они уходят к двум разработчикам в разные worktree и сходятся
конфликтом на слиянии; заметно это становится не при дроблении, а через час, на
`git merge`, и виноватым выглядит агент. Живой повод — подзадачи #5235 и #6439
«Вопросы и ответы в мини-приложении»: обе оказались в `planned` и обе были доступны
к захвату.

Позиция — вторая половина того же: продолжение с номером, уже занятым соседом,
встаёт в списке не за своей строкой, а за чужой, и порядок работы читается неверно.

Тесты идут на живой базе и убирают за собой: строки заводятся под проектом
`TEST_PROJECT_ID`, которого в установке нет.
"""

import json

import pytest

pytestmark = pytest.mark.pipeline

# Проект, которого в базе нет: под ним заводятся тестовые строки, и уборка сносит
# ровно их. Настоящие задачи установки при этом не задеваются ничем.
TEST_PROJECT_ID = 987656


@pytest.fixture(autouse=True)
async def task_cleanup():
    """Снести тестовые задачи и их связи — до теста и после."""
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestSplitDependency:
    """Продолжение ждёт исходную: две половины одной работы не идут параллельно."""

    async def test_continuation_depends_on_origin(self):
        from src.project.task.task_depend import task_depend_of
        from src.project.task.task_goal_scope import task_goal_scope_split

        parent_id = await _task_create('родитель', position=0)
        subtask = await _task_get(await _task_create(
            'работа', position=0, parent_id=parent_id,
            goals=[{'text': 'цель раз'}, {'text': 'цель два'}]))

        result = await task_goal_scope_split(subtask, [1])
        assert result['ok'], result

        links = await task_depend_of([result['subtask_id']])

        assert links.get(result['subtask_id']) == [subtask['id']]

    async def test_continuation_waits_until_origin_closed(self):
        """
        Связь не декоративная: пока исходная открыта, отбор работы обязан проходить
        мимо продолжения. Проверяем тем же условием, которым отбирает захват, —
        иначе тест подтверждал бы наличие строки в таблице, а не поведение.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_depend import task_depend_ready_sql
        from src.project.task.task_goal_scope import task_goal_scope_split

        parent_id = await _task_create('родитель', position=0)
        subtask = await _task_get(await _task_create(
            'работа', position=0, parent_id=parent_id,
            goals=[{'text': 'цель раз'}, {'text': 'цель два'}]))
        created = (await task_goal_scope_split(subtask, [1]))['subtask_id']

        assert not await _depend_ready(created), 'исходная открыта — продолжение ждёт'

        async with mysql_get_db_async() as db:
            await db.execute("UPDATE project_task SET pipeline_state = 'done' WHERE id = %s",
                             (subtask['id'],))
            await db.connection.commit()

        assert await _depend_ready(created), 'исходная закрыта — продолжение свободно'
        assert task_depend_ready_sql('project_task.id')   # условие собирается, не пустое


class TestSplitPosition:
    """Место продолжения в списке: сразу за исходной, не деля номер с соседом."""

    async def test_neighbours_shift_down(self):
        """
        Соседи ниже сдвигаются. Без сдвига продолжение получало бы номер следующей
        подзадачи, и две строки делили бы одну позицию — порядок работы читался бы
        случайным образом.
        """
        from src.project.task.task_goal_scope import task_goal_scope_split

        parent_id = await _task_create('родитель', position=0)
        first = await _task_get(await _task_create(
            'первая', position=0, parent_id=parent_id,
            goals=[{'text': 'цель раз'}, {'text': 'цель два'}]))
        second = await _task_create('вторая', position=1, parent_id=parent_id)
        third = await _task_create('третья', position=2, parent_id=parent_id)

        created = (await task_goal_scope_split(first, [1]))['subtask_id']

        assert await _position(first['id']) == 0
        assert await _position(created) == 1
        assert await _position(second) == 2
        assert await _position(third) == 3

    async def test_split_does_not_touch_other_parents(self):
        """
        Сдвиг ограничен детьми того же родителя: у соседней задачи свои позиции, и
        задеть их значило бы переставить работу, которой дробление не касалось.
        """
        from src.project.task.task_goal_scope import task_goal_scope_split

        parent_id = await _task_create('родитель', position=0)
        other_parent = await _task_create('другой родитель', position=1)
        subtask = await _task_get(await _task_create(
            'работа', position=0, parent_id=parent_id,
            goals=[{'text': 'цель раз'}, {'text': 'цель два'}]))
        foreign = await _task_create('чужая', position=1, parent_id=other_parent)

        await task_goal_scope_split(subtask, [1])

        assert await _position(foreign) == 1


class TestSplitGoals:
    """Цели не теряются и не двоятся."""

    async def test_goals_move_without_loss(self):
        from src.project.task.task_goal_scope import task_goal_scope_split

        parent_id = await _task_create('родитель', position=0)
        subtask = await _task_get(await _task_create(
            'работа', position=0, parent_id=parent_id,
            goals=[{'text': 'раз'}, {'text': 'два'}, {'text': 'три'}]))

        created = (await task_goal_scope_split(subtask, [1, 2]))['subtask_id']

        assert [g['text'] for g in await _goals(subtask['id'])] == ['раз']
        assert [g['text'] for g in await _goals(created)] == ['два', 'три']

    async def test_all_goals_marked_is_refused(self):
        """Отметить все — оставить исходную пустой: принимать её станет нечем."""
        from src.project.task.task_goal_scope import task_goal_scope_split

        parent_id = await _task_create('родитель', position=0)
        subtask = await _task_get(await _task_create(
            'работа', position=0, parent_id=parent_id, goals=[{'text': 'раз'}]))

        result = await task_goal_scope_split(subtask, [0])

        assert result['ok'] is False


async def _task_create(title: str, position: int, parent_id: int = None,
                       goals: list = None) -> int:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task (project_id, parent_id, title, description, goals, '
            '                          position, status, task_type_id, pipeline_state) '
            "VALUES (%s, %s, %s, '', %s, %s, 'queued', "
            "        (SELECT id FROM project_task_type WHERE name = 'dev'), 'planned')",
            (TEST_PROJECT_ID, parent_id, title,
             json.dumps(goals or [], ensure_ascii=False), position))
        task_id = db.lastrowid
        await db.connection.commit()

    return task_id


async def _task_get(task_id: int) -> dict:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('SELECT * FROM project_task WHERE id = %s', (task_id,))

        return await db.fetchone()


async def _position(task_id: int) -> int:
    return int((await _task_get(task_id))['position'])


async def _goals(task_id: int) -> list:
    from src.project.task.task_plan import task_plan_goals_normalize

    return task_plan_goals_normalize((await _task_get(task_id))['goals'])


async def _depend_ready(task_id: int) -> bool:
    """Прошла бы строка условие отбора «все предшественники закрыты»."""
    from mysql_.mysql_ import mysql_get_db_async
    from src.project.task.task_depend import task_depend_ready_sql

    async with mysql_get_db_async() as db:
        await db.execute('SELECT id FROM project_task '
                         f' WHERE id = %s AND {task_depend_ready_sql("project_task.id")}',
                         (task_id,))

        return bool(await db.fetchone())


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        # Связи сносим первыми: на `project_task` у них FK, и удаление задач с
        # живыми связями отвергается целиком.
        await db.execute(
            'DELETE FROM project_task_depend WHERE task_id IN '
            '   (SELECT id FROM (SELECT id FROM project_task WHERE project_id = %s) AS t)',
            (TEST_PROJECT_ID,))
        # Дети раньше родителей — иначе FK `parent_id` не даст снести родителя.
        await db.execute('DELETE FROM project_task WHERE project_id = %s AND parent_id IS NOT NULL',
                         (TEST_PROJECT_ID,))
        await db.execute('DELETE FROM project_task WHERE project_id = %s', (TEST_PROJECT_ID,))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

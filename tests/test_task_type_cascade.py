"""
Тип задачи как указатель на владельца: у ветки он один (`task_state.py`).

Тип отвечает не на «что это за работа», а на «у кого она сейчас»: `plan` — у
менеджера, `dev` — у разработчика, `test` — у QA. Отсюда правило: пока родитель на
планировании, подзадачи тоже на планировании — разрабатывать нечего, план ещё пишется.

Из правила есть ровно одно исключение, и оно тоже проверяется здесь: подзадача,
которая не идёт, уходит менеджеру на разбиение в одиночку (`task_goal_replan_send`),
пока остальная ветка разрабатывается. Тогда родитель `dev`, а эта строка `plan` — и
каскад её не трогает, иначе отобрал бы работу у менеджера посреди дела.

Тесты заводят свой проект и сносят его в конце. Задачи удаляются явно: FK от
`project_task.project_id` к `project` в схеме нет.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST`
на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

TEST_PROJECT_TITLE = '__pytest_type_cascade'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def tree():
    """Задача с двумя подзадачами и словарь id типов."""
    await _drop()
    from mysql_.mysql_ import mysql_get_db_async
    from src.mysql_.repository.project.project_repository import PlanningProjectRepository

    project_id = await PlanningProjectRepository().add(
        {'title': TEST_PROJECT_TITLE, 'work_dir': '/tmp/test-cascade'})

    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, name FROM project_task_type')
        types = {row['name']: int(row['id']) for row in await db.fetchall() or []}

        await db.execute(
            'INSERT INTO project_task (project_id, title, task_type_id, pipeline_state, position) '
            "VALUES (%s, 'родитель', %s, 'processing', 0)",
            (project_id, types['dev']))
        parent_id = db.lastrowid

        ids = []
        for position in range(2):
            await db.execute(
                'INSERT INTO project_task (project_id, parent_id, title, task_type_id, '
                '                          pipeline_state, position, pipeline_from_plan) '
                "VALUES (%s, %s, %s, %s, 'planned', %s, 1)",
                (project_id, parent_id, f'подзадача {position + 1}', types['dev'], position))
            ids.append(db.lastrowid)
        await db.connection.commit()

    yield {'parent': parent_id, 'subtasks': ids, 'types': types, 'project': project_id}

    await _drop()


class TestCascade:
    """Перевод родителя тянет за собой детей."""

    async def test_parent_to_plan_takes_children(self, tree):
        """
        Ветку пересматривают целиком: родитель ушёл на планирование — дети за ним.

        Это главное правило: задача на планировании не может иметь подзадачи в
        разработке. Разрабатывать нечего, план ещё пишется.
        """
        from src.project.task.task_state import task_state_type_to_plan

        await task_state_type_to_plan(tree['parent'])

        assert await _types_of(tree['subtasks']) == [tree['types']['plan']] * 2

    async def test_parent_to_testing_takes_children(self, tree):
        """
        Родитель уходит на проверку только когда все дети дошли до QA — значит и
        владелец у них теперь тот же. Иначе ветка расползлась бы по двум вкладкам.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_state import task_state_type_cascade

        async with mysql_get_db_async() as db:
            await db.execute('UPDATE project_task SET task_type_id=%s WHERE id=%s',
                             (tree['types']['test'], tree['parent']))
            await db.connection.commit()

        assert await task_state_type_cascade(tree['parent']) == 2
        assert await _types_of(tree['subtasks']) == [tree['types']['test']] * 2

    async def test_cascade_is_idempotent(self, tree):
        """Второй прогон не трогает ничего: строки уже того же типа."""
        from src.project.task.task_state import task_state_type_cascade

        assert await task_state_type_cascade(tree['parent']) == 0

    async def test_grandchildren_untouched(self, tree):
        """
        Каскад на один уровень. У разложенной подзадачи свой перевод, и он позовёт
        каскад сам; обход всего дерева на каждом тике здесь не нужен.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_state import task_state_type_to_plan

        async with mysql_get_db_async() as db:
            await db.execute(
                'INSERT INTO project_task (project_id, parent_id, title, task_type_id, '
                "                          pipeline_state, position) "
                "VALUES (%s, %s, 'внук', %s, 'planned', 0)",
                (tree['project'], tree['subtasks'][0], tree['types']['dev']))
            grandchild = db.lastrowid
            await db.connection.commit()

        await task_state_type_to_plan(tree['parent'])

        assert await _types_of([grandchild]) == [tree['types']['dev']]


class TestExtraPlanning:
    """Единственное исключение: подзадача ушла на планирование одна."""

    async def test_replan_moves_subtask_to_plan(self, tree):
        """
        Возврат из тупика меняет не только состояние, но и тип: строку забрал
        менеджер, и на вкладке разработчика ей больше не место.
        """
        from src.project.task.task_goal_replan import task_goal_replan_send

        subtask_id = tree['subtasks'][0]
        result = await task_goal_replan_send({'id': subtask_id, 'parent_id': tree['parent']})

        assert result['ok'] is True, result
        assert await _types_of([subtask_id]) == [tree['types']['plan']]

    async def test_cascade_leaves_extra_planning_alone(self, tree):
        """
        Родитель разрабатывается, одна подзадача разбирается заново — расхождение
        законное. Каскад отобрал бы строку у менеджера посреди работы.
        """
        from src.project.task.task_goal_replan import task_goal_replan_send
        from src.project.task.task_state import task_state_type_cascade

        planning, working = tree['subtasks']
        await task_goal_replan_send({'id': planning, 'parent_id': tree['parent']})

        await task_state_type_cascade(tree['parent'])

        assert await _types_of([planning]) == [tree['types']['plan']], \
            'подзадачу на дополнительном планировании вернули разработчику'
        assert await _types_of([working]) == [tree['types']['dev']]

    async def test_parent_to_plan_overrides_the_exception(self, tree):
        """
        Исключение снимается, когда на планирование уходит сам родитель: пересматривают
        всю ветку, и отдельного владельца у строки больше нет.
        """
        from src.project.task.task_goal_replan import task_goal_replan_send
        from src.project.task.task_state import task_state_type_to_plan

        await task_goal_replan_send({'id': tree['subtasks'][0], 'parent_id': tree['parent']})
        await task_state_type_to_plan(tree['parent'])

        assert await _types_of(tree['subtasks']) == [tree['types']['plan']] * 2


class TestInherit:
    """Подзадача рождается с типом родителя, а не с жёстким `dev`."""

    async def test_subtasks_inherit_parent_type(self, tree):
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_state import task_state_subtasks_create

        async with mysql_get_db_async() as db:
            await db.execute('UPDATE project_task SET task_type_id=%s WHERE id=%s',
                             (tree['types']['plan'], tree['parent']))
            await db.connection.commit()

        await task_state_subtasks_create(tree['parent'], [{'title': 'новая', 'plan': 'шаг'}])

        async with mysql_get_db_async() as db:
            await db.execute("SELECT task_type_id FROM project_task "
                             " WHERE parent_id=%s AND title='новая'", (tree['parent'],))
            row = await db.fetchone()

        assert int(row['task_type_id']) == tree['types']['plan']


async def _types_of(ids: list) -> list:
    """Типы строк в том же порядке, в каком переданы номера."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        placeholders = ', '.join(['%s'] * len(ids))
        await db.execute(f'SELECT id, task_type_id FROM project_task '
                         f' WHERE id IN ({placeholders})', list(ids))
        by_id = {int(r['id']): int(r['task_type_id']) for r in await db.fetchall() or []}

    return [by_id.get(int(i)) for i in ids]


async def _drop() -> None:
    """Снести тестовый проект вместе с задачами: FK к `project` у задач нет."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        for depth in range(3):
            await db.execute(
                'DELETE FROM project_task WHERE parent_id IS NOT NULL AND project_id IN '
                '  (SELECT id FROM (SELECT id FROM project WHERE title = %s) AS p)',
                (TEST_PROJECT_TITLE,))
        await db.execute(
            'DELETE FROM project_task WHERE project_id IN '
            '  (SELECT id FROM (SELECT id FROM project WHERE title = %s) AS p)',
            (TEST_PROJECT_TITLE,))
        await db.execute('DELETE FROM project WHERE title = %s', (TEST_PROJECT_TITLE,))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

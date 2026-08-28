"""
Спецификации задачи: что делаем и чем это считается сделанным (`task_spec.py`).

Главное, что здесь проверяется: **у родителя и у листа документы разные**. Лист
получает свою работу и свои критерии приёмки, родитель — сводную: то же по всем
подзадачам плюс порядок выполнения и зависимости, которых в отдельных спецификациях
нет и быть не может. Ради этой разницы сводную и заводят — по ней видно, сходится ли
план как целое.

Второе: **читаем файл, а собираем только если его нет**. Файл — то, что видел агент;
пересобранный на лету документ отличался бы от того, по которому работали, и разбор
«почему сделано не так» шёл бы по чужой бумаге.

Тесты заводят свой проект и сносят его в конце — задачи и связи уходят каскадом по FK.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST` на
импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import json
import os

import pytest

TEST_PROJECT_TITLE = '__pytest_task_spec'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def tree():
    """Задача с двумя подзадачами: у второй зависимость от первой."""
    await _drop()
    from mysql_.mysql_ import mysql_get_db_async
    from src.mysql_.repository.project.project_repository import PlanningProjectRepository
    from src.project.task.task_depend import task_depend_set
    from src.project.task.task_plan import task_plan_serialize

    project_id = await PlanningProjectRepository().add(
        {'title': TEST_PROJECT_TITLE, 'work_dir': '/tmp/test-spec'})

    goals = json.dumps([{'text': 'задача закрыта', 'done': False}], ensure_ascii=False)
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task (project_id, title, description, goals, pipeline_plan, '
            '                          pipeline_state, position) '
            "VALUES (%s, 'родитель', 'общее описание', %s, %s, 'processing', 0)",
            (project_id, goals, task_plan_serialize('общий план', [], [])))
        parent_id = db.lastrowid

        ids = []
        for position, (title, plan) in enumerate((('первая', 'шаг А'), ('вторая', 'шаг Б'))):
            await db.execute(
                'INSERT INTO project_task (project_id, parent_id, title, description, goals, '
                '                          pipeline_plan, pipeline_state, position, '
                '                          pipeline_from_plan) '
                "VALUES (%s, %s, %s, %s, %s, %s, 'planned', %s, 1)",
                (project_id, parent_id, title, f'описание {title}',
                 json.dumps([{'text': f'цель {title}', 'done': False}], ensure_ascii=False),
                 task_plan_serialize(plan, [], []), position))
            ids.append(db.lastrowid)
        await db.connection.commit()

    await task_depend_set(ids[1], [ids[0]])

    yield {'parent': parent_id, 'subtasks': ids}

    await _drop()


class TestLeafSpec:
    """Спецификация подзадачи: своя работа и свои критерии приёмки."""

    async def test_has_goals_as_checkboxes(self, tree):
        """
        Цели — не список пожеланий, а то, по чему QA примет работу. Поэтому чекбоксы.
        """
        from src.project.task.task_spec import task_spec_build

        text = await task_spec_build(tree['subtasks'][0])

        assert '- [ ] цель первая' in text
        assert 'Чем считается сделанным' in text

    async def test_mentions_dependencies(self, tree):
        """
        Зависимость в спецификации нужна: она объясняет, почему в ветке уже есть
        чужие файлы — их принесло слияние перед кругом.
        """
        from src.project.task.task_spec import task_spec_build

        text = await task_spec_build(tree['subtasks'][1])

        assert f"#{tree['subtasks'][0]}" in text
        assert 'Зависит от' in text

    async def test_no_dependencies_no_section(self, tree):
        """У независимой подзадачи раздела нет — пустой заголовок только шумит."""
        from src.project.task.task_spec import task_spec_build

        assert 'Зависит от' not in await task_spec_build(tree['subtasks'][0])

    async def test_missing_goals_are_named(self, tree):
        """
        Подзадача без целей — не норма, а разрыв: QA нечем принимать работу.
        Документ обязан сказать об этом прямо, а не промолчать пустым разделом.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_spec import task_spec_build

        async with mysql_get_db_async() as db:
            await db.execute("UPDATE project_task SET goals='[]' WHERE id=%s",
                             (tree['subtasks'][0],))
            await db.connection.commit()

        assert 'Цели не заданы' in await task_spec_build(tree['subtasks'][0])


class TestParentSpec:
    """Сводная: то, чего нет ни в одной частной."""

    async def test_lists_all_subtasks(self, tree):
        from src.project.task.task_spec import task_spec_build

        text = await task_spec_build(tree['parent'])

        for task_id in tree['subtasks']:
            assert f'#{task_id}' in text

    async def test_shows_execution_order(self, tree):
        """Порядок выполнения — главное, ради чего сводная и нужна."""
        from src.project.task.task_spec import task_spec_build

        text = await task_spec_build(tree['parent'])

        assert 'Порядок выполнения' in text
        assert 'Волна' in text, 'Есть зависимость — значит волн больше одной'

    async def test_flat_plan_says_parallel(self, tree):
        """Связей нет — так и пишем: подзадачи идут параллельно."""
        from src.project.task.task_spec import task_spec_build
        from src.project.task.task_depend import task_depend_set

        await task_depend_set(tree['subtasks'][1], [])
        text = await task_spec_build(tree['parent'])

        assert 'независимы' in text

    async def test_cycle_is_named(self, tree):
        """
        Кольцо зависимостей в документе называется прямо: такой план не выполнить, и
        человек должен увидеть это раньше, чем подзадачи встанут навсегда.
        """
        from src.project.task.task_spec import task_spec_build
        from src.project.task.task_depend import task_depend_set

        first, second = tree['subtasks']
        await task_depend_set(first, [second])
        text = await task_spec_build(tree['parent'])

        assert 'Кольцо зависимостей' in text

    async def test_parent_and_leaf_differ(self, tree):
        """Сводная и частная — разные документы, а не один и тот же текст."""
        from src.project.task.task_spec import task_spec_build

        parent = await task_spec_build(tree['parent'])
        leaf = await task_spec_build(tree['subtasks'][0])

        assert 'Подзадачи' in parent and 'Подзадачи' not in leaf


class TestFile:
    """Файл в каталоге: его читает агент, его же показывают человеку."""

    async def test_write_and_read_roundtrip(self, tree, tmp_path):
        from src.project.task.task_spec import TASK_SPEC_FILE, task_spec_read, task_spec_write

        # Каталог подзадачи, какой завёл бы конвейер: `.claude/worktrees/feature_task_<id>`.
        task_id = tree['subtasks'][0]
        work_dir = str(tmp_path)
        os.makedirs(os.path.join(work_dir, '.claude', 'worktrees', f'feature_task_{task_id}'))

        path = await task_spec_write(work_dir, task_id)

        assert path.endswith(TASK_SPEC_FILE)
        read = await task_spec_read(work_dir, task_id)
        assert read['stored'] is True
        assert 'цель первая' in read['text']

    async def test_read_without_file_builds_and_marks_it(self, tree, tmp_path):
        """
        Файла нет — собираем сейчас, но помечаем: агент этот текст не видел, и
        разбирать по нему «почему сделано не так» нельзя.
        """
        from src.project.task.task_spec import task_spec_read

        read = await task_spec_read(str(tmp_path), tree['subtasks'][0])

        assert read['stored'] is False
        assert read['text']

    async def test_write_without_worktree_is_silent(self, tree, tmp_path):
        """Каталога нет — молча ничего не делаем: спецификация не условие работы."""
        from src.project.task.task_spec import task_spec_write

        assert await task_spec_write(str(tmp_path), tree['subtasks'][0]) == ''


async def _drop() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM project WHERE title = %s', (TEST_PROJECT_TITLE,))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

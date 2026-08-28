"""
Зависимости между подзадачами: кто кого ждёт (`src/project/task/task_depend.py`).

Главное, что здесь проверяется: **подзадача не уходит в работу раньше тех, от кого
зависит**, а всё остальное по-прежнему идёт параллельно. Живой повод: задача #2438
разложилась на три подзадачи, где третья опиралась на первую, и все три ушли в работу
одновременно — параллельность работала, а порядок нет.

Разбор плана и раскладка на волны — чистые функции, они проверяются без базы. Запись
связей и условие отбора ходят в MySQL: тесты заводят свой проект и сносят его в конце,
связи уходят каскадом по FK.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST` на
импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

TEST_PROJECT_TITLE = '__pytest_task_depend'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def tree():
    """
    Дерево под тест: задача и три подзадачи. Возвращает их номера.

    Свой проект, а не чужой: подзадачи настоящих задач — рабочие данные, и заводить
    между ними связи тест не вправе.
    """
    await _drop()
    from src.mysql_.repository.project.project_repository import PlanningProjectRepository
    from mysql_.mysql_ import mysql_get_db_async

    project_id = await PlanningProjectRepository().add(
        {'title': TEST_PROJECT_TITLE, 'work_dir': '/tmp/test-depend'})

    ids = []
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task (project_id, title, pipeline_state, position) '
            "VALUES (%s, 'родитель', 'processing', 0)", (project_id,))
        parent_id = db.lastrowid
        for position in range(3):
            await db.execute(
                'INSERT INTO project_task (project_id, parent_id, title, pipeline_state, '
                '                          position, pipeline_from_plan) '
                "VALUES (%s, %s, %s, 'planned', %s, 1)",
                (project_id, parent_id, f'подзадача {position + 1}', position))
            ids.append(db.lastrowid)
        await db.connection.commit()

    yield {'parent': parent_id, 'subtasks': ids}

    await _drop()


class TestPlanLinks:
    """Разбор `depends_on` из плана менеджера — до всякой базы."""

    def test_backward_links_pass(self):
        from src.project.task.task_depend import task_depend_plan_links

        plan = [{'title': 'A'}, {'title': 'B', 'depends_on': [1]},
                {'title': 'C', 'depends_on': [1, 2]}]

        assert task_depend_plan_links(plan) == {1: [0], 2: [0, 1]}

    def test_forward_link_dropped(self):
        """
        Ссылка вперёд — не порядок работы, а нерешённость: приняв её, заведём цикл.
        """
        from src.project.task.task_depend import task_depend_plan_links

        plan = [{'title': 'A', 'depends_on': [2]}, {'title': 'B'}]

        assert task_depend_plan_links(plan) == {}

    def test_self_link_dropped(self):
        from src.project.task.task_depend import task_depend_plan_links

        assert task_depend_plan_links([{'title': 'A', 'depends_on': [1]}]) == {}

    def test_string_form_parsed(self):
        """Модель возвращает и строку «1, 2» вместо массива — читаем и так."""
        from src.project.task.task_depend import task_depend_plan_links

        plan = [{'title': 'A'}, {'title': 'B'}, {'title': 'C', 'depends_on': '1, 2'}]

        assert task_depend_plan_links(plan) == {2: [0, 1]}

    def test_garbage_ignored(self):
        from src.project.task.task_depend import task_depend_plan_links

        plan = [{'title': 'A'}, {'title': 'B', 'depends_on': ['первая', None, 0]}]

        assert task_depend_plan_links(plan) == {}

    def test_flat_plan_has_no_links(self):
        """План без зависимостей — обычный случай, и он должен остаться плоским."""
        from src.project.task.task_depend import task_depend_plan_links

        assert task_depend_plan_links([{'title': 'A'}, {'title': 'B'}]) == {}


class TestWaves:
    """Раскладка графа на волны: что можно вести параллельно."""

    async def test_chain_gives_three_waves(self, tree):
        from src.project.task.task_depend import task_depend_set, task_depend_tree

        first, second, third = tree['subtasks']
        await task_depend_set(second, [first])
        await task_depend_set(third, [second])

        graph = await task_depend_tree(tree['parent'])

        assert graph['waves'] == [[first], [second], [third]]
        assert graph['cycle'] == []

    async def test_independent_go_in_one_wave(self, tree):
        """Связей нет — одна волна: параллельность не отменяется, из неё вычитают связи."""
        from src.project.task.task_depend import task_depend_tree

        graph = await task_depend_tree(tree['parent'])

        assert len(graph['waves']) == 1
        assert sorted(graph['waves'][0]) == sorted(tree['subtasks'])

    async def test_fan_in(self, tree):
        """Двое независимых, третий ждёт обоих: две волны, а не три."""
        from src.project.task.task_depend import task_depend_set, task_depend_tree

        first, second, third = tree['subtasks']
        await task_depend_set(third, [first, second])

        graph = await task_depend_tree(tree['parent'])

        assert graph['waves'] == [[first, second], [third]]

    async def test_cycle_is_reported(self, tree):
        """
        Кольцо не разворачиваем молча: план с ним не выполнить, о нём нужно сказать.
        """
        from src.project.task.task_depend import task_depend_set, task_depend_tree

        first, second, _ = tree['subtasks']
        await task_depend_set(first, [second])
        await task_depend_set(second, [first])

        graph = await task_depend_tree(tree['parent'])

        assert graph['cycle'] == sorted([first, second])

    async def test_blocks_is_the_reverse_edge(self, tree):
        """`blocks` — кого разблокирует закрытие строки; по нему страница рисует связь."""
        from src.project.task.task_depend import task_depend_set, task_depend_tree

        first, second, _ = tree['subtasks']
        await task_depend_set(second, [first])

        nodes = {n['id']: n for n in (await task_depend_tree(tree['parent']))['nodes']}

        assert nodes[first]['blocks'] == [second]
        assert nodes[second]['depends_on'] == [first]


class TestSet:
    """Запись связей: замена, а не накопление."""

    async def test_rewrite_replaces_previous(self, tree):
        """
        План пересматривают, и связи прошлого разбора не должны его пережить —
        иначе подзадача ждала бы соседа, которого в плане уже нет.
        """
        from src.project.task.task_depend import task_depend_of, task_depend_set

        first, second, third = tree['subtasks']
        await task_depend_set(third, [first])
        await task_depend_set(third, [second])

        assert (await task_depend_of([third]))[third] == [second]

    async def test_missing_id_is_skipped(self, tree):
        """Опечатка модели не должна лишать связей весь план: FK отверг бы вставку целиком."""
        from src.project.task.task_depend import task_depend_of, task_depend_set

        first, second, _ = tree['subtasks']
        await task_depend_set(second, [first, 99999999])

        assert (await task_depend_of([second]))[second] == [first]

    async def test_blocked_by_lists_open_predecessors(self, tree):
        from src.project.task.task_depend import task_depend_blocked_by, task_depend_set

        first, second, _ = tree['subtasks']
        await task_depend_set(second, [first])

        blocked = await task_depend_blocked_by(second)

        assert [b['id'] for b in blocked] == [first]

    async def test_done_predecessor_stops_blocking(self, tree):
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_depend import task_depend_blocked_by, task_depend_set

        first, second, _ = tree['subtasks']
        await task_depend_set(second, [first])
        async with mysql_get_db_async() as db:
            await db.execute("UPDATE project_task SET pipeline_state='done' WHERE id=%s", (first,))
            await db.connection.commit()

        assert await task_depend_blocked_by(second) == []


class TestReadySql:
    """
    Условие отбора: строка без связей проходит всегда, ждущая — нет.

    Столбец в условии обязан быть квалифицированным: голое `id` MySQL разрешает в
    пользу таблицы подзапроса, и условие молча становится тождеством — подзадача
    уходит в работу раньше предшественника. Тест ниже это и ловит.
    """

    async def test_free_subtask_is_selectable(self, tree):
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_depend import task_depend_ready_sql

        async with mysql_get_db_async() as db:
            await db.execute(f'SELECT id FROM project_task '
                             f' WHERE parent_id = %s AND {task_depend_ready_sql()}',
                             (tree['parent'],))
            ids = {int(r['id']) for r in await db.fetchall() or []}

        assert ids == set(tree['subtasks'])

    async def test_condition_works_inside_update(self, tree):
        """
        Условие обязано работать в `UPDATE`, а не только в `SELECT`.

        Захват работы — это `UPDATE project_task SET pipeline_state = …`, и MySQL
        запрещает читать в подзапросе ту же таблицу, которую пишет: ошибка 1093, «You
        can't specify target table for update in FROM clause». Прямой `JOIN
        project_task` внутри условия валил весь тик оркестратора — конвейер вставал
        целиком, ни одна задача не бралась в работу.

        Прошлая версия теста проверяла условие через `SELECT` и этого не видела.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_depend import task_depend_ready_sql, task_depend_set

        first, second, _ = tree['subtasks']
        await task_depend_set(second, [first])

        async with mysql_get_db_async() as db:
            # Присваиваем то же значение: важно, что запрос выполняется, а не что
            # меняет. Упадёт на 1093 — тест провалится с текстом ошибки.
            await db.execute(f'UPDATE project_task SET position = position '
                             f' WHERE parent_id = %s AND {task_depend_ready_sql()}',
                             (tree['parent'],))
            await db.connection.commit()

    async def test_waiting_subtask_is_filtered_out(self, tree):
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_depend import task_depend_ready_sql, task_depend_set

        first, second, third = tree['subtasks']
        await task_depend_set(second, [first])

        async with mysql_get_db_async() as db:
            await db.execute(f'SELECT id FROM project_task '
                             f' WHERE parent_id = %s AND {task_depend_ready_sql()}',
                             (tree['parent'],))
            ids = {int(r['id']) for r in await db.fetchall() or []}

        assert second not in ids, 'Подзадача ушла бы в работу раньше предшественника'
        assert {first, third} <= ids, 'Независимые подзадачи должны остаться в отборе'


async def _drop() -> None:
    """
    Снести тестовый проект вместе с его задачами.

    Задачи удаляем явно: FK от `project_task.project_id` к `project` в схеме нет —
    есть только связь с родительской строкой. Каскада, на который тут раньше
    надеялись, не существует, и задачи оставались сиротами: 624 штуки за один день
    прогонов, пока это не заметили.

    Порядок обратный созданию: сначала дети (`parent_id IS NOT NULL`), потом
    родители. Связи `project_task_depend` уходят сами — там каскад настоящий.
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
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

"""
Роль, работающая над строкой сейчас — `task_role_of_state`.

Зачем это нужно. Вкладки `/admin/task` делят задачи по ролям, а делали это по типу
задачи. Тип статичен: его ставят при заведении, и он говорит, кто задачу **планирует**.
Работа же переходит из рук в руки — QA вернул подзадачу на доработку, её делает
разработчик, а тип так и остался `test`. Живьём подзадача #5219 висела на вкладке
«Тестировщик» в состоянии `developing`: страница показывала её не тому, кто над ней
работает, и разработчик не видел своей работы на своей вкладке.

Ключевая тонкость — состояния, которые **ничьи**. `plan_approval` ждёт человека,
`done` закрыто, `blocked` остановлено: приписав их роли, мы отправили бы готовую
работу на чью-то вкладку и спрятали бы её от того, кто её заводил. Поэтому пустая
строка здесь значимый ответ, а не «не нашли».
"""

import os

import pytest

# Проект, которого нет: под ним заводятся строки теста типов.
TEST_TYPE_PROJECT_ID = 987680
_PARENT_ID = 0


class TestRoleOfState:
    """Каждое рабочее состояние принадлежит ровно одной роли."""

    def test_developing_belongs_to_developer(self):
        """Тот самый случай: строка вернулась в разработку, а тип остался `test`."""
        from src.project.task.task_role import task_role_of_state

        assert task_role_of_state('developing') == 'developer'

    def test_failed_qa_belongs_to_developer(self):
        """
        `failed_qa` — «QA вернул на доработку». Работа снова у разработчика, и ждёт
        она его очереди, а не проверки.
        """
        from src.project.task.task_role import task_role_of_state

        assert task_role_of_state('failed_qa') == 'developer'

    def test_testing_belongs_to_qa(self):
        from src.project.task.task_role import task_role_of_state

        assert task_role_of_state('testing') == 'qa'
        assert task_role_of_state('qa_pending') == 'qa'

    def test_planning_belongs_to_manager(self):
        from src.project.task.task_role import task_role_of_state

        assert task_role_of_state('planning') == 'manager'
        assert task_role_of_state('reviewing') == 'manager'

    def test_bugfixing_belongs_to_bugfixer(self):
        from src.project.task.task_role import task_role_of_state

        assert task_role_of_state('bugfixing') == 'bugfixer'


class TestOwnerlessStates:
    """Ничьи состояния возвращают пустую строку, а не роль по умолчанию."""

    def test_waiting_and_closed_states_have_no_owner(self):
        """
        `plan_approval` ждёт человека, `done` закрыто, `blocked` остановлено. Отдай
        мы здесь роль — готовая работа уехала бы на чужую вкладку, а найти её человек
        рассчитывает там, где заводил.
        """
        from src.project.task.task_role import task_role_of_state

        for state in ('new', 'plan_approval', 'done', 'no_code_for_testing',
                      'blocked', 'failed'):
            assert task_role_of_state(state) == '', state

    def test_empty_and_unknown_state_have_no_owner(self):
        """
        Строка, которую конвейер не вёл вовсе (заведена руками), роли не имеет —
        страница остаётся при типе задачи.
        """
        from src.project.task.task_role import task_role_of_state

        for state in ('', None, 'выдуманное_состояние'):
            assert task_role_of_state(state) == ''


class TestStateMapConsistency:
    """Карта не должна разъезжаться с остальным конвейером."""

    def test_states_do_not_overlap(self):
        """
        Состояние в двух ролях означало бы строку на двух вкладках сразу — ровно тот
        симптом, от которого уходим.
        """
        from src.project.task.task_role import TASK_ROLE_STATES

        seen = [state for states in TASK_ROLE_STATES.values() for state in states]

        assert len(seen) == len(set(seen)), 'состояние принадлежит двум ролям'

    def test_every_state_is_known_to_kanban(self):
        """
        Каждое состояние карты должно быть настоящим — опечатка молча оставила бы
        строку без роли, и она вернулась бы на вкладку по типу, никого не уведомив.
        """
        from src.project.task.task_role import TASK_ROLE_STATES
        from src.project.task.task_state import _TASK_STATE_KANBAN

        for role, states in TASK_ROLE_STATES.items():
            for state in states:
                assert state in _TASK_STATE_KANBAN, f'{role}: {state} нет в карте состояний'

    def test_roles_match_shell_roles(self):
        """
        Имена ролей — те же, что у оболочек: по ним же считается отбор работы и
        подписи вкладок. Разойдись они, вкладка искала бы роль, которой нет.
        """
        from src.project.task.task_role import TASK_ROLE_STATES, TASK_ROLE_TYPES

        assert set(TASK_ROLE_STATES) == set(TASK_ROLE_TYPES)


class TestSubtaskTypeFollowsState:
    """
    Тип подзадачи идёт за её собственной работой, а не за типом родителя.

    Тип — это нынешний владелец строки (`plan` — у менеджера, `dev` — у разработчика,
    `test` — у QA). Каскад от родителя держит ветку в одних руках, пока работа общая,
    но у подзадач она расходится: родитель ушёл в `testing` и стал `test`, а ребёнок
    в это время вернулся к разработчику.

    Живьём #5219: строка в `developing`, вкладка «Разработчик», а в колонке типа —
    «Тестирование». И #5235: ушла к менеджеру, вернулась в работу, дошла до QA — а тип
    так и остался `plan`, то есть «планирование» у Тестировщика.
    """

    async def test_developing_makes_type_dev(self):
        """Тот самый случай #5219: строка у разработчика — значит тип `dev`."""
        from src.project.task.task_state import _subtask_type_follow_state

        subtask_id = await _subtask_create(type_name='test')
        await _subtask_type_follow_state(subtask_id, 'developing')

        assert await _type_of(subtask_id) == 'dev'

    async def test_qa_pending_makes_type_test(self):
        from src.project.task.task_state import _subtask_type_follow_state

        subtask_id = await _subtask_create(type_name='dev')
        await _subtask_type_follow_state(subtask_id, 'qa_pending')

        assert await _type_of(subtask_id) == 'test'

    async def test_plan_type_changes_when_work_resumes(self):
        """
        Случай #5235: строка вернулась с планирования в работу — тип обязан смениться.

        Пока она у менеджера, состояние `new` — ничьё, и до смены типа дело не
        доходит. Забрала работа — владелец сменился по-настоящему.
        """
        from src.project.task.task_state import _subtask_type_follow_state

        subtask_id = await _subtask_create(type_name='plan')
        await _subtask_type_follow_state(subtask_id, 'qa_pending')

        assert await _type_of(subtask_id) == 'test'

    async def test_ownerless_state_keeps_type(self):
        """
        Состояния без владельца тип не трогают: над ними никто не работает, и менять
        владельца не на кого. Строка на планировании (`new`) остаётся у менеджера.
        """
        from src.project.task.task_state import _subtask_type_follow_state

        for state in ('new', 'plan_approval', 'done', 'blocked'):
            subtask_id = await _subtask_create(type_name='plan')
            await _subtask_type_follow_state(subtask_id, state)

            assert await _type_of(subtask_id) == 'plan', state

    async def test_root_task_is_not_touched(self):
        """
        Корневым типом распоряжаются свои переходы (`task_state_type_to_*`), и лезть
        в них отсюда нельзя: у задачи целиком владелец считается иначе.
        """
        from src.project.task.task_state import _subtask_type_follow_state

        task_id = await _subtask_create(type_name='test', root=True)
        await _subtask_type_follow_state(task_id, 'developing')

        assert await _type_of(task_id) == 'test'

    async def test_state_set_applies_type(self):
        """
        Тип правится самим переходом состояния, а не отдельным вызовом: иначе о нём
        пришлось бы помнить в каждом месте, где состояние меняется.
        """
        from src.project.task.task_state import task_state_subtask_set

        subtask_id = await _subtask_create(type_name='test')
        await task_state_subtask_set(subtask_id, 'developing')

        assert await _type_of(subtask_id) == 'dev'


class TestApiCarriesRole:
    """Роль приезжает на страницу с сервера, а не считается в JS второй копией карты."""

    async def test_task_list_has_pipeline_role(self):
        """
        Считай страница роль сама, у карты состояний появилась бы вторая копия — и
        разошлась бы с первой на ближайшем новом состоянии.
        """
        import httpx

        from tests.constants import TEST_AUTH

        base = os.getenv('BASE_URL', 'http://localhost:8011')
        async with httpx.AsyncClient(base_url=base, timeout=20.0) as client:
            login = await client.post('/auth/login', json=TEST_AUTH)
            assert login.status_code == 200, login.text
            response = await client.get('/tasks/2')

        assert response.status_code == 200, response.text
        tasks = response.json().get('tasks') or []
        assert tasks, 'в проекте нет задач — проверять нечего'
        assert all('pipeline_role' in task for task in tasks)

        # Роль обязана совпадать с той, что даёт карта: иначе страница и отбор работы
        # разъедутся, а увидит это только человек, не нашедший задачу на вкладке.
        from src.project.task.task_role import task_role_of_state

        for task in tasks:
            assert task['pipeline_role'] == task_role_of_state(task.get('pipeline_state'))


async def _subtask_create(type_name: str, root: bool = False) -> int:
    """
    Завести строку нужного типа. `root` — задача целиком, без родителя.

    Строка настоящая: проверяемый код пишет в базу, и выдуманный номер молча ничего
    бы не обновил — тест был бы зелёным при любом состоянии кода.
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task (project_id, parent_id, title, description, goals, '
            '                          position, status, task_type_id, pipeline_state) '
            "SELECT %s, %s, 'type-follow-test', '', '[]', 0, 'queued', id, 'planned' "
            '  FROM project_task_type WHERE name = %s',
            (TEST_TYPE_PROJECT_ID, None if root else await _parent_id(), type_name))
        task_id = db.lastrowid
        await db.connection.commit()

    return task_id


async def _parent_id() -> int:
    """Родитель для подзадач теста: заводится один раз на прогон."""
    global _PARENT_ID
    if _PARENT_ID:
        return _PARENT_ID

    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task (project_id, title, description, goals, position, '
            "                          status, task_type_id, pipeline_state) "
            "SELECT %s, 'type-follow-parent', '', '[]', 0, 'queued', id, 'processing' "
            '  FROM project_task_type WHERE name = %s',
            (TEST_TYPE_PROJECT_ID, 'dev'))
        _PARENT_ID = db.lastrowid
        await db.connection.commit()

    return _PARENT_ID


async def _type_of(task_id: int) -> str:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT tt.name FROM project_task t '
            '  LEFT JOIN project_task_type tt ON tt.id = t.task_type_id '
            ' WHERE t.id = %s', (task_id,))

        return str((await db.fetchone() or {}).get('name') or '')


@pytest.fixture(autouse=True)
async def type_test_cleanup():
    """Снести тестовые строки — до теста и после."""
    global _PARENT_ID

    await _type_cleanup()
    _PARENT_ID = 0
    yield
    await _type_cleanup()
    _PARENT_ID = 0

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


async def _type_cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM project_task WHERE project_id = %s AND parent_id IS NOT NULL',
                         (TEST_TYPE_PROJECT_ID,))
        await db.execute('DELETE FROM project_task WHERE project_id = %s', (TEST_TYPE_PROJECT_ID,))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

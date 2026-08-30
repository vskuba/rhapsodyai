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


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

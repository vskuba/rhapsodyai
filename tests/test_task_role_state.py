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

pytestmark = pytest.mark.pipeline

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

    def test_processing_belongs_to_developer(self):
        """
        `processing` — состояние родителя, пока его подзадачи пишут код.

        Обманчиво: оно стоит сразу за `approved`, и раньше числилось за менеджером.
        Но разбор плана (`_run_plan_split`) идёт чистым кодом, без единого обращения
        к оболочке, и уходит, закончив; строка остаётся в `processing`, пока не
        закроются дети. Парное ему `testing` (дети на проверке) за QA и числится.

        Живьём #4996: вкладка «Планирование», тип «Разработка». Тип был верен —
        `task_state_task_testing` меняет его на `test` ровно при переходе
        `processing → testing`, — врала вкладка.
        """
        from src.project.task.task_role import task_role_of_state

        assert task_role_of_state('processing') == 'developer'
        assert task_role_of_state('approved') == 'manager'

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

    def test_parent_states_agree_with_the_type_they_carry(self):
        """
        Вкладка и колонка типа обязаны говорить одно и то же.

        У родителя два долгих состояния — `processing` (дети пишут код) и `testing`
        (дети на проверке), и переход между ними меняет тип: `dev` → `test`
        (`task_state_task_testing`). Значит роль состояния, переведённая в тип, должна
        давать ровно тот тип, который в строке и стоит. Разойдись они — строка отвечает
        на вопрос «чья работа» двумя способами, как #4996: «Планирование» + «Разработка».
        """
        from src.project.task.task_role import task_role_of_state
        from src.project.task.task_state import _TASK_STATE_ROLE_TYPE

        pairs = {'processing': 'dev', 'testing': 'test'}

        for state, expected_type in pairs.items():
            role = task_role_of_state(state)
            assert _TASK_STATE_ROLE_TYPE.get(role) == expected_type, (
                f'состояние {state} показывается у роли «{role}», а тип в строке — '
                f'«{expected_type}»')

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


class TestParentReturnsToDevelopment:
    """
    Родитель уходит на «Тестирование», только пока писать больше нечего.

    Условие входа (`task_state_dev_to_testing`) строгое — все ветки плана должны
    упереться в QA, — но состояние не запирается: у задачи появляются новые
    подзадачи. QA вернул работу, человек добавил продолжение, менеджер доразбил
    охват — и родитель на «Тестировании» оказывается с детьми у разработчика.

    Живьём #4915: один ребёнок дошёл до `qa_pending`, задача законно уехала в
    `testing`, а через четыре часа к ней завели три «продолжения» в `planned`. К
    вечеру на проверке не было **ни одного** ребёнка — три в разработке, один
    готов, — а вкладка по-прежнему говорила «Тестирование».

    Функция возвращает по одной задаче за вызов, поэтому зовём её в цикле: в базе
    живут и настоящие строки, и брать первую попавшуюся тест не вправе.
    """

    async def test_parent_with_kid_in_development_returns(self):
        """Тот самый случай #4915: появился ребёнок в разработке — родитель обратно."""
        from src.project.task.task_state import task_state_testing_to_dev

        parent_id = await _subtask_create(type_name='test', root=True,
                                          state='testing')
        await _subtask_create(type_name='test', parent=parent_id,
                              state='qa_pending', from_plan=True)
        await _subtask_create(type_name='dev', parent=parent_id,
                              state='planned', from_plan=True)

        assert parent_id in await _return_all(), 'родитель остался у QA'
        assert await _state_of(parent_id) == 'processing'
        assert await _type_of(parent_id) == 'dev'

    async def test_parent_with_all_kids_at_qa_stays(self):
        """
        Контрпример: все ветки у QA — задача обязана остаться на «Тестировании».

        Без него тест прошёл бы и на функции, возвращающей всех подряд.
        """
        from src.project.task.task_state import task_state_testing_to_dev

        parent_id = await _subtask_create(type_name='test', root=True,
                                          state='testing')
        await _subtask_create(type_name='test', parent=parent_id,
                              state='qa_pending', from_plan=True)
        await _subtask_create(type_name='test', parent=parent_id,
                              state='testing', from_plan=True)
        await _subtask_create(type_name='dev', parent=parent_id,
                              state='done', from_plan=True)

        assert parent_id not in await _return_all(), 'задачу отобрали у QA зря'
        assert await _state_of(parent_id) == 'testing'

    async def test_kid_at_qa_keeps_its_type(self):
        """
        Ребёнок, который прямо сейчас на проверке, своего типа не теряет.

        Прямой перевод тянет за собой детей каскадом — там у ветки один владелец.
        Здесь владельцы разошлись, и каскад отобрал бы у QA строку посреди работы.
        """
        from src.project.task.task_state import task_state_testing_to_dev

        parent_id = await _subtask_create(type_name='test', root=True,
                                          state='testing')
        at_qa = await _subtask_create(type_name='test', parent=parent_id,
                                      state='testing', from_plan=True)
        await _subtask_create(type_name='dev', parent=parent_id,
                              state='developing', from_plan=True)

        assert parent_id in await _return_all()
        assert await _type_of(at_qa) == 'test', 'у QA отобрали подзадачу'

    async def test_handmade_kids_do_not_return_the_parent(self):
        """
        Подзадачи, заведённые человеком (`pipeline_from_plan = 0`), родителя не
        держат — по той же причине, по какой их не ждёт финализация: они живут
        своей жизнью, и ветка плана про них ничего не знает.
        """
        from src.project.task.task_state import task_state_testing_to_dev

        parent_id = await _subtask_create(type_name='test', root=True,
                                          state='testing')
        await _subtask_create(type_name='test', parent=parent_id,
                              state='qa_pending', from_plan=True)
        await _subtask_create(type_name='dev', parent=parent_id,
                              state='planned', from_plan=False)

        assert parent_id not in await _return_all()

    async def test_second_call_does_not_return_it_twice(self):
        """
        Возврат одноразовый: строка уже в `processing`, и второй раз её брать
        неоткуда. Иначе тик писал бы отчёт каждые полминуты.
        """
        from src.project.task.task_state import task_state_testing_to_dev

        parent_id = await _subtask_create(type_name='test', root=True,
                                          state='testing')
        await _subtask_create(type_name='test', parent=parent_id,
                              state='qa_pending', from_plan=True)
        await _subtask_create(type_name='dev', parent=parent_id,
                              state='planned', from_plan=True)

        assert parent_id in await _return_all()
        assert parent_id not in await _return_all(), 'задачу вернули дважды'

    async def test_tick_calls_the_return(self):
        """
        Возврат живёт в тике, а не в месте создания подзадачи: дорог туда
        несколько — продолжение от QA, доразбиение менеджером, строка от
        человека, — и проверка на одной из них молчала бы для остальных.
        """
        import inspect

        from src.project.task import task_pipeline

        source = inspect.getsource(task_pipeline.task_pipeline_tick)

        assert 'task_state_testing_to_dev' in source


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


async def _subtask_create(type_name: str, root: bool = False, state: str = 'planned',
                          parent: int | None = None, from_plan: bool = False) -> int:
    """
    Завести строку нужного типа. `root` — задача целиком, без родителя.

    Строка настоящая: проверяемый код пишет в базу, и выдуманный номер молча ничего
    бы не обновил — тест был бы зелёным при любом состоянии кода.

    `from_plan` — «подзадача из плана». Умолчание `0` стоит в самой колонке, а
    ветку плана видят только строки с единицей: возврат родителя и финализация
    считают детей именно по ней.
    """
    from mysql_.mysql_ import mysql_get_db_async

    if root:
        parent_id = None
    elif parent is not None:
        parent_id = parent
    else:
        parent_id = await _parent_id()

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task (project_id, parent_id, title, description, goals, '
            '                          position, status, task_type_id, pipeline_state, '
            '                          pipeline_from_plan) '
            "SELECT %s, %s, 'type-follow-test', '', '[]', 0, 'queued', id, %s, %s "
            '  FROM project_task_type WHERE name = %s',
            (TEST_TYPE_PROJECT_ID, parent_id, state, 1 if from_plan else 0, type_name))
        task_id = db.lastrowid
        await db.connection.commit()

    return task_id


async def _return_all(limit: int = 40) -> set:
    """
    Все задачи, которые вернул бы возврат из `testing`, — по одной за вызов.

    Функция берёт первую подходящую строку во всей базе, а не только тестовую:
    рядом живут настоящие задачи, и «вернула не мою» не значит «сломана». Поэтому
    крутим до опустошения и смотрим на множество.
    """
    from src.project.task.task_state import task_state_testing_to_dev

    seen = set()
    for _ in range(limit):
        task_id = await task_state_testing_to_dev()
        if not task_id:
            break
        seen.add(int(task_id))

    return seen


async def _state_of(task_id: int) -> str:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('SELECT pipeline_state FROM project_task WHERE id = %s', (task_id,))

        return str((await db.fetchone() or {}).get('pipeline_state') or '')


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

"""
Запись состояний подзадачи — `src/project/task/task_state.py`.

Проверяется защита от опоздавшего круга. Круг отваливается по таймауту через
двадцать минут, и за это время строку могли закрыть: пропуском по целям или рукой
человека. Итог такого круга не должен ложиться поверх — иначе он воскрешает работу,
которой нет.

Поймано живьём: подзадача #1028 закрылась пропуском по целям, а через десять минут
вернулся оборванный круг QA и увёл её обратно в `failed_qa`.

Тесты ходят в базу напрямую и строки заводят сами: HTTP тут не нужен, а клиентские
фикстуры притащили бы сессионную уборку со своим циклом событий.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST`
на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""
import pytest

# Тот же префикс, по которому сессионная уборка `conftest` сносит следы тестов.
TASK_STATE_TEST_TITLE = '__pytest_task_state'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """
    Закрыть пул MySQL после каждого теста.

    Пул в `mysql_` модульный и привязан к циклу событий, в котором создан, а
    pytest-asyncio даёт каждому тесту свой. Оставленный пул ломает уборку на
    teardown — «Event loop is closed». Та же дисциплина в `test_task_log.py`.
    """
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def subtask_id():
    """Подзадача плана: родитель и ребёнок, оба сносятся после теста."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_task (title, description, status, position) VALUES (%s, '', 'queued', 0)",
            (f'{TASK_STATE_TEST_TITLE}_parent',))
        parent = db.lastrowid
        await db.execute(
            "INSERT INTO project_task (parent_id, title, description, status, position, "
            "                          pipeline_state, pipeline_from_plan) "
            "VALUES (%s, %s, '', 'queued', 0, 'planned', 1)",
            (parent, f'{TASK_STATE_TEST_TITLE}_kid'))
        kid = db.lastrowid
        await db.connection.commit()

    yield kid

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_task WHERE id IN (%s, %s)", (kid, parent))
        await db.connection.commit()


class TestLateRoundGuard:
    """`unless_done` — щит закрытой подзадачи от итога опоздавшего круга."""

    async def test_итог_круга_не_трогает_закрытую(self, subtask_id: int):
        from src.project.task.task_state import task_state_subtask_get, task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'done')
        await task_state_subtask_set(subtask_id, 'failed_qa', last_error='опоздал',
                                     attempt_count=1, unless_done=True)

        row = await task_state_subtask_get(subtask_id)
        assert row['pipeline_state'] == 'done'
        assert not row['pipeline_error'], 'замечание опоздавшего круга не должно записаться'

    async def test_без_флага_переход_проходит(self, subtask_id: int):
        """Человеческие переходы флаг не ставят: «Перезапустить» вправе вернуть закрытую."""
        from src.project.task.task_state import task_state_subtask_get, task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'done')
        await task_state_subtask_set(subtask_id, 'planned')

        row = await task_state_subtask_get(subtask_id)
        assert row['pipeline_state'] == 'planned'

    async def test_незакрытую_щит_не_держит(self, subtask_id: int):
        from src.project.task.task_state import task_state_subtask_get, task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'developing')
        await task_state_subtask_set(subtask_id, 'failed_qa', unless_done=True)

        row = await task_state_subtask_get(subtask_id)
        assert row['pipeline_state'] == 'failed_qa'

    async def test_провал_круга_щит_ставит(self, subtask_id: int):
        """`task_state_subtask_fail` — тот самый писатель итога, ради которого щит и заводился."""
        from src.project.task.task_state import (task_state_subtask_fail, task_state_subtask_get,
                                                 task_state_subtask_set)

        await task_state_subtask_set(subtask_id, 'done')
        await task_state_subtask_fail(subtask_id, attempt_no=3, error='опоздал', max_attempts=3)

        row = await task_state_subtask_get(subtask_id)
        assert row['pipeline_state'] == 'done'


class TestTickGoalsFinish:
    """
    Тик закрывает строки, по которым делать нечего.

    Проверка есть и на входе раннеров, но туда подзадача попадает, только выиграв
    очередь, а очередь у проекта одна на всех и занята чужими кругами по двадцать
    минут. Живьём #1028 стояла в `failed_qa` с закрытыми целями, пока сосед
    доделывал свой круг, — хотя закрыть её стоило одного UPDATE.
    """

    async def _goals_set(self, subtask_id: int, goals: str, state: str = 'planned'):
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute("UPDATE project_task SET goals = %s, pipeline_state = %s WHERE id = %s",
                             (goals, state, subtask_id))
            await db.connection.commit()

    async def test_закрывает_строку_с_закрытыми_целями(self, subtask_id: int):
        from src.project.task.task_pipeline import _subtasks_goals_finish
        from src.project.task.task_state import task_state_subtask_get

        await self._goals_set(subtask_id, '[{"text": "цель", "done": true}]', 'failed_qa')

        assert await _subtasks_goals_finish() >= 1
        assert (await task_state_subtask_get(subtask_id))['pipeline_state'] == 'done'

    async def test_не_трогает_незакрытые_цели(self, subtask_id: int):
        from src.project.task.task_pipeline import _subtasks_goals_finish
        from src.project.task.task_state import task_state_subtask_get

        await self._goals_set(subtask_id, '[{"text": "цель", "done": false}]')

        await _subtasks_goals_finish()
        assert (await task_state_subtask_get(subtask_id))['pipeline_state'] == 'planned'

    async def test_не_трогает_занятую_строку(self, subtask_id: int):
        """Идущий круг закрывать нельзя: его итог придёт своим путём."""
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_pipeline import _subtasks_goals_finish
        from src.project.task.task_state import task_state_subtask_get

        await self._goals_set(subtask_id, '[{"text": "цель", "done": true}]')
        async with mysql_get_db_async() as db:
            await db.execute("UPDATE project_task SET pipeline_locked_at = NOW() WHERE id = %s",
                             (subtask_id,))
            await db.connection.commit()

        await _subtasks_goals_finish()
        assert (await task_state_subtask_get(subtask_id))['pipeline_state'] == 'planned'


class TestShellBlockedByPermission:
    """
    Оболочка, запертая на запросе разрешения, из отбора выпадает.

    Она жива и пингует, но ответить не может, пока человек не нажмёт в терминале.
    Круг ей отдать — потерять двадцать минут и сжечь попытку. Живьём задача #1027
    потеряла так два круга QA подряд.
    """

    async def _session_add(self, role: str, reason: str, work_dir: str = '/tmp/pytest_shell'):
        """Сессия в реестре.

        `last_seen_at` берём временем приложения, а не MySQL `NOW()`: свежесть
        считается в Python против `datetime_now()`, и запись временем базы выглядит
        протухшей ровно на смещение часового пояса настройки.
        """
        from datetime_.datetime_ import datetime_now
        from mysql_.mysql_ import mysql_get_db_async

        seen = await datetime_now()
        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO ai_claude_session_registry "
                "       (session_uuid, role, work_dir, status, agent_status, agent_status_reason, "
                "        last_seen_at) "
                "VALUES (UUID(), %s, %s, 'active', 'busy', %s, %s)",
                (role, work_dir, reason, seen))
            row_id = db.lastrowid
            await db.connection.commit()

        return row_id

    async def _session_drop(self, row_id: int):
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute("DELETE FROM ai_claude_session_registry WHERE id = %s", (row_id,))
            await db.connection.commit()

    async def test_запертая_не_попадает_в_живые(self):
        from src.project.task.task_role import (TASK_ROLE_PROJECT_NONE,
                                                task_role_shell_live_by_project)

        row_id = await self._session_add('__pytest_role', 'permission')
        try:
            live = await task_role_shell_live_by_project()
            assert '__pytest_role' not in live.get(TASK_ROLE_PROJECT_NONE, [])
        finally:
            await self._session_drop(row_id)

    async def test_занятая_ходом_остаётся_живой(self):
        """`turn` — это работа, а не ожидание человека: такую оболочку не трогаем."""
        from src.project.task.task_role import (TASK_ROLE_PROJECT_NONE,
                                                task_role_shell_live_by_project)

        row_id = await self._session_add('__pytest_role', 'turn')
        try:
            live = await task_role_shell_live_by_project()
            assert '__pytest_role' in live.get(TASK_ROLE_PROJECT_NONE, [])
        finally:
            await self._session_drop(row_id)

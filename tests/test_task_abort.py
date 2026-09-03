"""
Обрыв круга удалённой задачи — `src/project/task/task_abort.py`.

Удаление строки снимало захваты и каталог, но прогон в воркере продолжал ждать ответа
агента до своего таймаута: сорок минут у багфиксера, вчетверо больше у разработчика.
Роль всё это время занята, а следующая задача, приехав в ту же оболочку, начинает с
перезапуска агента и рвёт незаконченный ход соседа. Живьём: баг #34226 удалили в 06:44,
прогон досидел до 06:56, и пришедший в 06:51 сосед оборвал его ответ.

Проверяется здесь главное свойство: обрыв точен. Он снимает **своё** задание и не
трогает ни соседнее по времени, ни чужое по сессии, ни уже отвеченное — иначе лекарство
било бы по живым кругам ровно так же, как болезнь.

Тесты ходят в базу напрямую и строки заводят сами: HTTP тут не нужен, а клиентские
фикстуры притащили бы сессионную уборку со своим циклом событий.
"""
import json
import uuid

import pytest

pytestmark = pytest.mark.pipeline

# Тот же префикс, по которому сессионная уборка `conftest` сносит следы тестов.
TASK_ABORT_TEST_TITLE = '__pytest_task_abort'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """
    Закрыть пул MySQL после каждого теста.

    Пул в `mysql_` модульный и привязан к циклу событий, в котором создан, а
    pytest-asyncio даёт каждому тесту свой. Оставленный пул ломает уборку на
    teardown — «Event loop is closed». Та же дисциплина в `test_task_state.py`.
    """
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def stage():
    """
    Задача, её живая трасса и задание в очереди — то, что обрывает `task_abort_runs`.

    Отдаёт `{'task_id', 'run_id', 'session', 'inbox_id'}` и убирает за собой всё
    заведённое. Сессию берём случайную: тест не должен зависеть от того, какие оболочки
    подняты на машине, и не должен задевать их очередь.
    """
    from mysql_.mysql_ import mysql_get_db_async

    session = str(uuid.uuid4())
    made = {'session': session}

    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_task (title, description, status, position) "
            "VALUES (%s, '', 'queued', 0)", (TASK_ABORT_TEST_TITLE,))
        made['task_id'] = db.lastrowid

        # Трасса живая и знает обе нужные вещи: чья она и в какой сессии работает.
        await db.execute(
            "INSERT INTO agent_workflow_trace (run_uuid, workflow_id, status, variables_start, "
            "                                  started_at) "
            "VALUES (UUID(), 59, 'running', %s, NOW())",
            (json.dumps({'task_id': made['task_id'], 'task_shell_session': session,
                         'task_shell_role': 'bugfixer'}, ensure_ascii=False),))
        made['run_id'] = db.lastrowid

        # Задание после старта трассы — то самое, которого ждёт прогон.
        await db.execute(
            "INSERT INTO ai_claude_session (session_uuid, content, status, created_at) "
            "VALUES (%s, 'задание', 'delivered', NOW())", (session,))
        made['inbox_id'] = db.lastrowid
        await db.connection.commit()

    yield made

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM ai_claude_session WHERE session_uuid = %s", (session,))
        await db.execute("DELETE FROM agent_workflow_trace WHERE id = %s", (made['run_id'],))
        await db.execute("DELETE FROM project_task WHERE id = %s", (made['task_id'],))
        await db.connection.commit()


async def _inbox_row(inbox_id: int) -> dict:
    """Строка очереди — её и опрашивает прогон, ожидая ответа."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute("SELECT status, handled, response FROM ai_claude_session WHERE id = %s",
                         (inbox_id,))

        return dict(await db.fetchone() or {})


class TestAbortStopsTheWait:
    """Задание переходит в `failed` — ожидание прогона кончается штатным путём."""

    async def test_task_abort_marks_pending_job_failed(self, stage):
        from src.project.task.task_abort import TASK_ABORT_REASON, task_abort_runs

        assert await task_abort_runs([stage['task_id']]) == 1

        row = await _inbox_row(stage['inbox_id'])
        assert row['status'] == 'failed', 'прогон продолжит ждать: фаза не изменилась'
        assert row['handled'] == 1
        assert row['response'] == TASK_ABORT_REASON, 'причина обрыва не дошла до отчёта'

    async def test_task_abort_counts_nothing_without_ids(self):
        """`IN ()` неверен синтаксически, а «оборвать ничего» ≠ «оборвать всё»."""
        from src.project.task.task_abort import task_abort_runs

        assert await task_abort_runs([]) == 0
        assert await task_abort_runs(None) == 0
        assert await task_abort_runs([0]) == 0

    async def test_task_abort_skips_finished_run(self, stage):
        """Прогон уже кончился — обрывать нечего, и трогать его итог нельзя."""
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_abort import task_abort_runs

        async with mysql_get_db_async() as db:
            await db.execute("UPDATE agent_workflow_trace SET status = 'success' WHERE id = %s",
                             (stage['run_id'],))
            await db.connection.commit()

        assert await task_abort_runs([stage['task_id']]) == 0
        assert (await _inbox_row(stage['inbox_id']))['status'] == 'delivered'


class TestAbortIsPrecise:
    """
    Обрыв не задевает лишнего.

    Здесь и проходит граница между лекарством и болезнью: снять чужое задание —
    ровно та беда, от которой обрыв и заводился.
    """

    async def test_task_abort_keeps_answered_job(self, stage):
        """Отвеченное задание — итог чужого круга, переписывать его нечем."""
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_abort import task_abort_runs

        async with mysql_get_db_async() as db:
            await db.execute(
                "UPDATE ai_claude_session SET status = 'answered', response = 'готово' "
                " WHERE id = %s", (stage['inbox_id'],))
            await db.connection.commit()

        assert await task_abort_runs([stage['task_id']]) == 0
        assert (await _inbox_row(stage['inbox_id']))['response'] == 'готово'

    async def test_task_abort_keeps_job_of_earlier_round(self, stage):
        """
        Задание прошлого круга старше трассы: его итог не наш.

        Сессия у роли одна и живёт кругами, поэтому нижняя граница окна обязательна.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_abort import task_abort_runs

        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO ai_claude_session (session_uuid, content, status, created_at) "
                "VALUES (%s, 'прошлый круг', 'delivered', NOW() - INTERVAL 1 HOUR)",
                (stage['session'],))
            older = db.lastrowid
            await db.connection.commit()

        assert await task_abort_runs([stage['task_id']]) == 1
        assert (await _inbox_row(older))['status'] == 'delivered', 'снято задание прошлого круга'

    async def test_task_abort_keeps_job_of_next_round(self, stage):
        """
        Задание следующего круга в той же оболочке — живой круг чужой задачи.

        Верхняя граница окна ровно про это: сосед уже прислал своё задание, и снять его
        значило бы оборвать работающий круг вместо своего.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_abort import task_abort_runs

        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO agent_workflow_trace (run_uuid, workflow_id, status, "
                "                                  variables_start, started_at) "
                "VALUES (UUID(), 59, 'running', %s, NOW() + INTERVAL 1 MINUTE)",
                (json.dumps({'task_id': 0, 'task_shell_session': stage['session']}),))
            neighbour_run = db.lastrowid
            await db.execute(
                "INSERT INTO ai_claude_session (session_uuid, content, status, created_at) "
                "VALUES (%s, 'круг соседа', 'delivered', NOW() + INTERVAL 2 MINUTE)",
                (stage['session'],))
            neighbour_job = db.lastrowid
            await db.connection.commit()

        try:
            assert await task_abort_runs([stage['task_id']]) == 1
            assert (await _inbox_row(neighbour_job))['status'] == 'delivered', \
                'оборван круг соседней задачи — та самая беда, от которой уходим'
        finally:
            async with mysql_get_db_async() as db:
                await db.execute("DELETE FROM agent_workflow_trace WHERE id = %s", (neighbour_run,))
                await db.connection.commit()

    async def test_task_abort_keeps_other_session(self, stage):
        """Чужая оболочка — чужой круг, даже если задание пришло в то же время."""
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_abort import task_abort_runs

        other = str(uuid.uuid4())
        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO ai_claude_session (session_uuid, content, status, created_at) "
                "VALUES (%s, 'чужая оболочка', 'delivered', NOW())", (other,))
            foreign = db.lastrowid
            await db.connection.commit()

        try:
            assert await task_abort_runs([stage['task_id']]) == 1
            assert (await _inbox_row(foreign))['status'] == 'delivered'
        finally:
            async with mysql_get_db_async() as db:
                await db.execute("DELETE FROM ai_claude_session WHERE session_uuid = %s", (other,))
                await db.connection.commit()

    async def test_task_abort_matches_subtask_id(self, stage):
        """
        Номер круга плана лежит в `subtask_id`, а не в `task_id` — ищем по обоим.

        Разойдись это с движком, обрыв работал бы только на багах, а на подзадачах —
        там, где кругов больше всего, — молча не делал бы ничего.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_abort import task_abort_runs

        async with mysql_get_db_async() as db:
            await db.execute(
                "UPDATE agent_workflow_trace SET variables_start = %s WHERE id = %s",
                (json.dumps({'subtask_id': str(stage['task_id']),
                             'task_shell_session': stage['session']}), stage['run_id']))
            await db.connection.commit()

        assert await task_abort_runs([stage['task_id']]) == 1
        assert (await _inbox_row(stage['inbox_id']))['status'] == 'failed'

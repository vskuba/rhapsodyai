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


class TestRunningRowsFromTrace:
    """
    «Строка в работе» сверяется с состоянием строки, а не только с трассой.

    Статус `running` в трассе держится, пока прогон её не закроет, — а закрыть он
    может не успеть: перезапуск контейнера или смерть воркера оставляют запись
    висеть навсегда. Живьём две такие трассы от вчерашних кругов подсвечивали
    подзадачу #1033 как работающую, хотя она стояла в `planned`.
    """

    async def _trace_add(self, subtask_id: int, role: str = 'developer'):
        import json

        from mysql_.mysql_ import mysql_get_db_async

        variables = json.dumps({'subtask_id': str(subtask_id), 'task_shell_role': role},
                               ensure_ascii=False)
        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO agent_workflow_trace (run_uuid, workflow_id, status, variables_start) "
                "VALUES (UUID(), 56, 'running', %s)", (variables,))
            row_id = db.lastrowid
            await db.connection.commit()

        return row_id

    async def _trace_drop(self, row_id: int):
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute("DELETE FROM agent_workflow_trace WHERE id = %s", (row_id,))
            await db.connection.commit()

    async def test_зависшая_трасса_не_делает_строку_работающей(self, subtask_id: int):
        from src.project.task.task_log import task_log_rows_running
        from src.project.task.task_state import task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'planned')
        trace_id = await self._trace_add(subtask_id)
        try:
            assert subtask_id not in await task_log_rows_running()
        finally:
            await self._trace_drop(trace_id)

    async def test_настоящая_работа_видна(self, subtask_id: int):
        from src.project.task.task_log import task_log_rows_running
        from src.project.task.task_state import task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'developing')
        trace_id = await self._trace_add(subtask_id)
        try:
            assert (await task_log_rows_running()).get(subtask_id) == 'developer'
        finally:
            await self._trace_drop(trace_id)

    async def test_закрытая_строка_не_работает(self, subtask_id: int):
        from src.project.task.task_log import task_log_rows_running
        from src.project.task.task_state import task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'done')
        trace_id = await self._trace_add(subtask_id)
        try:
            assert subtask_id not in await task_log_rows_running()
        finally:
            await self._trace_drop(trace_id)


class TestDirtyLines:
    """
    Что считается несохранённой работой на входе в слияние.

    Слияние останавливается на несохранённых правках — иначе снятый каталог унёс
    бы с собой то, чего нет в коммитах. Но записи конвейера правками не являются:
    журнал строки пишет код, и на #1028 собственный `.task-log.md` встал поперёк
    слияния, потому что ветка отошла раньше, чем шаблон попал в `.gitignore`.
    """

    def test_журнал_не_мешает(self):
        from src.project.task.task_worktree import _dirty_lines

        status = '?? .task-log.md\n?? .task-state.md\n'

        assert _dirty_lines('/tmp', status) == []

    def test_работа_мешает(self):
        from src.project.task.task_worktree import _dirty_lines

        status = ' M src/project/task/task_pipeline.py\n?? src/project/task/task_pipeline_run.py\n'

        assert len(_dirty_lines('/tmp', status)) == 2

    def test_журнал_среди_работы_не_прячет_её(self):
        from src.project.task.task_worktree import _dirty_lines

        status = '?? .task-log.md\n M src/app.py\n?? .task-state.md\n'

        assert _dirty_lines('/tmp', status) == [' M src/app.py']

    def test_похожее_имя_не_путаем(self):
        """`.taskrc` и `.task-log.txt` журналом не являются."""
        from src.project.task.task_worktree import _dirty_lines

        status = '?? .taskrc\n?? .task-log.txt\n'

        assert len(_dirty_lines('/tmp', status)) == 2


class TestWorktreeOwner:
    """
    Корень репозитория, которому принадлежит каталог подзадачи.

    Репозиторий бывает виден по нескольким адресам сразу — в контейнере это `/app`
    и путь хоста. Реестр git хранит тот, которым каталог заводили, и снять его из
    чужого корня нельзя: git отвечает «does not point back». Ответ лежит в самом
    каталоге, в его файле `.git`.
    """

    def test_читает_обратную_ссылку(self, tmp_path):
        from src.project.task.task_worktree import _worktree_owner

        (tmp_path / '.git').write_text('gitdir: /app/.git/worktrees/feature_task_42\n')

        assert _worktree_owner(str(tmp_path)) == '/app'

    def test_путь_хоста(self, tmp_path):
        from src.project.task.task_worktree import _worktree_owner

        (tmp_path / '.git').write_text('gitdir: /home/vasyl/proj/.git/worktrees/feature_task_7')

        assert _worktree_owner(str(tmp_path)) == '/home/vasyl/proj'

    def test_нет_файла(self, tmp_path):
        from src.project.task.task_worktree import _worktree_owner

        assert _worktree_owner(str(tmp_path)) == ''

    def test_чужой_формат(self, tmp_path):
        """Обычный репозиторий: `.git` — каталог, а не ссылка."""
        from src.project.task.task_worktree import _worktree_owner

        (tmp_path / '.git').write_text('ref: refs/heads/master')

        assert _worktree_owner(str(tmp_path)) == ''


class TestTreeDescendants:
    """Строка и всё, что уйдёт с ней каскадом, — собирается до удаления."""

    async def test_родитель_и_ребёнок(self, subtask_id: int):
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_tree import task_tree_descendants

        async with mysql_get_db_async() as db:
            await db.execute("SELECT parent_id FROM project_task WHERE id = %s", (subtask_id,))
            parent = int((await db.fetchone())['parent_id'])
            found = await task_tree_descendants(db, parent)

        assert found[0] == parent
        assert subtask_id in found

    async def test_лист_сам_по_себе(self, subtask_id: int):
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_tree import task_tree_descendants

        async with mysql_get_db_async() as db:
            found = await task_tree_descendants(db, subtask_id)

        assert found == [subtask_id]


class TestSessionReplaced:
    """
    Ожидающий прогон замечает, что адресат сменился.

    Оболочку перезапускают и мимо конвейера — руками в терминале. Тогда у роли
    появляется новая сессия, а отправленное сообщение висит в старой: отвечать
    некому. Без проверки прогон досиживал до своего таймаута — сорок шесть минут
    при свободной роли.
    """

    async def _session_add(self, role: str, uuid_value: str, work_dir: str = '/tmp/pytest_shell'):
        from datetime_.datetime_ import datetime_now
        from mysql_.mysql_ import mysql_get_db_async

        seen = await datetime_now()
        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO ai_claude_session_registry "
                "       (session_uuid, role, work_dir, status, agent_status, agent_status_reason, "
                "        last_seen_at) "
                "VALUES (%s, %s, %s, 'active', 'ready', 'idle', %s)",
                (uuid_value, role, work_dir, seen))
            row_id = db.lastrowid
            await db.connection.commit()

        return row_id

    async def _session_drop(self, row_id: int):
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute("DELETE FROM ai_claude_session_registry WHERE id = %s", (row_id,))
            await db.connection.commit()

    async def test_своя_сессия_не_смена(self):
        from src.tool.claude_shell.claude_shell import _session_replaced

        row_id = await self._session_add('__pytest_shell', 'uuid-первый')
        try:
            assert await _session_replaced('__pytest_shell', '/tmp/pytest_shell', 'uuid-первый') is False
        finally:
            await self._session_drop(row_id)

    async def test_чужая_сессия_это_смена(self):
        from src.tool.claude_shell.claude_shell import _session_replaced

        row_id = await self._session_add('__pytest_shell', 'uuid-второй')
        try:
            assert await _session_replaced('__pytest_shell', '/tmp/pytest_shell', 'uuid-первый') is True
        finally:
            await self._session_drop(row_id)

    async def test_пропавшая_сессия_сменой_не_считается(self):
        """Оболочку могли на секунду потерять по пингу — на это есть таймаут."""
        from src.tool.claude_shell.claude_shell import _session_replaced

        assert await _session_replaced('__pytest_нет_такой', '/tmp/pytest_shell', 'uuid') is False


class TestShellWorkDirAddressing:
    """
    Каталог проекта и его рабочие выкладки адресуют одну оболочку.

    Роль поднимают в `<проект>/.claude/worktrees`, чтобы корень репозитория остался
    выше рабочего каталога агента и его правки не уходили в чекаут человека. А
    спрашивают её по каталогу проекта: конвейер знает проект, про выкладки он не
    знает. Разъедься эти два адреса — роль стала бы невидимой для отбора.

    Живой повод: агент подзадачи #1033 час писал в основной чекаут, доведя дерево
    до незапускаемого состояния.
    """

    def test_адрес_проекта_даёт_оба_варианта(self):
        from src.tool.claude_shell.claude_shell import _work_dir_variants

        variants = _work_dir_variants('/srv/app')

        assert variants == ['/srv/app', '/srv/app/.claude/worktrees']

    def test_адрес_выкладок_не_удваивается(self):
        """Иначе получился бы `worktrees/worktrees`, которого нет."""
        from src.tool.claude_shell.claude_shell import _work_dir_variants

        assert _work_dir_variants('/srv/app/.claude/worktrees') == ['/srv/app/.claude/worktrees']

    def test_хвостовой_слеш_не_мешает(self):
        from src.tool.claude_shell.claude_shell import _work_dir_variants

        assert _work_dir_variants('/srv/app/')[0] == '/srv/app'

    def test_пустой_адрес(self):
        from src.tool.claude_shell.claude_shell import _work_dir_variants

        assert _work_dir_variants('') == []

    def test_проект_по_адресу_выкладок(self):
        from src.project.task.task_role import _shell_project_dir

        assert _shell_project_dir('/srv/app/.claude/worktrees') == '/srv/app'

    def test_проект_по_адресу_корня(self):
        """Старая расстановка обязана работать по-прежнему."""
        from src.project.task.task_role import _shell_project_dir

        assert _shell_project_dir('/srv/app') == '/srv/app'

    def test_похожий_хвост_не_срезаем(self):
        from src.project.task.task_role import _shell_project_dir

        assert _shell_project_dir('/srv/worktrees') == '/srv/worktrees'


class TestTeamLaunchCommand:
    """
    Команда с кнопки «Команда запуска» ведёт в рабочие выкладки.

    Оболочка роли обязана стартовать в `<проект>/.claude/worktrees`: тогда корень
    репозитория оказывается выше рабочего каталога, и Claude Code не пишет в чекаут
    человека. Команду копируют кнопкой и выполняют руками — если она приведёт в
    корень, вся защита обойдётся одним `cd`.
    """

    def test_ведёт_в_выкладки(self):
        from src.project.team.team_project import _command_build

        cmd = _command_build('claude-shell --developer', '/srv/app')

        assert cmd == 'cd /srv/app/.claude/worktrees && claude-shell --developer'

    def test_адрес_выкладок_не_удваивается(self):
        from src.project.team.team_project import _command_build

        cmd = _command_build('claude-shell --qa', '/srv/app/.claude/worktrees')

        assert cmd == 'cd /srv/app/.claude/worktrees && claude-shell --qa'

    def test_без_каталога_только_команда(self):
        """Проект без каталога: подставлять путь из ниоткуда нельзя."""
        from src.project.team.team_project import _command_build

        assert _command_build('claude-shell --manager', '') == 'claude-shell --manager'

    def test_без_команды_пусто(self):
        from src.project.team.team_project import _command_build

        assert _command_build('', '/srv/app') == ''

    def test_хвостовой_слеш(self):
        from src.project.team.team_project import _command_build

        cmd = _command_build('claude-shell --qa', '/srv/app/')

        assert cmd.startswith('cd /srv/app/.claude/worktrees &&')

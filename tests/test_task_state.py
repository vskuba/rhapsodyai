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

pytestmark = pytest.mark.pipeline

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

    async def test_task_state_late_round_skips_closed_subtask(self, subtask_id: int):
        from src.project.task.task_state import task_state_subtask_get, task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'done')
        await task_state_subtask_set(subtask_id, 'failed_qa', last_error='опоздал',
                                     attempt_count=1, unless_done=True)

        row = await task_state_subtask_get(subtask_id)
        assert row['pipeline_state'] == 'done'
        assert not row['pipeline_error'], 'замечание опоздавшего круга не должно записаться'

    async def test_task_state_transition_passes_without_guard(self, subtask_id: int):
        """Человеческие переходы флаг не ставят: «Перезапустить» вправе вернуть закрытую."""
        from src.project.task.task_state import task_state_subtask_get, task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'done')
        await task_state_subtask_set(subtask_id, 'planned')

        row = await task_state_subtask_get(subtask_id)
        assert row['pipeline_state'] == 'planned'

    async def test_task_state_guard_lets_open_subtask_through(self, subtask_id: int):
        from src.project.task.task_state import task_state_subtask_get, task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'developing')
        await task_state_subtask_set(subtask_id, 'failed_qa', unless_done=True)

        row = await task_state_subtask_get(subtask_id)
        assert row['pipeline_state'] == 'failed_qa'

    async def test_task_state_failed_round_raises_guard(self, subtask_id: int):
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

    async def test_task_state_tick_closes_row_with_all_goals_done(self, subtask_id: int):
        from src.project.task.task_pipeline import _subtasks_goals_finish
        from src.project.task.task_state import task_state_subtask_get

        await self._goals_set(subtask_id, '[{"text": "цель", "done": true}]', 'failed_qa')

        assert await _subtasks_goals_finish() >= 1
        assert (await task_state_subtask_get(subtask_id))['pipeline_state'] == 'done'

    async def test_task_state_tick_keeps_row_with_open_goals(self, subtask_id: int):
        from src.project.task.task_pipeline import _subtasks_goals_finish
        from src.project.task.task_state import task_state_subtask_get

        await self._goals_set(subtask_id, '[{"text": "цель", "done": false}]')

        await _subtasks_goals_finish()
        assert (await task_state_subtask_get(subtask_id))['pipeline_state'] == 'planned'

    async def test_task_state_tick_keeps_busy_row(self, subtask_id: int):
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

    async def test_task_state_blocked_shell_is_not_live(self):
        from src.project.task.task_role import (TASK_ROLE_PROJECT_NONE,
                                                task_role_shell_live_by_project)

        row_id = await self._session_add('__pytest_role', 'permission')
        try:
            live = await task_role_shell_live_by_project()
            assert '__pytest_role' not in live.get(TASK_ROLE_PROJECT_NONE, [])
        finally:
            await self._session_drop(row_id)

    async def test_task_state_busy_shell_stays_live(self):
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

    async def test_task_state_stale_trace_does_not_mark_row_running(self, subtask_id: int):
        from src.project.task.task_log import task_log_rows_running
        from src.project.task.task_state import task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'planned')
        trace_id = await self._trace_add(subtask_id)
        try:
            assert subtask_id not in await task_log_rows_running()
        finally:
            await self._trace_drop(trace_id)

    async def test_task_state_real_work_is_visible(self, subtask_id: int):
        from src.project.task.task_log import task_log_rows_running
        from src.project.task.task_state import task_state_subtask_set

        await task_state_subtask_set(subtask_id, 'developing')
        trace_id = await self._trace_add(subtask_id)
        try:
            assert (await task_log_rows_running()).get(subtask_id) == 'developer'
        finally:
            await self._trace_drop(trace_id)

    async def test_task_state_closed_row_is_not_running(self, subtask_id: int):
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

    def test_task_state_dirty_ignores_own_journal(self):
        from src.project.task.task_worktree import _dirty_lines

        status = '?? .task-log.md\n?? .task-state.md\n'

        assert _dirty_lines('/tmp', status) == []

    def test_task_state_dirty_counts_real_changes(self):
        from src.project.task.task_worktree import _dirty_lines

        status = ' M src/project/task/task_pipeline.py\n?? src/project/task/task_pipeline_run.py\n'

        assert len(_dirty_lines('/tmp', status)) == 2

    def test_task_state_dirty_journal_does_not_hide_changes(self):
        from src.project.task.task_worktree import _dirty_lines

        status = '?? .task-log.md\n M src/app.py\n?? .task-state.md\n'

        assert _dirty_lines('/tmp', status) == [' M src/app.py']

    def test_task_state_dirty_similar_name_not_confused(self):
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

    def test_task_state_worktree_owner_reads_backlink(self, tmp_path):
        from src.project.task.task_worktree import _worktree_owner

        (tmp_path / '.git').write_text('gitdir: /app/.git/worktrees/feature_task_42\n')

        assert _worktree_owner(str(tmp_path)) == '/app'

    def test_task_state_worktree_owner_host_path(self, tmp_path):
        from src.project.task.task_worktree import _worktree_owner

        (tmp_path / '.git').write_text('gitdir: /home/vasyl/proj/.git/worktrees/feature_task_7')

        assert _worktree_owner(str(tmp_path)) == '/home/vasyl/proj'

    def test_task_state_worktree_owner_no_file(self, tmp_path):
        from src.project.task.task_worktree import _worktree_owner

        assert _worktree_owner(str(tmp_path)) == ''

    def test_task_state_worktree_owner_foreign_format(self, tmp_path):
        """Обычный репозиторий: `.git` — каталог, а не ссылка."""
        from src.project.task.task_worktree import _worktree_owner

        (tmp_path / '.git').write_text('ref: refs/heads/master')

        assert _worktree_owner(str(tmp_path)) == ''


class TestTreeDescendants:
    """Строка и всё, что уйдёт с ней каскадом, — собирается до удаления."""

    async def test_task_state_tree_parent_and_child(self, subtask_id: int):
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_tree import task_tree_descendants

        async with mysql_get_db_async() as db:
            await db.execute("SELECT parent_id FROM project_task WHERE id = %s", (subtask_id,))
            parent = int((await db.fetchone())['parent_id'])
            found = await task_tree_descendants(db, parent)

        assert found[0] == parent
        assert subtask_id in found

    async def test_task_state_tree_leaf_alone(self, subtask_id: int):
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

    async def _session_add(self, role: str, uuid_value: str, work_dir: str = '/tmp/pytest_shell',
                           seen_ago: int = 0, created_ago: int = 0):
        """
        Строка реестра. `seen_ago` и `created_ago` — на сколько секунд состарить.

        Возраст задаётся явно, потому что «замена» — про две метки сразу: наша
        оболочка должна быть уже не живой по пингу, а сменившая её — новее по
        `created_at`. Со всеми строками «сейчас» такой расклад не выразить.

        Время берём в UTC: реестр хранит его так (`datetime_utc_now`), и проверка
        свежести сравнивает с тем же источником. Возьми мы местное — строка легла бы
        на три часа в будущее и «протухшая» осталась бы живой.
        """
        from datetime import timedelta

        from datetime_.datetime_ import datetime_utc_now
        from mysql_.mysql_ import mysql_get_db_async

        now = datetime_utc_now()
        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO ai_claude_session_registry "
                "       (session_uuid, role, work_dir, status, agent_status, agent_status_reason, "
                "        created_at, last_seen_at) "
                "VALUES (%s, %s, %s, 'active', 'ready', 'idle', %s, %s)",
                (uuid_value, role, work_dir,
                 now - timedelta(seconds=created_ago), now - timedelta(seconds=seen_ago)))
            row_id = db.lastrowid
            await db.connection.commit()

        return row_id

    async def _session_drop(self, row_id: int):
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute("DELETE FROM ai_claude_session_registry WHERE id = %s", (row_id,))
            await db.connection.commit()

    async def test_task_state_own_session_is_not_replacement(self):
        from src.tool.claude_shell.claude_shell import _session_replaced

        row_id = await self._session_add('__pytest_shell', 'uuid-первый')
        try:
            assert await _session_replaced('__pytest_shell', '/tmp/pytest_shell', 'uuid-первый') is False
        finally:
            await self._session_drop(row_id)

    async def test_task_state_foreign_session_is_replacement(self):
        """
        Замена — это две вещи разом: нашей оболочки среди живых нет, а у роли есть
        поднятая **позже** нашей. Так выглядит перезапущенный человеком терминал.

        Одного «нашей не видно» мало: соседняя оболочка, поднятая раньше и всё это
        время простаивавшая, засчитывалась бы за замену, и круг срывался бы каждый
        раз, когда наша молчит дольше порога свежести.
        """
        from src.tool.claude_shell.claude_shell import _session_replaced

        ours = await self._session_add('__pytest_shell', 'uuid-первый',
                                       seen_ago=86400, created_ago=86400)
        newer = await self._session_add('__pytest_shell', 'uuid-второй', created_ago=60)
        try:
            assert await _session_replaced(
                '__pytest_shell', '/tmp/pytest_shell', 'uuid-первый') is True
        finally:
            await self._session_drop(ours)
            await self._session_drop(newer)

    async def test_task_state_older_neighbour_is_not_replacement(self):
        """
        Соседка старше нашей — не замена, а простаивавшая рядом оболочка. Без сверки
        по `created_at` круг срывался бы на каждой паузе в пинге.
        """
        from src.tool.claude_shell.claude_shell import _session_replaced

        ours = await self._session_add('__pytest_shell', 'uuid-первый',
                                       seen_ago=86400, created_ago=60)
        older = await self._session_add('__pytest_shell', 'uuid-второй', created_ago=86400)
        try:
            assert await _session_replaced(
                '__pytest_shell', '/tmp/pytest_shell', 'uuid-первый') is False
        finally:
            await self._session_drop(ours)
            await self._session_drop(older)

    async def test_task_state_missing_session_is_not_replacement(self):
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

    def test_task_state_shell_dir_project_gives_both_forms(self):
        from src.tool.claude_shell.claude_shell import _work_dir_variants

        variants = _work_dir_variants('/srv/app')

        assert variants == ['/srv/app', '/srv/app/.claude/worktrees']

    def test_task_state_shell_dir_worktree_not_doubled(self):
        """Иначе получился бы `worktrees/worktrees`, которого нет."""
        from src.tool.claude_shell.claude_shell import _work_dir_variants

        assert _work_dir_variants('/srv/app/.claude/worktrees') == ['/srv/app/.claude/worktrees']

    def test_task_state_shell_dir_trailing_slash_ignored(self):
        from src.tool.claude_shell.claude_shell import _work_dir_variants

        assert _work_dir_variants('/srv/app/')[0] == '/srv/app'

    def test_task_state_shell_dir_empty_path(self):
        from src.tool.claude_shell.claude_shell import _work_dir_variants

        assert _work_dir_variants('') == []

    def test_task_state_shell_dir_project_from_worktree_path(self):
        from src.project.task.task_role import _shell_project_dir

        assert _shell_project_dir('/srv/app/.claude/worktrees') == '/srv/app'

    def test_task_state_shell_dir_project_from_root_path(self):
        """Старая расстановка обязана работать по-прежнему."""
        from src.project.task.task_role import _shell_project_dir

        assert _shell_project_dir('/srv/app') == '/srv/app'

    def test_task_state_shell_dir_similar_tail_kept(self):
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

    def test_task_state_launch_command_leads_to_worktree(self):
        from src.project.team.team_project import _command_build

        cmd = _command_build('claude-shell --developer', '/srv/app')

        assert cmd == 'cd /srv/app/.claude/worktrees && claude-shell --developer'

    def test_task_state_launch_command_worktree_not_doubled(self):
        from src.project.team.team_project import _command_build

        cmd = _command_build('claude-shell --qa', '/srv/app/.claude/worktrees')

        assert cmd == 'cd /srv/app/.claude/worktrees && claude-shell --qa'

    def test_task_state_launch_command_without_dir(self):
        """Проект без каталога: подставлять путь из ниоткуда нельзя."""
        from src.project.team.team_project import _command_build

        assert _command_build('claude-shell --manager', '') == 'claude-shell --manager'

    def test_task_state_launch_command_empty_without_command(self):
        from src.project.team.team_project import _command_build

        assert _command_build('', '/srv/app') == ''

    def test_task_state_launch_command_trailing_slash(self):
        from src.project.team.team_project import _command_build

        cmd = _command_build('claude-shell --qa', '/srv/app/')

        assert cmd.startswith('cd /srv/app/.claude/worktrees &&')


class TestBackupOrder:
    """
    Список копий — от свежих к старым, по времени файла.

    Сортировка шла по имени, и порядок выглядел случайным: копии кладут не только
    кнопкой на странице, рядом лежат снимки, снятые руками перед рискованной
    правкой, и у них свои префиксы. По алфавиту `prod_rescue_2026-08-25`
    оказывается ниже `before_volume_2026-08-25`.
    """

    def _dir(self, tmp_path, files):
        """Каталог с копиями: имя -> время файла."""
        import os

        for name, when in files.items():
            path = tmp_path / name
            path.write_bytes(b'x')
            os.utime(path, (when, when))

        return str(tmp_path)

    def _list(self, monkeypatch, path):
        from src.uvicorn.routers.backup import backup

        monkeypatch.setattr(backup, 'BACKUPS_DIR', path)

        return [f['name'] for f in backup._backup_list()]

    def test_task_state_backup_newest_first_not_alphabetical(self, tmp_path, monkeypatch):
        path = self._dir(tmp_path, {
            'aaa_старый.sql.gz':  1_000_000,
            'zzz_свежий.sql.gz':  3_000_000,
            'mmm_средний.sql.gz': 2_000_000,
        })

        assert self._list(monkeypatch, path) == [
            'zzz_свежий.sql.gz', 'mmm_средний.sql.gz', 'aaa_старый.sql.gz']

    def test_task_state_backup_same_time_ordered_by_name(self, tmp_path, monkeypatch):
        """Иначе строки прыгали бы при каждом обновлении страницы."""
        path = self._dir(tmp_path, {
            'б_вторая.sql.gz': 2_000_000,
            'а_первая.sql.gz': 2_000_000,
            'в_третья.sql.gz': 2_000_000,
        })

        # Одно и то же время у всех: порядок задаёт имя, по убыванию.
        assert self._list(monkeypatch, path) == [
            'в_третья.sql.gz', 'б_вторая.sql.gz', 'а_первая.sql.gz']

    def test_task_state_backup_foreign_extensions_skipped(self, tmp_path, monkeypatch):
        path = self._dir(tmp_path, {
            'копия.sql.gz': 2_000_000,
            'заметка.txt':  3_000_000,
        })

        assert self._list(monkeypatch, path) == ['копия.sql.gz']

    def test_task_state_backup_missing_directory(self, tmp_path, monkeypatch):
        assert self._list(monkeypatch, str(tmp_path / 'нет-такого')) == []


class TestSubtaskVolume:
    """
    Дробление по объёму: крупная подзадача уходит на планирование, а не к разработчику.

    Исполнитель держит код в окне ограниченного размера. Замер токенизатором на
    наших прогонах: подзадача #1028 «имена во всех файлах src/**» требовала 459k
    токенов при окне 131k — двенадцать сорвавшихся кругов, ни одного удачного.
    Менеджер теперь оценивает объём и помечает неделимо-крупные `split_more`.
    """

    def test_task_state_subtask_normal_goes_to_developer(self):
        from src.project.task.task_state import _subtask_state

        assert _subtask_state({'title': 'правка'}) == 'planned'

    def test_task_state_subtask_big_goes_to_planning(self):
        """`new` — состояние, из которого работу забирает планирование."""
        from src.project.task.task_state import _subtask_state

        assert _subtask_state({'split_more': True}) == 'new'

    def test_task_state_subtask_context_lines_kept(self):
        import json

        from src.project.task.task_state import _subtask_metadata

        assert json.loads(_subtask_metadata({'context_lines': 800})) == {'context_lines': 800}

    def test_task_state_subtask_big_marked_in_metadata(self):
        import json

        from src.project.task.task_state import _subtask_metadata

        data = json.loads(_subtask_metadata({'split_more': True, 'context_lines': 4200}))
        assert data == {'split_more': True, 'context_lines': 4200}

    def test_task_state_subtask_final_dropped_volume_kept(self):
        """
        `final` не переживает разбиение, что бы менеджер ни прислал.

        Подзадача-приёмка проверяла сумму работы соседей, а суммы не существует ни в
        одном дереве: ветки режутся от главной, вливает их человек уже после
        конвейера. Такая строка не могла закрыться никогда (#1631). Промпт это
        запрещает словами, а `_subtask_metadata` — делом; оценка объёма рядом с ней
        при этом должна уцелеть.
        """
        import json

        from src.project.task.task_state import _subtask_metadata

        data = json.loads(_subtask_metadata({'final': True, 'context_lines': 300}))
        assert data == {'context_lines': 300}

    def test_task_state_subtask_no_empty_marks(self):
        """Ключа нет — пометки нет, как у флажков фаз."""
        from src.project.task.task_state import _subtask_metadata

        assert _subtask_metadata({'title': 'x', 'final': False, 'split_more': False}) is None

    def test_task_state_subtask_garbage_estimate_dropped(self):
        """Менеджер живой и вместо числа присылает «много» или ноль."""
        from src.project.task.task_state import _subtask_metadata

        assert _subtask_metadata({'context_lines': 'много'}) is None
        assert _subtask_metadata({'context_lines': 0}) is None
        assert _subtask_metadata({'context_lines': -5}) is None


class TestSubtaskPlanPhaseType:
    """
    Тип подзадачи, ушедшей в планирование.

    Подзадача рождается типом `dev` (`task_state_subtasks_create`), а планирование
    берёт её двумя дорогами: пометка «дробить дальше» и возврат из тупика
    (`task_goal_replan`). Роль-планировщик выбирается по типу (`task_role_by_type`),
    поэтому без перевода в `plan` план подзадачи пишет карточка разработчика.

    Поймано живьём на #1628: в отчёте «Задача взята в планирование (Разработчик)».
    """

    async def test_task_state_type_to_plan_covers_subtask(self, subtask_id):
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_state import task_state_type_to_plan

        async with mysql_get_db_async() as db:
            await db.execute(
                "UPDATE project_task "
                "   SET task_type_id = (SELECT id FROM project_task_type WHERE name = 'dev') "
                " WHERE id = %s", (subtask_id,))
            await db.connection.commit()

        assert await task_state_type_to_plan(subtask_id) is True
        assert await _type_name(subtask_id) == 'plan'

    async def test_task_state_planned_subtask_belongs_to_manager(self, subtask_id):
        """Смысл перевода: роль выбирается по типу, и после него это менеджер."""
        from mysql_.mysql_ import mysql_get_db_async
        from src.project.task.task_role import task_role_of_task
        from src.project.task.task_state import (task_state_subtask_get,
                                                 task_state_type_to_plan)

        async with mysql_get_db_async() as db:
            await db.execute(
                "UPDATE project_task "
                "   SET task_type_id = (SELECT id FROM project_task_type WHERE name = 'dev') "
                " WHERE id = %s", (subtask_id,))
            await db.connection.commit()

        assert await task_role_of_task(await task_state_subtask_get(subtask_id)) == 'developer'
        await task_state_type_to_plan(subtask_id)
        assert await task_role_of_task(await task_state_subtask_get(subtask_id)) == 'manager'

    async def test_task_state_type_to_dev_covers_subtask(self, subtask_id):
        """Парность обязательна: иначе подзадача осталась бы на «Планировании»."""
        from src.project.task.task_state import (task_state_type_to_dev,
                                                 task_state_type_to_plan)

        await task_state_type_to_plan(subtask_id)
        assert await task_state_type_to_dev(subtask_id) is True
        assert await _type_name(subtask_id) == 'dev'


async def _type_name(task_id: int) -> str:
    """Имя типа задачи — по нему выбирается роль и вкладка страницы."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT y.name FROM project_task t '
            '  JOIN project_task_type y ON y.id = t.task_type_id WHERE t.id = %s', (task_id,))
        row = await db.fetchone()

    return (row or {}).get('name') or ''

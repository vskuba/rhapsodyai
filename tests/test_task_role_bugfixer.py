"""
Роль bugfixer: тип `bug` принадлежит ей, а не QA, и в менеджерский захват она не попадает.

Модули проекта импортируются внутри тестов, а не сверху файла: они тянут `mysql_`,
который читает `MYSQL_HOST` один раз при импорте, а подмену хоста на `localhost` ставят
сессионные фикстуры `conftest.py`. Импорт на уровне модуля случился бы раньше них.
"""


class TestTaskRoleBugfixer:

    def test_bug_type_belongs_to_bugfixer(self):
        from src.project.task.task_role import task_role_by_type
        assert task_role_by_type('bug') == 'bugfixer'

    def test_qa_keeps_only_test_type(self):
        from src.project.task.task_role import TASK_ROLE_TYPES
        assert TASK_ROLE_TYPES['qa'] == ('test',)
        assert TASK_ROLE_TYPES['bugfixer'] == ('bug',)

    def test_unknown_type_still_goes_to_manager(self):
        from src.project.task.task_role import task_role_by_type
        assert task_role_by_type('') == 'manager'
        assert task_role_by_type('что-то новое') == 'manager'

    def test_planners_only_drops_bugfixer(self):
        from src.project.task.task_role import task_role_planners_only
        live = {2: ['manager', 'bugfixer'], 3: ['bugfixer'], 0: ['qa']}
        assert task_role_planners_only(live) == {2: ['manager'], 0: ['qa']}

    def test_planners_only_survives_empty_input(self):
        from src.project.task.task_role import task_role_planners_only
        assert task_role_planners_only({}) == {}
        assert task_role_planners_only(None) == {}

    def test_bug_type_sql_selects_by_name(self):
        from src.project.task.task_role import task_role_type_sql
        sql, params = task_role_type_sql(['bugfixer'])
        assert 'project_task_type' in sql
        assert params == ['bug']


class TestTaskMetadataBugfixFree:

    def test_key_name(self):
        from src.project.task.task_metadata import TASK_METADATA_KEY_BUGFIX
        assert TASK_METADATA_KEY_BUGFIX == 'to_bugfix'

    def test_free_sql_checks_explicit_false(self):
        from src.project.task.task_metadata import task_metadata_bugfix_free_sql
        sql = task_metadata_bugfix_free_sql()
        # Умолчание «включено», поэтому ищем именно отклонение — явный false.
        assert '$.to_bugfix' in sql
        assert '= FALSE' in sql
        assert sql.startswith('NOT COALESCE(')
        # COALESCE обёрнут вокруг сравнения, а не вокруг JSON_EXTRACT: иначе MySQL
        # приведёт JSON-значение к типу второго аргумента и условие станет ложным
        # для всех строк разом.
        assert 'JSON_EXTRACT' in sql and sql.index('JSON_EXTRACT') > sql.index('COALESCE')

    def test_free_sql_respects_column_name(self):
        from src.project.task.task_metadata import task_metadata_bugfix_free_sql
        assert 'JSON_VALID(t.metadata)' in task_metadata_bugfix_free_sql('t.metadata')

    def test_plan_free_sql_unchanged(self):
        from src.project.task.task_metadata import task_metadata_plan_free_sql
        sql = task_metadata_plan_free_sql()
        assert '$.to_planning' in sql
        assert sql.startswith('NOT COALESCE(')


class TestTaskStateBugfixing:

    def test_bugfixing_is_active(self):
        from src.project.task.task_state import task_state_kanban_status
        assert task_state_kanban_status('bugfixing') == 'active'

    def test_failed_stays_blocked(self):
        from src.project.task.task_state import task_state_kanban_status
        # Провалившийся баг человек видит как «Заблокировано» — отдельного маппинга
        # для него не нужно, `failed` уже ведёт туда.
        assert task_state_kanban_status('failed') == 'blocked'
        assert task_state_kanban_status('done') == 'done'

    def test_task_done_is_public_coroutine(self):
        import inspect
        from src.project.task.task_state import task_state_task_done
        assert inspect.iscoroutinefunction(task_state_task_done)
        assert list(inspect.signature(task_state_task_done).parameters) == ['task_id', 'report']


class TestTaskSettingTimeoutBugfix:

    def test_registry_has_bugfix_item(self):
        from src.project.task.task_setting_timeout import (
            TASK_SETTING_TIMEOUT_BUGFIX_RUN, TASK_SETTING_TIMEOUT_ITEMS)
        item = next(i for i in TASK_SETTING_TIMEOUT_ITEMS
                    if i['key'] == TASK_SETTING_TIMEOUT_BUGFIX_RUN)
        assert item['default'] == 3600
        assert item['role'] == 'bugfixer'
        assert item['group'] == 'Агент'

    def test_ladder_counts_bugfix_timeout(self):
        from src.project.task.task_setting_timeout import (
            TASK_SETTING_TIMEOUT_BUGFIX_RUN, TASK_SETTING_TIMEOUT_MANAGER_RUN,
            TASK_SETTING_TIMEOUT_DEVELOPER_RUN, TASK_SETTING_TIMEOUT_QA_RUN,
            TASK_SETTING_TIMEOUT_TASK_LOCK, TASK_SETTING_TIMEOUT_WORKER_JOB,
            task_setting_timeout_ladder_problem)
        values = {
            TASK_SETTING_TIMEOUT_MANAGER_RUN: 3600,
            TASK_SETTING_TIMEOUT_DEVELOPER_RUN: 3600,
            TASK_SETTING_TIMEOUT_QA_RUN: 3600,
            TASK_SETTING_TIMEOUT_BUGFIX_RUN: 3600,
            TASK_SETTING_TIMEOUT_WORKER_JOB: 3900,
            TASK_SETTING_TIMEOUT_TASK_LOCK: 4200,
        }
        assert task_setting_timeout_ladder_problem(values) == ''

        # Багфиксер, переросший job воркера, обязан ломать лестницу так же, как остальные.
        values[TASK_SETTING_TIMEOUT_BUGFIX_RUN] = 4000
        assert 'Ожидание агента' in task_setting_timeout_ladder_problem(values)


class TestTaskClaimBug:

    def test_reclaim_returns_bugfixing_to_new(self):
        from src.project.task.task_claim import TASK_CLAIM_STATE_RECLAIM
        # Брошенная блокировка возвращает баг в очередь, а не хоронит его.
        assert TASK_CLAIM_STATE_RECLAIM['bugfixing'] == 'new'

    def test_bugfixing_counts_as_inflight(self):
        from src.project.task.task_claim import TASK_CLAIM_INFLIGHT_STATES
        # Отсюда же берётся предел «Parallel LLM»: прогон занимает живую оболочку.
        assert 'bugfixing' in TASK_CLAIM_INFLIGHT_STATES

    def test_claim_task_bug_is_public_coroutine(self):
        import inspect
        from src.project.task.task_claim import task_claim_task_bug
        assert inspect.iscoroutinefunction(task_claim_task_bug)
        assert list(inspect.signature(task_claim_task_bug).parameters) == [
            'worker', 'roles_by_project']


class TestPipelineStateEnum:
    """
    Каждое состояние конвейера обязано быть в ENUM `project_task.pipeline_state`.

    Проверка появилась по факту: `bugfixing` завели в коде и забыли в схеме. Колонка —
    ENUM, а MySQL в нестрогом режиме пишет туда пустую строку вместо неизвестного
    значения и **не ругается**. Захват выглядел удачным (rowcount = 1, человеческий
    статус менялся), но строка залипала навсегда: реклейм ищет своё состояние,
    следующий тик — NULL или `new`, и пустую строку не видит ни один.

    Читаем сам DDL, а не INFORMATION_SCHEMA: тест обязан ловить расхождение с
    `migrations/0001.sql` — источником схемы, — а не с той базой, где его запустили.
    Живая база может быть догнана вручную и скрыть забытую правку файла.
    """

    def _enum_values(self) -> set:
        import re
        from pathlib import Path

        ddl = Path(__file__).resolve().parent.parent / 'migrations' / '0001.sql'
        text = ddl.read_text(encoding='utf-8')
        # Объявление растянуто на несколько строк, поэтому берём его целиком до `)`.
        match = re.search(r'`pipeline_state`\s+ENUM\s*\((.*?)\)\s', text, re.S)
        assert match, 'в migrations/0001.sql не найдено объявление pipeline_state'

        return set(re.findall(r"'([^']+)'", match.group(1)))

    def test_kanban_map_states_declared(self):
        from src.project.task.task_state import _TASK_STATE_KANBAN
        missing = set(_TASK_STATE_KANBAN) - self._enum_values()
        assert not missing, f'состояния есть в коде, но не в ENUM схемы: {sorted(missing)}'

    def test_reclaim_map_states_declared(self):
        from src.project.task.task_claim import (TASK_CLAIM_STATE_RECLAIM,
                                                 TASK_CLAIM_SUBTASK_STATE_RECLAIM)
        used = (set(TASK_CLAIM_STATE_RECLAIM) | set(TASK_CLAIM_STATE_RECLAIM.values())
                | set(TASK_CLAIM_SUBTASK_STATE_RECLAIM) | set(TASK_CLAIM_SUBTASK_STATE_RECLAIM.values()))
        missing = used - self._enum_values()
        assert not missing, f'состояния есть в коде, но не в ENUM схемы: {sorted(missing)}'

    def test_bugfixing_declared(self):
        assert 'bugfixing' in self._enum_values()


class TestTaskAgentBugfixer:

    def test_names(self):
        from src.project.task.task_agent_bugfixer import (
            TASK_BUGFIXER_AGENT_NAME, TASK_BUGFIXER_ROLE)
        assert TASK_BUGFIXER_AGENT_NAME == 'task_bug_fixer'
        assert TASK_BUGFIXER_ROLE == 'bugfixer'

    def test_run_signature(self):
        import inspect
        from src.project.task.task_agent_bugfixer import task_agent_bugfixer_run
        assert inspect.iscoroutinefunction(task_agent_bugfixer_run)
        assert list(inspect.signature(task_agent_bugfixer_run).parameters) == [
            'task', 'role', 'work_dir', 'task_dir']

    def test_result_parse_plain_json(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        out = _result_parse('json:{"ok": true, "report": {"summary": "починил"}, "error": ""}')
        assert out['ok'] is True
        assert 'починил' in out['output']
        assert out['error'] == ''

    def test_result_parse_report_ok_false_wins(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        # Прогон состоялся (внешний ok), но фикса нет (report.ok) — это `blocked`.
        out = _result_parse('json:{"ok": true, "report": {"ok": false, "error": "не воспроизвёлся"}}')
        assert out['ok'] is False
        assert out['error'] == 'не воспроизвёлся'

    def test_result_parse_garbage_is_not_an_exception(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        out = _result_parse('оболочка ответила текстом, а не JSON')
        assert out['ok'] is False
        assert 'не JSON' in out['error']

    def test_result_parse_missing_reason(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        out = _result_parse('json:{"ok": false}')
        assert out['ok'] is False
        assert out['error'] == 'Багфиксер не назвал причину отказа'

    def test_result_parse_env_not_ready(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        # «Чинить не на чем» — не вердикт по багу, а несостоявшийся прогон: конвейер
        # обязан отличить это от «не смог починить» и увести баг в повтор.
        out = _result_parse('json:{"ok": false, "env_ok": false, "report": {},'
                            ' "error": "Среда не готова: нет каталога"}')
        assert out['env_ok'] is False
        assert out['ok'] is False

    def test_result_parse_env_ok_by_default(self):
        from src.project.task.task_agent_bugfixer import _result_parse
        assert _result_parse('json:{"ok": true, "report": {}}')['env_ok'] is True
        assert _result_parse('мусор')['env_ok'] is True

    def test_pipeline_retries_on_bad_env(self):
        import inspect
        from src.project.task import task_pipeline
        source = inspect.getsource(task_pipeline._run_bugfix)
        assert "env_ok" in source
        # Ветка среды обязана стоять до записи результата, иначе баг успеет уйти в failed.
        assert source.index('env_ok') < source.index('task_state_task_fail')

    def test_trace_meta_text_of_scanner_bug(self):
        from src.project.task.task_agent_bugfixer import _trace_meta_text
        text = _trace_meta_text('{"domain": "workflow_trace", "workflow_title": "Анализ идеи",'
                                ' "agent_name": "planner", "error_summary": "Connection error."}')
        assert 'Workflow: Анализ идеи' in text
        assert 'Ошибка: Connection error.' in text

    def test_trace_meta_text_of_manual_bug_is_empty(self):
        from src.project.task.task_agent_bugfixer import _trace_meta_text
        # Пустая строка ложна для `%if%` — блок промпта про журнал не раскроется.
        assert _trace_meta_text(None) == ''
        assert _trace_meta_text('') == ''
        assert _trace_meta_text('не json') == ''


class TestTaskPipelineBugfix:

    def test_runner_registered(self):
        from src.project.task.task_pipeline import _RUNNERS
        assert 'bugfix' in _RUNNERS

    def test_bugfix_claimed_after_developer_before_plan_split(self):
        import inspect
        from src.project.task import task_pipeline
        source = inspect.getsource(task_pipeline._action_claim)
        order = [name for name in ('_claim_qa', '_claim_developer', '_claim_bugfix',
                                   '_claim_plan_split', '_claim_manager_review',
                                   '_claim_manager_plan')
                 if name in source]
        assert order == ['_claim_qa', '_claim_developer', '_claim_bugfix',
                         '_claim_plan_split', '_claim_manager_review', '_claim_manager_plan']

    def test_manager_claims_filter_planners(self):
        import inspect
        from src.project.task import task_pipeline
        # Менеджерские захваты обязаны отсеивать багфиксера, иначе баг уйдёт писать план.
        for fn in (task_pipeline._claim_manager_plan, task_pipeline._claim_manager_review):
            assert 'task_role_planners_only' in inspect.getsource(fn)


class TestTaskStopBugfixFlag:

    def test_bug_task_stop_clears_bugfix_flag(self):
        from src.project.task.task_stop import _task_stop_patch
        patch = _task_stop_patch({'id': 1, 'parent_id': None}, 'bugfixer')
        assert patch['stopped'] is True
        # Флажок вкладки снимаем явным false: умолчание у него «включено», и
        # оставленный ключ увёл бы баг обратно в работу следующим же тиком.
        assert patch['to_bugfix'] is False

    def test_developer_task_stop_unchanged(self):
        from src.project.task.task_stop import _task_stop_patch
        patch = _task_stop_patch({'id': 1, 'parent_id': None}, 'developer')
        assert patch['to_testing'] is False
        assert 'to_bugfix' not in patch

    def test_manager_task_stop_unchanged(self):
        from src.project.task.task_stop import _task_stop_patch
        patch = _task_stop_patch({'id': 1, 'parent_id': None}, 'manager')
        assert patch['to_development'] is None
        assert 'to_bugfix' not in patch


class TestTeamBugfixerCard:

    def test_role_is_base_for_every_project(self):
        from src.project.team.team_project import (
            TEAM_PROJECT_ROLE_BASE, TEAM_PROJECT_ROLE_ORDER, TEAM_PROJECT_ROLE_TITLE)
        assert 'bugfixer' in TEAM_PROJECT_ROLE_BASE
        assert TEAM_PROJECT_ROLE_TITLE['bugfixer'] == 'Багфиксер'
        # Порядок в ряду: менеджер, разработчик, QA, багфиксер — сначала конвейер
        # задачи целиком, а починка бага отдельной веткой в конце. Сверяем взаимный
        # порядок, а не сами числа: между ними оставлен зазор под роли вне списка.
        assert [role for role, _ in sorted(TEAM_PROJECT_ROLE_ORDER.items(), key=lambda kv: kv[1])] \
            == ['manager', 'developer', 'qa', 'bugfixer']
        assert list(TEAM_PROJECT_ROLE_BASE) == ['manager', 'developer', 'qa', 'bugfixer']

        from src.project.team.team_project import TEAM_PROJECT_ROLE_ORDER_OTHER
        assert (TEAM_PROJECT_ROLE_ORDER['developer']
                < TEAM_PROJECT_ROLE_ORDER_OTHER
                < TEAM_PROJECT_ROLE_ORDER['qa']), \
            'роль вне списка должна вставать между разработчиком и QA, а не слипаться с ними'

    def test_card_template_has_launch_command(self):
        from src.project.team.team_member import TEAM_MEMBER_ROLE_CARD
        name, command = TEAM_MEMBER_ROLE_CARD['bugfixer']
        assert name == 'Bugfixer'
        assert command == 'claude-shell --gx10 --bugfixer --autocompact 115k'

    def test_agent_bound_to_role(self):
        from src.project.team.team_agent import TEAM_AGENT_BY_ROLE
        assert TEAM_AGENT_BY_ROLE['bugfixer'] == 'task_bug_fixer'

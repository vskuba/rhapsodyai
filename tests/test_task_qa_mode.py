"""
Режим проверки QA (`lite`/`full`): от свитчера на странице до промптов workflow #57.

Проверяется то, из-за чего цель не считалась закрытой: выбранное значение не должно
оставаться в metadata — оно доезжает до `wf_vars` настоящим входом `task_agent_qa_run`
(тем же, что вызывает конвейер), и промпты шагов 57 обязаны его подставлять.

Модули проекта импортируются внутри тестов, а не сверху файла: они тянут `mysql_`,
который читает `MYSQL_HOST` один раз при импорте, а подмену хоста на `localhost`
ставят сессионные фикстуры `conftest.py`.
"""

import contextlib

import pytest

# Группа ставится файлу целиком, а не каждому классу (см. `.claude/docs/testing.md`).
# Правил роль конвейера — значит `pipeline`, хотя задеты и промпты workflow: контракт,
# который стережёт этот файл, — «режим доезжает до QA-агента», а он конвейерный.
pytestmark = pytest.mark.pipeline

LITE_STEPS = (445, 447, 516, 451)

# Строки для проверки автоматического захвата.
QA_MODE_ROW_TITLE = '__pytest_qa_mode__'
QA_MODE_SUBTASK_GOALS = '[{"text": "цель подзадачи", "done": false}]'
# Проект, которого нет, — как в `tests/test_task_role_state.py`. Отбор берёт подзадачу
# только там, где жива оболочка роли (`task_role_project_sql`), и свой номер проекта
# сужает выбор до наших строк: чужие в него не попадают вовсе.
#
# Корзина «без проекта» для этого не годится, хотя подмена конвейера держит оболочки
# именно в ней. Предел одновременных прогонов корзины — единица
# (`TASK_SETTING_PARALLEL_DEFAULT`), а в полёте числится любая заблокированная строка
# в переходном состоянии (`task_claim_inflight_by_project`): одна чужая строка,
# оставленная соседним тестом, закрывала бы отбор целиком, и проверка падала бы не на
# режиме QA, а на пустом захвате.
QA_MODE_PROJECT_ID = 987733


@pytest.fixture(autouse=True)
async def db_pool_release():
    """
    Закрыть пул MySQL после каждого теста.

    Пул в `mysql_` модульный и привязан к циклу событий, в котором создан, а
    pytest-asyncio даёт каждому тесту свой. Та же дисциплина, что в
    `tests/test_task_metadata.py` и `tests/test_planning.py`.
    """
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestTaskQaMode:
    """Режим читается из metadata родителя и остаётся `lite` при любом мусоре."""

    def test_absent_key_is_lite(self):
        from src.project.task.task_agent_qa import (QA_MODE_LITE, task_agent_qa_mode,
                                                    task_agent_qa_mode_full)

        for raw in (None, '', '{}', '{"other": 1}'):
            assert task_agent_qa_mode({'metadata': raw}) == QA_MODE_LITE
            assert task_agent_qa_mode_full({'metadata': raw}) == ''

    def test_full_is_read_from_parent_metadata(self):
        """`full` — отклонение от умолчания; флаг для `%if%` загорается только в нём."""
        from src.project.task.task_agent_qa import (QA_MODE_FULL, task_agent_qa_mode,
                                                    task_agent_qa_mode_full)

        assert task_agent_qa_mode({'metadata': '{"qa_mode": "full"}'}) == QA_MODE_FULL
        assert task_agent_qa_mode_full({'metadata': '{"qa_mode": "full"}'}) == 'yes'

    def test_junk_values_fall_back_to_lite(self):
        """Мешок `metadata` переживает ручную правку: `false`, число, иное слово, пробел."""
        from src.project.task.task_agent_qa import QA_MODE_LITE, task_agent_qa_mode

        for raw in ('{"qa_mode": false}', '{"qa_mode": null}', '{"qa_mode": 2}',
                    '{"qa_mode": "полный"}', '{"qa_mode": "  "}'):
            assert task_agent_qa_mode({'metadata': raw}) == QA_MODE_LITE

    def test_full_is_case_insensitive(self):
        """Регистр и пробелы правки не превращают полный режим в лёгкий."""
        from src.project.task.task_agent_qa import QA_MODE_FULL, task_agent_qa_mode

        for raw in ('{"qa_mode": "FULL"}', '{"qa_mode": " full "}'):
            assert task_agent_qa_mode({'metadata': raw}) == QA_MODE_FULL

    def test_mode_without_metadata_column(self):
        """Нет колонки вовсе (задача из SELECT без metadata) — читатель не падает."""
        from src.project.task.task_agent_qa import (QA_MODE_LITE, task_agent_qa_mode,
                                                    task_agent_qa_mode_full)

        assert task_agent_qa_mode({}) == QA_MODE_LITE
        assert task_agent_qa_mode(None) == QA_MODE_LITE
        assert task_agent_qa_mode_full({}) == ''

    def test_key_is_documented_next_to_writer(self):
        """Ключ пишет фронт под тем же именем, под которым его читает бэкенд."""
        from src.project.task.task_metadata import TASK_METADATA_KEY_QA_MODE

        assert TASK_METADATA_KEY_QA_MODE == 'qa_mode'


class TestTaskQaModeReachesWorkflow:
    """
    Выбор доходит до workflow: `wf_vars` собираются настоящим входом QA-агента.

    Движок прогона, подъём оболочки и выбор модели заглушены — они тратят время и
    обращаются наружу. Всё остальное настоящее: `_agent_get`, `ai_workflow_load`,
    сборка `wf_vars` из metadata родителя и движковый рендер промптов.
    """

    async def test_default_task_gets_lite_variables(self):
        captured = await _wf_vars_capture({'id': 1, 'metadata': None}, {'id': 1, 'title': 'x'})
        variables = captured['variables']
        assert variables['subtask_qa_mode'] == 'lite'
        assert variables['subtask_qa_full'] == ''

    async def test_full_mode_of_parent_reaches_variables(self):
        captured = await _wf_vars_capture({'id': 1, 'metadata': '{"qa_mode": "full"}'},
                                          {'id': 1, 'title': 'x'})
        assert captured['variables']['subtask_qa_mode'] == 'full'
        assert captured['variables']['subtask_qa_full'] == 'yes'

    async def test_rendered_prompts_differ_by_mode(self):
        """
        Промпт Lite не обещает прогонов, Full обещает — иначе режим выбирается ни на что не влияя.
        """
        from src.ai.ai_workflow import ai_workflow_variables_render

        rendered = {}
        for mode, meta in (('lite', None), ('full', '{"qa_mode": "full"}')):
            captured = await _wf_vars_capture({'id': 1, 'metadata': meta}, {'id': 1, 'title': 'x'})
            variables = captured['variables']
            steps = {s['id']: ai_workflow_variables_render(s['metadata'], variables)
                     for s in captured['steps'] if s.get('id') in LITE_STEPS}
            assert len(steps) == len(LITE_STEPS), 'шаги 57 не загрузились — проверка не о чём'
            rendered[mode] = {sid: str(payload) for sid, payload in steps.items()}
            for sid, blob in rendered[mode].items():
                assert '%if' not in blob and '%endif' not in blob, f'шаг {sid}: условие не развернулось'
        assert 'pytest' not in rendered['lite'][447], 'Lite всё ещё зовёт pytest'
        assert 'pytest' in rendered['full'][447], 'Full перестал звать pytest'
        assert 'РЕЖИМ ПРОВЕРКИ: lite' in rendered['lite'][445]
        assert 'РЕЖИМ ПРОВЕРКИ: full' in rendered['full'][445]


class TestTaskQaModePromptsMigrated:
    """
    Шаги #57 подставляют переменную — миграция `20260831*_wf57_qa_mode.sql` применена.

    Без этого workflow принимает `subtask_qa_mode`, но в своих промптах не использует:
    режим на странице есть, а поведение агента прежнее.
    """

    async def test_workflow_steps_carry_the_branch(self):
        from mysql_.mysql_ import mysql_get_db_async

        async with mysql_get_db_async() as db:
            await db.execute("SELECT id, metadata FROM agent_workflow_step "
                             "  WHERE workflow_id = 57 AND id IN (445, 447, 516, 451)")
            rows = await db.fetchall()

        assert len(rows) == len(LITE_STEPS), 'шаги 445/447/516/451 не найдены — проверка не о чём'
        missing = [row['id'] for row in rows
                   if 'subtask_qa_full' not in str(row['metadata'])]
        assert not missing, (f'шаги {missing} не знают про `subtask_qa_full`: '
                             f'миграция wf57_qa_mode не применена')


class TestTaskQaModeAtWorkerClaim:
    """
    Автоматический захват: режим доезжает до QA-агента без участия человека.

    Проверки выше зовут `task_agent_qa_run` руками — так режим задаёт тест, а не
    конвейер. Живьём подзадачу к проверке отбирает воркер, и родителя для прогона он
    читает сам (`_run_qa` -> `task_state_task_get`). Порвётся это чтение — колонка
    `metadata` пропадёт из выборки, родителем окажется чужая строка, — и на странице
    режим будет стоять `full`, а проверка пойдёт лёгкая, ничего об этом не сказав.

    Поэтому путь берётся целиком и настоящий, одним проходом: отбор `_action_claim`,
    раннер `_run_qa`, вход агента `task_agent_qa_run` — и переменные ловятся на том же
    прогоне, который начал воркер. Подменены только выходы наружу — движок прогона,
    выкладка подзадачи и осмотр её ветки: они ходят в LLM, в git и в живой Claude Code,
    а проверяем мы не их.
    """

    async def test_full_mode_reaches_variables_after_claim(self):
        """Свитчер стоит в `full` — воркер обязан привезти агенту тот же `full`."""
        captured = await _claim_and_capture('{"qa_mode": "full"}')

        assert captured['action']['kind'] == 'qa', 'подзадачу отобрали не как работу QA'
        assert captured['variables']['subtask_qa_mode'] == 'full'
        assert captured['variables']['subtask_qa_full'] == 'yes'

    async def test_default_mode_reaches_variables_after_claim(self):
        """Ключа в мешке нет — тот же путь обязан дать `lite`, а не пустое значение."""
        captured = await _claim_and_capture(None)

        assert captured['variables']['subtask_qa_mode'] == 'lite'
        assert captured['variables']['subtask_qa_full'] == ''

    async def test_claim_reads_the_mode_from_the_parent(self):
        """
        Режим приезжает из мешка родителя, а не подзадачи.

        Проверяем по самим переменным прогона: `task_id` в них — это родитель,
        `subtask_id` — проверяемая строка. Подсунутая вместо родителя подзадача (её
        `metadata` пишет конвейер — ветка, merge request) молча вернула бы `lite` при
        любом выборе человека, и обе переменные стали бы одним номером.
        """
        captured = await _claim_and_capture('{"qa_mode": "full"}')

        assert captured['variables']['task_id'] == str(captured['parent_id'])
        assert captured['variables']['subtask_id'] == str(captured['subtask_id'])
        assert captured['variables']['subtask_qa_mode'] == 'full'


class _QaStop(Exception):
    """Сигнал «переменные пойманы, дальше не надо»: движок прогона подменён."""


@contextlib.contextmanager
def _qa_engine_stubbed(captured: dict):
    """
    Подменить движок прогона QA-агента: `wf_vars` ловим, в LLM и в оболочку не идём.

    Кладёт в `captured` ключи `variables` и `steps`, после чего роняет прогон `_QaStop`.
    Ставится и вокруг прямого вызова `task_agent_qa_run`, и вокруг круга конвейера —
    подмена одна на оба пути, иначе они разъехались бы в том, что именно заглушено.
    """
    import asyncio

    import src.project.task.task_agent_qa as qa

    class _Manager:
        async def framework_model_create(self, params, *args, **kwargs):
            captured['variables'] = params['workflow_variables']
            captured['steps'] = params['workflow_steps']
            return params

        def framework_workflow_run(self, model, future, loop):
            raise _QaStop()

    original_manager, original_restart = qa.AiFrameworkAgentManager, qa.team_session_restart_role
    qa.AiFrameworkAgentManager = _Manager
    qa.team_session_restart_role = lambda *a, **k: asyncio.sleep(0)
    try:
        yield
    finally:
        qa.AiFrameworkAgentManager, qa.team_session_restart_role = original_manager, original_restart


async def _wf_vars_capture(parent: dict, subtask: dict) -> dict:
    """
    Отдать `wf_vars`, которые `task_agent_qa_run` сует в модель, и не запускать прогон.

    Returns: `{'variables': ..., 'steps': ...}` — переменные прогона и шаги workflow,
    как их получил бы движок.
    """
    import src.project.task.task_agent_qa as qa

    captured: dict = {}
    with _qa_engine_stubbed(captured), contextlib.suppress(_QaStop):
        await qa.task_agent_qa_run(parent, subtask)

    return captured


async def _claim_and_capture(metadata: str | None) -> dict:
    """
    Провести подзадачу автоматическим путём и вернуть, с чем позвали QA-агента.

    Args:
        metadata: мешок родителя — то, что записал бы свитчер на странице задач.

    Returns: `{'action', 'variables', 'steps', 'outcome', 'parent_id', 'subtask_id'}` —
        отобранное действие, переменные его прогона и итог круга.

    Отбор настоящий (`pipeline_claim` -> `_action_claim`), потому что проверяется он.
    Захват один, без перебора: оболочки заведены на свой номер проекта, а круг QA идёт
    в отборе первым, и чужой строке взяться неоткуда.

    Подменяем четыре выхода наружу. Движок прогона (`_qa_engine_stubbed`) — иначе круг
    уйдёт в LLM, а `task_agent_qa_run` при этом остаётся настоящим, и переменные
    собирает он. Выкладку подзадачи (`_subtask_dir`) и осмотр её ветки
    (`task_worktree_state`) — они зовут git по выдуманному номеру: первый завёл бы
    каталог, второй прочёл бы «кода нет» и закрыл бы подзадачу, не дойдя до QA вовсе.

    Четвёртый — перезапуск оболочки, и он здесь не для скорости. Прогон обрывается
    `_QaStop` уже после сборки переменных, `_run_qa` читает это как сорвавшийся круг и
    уводит подзадачу в `_retry_subtask`, а тот перезапускает оболочку роли. Каталога у
    выдуманного проекта нет, и адрес выходит «роль `qa`, каталог любой» — то есть
    маркер уходит в самую свежую живую оболочку QA на стенде и сносит ей ход посреди
    работы (см. докстринг `team_session_restart_role`). Под удар попадала и та
    оболочка, которой потом проверять эту же ветку.

    Подменять надо именно `pipeline.team_session_restart_role`: `_retry_subtask` берёт
    функцию из своего пространства имён, и подмена в модуле агента (`_qa_engine_stubbed`)
    туда не достаёт. Замером: с заглушкой круг идёт 0.2 s, без неё — 14.2 s ожидания
    подтверждения от чужой оболочки.
    """
    from unittest.mock import patch

    import src.project.task.task_pipeline as pipeline
    from src.project.task.task_agent_qa import task_agent_qa_run
    from src.project.task.task_pipeline import task_pipeline_action_run
    from tests.pipeline_mock import pipeline_agents_mocked, pipeline_claim

    captured: dict = {}

    async def _dir(work_dir, subtask_id):
        return ''

    async def _worktree(subtask_id, work_dir='', since=''):
        return {'done_has': 'yes'}

    async def _restart(role, work_dir='', wait=True, session_uuid=''):
        captured.setdefault('restarts', []).append({'role': role, 'work_dir': work_dir})

        return {'role': role, 'session_uuid': '', 'restarted': False, 'ready': False,
                'reason': 'no_session', 'elapsed': 0}

    parent_id, subtask_id = await _rows_create(metadata)
    captured['parent_id'], captured['subtask_id'] = parent_id, subtask_id
    try:
        async with pipeline_agents_mocked(roles={QA_MODE_PROJECT_ID: {'qa': ['mock-qa']}}):
            # Подмену самого агента снимаем: общая заглушка конвейера отвечает за него
            # готовым вердиктом и до сборки переменных не доходит вовсе, а проверяем мы
            # именно её. Вместо агента заглушен движок его прогона.
            with patch.object(pipeline, 'task_agent_qa_run', task_agent_qa_run), \
                 _qa_engine_stubbed(captured), \
                 patch.object(pipeline, 'team_session_restart_role', _restart), \
                 patch.object(pipeline, '_subtask_dir', _dir), \
                 patch.object(pipeline, 'task_worktree_state', _worktree):
                action = await pipeline_claim()
                assert action and int(action.get('subtask_id') or 0) == subtask_id, \
                    f'отбор взял не нашу подзадачу, а {action!r} — проверять нечего'
                captured['action'] = action
                captured['outcome'] = await task_pipeline_action_run(action)
    finally:
        await _rows_drop(parent_id)

    assert 'variables' in captured, \
        f"круг QA не дошёл до сборки переменных: {captured.get('outcome')!r}"

    return captured


async def _rows_create(metadata: str | None) -> tuple[int, int]:
    """
    Завести задачу с мешком и её подзадачу, ждущую проверки.

    Строки настоящие: отбор ходит в базу, и выдуманный номер молча ничего бы не нашёл
    — тест был бы зелёным при любом состоянии кода.

    Состояние родителя `processing` — «дети работают»: в нём его не отберут ни к
    планированию, ни к пересмотру, и в отборе останется одна наша подзадача.

    Проект — `QA_MODE_PROJECT_ID`, которого нет: он и сужает отбор до этих двух строк.
    Каталога у такого проекта не найдётся, и `task_role_project_work_dir` честно вернёт
    пустую строку — адресация останется только по роли, как у задач без проекта.
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task (project_id, parent_id, title, description, goals, report, '
            '                          position, status, task_type_id, pipeline_state, '
            '                          pipeline_plan, pipeline_error, pipeline_from_plan, metadata) '
            "SELECT %s, NULL, %s, '', '[]', '', 0, 'queued', id, 'processing', '', '', 0, %s "
            "  FROM project_task_type WHERE name = 'dev'",
            (QA_MODE_PROJECT_ID, QA_MODE_ROW_TITLE, metadata))
        parent_id = db.lastrowid
        await db.execute(
            'INSERT INTO project_task (project_id, parent_id, title, description, goals, report, '
            '                          position, status, task_type_id, pipeline_state, '
            '                          pipeline_plan, pipeline_error, pipeline_from_plan) '
            "SELECT %s, %s, %s, '', %s, '', 0, 'queued', id, 'qa_pending', '', '', 1 "
            "  FROM project_task_type WHERE name = 'test'",
            (QA_MODE_PROJECT_ID, parent_id, QA_MODE_ROW_TITLE, QA_MODE_SUBTASK_GOALS))
        subtask_id = db.lastrowid
        await db.connection.commit()

    return parent_id, subtask_id


async def _rows_drop(parent_id: int) -> None:
    """
    Убрать за собой. Хватает родителя: подзадачи и попытки уносит каскад по `parent_id`
    и `fk_pta_task`.
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM project_task WHERE id = %s', (parent_id,))
        await db.connection.commit()

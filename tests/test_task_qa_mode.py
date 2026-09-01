"""
Режим проверки QA (`lite`/`full`): от свитчера на странице до промптов workflow #57.

Проверяется то, из-за чего цель не считалась закрытой: выбранное значение не должно
оставаться в metadata — оно доезжает до `wf_vars` настоящим входом `task_agent_qa_run`
(тем же, что вызывает конвейер), и промпты шагов 57 обязаны его подставлять.

Модули проекта импортируются внутри тестов, а не сверху файла: они тянут `mysql_`,
который читает `MYSQL_HOST` один раз при импорте, а подмену хоста на `localhost`
ставят сессионные фикстуры `conftest.py`.
"""

import pytest

# Группа ставится файлу целиком, а не каждому классу (см. `.claude/docs/testing.md`).
# Правил роль конвейера — значит `pipeline`, хотя задеты и промпты workflow: контракт,
# который стережёт этот файл, — «режим доезжает до QA-агента», а он конвейерный.
pytestmark = pytest.mark.pipeline

LITE_STEPS = (445, 447, 516, 451)

# Строки для проверки автоматического захвата. Заводятся без проекта: отбор берёт
# подзадачу только там, где жива оболочка роли, а подмена конвейера
# (`tests/pipeline_mock.py`) держит оболочки в корзине «без проекта». Заодно это
# отсекает настоящие задачи установки — они принадлежат проектам и в отбор не попадут.
QA_MODE_ROW_TITLE = '__pytest_qa_mode__'
QA_MODE_SUBTASK_GOALS = '[{"text": "цель подзадачи", "done": false}]'
# Сколько отборов подряд смотрим в поисках своей строки. Рядом крутятся чужие
# project-less строки других тестов, и первый же захват не обязан быть нашим.
QA_MODE_CLAIM_STEPS = 10


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

    Поэтому путь берётся целиком и настоящий: отбор `_action_claim`, раннер `_run_qa`,
    сборка `wf_vars` тем же `task_agent_qa_run`. Подменены только выходы наружу —
    прогон агента, выкладка подзадачи и осмотр её ветки: они ходят в git и в живой
    Claude Code, а проверяем мы не их.
    """

    async def test_full_mode_reaches_variables_after_claim(self):
        """Свитчер стоит в `full` — воркер обязан привезти агенту тот же `full`."""
        captured = await _claim_and_capture('{"qa_mode": "full"}')

        assert captured['action']['kind'] == 'qa', 'подзадачу отобрали не как работу QA'
        variables = await _wf_vars_capture(captured['task'], captured['subtask'])
        assert variables['variables']['subtask_qa_mode'] == 'full'
        assert variables['variables']['subtask_qa_full'] == 'yes'

    async def test_default_mode_reaches_variables_after_claim(self):
        """Ключа в мешке нет — тот же путь обязан дать `lite`, а не пустое значение."""
        captured = await _claim_and_capture(None)

        variables = await _wf_vars_capture(captured['task'], captured['subtask'])
        assert variables['variables']['subtask_qa_mode'] == 'lite'
        assert variables['variables']['subtask_qa_full'] == ''

    async def test_claim_hands_the_parent_not_the_subtask(self):
        """
        Родителем в прогон уходит именно родитель.

        Режим лежит в его мешке, и подсунутая вместо него подзадача (её `metadata`
        пишет конвейер — ветка, merge request) молча вернула бы `lite` при любом
        выборе человека.
        """
        from src.project.task.task_agent_qa import task_agent_qa_mode

        captured = await _claim_and_capture('{"qa_mode": "full"}')

        assert captured['task']['id'] == captured['subtask']['parent_id']
        assert task_agent_qa_mode(captured['task']) == 'full'
        assert task_agent_qa_mode(captured['subtask']) == 'lite', \
            'у подзадачи своего режима нет — иначе читатель смотрит не в тот мешок'


async def _wf_vars_capture(parent: dict, subtask: dict) -> dict:
    """
    Отдать `wf_vars`, которые `task_agent_qa_run` сует в модель, и не запускать прогон.

    Returns: `{'variables': ..., 'steps': ...}` — переменные прогона и шаги workflow,
    как их получил бы движок.
    """
    import asyncio

    import src.project.task.task_agent_qa as qa

    captured = {}

    class _Stop(Exception):
        pass

    class _Manager:
        async def framework_model_create(self, params, *args, **kwargs):
            captured['variables'] = params['workflow_variables']
            captured['steps'] = params['workflow_steps']
            return params

        def framework_workflow_run(self, model, future, loop):
            raise _Stop()

    original_manager, original_restart = qa.AiFrameworkAgentManager, qa.team_session_restart_role
    qa.AiFrameworkAgentManager = _Manager
    qa.team_session_restart_role = lambda *a, **k: asyncio.sleep(0)
    try:
        try:
            await qa.task_agent_qa_run(parent, subtask)
        except _Stop:
            pass
    finally:
        qa.AiFrameworkAgentManager, qa.team_session_restart_role = original_manager, original_restart

    return captured


async def _claim_and_capture(metadata: str | None) -> dict:
    """
    Провести подзадачу автоматическим путём и вернуть, с чем позвали QA-агента.

    Args:
        metadata: мешок родителя — то, что записал бы свитчер на странице задач.

    Returns: `{'action', 'task', 'subtask', 'outcome'}` — отобранное действие, его
        аргументы и итог круга.

    Отбор настоящий (`pipeline_claim` -> `_action_claim`), потому что проверяется он.
    Чужие строки, попавшие в тот же отбор, пропускаем: рядом крутятся project-less
    задачи других тестов, и первое действие не обязано быть нашим.

    Подменяем три выхода наружу. Сам агент — иначе круг уйдёт в LLM. Выкладку
    подзадачи (`_subtask_dir`) и осмотр её ветки (`task_worktree_state`) — они зовут
    git по выдуманному номеру: первый завёл бы каталог, второй прочёл бы «кода нет»
    и закрыл бы подзадачу, не дойдя до QA вовсе.
    """
    from unittest.mock import patch

    import src.project.task.task_pipeline as pipeline
    from src.project.task.task_pipeline import task_pipeline_action_run
    from tests.pipeline_mock import PIPELINE_MOCK_QA, pipeline_agents_mocked, pipeline_claim

    captured: dict = {}

    async def _qa(task, subtask, *args, **kwargs):
        captured['task'], captured['subtask'] = task, subtask

        return dict(PIPELINE_MOCK_QA)

    async def _dir(work_dir, subtask_id):
        return ''

    async def _worktree(subtask_id, work_dir='', since=''):
        return {'done_has': 'yes'}

    parent_id, subtask_id = await _rows_create(metadata)
    try:
        async with pipeline_agents_mocked():
            with patch.object(pipeline, 'task_agent_qa_run', _qa), \
                 patch.object(pipeline, '_subtask_dir', _dir), \
                 patch.object(pipeline, 'task_worktree_state', _worktree):
                for _ in range(QA_MODE_CLAIM_STEPS):
                    action = await pipeline_claim()
                    if not action:
                        break
                    if int(action.get('subtask_id') or 0) != subtask_id:
                        continue
                    captured['action'] = action
                    captured['outcome'] = await task_pipeline_action_run(action)
                    break
    finally:
        await _rows_drop(parent_id)

    assert 'action' in captured, ('подзадача в `qa_pending` не отобралась к QA — '
                                 'проверять нечего, дело в отборе, а не в режиме')
    assert 'task' in captured, f"круг QA не дошёл до агента: {captured.get('outcome')!r}"

    return captured


async def _rows_create(metadata: str | None) -> tuple[int, int]:
    """
    Завести задачу с мешком и её подзадачу, ждущую проверки.

    Строки настоящие: отбор ходит в базу, и выдуманный номер молча ничего бы не нашёл
    — тест был бы зелёным при любом состоянии кода.

    Состояние родителя `processing` — «дети работают»: в нём его не отберут ни к
    планированию, ни к пересмотру, и в отборе останется одна наша подзадача.
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task (project_id, parent_id, title, description, goals, report, '
            '                          position, status, task_type_id, pipeline_state, '
            '                          pipeline_plan, pipeline_error, pipeline_from_plan, metadata) '
            "SELECT NULL, NULL, %s, '', '[]', '', 0, 'queued', id, 'processing', '', '', 0, %s "
            "  FROM project_task_type WHERE name = 'dev'",
            (QA_MODE_ROW_TITLE, metadata))
        parent_id = db.lastrowid
        await db.execute(
            'INSERT INTO project_task (project_id, parent_id, title, description, goals, report, '
            '                          position, status, task_type_id, pipeline_state, '
            '                          pipeline_plan, pipeline_error, pipeline_from_plan) '
            "SELECT NULL, %s, %s, '', %s, '', 0, 'queued', id, 'qa_pending', '', '', 1 "
            "  FROM project_task_type WHERE name = 'test'",
            (parent_id, QA_MODE_ROW_TITLE, QA_MODE_SUBTASK_GOALS))
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

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

    @staticmethod
    async def _capture(parent: dict, subtask: dict) -> dict:
        """Отдать `wf_vars`, которые `task_agent_qa_run` сует в модель, и не запускать прогон."""
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

    async def test_default_task_gets_lite_variables(self):
        captured = await self._capture({'id': 1, 'metadata': None}, {'id': 1, 'title': 'x'})
        variables = captured['variables']
        assert variables['subtask_qa_mode'] == 'lite'
        assert variables['subtask_qa_full'] == ''

    async def test_full_mode_of_parent_reaches_variables(self):
        captured = await self._capture({'id': 1, 'metadata': '{"qa_mode": "full"}'},
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
            captured = await self._capture({'id': 1, 'metadata': meta}, {'id': 1, 'title': 'x'})
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

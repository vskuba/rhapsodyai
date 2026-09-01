"""
Режим проверки QA (`lite`/`full`): от свитчера на странице до промптов workflow #57.

Проверяется то, из-за чего цель не считалась закрытой: выбранное значение не должно
оставаться в metadata — оно доезжает до `wf_vars` настоящим входом `task_agent_qa_run`
(тем же, что вызывает конвейер), и промпты шагов 57 обязаны его подставлять.

Модули проекта импортируются внутри тестов, а не сверху файла: они тянут `mysql_`,
который читает `MYSQL_HOST` один раз при импорте, а подмену хоста на `localhost`
ставят сессионные фикстуры `conftest.py`.

Восстановление после перезагрузки страницы доказывается **до разметки ряда, а не до DOM
после живого щелчка** — границы расписаны у `test_restored_row_renders_switcher_in_same_state`.
"""

import os
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

# Группа ставится файлу целиком, а не каждому классу (см. `.claude/docs/testing.md`).
# Правил роль конвейера — значит `pipeline`, хотя задеты и промпты workflow: контракт,
# который стережёт этот файл, — «режим доезжает до QA-агента», а он конвейерный.
pytestmark = pytest.mark.pipeline

LITE_STEPS = (445, 447, 516, 451)

# Адрес сервера подменясем окружением — так же, как `tests/test_task_metadata.py`:
# QA конвейера гоняет сюиту против сервера ветки, а не общего `:8011`.
BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')


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


class TestQaModeNormalizationAgreesBothBanks:
    """
    Что показывает свитчер и что выбирает движок — одно и то же значение.

    Глубину проверки выбирает `task_agent_qa_mode`, а человек судит по кнопке. Разойдись
    нормы — человек смотрит на `Full`, агент проверяет по `lite`, и по одному берегу
    расхождения не увидеть: список из одной строки `['full']` фронт читал как `full`,
    движок — как `lite`.

    Поэтому половина страницы берется наяву: из шаблона вырываются `esc`,
    `TASK_META_KEY_QA_MODE`, `_qaModeNormalize` и `renderQaModeSwitcher`, их исполняет
    node, и сравнивается `data-mode` настоящей разметки. Держать копию функции дешевле,
    но копия пропустила бы правку шаблона молча — а она и есть половина нормы. Рядом
    проверяется подпись на кнопке: она выведена из того же значения и, расходясь с
    атрибутом, врёт человеку.

    Покрыто рядовое содержимое мешка — ручная правка, ответы LLM, старые записи.
    Экзотика вроде `NaN` или `1e+21` в metadata не бывает и тестом не держится.
    """

    CORPUS = [None, '', '   ', 'full', 'FULL', ' full ', '\tfull\n', 'fulllite', 'lite',
              'Lite', 'полный', 'true', 'null', '0', True, False, 0, -0.0, 1, 2, 1.0,
              '0.0', [], ['full'], ['FULL'], ['full', 'lite'], ['  full  '], [None],
              [0], [True], {}, {'mode': 'full'}, {'qa_mode': 'full'}]

    @staticmethod
    def _front_rows(rows: list) -> list:
        """
        Отдать разметку свитчера для готовых строк задачи — так, как её делает браузер.
        """
        import json
        import re
        import shutil
        import subprocess
        from pathlib import Path

        # Нет node — нет и второй половины: пропускаем со внятной причиной, а не падим
        # сюиту чужой для теста средой. Шаги конвейера и страница живут на этой машине,
        # где node есть, поэтому пропуск виден глазами, а не прячется.
        if not shutil.which('node'):
            pytest.skip('node недоступен — норму фронтенда проверить нечем')
        page = Path('data/uvicorn/template/admin/project/task.html').read_text(encoding='utf-8')
        parts = []
        for pattern, name in (
                (r"\nconst TASK_META_KEY_QA_MODE = 'qa_mode';", 'ключ режима'),
                (r'\nfunction esc\(s\)\s*\{.*?\n\}', '`esc`'),
                (r'\nfunction _qaModeNormalize\(value\)\s*\{.*?\n\}', '`_qaModeNormalize`'),
                (r'\nfunction renderQaModeSwitcher\(t\)\s*\{.*?\n\}', '`renderQaModeSwitcher`')):
            found = re.search(pattern, page, re.DOTALL)
            assert found, (f'{name} в шаблоне не найдена: страницу переписали, и тест больше '
                           f'не сторожит норму — править его вместе с шаблоном')
            parts.append(found.group(0))
        script = ('let buf = "";\n'
                  'process.stdin.on("data", c => buf += c);\n'
                  'process.stdin.on("end", () => {\n'
                  + '\n'.join(parts) + '\n'
                  '  const rows = JSON.parse(buf);\n'
                  '  process.stdout.write(JSON.stringify(rows.map(t => renderQaModeSwitcher(t))));\n'
                  '});\n')
        done = subprocess.run(['node', '-e', script], input=json.dumps(rows, ensure_ascii=False),
                              capture_output=True, text=True, timeout=30)
        assert done.returncode == 0, f'node: {done.stderr}'
        return json.loads(done.stdout)

    @classmethod
    def _front_markup(cls, values: list) -> list:
        """Разметка свитчера для каждого значения мешка — ряд без проекта и без родителя."""
        return cls._front_rows([{'id': 1, 'parent_id': None, 'metadata': {'qa_mode': value}}
                                for value in values])

    @staticmethod
    def _data_mode(markup: str) -> str:
        """Значение из `data-mode` — его читает `toggleQaMode` при следующем щелчке."""
        import re
        found = re.search(r'data-mode="([^"]*)"', markup)
        assert found, f'свитчер не отдал `data-mode`: {markup!r}'
        return found.group(1)

    def test_front_half_actually_ran(self):
        """
        Сторожит **непустоту** разметки, а не норму — норма в соседних тестах.

        Остальные проверки этого класса сравнивают значения; сравнение пустого списка с
        пустым списком зелёное, и рядом `zip`, который при коротком ответе `node` молча
        сливает всё в ноль пар. Этот тест первым и единственный говорит, что половина
        страницы взята наяву: ряды получены, кнопка в них есть, `data-mode` читается.
        Убирать его как дубль `test_subtask_row_shows_no_switcher` нельзя: тот сторожит
        ряд с родителем, а не размер ответа.
        """
        rows = self._front_rows([{'id': 1, 'parent_id': None, 'metadata': {'qa_mode': 'full'}},
                                 {'id': 2, 'parent_id': None, 'metadata': {}}])
        assert len(rows) == 2, f'node вернул другой счёт рядов: {rows!r}'
        assert 'qa-mode-switcher' in rows[0], f'ряд без свитчера: {rows[0]!r}'
        assert self._data_mode(rows[0]) == 'full', rows[0]
        # Ряд без ключа тоже обязан отдать кнопку: отсутствие разметки и отсутствие
        # значения — разные вещи, и по пустому ответу норму не сверить.
        assert 'qa-mode-switcher' in rows[1], f'ряд без ключа остался без кнопки: {rows[1]!r}'
        assert self._data_mode(rows[1]) == 'lite', rows[1]

    def test_both_banks_agree_on_every_value(self):
        """Одинаковый вход — одинаковый режим; расхождение хотя бы по одному значению проваливает тест."""
        from src.project.task.task_agent_qa import task_agent_qa_mode

        markup = self._front_markup(self.CORPUS)
        assert len(markup) == len(self.CORPUS), 'node вернул другой счёт — сравнивать нечего'
        diverged = [(value, self._data_mode(html), task_agent_qa_mode({'metadata': {'qa_mode': value}}))
                    for value, html in zip(self.CORPUS, markup)
                    if self._data_mode(html) != task_agent_qa_mode({'metadata': {'qa_mode': value}})]
        assert not diverged, (f'нормы разошлись (значение, фронт, движок): {diverged} — '
                              f'править нужно обе половины: `_qaModeNormalize` и `task_agent_qa_mode`')

    def test_button_label_matches_its_mode(self):
        """Подпись на кнопке говорит то же, что заложенный в неё режим."""
        markup = self._front_markup(self.CORPUS)
        lied = [(value, self._data_mode(html), html) for value, html in zip(self.CORPUS, markup)
                if f'QA {self._data_mode(html).capitalize()}' not in html]
        assert not lied, f'подпись расходится с режимом (значение, атрибут, разметка): {lied}'

    def test_junk_never_reaches_the_markup(self):
        """
        Мусорное значение не уезжает в атрибут как есть.

        Патч принимает что угодно, ключ правят и воркеры, и человек через API; кавычка в
        значении вышла бы из `data-mode` прямо в разметку строки задачи.
        """
        hostile = ['full" onclick="alert(1)', "full'><b>", '<script>full</script>']
        markup = self._front_markup(self.CORPUS + hostile)
        for value, html in zip(self.CORPUS + hostile, markup):
            assert self._data_mode(html) in ('lite', 'full'), (f'значение {value!r} прошло в '
                                                               f'атрибут как есть: {html!r}')
        # Отдельно и по существу: ни одного чужого тега или обработчика ряд не содержит.
        assert not [html for html in markup if 'alert(1)' in html or '<b>' in html or '<script>' in html]

    def test_subtask_row_shows_no_switcher(self):
        """
        У подзадачи свитчера нет: режим пишется родителю.

        Кнопка на ребёнке обещала бы менять проверку именно этого ребёнка, а меняла бы
        чужой режим — поэтому ряд с `parent_id` обязан оставаться пустым.
        """
        markup = self._front_rows([
            {'id': 2, 'parent_id': None, 'metadata': {'qa_mode': 'full'}},
            {'id': 3, 'parent_id': 2, 'metadata': {'qa_mode': 'full'}},
        ])
        assert 'qa-mode-switcher' in markup[0], 'у родителя свитчера нет — проверять нечего'
        assert markup[1] == '', f'подзадача получила свитчер: {markup[1]!r}'

    def test_mode_word_full_only_after_trim_and_lower(self):
        """`full` достигается только точным совпадением после обрезки пробелов и регистра."""
        from src.project.task.task_agent_qa import QA_MODE_FULL, QA_MODE_LITE, task_agent_qa_mode

        for value, expected in (('full', QA_MODE_FULL), (' FULL ', QA_MODE_FULL),
                                ('full ', QA_MODE_FULL), ('fulllite', QA_MODE_LITE),
                                ('fully', QA_MODE_LITE), (' полный', QA_MODE_LITE)):
            assert task_agent_qa_mode({'metadata': {'qa_mode': value}}) == expected


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


class TestTaskQaModeRoundTrip:
    """
    Режим переживает перезагрузку страницы: щелчок, перечитка списка, чтение движком.

    Цель держится на двух концах, и ни один настоящими данными не проверялся. Свитчер
    шлёт `POST /task/{id}/metadata` патчем одного ключа (`_taskFlagSave`), а после
    перезагрузки рисует себя заново из того, что вернул `GET /tasks/{project}`
    (`renderQaModeSwitcher`) — из колонки, а не из памяти страницы. Значит цель
    закрыта тогда, когда значение в базе, в списке и в `subtask_qa_mode` одно.

    Задача заводится в «Без проекта» и с префиксом `__pytest` — под сессионную уборку
    `conftest.py`, поэтому за собой её не сносим: `DELETE /task/{id}` вдобавок дёргает
    освобождение пулов (`team_llm_pool_forget`, `team_shell_pool_forget`) и снимает
    дерево выкладки, а ни того, ни другого эта строка в пуле не держала.

    Что задача не уйдёт в конвейер — не гарантируется, а зависит от окружения: отсутствия
    плана для отбора Менеджеру довольно (`task_claim_task_unplanned` берёт задачи именно
    без плана), и удерживает её только фильтр по живой карточке. Без живых оболочек
    `task_role_project_type_sql` даёт `1 = 0` и задача висит в очереди «Без проекта»;
    с живой оболочкой вне проектов она уйдёт планироваться — ровно поэтому сессионная
    уборка и сносит её после прогона. Дерево выкладки при этом не трогается: у задачи
    без проекта `task_role_project_work_dir` пустой, сносить нечего.

    Отсюда и второй сюжет, который класс не стерпит: **два прогона сюиты на одном
    стенде**. Уборка соседа по общей базе сносит строку между её созданием и первым
    щелчком, и тест падает на `404 task not found` там, где правка ни при чём. Перед
    прогоном — `pgrep -af "pytest tests/"` (подробнее в `.claude/docs/testing.md`).
    Зависимость от свободного стенда из сюжеты не выведена: чинится со стороны уборки
    (`tests/conftest.py`), а не этого файла, поэтому осталась и снята порядком прогонов.
    """

    # Признак, а не догадка: класс единственный в файлу ходит по HTTP и зависит от того,
    # чей код поднят на `BASE_URL` (см. `.claude/docs/testing.md`).
    pytestmark = [pytest.mark.pipeline, pytest.mark.integration]

    TEST_TITLE = "__pytest_qa_mode__"

    @pytest.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=90.0) as client:
            await client.post("/auth/login", json=TEST_AUTH)
            yield client

    async def _create(self, client, suffix: str) -> dict:
        """Новая задача теста; убирается сессией, поэтому id не возвращается."""
        resp = await client.post("/tasks/0", json={
            "title": f"{self.TEST_TITLE}{suffix}",
            "description": "временная задача теста режима QA",
        })
        assert resp.status_code == 200, resp.text
        return resp.json()["task"]

    async def _switch(self, client, task_id: int, mode: str) -> None:
        """Один щелчок свитчера — тот же запрос, что шлёт `_taskFlagSave`."""
        from src.project.task.task_metadata import TASK_METADATA_KEY_QA_MODE

        resp = await client.post(f"/task/{task_id}/metadata",
                                 json={"patch": {TASK_METADATA_KEY_QA_MODE: mode}})
        assert resp.status_code == 200, resp.text

    async def _drop_mode(self, client, task_id: int) -> None:
        """
        Удалить ключ режима, а не переключить его.

        Свитчер так не делает — он всегда пишет строку. Отдельный шаг нужен потому, что
        удаление (`null` в патче) — третье состояние мешка, в которое свитчер не
        заходит, а движок обязано читать тем же Lite, что и явное `lite`.
        """
        from src.project.task.task_metadata import TASK_METADATA_KEY_QA_MODE

        resp = await client.post(f"/task/{task_id}/metadata",
                                 json={"patch": {TASK_METADATA_KEY_QA_MODE: None}})
        assert resp.status_code == 200, resp.text

    async def _row(self, client, task_id: int) -> dict:
        """
        Перечитать список: этим же фронт восстанавливает состояние после перезагрузки.

        Список поднимается целиком, а не одна строка, — именно так и делает страница,
        и иначе мы проверяли бы endpoint, которого свитчер не вызывает.
        """
        resp = await client.get("/tasks/0")
        assert resp.status_code == 200, resp.text
        rows = {t["id"]: t for t in resp.json()["tasks"]}
        assert task_id in rows, f"задача {task_id} исчезла из списка — проверять нечего"
        return rows[task_id]

    async def test_full_mode_survives_reload(self, client):
        """Полный режим записан, перечитан и понятен движку — свитчер вернётся в то же состояние."""
        from src.project.task.task_agent_qa import QA_MODE_FULL, task_agent_qa_mode
        from src.project.task.task_metadata import TASK_METADATA_KEY_QA_MODE

        task = await self._create(client, "full")
        await self._switch(client, task["id"], QA_MODE_FULL)

        row = await self._row(client, task["id"])
        assert row["metadata"][TASK_METADATA_KEY_QA_MODE] == QA_MODE_FULL
        # Движок читает перечитанное как полный режим: иначе свитчер показывает одно,
        # а в `subtask_qa_mode` уезжает другое.
        assert task_agent_qa_mode(row) == QA_MODE_FULL

    async def test_back_to_lite_is_the_restored_default(self, client):
        """
        Возврат в Lite перечитывается Lite.

        Так делает свитчер: возврат пишется явно `lite`, а не удалением ключа.
        Разойдётся с движком — человек переключил одно, а агент проверяет другое.
        """
        from src.project.task.task_agent_qa import QA_MODE_FULL, QA_MODE_LITE, task_agent_qa_mode

        task = await self._create(client, "back")
        await self._switch(client, task["id"], QA_MODE_FULL)
        await self._switch(client, task["id"], QA_MODE_LITE)

        row = await self._row(client, task["id"])
        assert task_agent_qa_mode(row) == QA_MODE_LITE

    async def test_dropped_key_restores_lite_default(self, client):
        """
        Удалённый ключ читается тем же Lite, что и явное `lite`.

        Свитчер до удаления не доходит — доходит человек, правящий мешок руками, или
        сосед, которому ключ больше не нужен. Значение не должно остаться `full`:
        иначе режим пережил не перезагрузку страницы, а чужую запись в тот же мешок.
        """
        from src.project.task.task_agent_qa import QA_MODE_FULL, QA_MODE_LITE, task_agent_qa_mode
        from src.project.task.task_metadata import TASK_METADATA_KEY_QA_MODE

        task = await self._create(client, "drop")
        await self._switch(client, task["id"], QA_MODE_FULL)
        await self._drop_mode(client, task["id"])

        row = await self._row(client, task["id"])
        assert TASK_METADATA_KEY_QA_MODE not in row["metadata"], "ключ не удалён патчем null"
        assert task_agent_qa_mode(row) == QA_MODE_LITE

    async def test_restored_row_renders_switcher_in_same_state(self, client):
        """
        Перечитанная строка рисует свитчер в том же состоянии, что был до перезагрузки.

        Предыдущие тесты смыкают базу с движком, а цель сформулирована глазами: человек
        после перезагрузки видит выбранную глубину. Между списком и кнопкой стоит
        `renderQaModeSwitcher`, и разрыв в нём — тот же промах, что разошедшаяся норма:
        значение в базе `full`, а на кнопке Lite. Поэтому разметка берется наяву из
        настоящей строки `GET /tasks` — тем же вырыванием из шаблона, что и паритет
        норм (`TestQaModeNormalizationAgreesBothBanks`), без копии функции.

        Доказано **до разметки, а не до DOM**: сверяется `data-mode`, подпись и чтение
        движком. Обработчик щелчка (`toggleQaMode`: гашение `.busy`, запись
        `dataset.mode`, подпись) и CSS-состояние точки остаются за кадром — им нужен
        браузерный прогон с логином (`slow`), а расходятся они только с тем же
        нормализованным значением, которое здесь проверяется.
        """
        from src.project.task.task_agent_qa import QA_MODE_FULL, QA_MODE_LITE, task_agent_qa_mode

        task = await self._create(client, "render")
        for mode in (QA_MODE_FULL, QA_MODE_LITE):
            await self._switch(client, task["id"], mode)

            row = await self._row(client, task["id"])
            markup = TestQaModeNormalizationAgreesBothBanks._front_rows([row])[0]
            assert markup, (f'свитчер не отрисован для корневой задачи {task["id"]}: проверять '
                            f'нечего, а выглядит как доказанное состояние')
            rendered = TestQaModeNormalizationAgreesBothBanks._data_mode(markup)
            # Атрибут обязан совпасть с перечитанным мешком, движком и подписью на кнопке.
            assert rendered == mode, (f'после перезагрузки кнопка показывает {rendered}, '
                                      f'а записано {mode}: {markup!r}')
            assert task_agent_qa_mode(row) == rendered, (
                f'кнопка говорит {rendered}, движок читает {task_agent_qa_mode(row)}')
            assert f'QA {rendered.capitalize()}' in markup

    async def test_shared_keys_survive_mode_patch(self, client):
        """
        Запись режима не уносит чужие ключи мешка.

        Патч одного ключа — единственная причина, по которой свитчер стоит рядом с
        оркестратором и воркерами: они пишут в тот же мешок. Замена целиком стёрла бы
        их ключи, и переключатель режима стал бы опасной кнопкой.
        """
        from src.project.task.task_agent_qa import QA_MODE_FULL
        from src.project.task.task_metadata import (TASK_METADATA_KEY_BRANCH,
                                                    TASK_METADATA_KEY_QA_MODE,
                                                    TASK_METADATA_KEY_RETRY,
                                                    task_metadata_update)

        task = await self._create(client, "coexist")
        await task_metadata_update(task["id"], {TASK_METADATA_KEY_BRANCH: "task/6438",
                                                TASK_METADATA_KEY_RETRY: {"count": 2}})

        await self._switch(client, task["id"], QA_MODE_FULL)

        row = await self._row(client, task["id"])
        assert row["metadata"][TASK_METADATA_KEY_BRANCH] == "task/6438"
        assert row["metadata"][TASK_METADATA_KEY_RETRY] == {"count": 2}
        assert row["metadata"][TASK_METADATA_KEY_QA_MODE] == QA_MODE_FULL

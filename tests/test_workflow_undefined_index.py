"""Индекс «Undefined переменные»: кэш на фронте и сырьё с бэкенда.

Две половины одного имени, и здесь обе.

`variable-undefined.js` — сеть и кэш, правила в нём нет (оно — в `variable-group.js`).
Здесь проверяют именно его: «GET на первом открытии», «перечит на перезагрузке
без сети», «сохранение шага не кэширует». Тесты гоняют **настоящий модуль**
(`import`-ом, как его грузит браузер) на заглушках DOM и сети: что проверит
node, то и увидит браузер.

`ai_workflow_undefined.py` — сбор сырья (ручка `/workflow_variable/undefined_index`
над ним — тонкая). С него спрос за
`hiddenNames`: правило молчит ровно про то, что ручка туда сложила, и пропуск
источника оборачивается криком на рабочем имени — см.
`TestTheLauncherNamesReachTheIndex`.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from tests_.tests_guard import tests_guard_code as _source

from src.ai import ai_workflow_undefined
from src.ai.ai_workflow_undefined import ai_workflow_undefined_index

pytestmark = pytest.mark.core

INDEX = './data/uvicorn/public/js/workflow/variable-undefined.js'
STATE = './data/uvicorn/public/js/workflow/state.js'

# Идентификатор workflow, открытого «в редакторе»: для заглушки это значение
# `document.getElementById('workflowId').value`, его и зовёт модуль в вызовы.
EDITOR_ID = '6'


# Шаг редакторской формы — той же, что кладёт в стейт страница. Один на оба
# пакета ниже: они различаются не шагом, а тем, чьим этот шаг числится.
STEP_900 = {'id': 900, 'position': 900,
            'metadata': json.dumps({'agent_invoke': {'agent_id': 1,
                                                     'prompt': 'о %invite_name%'}},
                                   ensure_ascii=False)}

# Сырьё чужого workflow, какое отдаёт бэкенд одним пакетом: `{steps,
# registryNames, hiddenNames}`. В тестах — workflow 9: открытому (6) редактор
# верит самому, чужому он верит пакет, и различие этих дорог тесты сверяют.
RAW = {'9': {'steps': [STEP_900], 'registryNames': [], 'hiddenNames': []}}

# Пакет, скачанный ДО правки шага: для 6 он знает шаг, читающий «invite_name».
# Стейт редактора ниже — с шагом, читающим «girl_bio»: кому верит модуль, того
# список и покажет.
RAW_STALE_6 = {EDITOR_ID: {'steps': [STEP_900], 'registryNames': [], 'hiddenNames': []}}

REGISTRY = json.dumps([{'id': 901, 'name': 'girl_name'}], ensure_ascii=False)

# Шаги редакторской формы прямо в JS-теле тестов: их зовёт и стейт-адаптер,
# и заглушка сети — одним и тем же текстом, без второго «того же шага» на свете.
STEP_788 = json.dumps({'id': 788, 'position': 788,
                       'metadata': json.dumps({'agent_invoke': {
                           'agent_id': 3, 'prompt': 'о себе %girl_bio%'}}, ensure_ascii=False)},
                      ensure_ascii=False)

STEP_789 = json.dumps({'id': 789, 'position': 789,
                       'metadata': json.dumps({'agent_invoke': {
                           'agent_id': 3, 'prompt': 'о себе %girl_face%'}}, ensure_ascii=False)},
                      ensure_ascii=False)

STEP_788_AND_789 = STEP_788 + ', ' + STEP_789

# Заглушки сети и DOM + настоящие модули кэша, правила и стейта. Имена в
# заглушке — те же, что читает модуль: `window.location.search` для id из
# урла, `document.getElementById('workflowId')` — для id скрытой закладки.
_JS_PRELUDE = '''
let _fetched = __FETCHED__, _out = {};
const _fetches = [];
globalThis.fetch = async (url) => {
    _fetches.push(String(url).split('?')[0]);
    return {ok: true, status: 200, json: async () => _fetched};
};
globalThis.document = {
    createElement: (tag) => ({tag, kids: [], dataset: {}, style: {}, value: '',
        append(...one) { this.kids.push(...one); },
        appendChild(one) { this.kids.push(one); }}),
    getElementById: (id) => (id === 'workflowId' ? {value: '__EDITOR__'} : null)};
globalThis.window = {location: {search: '?workflow_id=__EDITOR__'},
    localStorage: {getItem: () => null, setItem: () => {}}};
globalThis.location = {search: '?workflow_id=__EDITOR__'};

import {ensureUndefinedIndex, invalidateUndefinedIndex,
    workflowUndefinedEntries, workflowUndefinedEntriesSync} from '__INDEX__';
import {state} from '__STATE__';

state.allWorkflows = [];
state.allAvailableTools = [];
state.allAgentVariables = [];
state.allNodes = [];
_out = {};
'''


class TestTheCacheIsNetwork:
    """⚠⚠ «Мигалка в левом списке» не стоит сетевых кругов на каждую перекладку."""

    def test_the_first_open_asks_the_network_once(self):
        """⚠⚠ Первый вопрос — один GET на всю установку; повторный вызов — тот же
        промис без новой сети.

        Модуль кэша знает workflow, а не вкладку: второй вызов обязан вернуться
        из кэша, не дойдя до `fetch` — иначе список слева качает 0.5 МБ на
        каждую перекладку вкладок.
        """
        out = _run(_script('''
const cold = workflowUndefinedEntriesSync('9') === null ? 'нет' : 'есть';
await ensureUndefinedIndex();
const first = _fetches.length;
await ensureUndefinedIndex();
const again = _fetches.length;
const warm = workflowUndefinedEntriesSync('9');
_out = {cold, first, again, urls: [..._fetches], warm: warm ? 'есть' : null};
'''))

        assert out['first'] == 1 and out['again'] == 1, \
            f'индекс качают повторно: {out["urls"]}'
        assert out['urls'] == ['/workflow_variable/undefined_index'], \
            f'индекс просят не одним GET: {out["urls"]}'
        assert out['cold'] == 'нет', \
            f'пустой список до загрузки сошёл за готовый: {out["cold"]}'
        assert out['warm'] == 'есть', \
            f'кэш промахнулся мимо готового индекса: {out["warm"]}'

    def test_a_broken_load_is_not_cached(self):
        """⚠⚠ Сбой сети не отметка «готово»: пустой список после сбоя — ложь,
        которую человек не заметит. Сбой не кэшим, следующий вызов пробует снова.
        """
        out = _run(_script('''
globalThis.fetch = async () => {throw new Error('сеть легла');};
await ensureUndefinedIndex();
const afterFail = {entries: (await workflowUndefinedEntries('9')) ? 1 : null,
                   sync: workflowUndefinedEntriesSync('9') ? 1 : null};
globalThis.fetch = async (url) => {
    _fetches.push(String(url).split('?')[0]);
    return {ok: true, status: 200, json: async () => _fetched};
};
const entries = await workflowUndefinedEntries('9');
_out = {asked: _fetches.length, afterFail, has: entries ? entries.size : null};
'''))

        assert out['afterFail']['entries'] is None and out['afterFail']['sync'] is None, \
            f'сбой сети притворился готовым индексом: {out["afterFail"]}'
        assert out['asked'] == 1, \
            f'после сбоя индекс не догнали новым запросом: {out["asked"]}'
        assert out['has'] == 1, f'после сбоя индекс не догнали: {out["has"]}'

    def test_a_foreign_workflow_is_answered_from_the_package(self):
        """Чужой workflow редактор не знает: ему верят пакет, скачанный ранее, —
        и только когда он есть; нет пакета — нет и ответа, молчание вместо выдумки.
        """
        out = _run(_script('''
await ensureUndefinedIndex();
state.allCurrentStepsData = [__STEP788__];
state.allCurrentVariables = __REGISTRY__;
const editor = workflowUndefinedEntriesSync('__EDITOR__');
const other = workflowUndefinedEntriesSync('9');
_out = {asked: _fetches.length, editor: editor ? editor.size : null,
        other: other ? [...other.keys()] : null,
        empty: workflowUndefinedEntriesSync('999') ? 'есть' : null};
''', fetched={**RAW, **RAW_STALE_6}, STEP788=STEP_788, REGISTRY=REGISTRY))

        assert out['editor'] == 1 and out['other'] == ['invite_name'], \
            f'разные workflow отвечают не из своих сырьёв: {out}'
        assert out['empty'] is None, \
            'для workflow без пакета список выдуман из пустоты'


class TestTheCacheTrustsTheEditor:
    """⚠⚠ Для открытого workflow сырьё — стейт страницы, пакет мог скачять до правки."""

    def test_the_editor_steps_beat_the_fetched_package(self):
        """⚠⚠ Перечит — тот же workflow, что открыт в редакторе: имена берут из
        стейта страницы, а не из пакета, скачанного до правки шага.

        Тест ставит дело так, как его видит страница: пакет для 6 знает шаг
        с `%invite_name%`, стейт редактора — шаг, который читает `%girl_bio%`.
        Если модуль верит пакету, список показывает чужое прошлое.
        """
        out = _run(_script('''
await ensureUndefinedIndex();
state.allCurrentStepsData = [__STEP788__];
state.allCurrentVariables = __REGISTRY__;
invalidateUndefinedIndex('__EDITOR__');
const entries = workflowUndefinedEntriesSync('__EDITOR__');
_out = {asked: _fetches.length, has: entries ? entries.has('girl_bio') : null,
        stale: entries ? entries.has('invite_name') : null};
''', fetched=RAW_STALE_6, STEP788=STEP_788, REGISTRY=REGISTRY))

        assert out['asked'] == 1, f'за свежим сырьём полезли в сеть: {out["asked"]}'
        assert out['has'] is True, \
            'список для открытого workflow считает по пакету, а не по стейту редактора'
        assert out['stale'] is False, \
            'имя из пакета чужого workflow протек в список открытого workflow'

    def test_saving_a_step_leaves_the_computed_cache(self):
        """⚠⚠ Сохранение шага не кэширует: кэш вычисления для этого workflow
        выбрасывают, списки пересчитают, а сырьё чужих workflow в кэше живет.

        Без сброса панель графа молчала бы про новую переменную до первой
        полной перезагрузки страницы — «сохранение шага не кэширует».
        """
        out = _run(_script('''
await ensureUndefinedIndex();
state.allCurrentStepsData = [__STEP788__];
const before = workflowUndefinedEntriesSync('__EDITOR__');
state.allCurrentStepsData = [__STEP788_789__];
invalidateUndefinedIndex('__EDITOR__');
const after = workflowUndefinedEntriesSync('__EDITOR__');
_out = {asked: _fetches.length,
        before: before ? [...before.keys()] : null,
        after: after ? [...after.keys()] : null};
''', fetched=RAW_STALE_6, STEP788_789=STEP_788_AND_789, STEP788=STEP_788,
           REGISTRY=REGISTRY))

        assert out['asked'] == 1, \
            f'сброс кэша погнал за индексом в сеть заново: {out["asked"]}'
        assert out['before'] == ['girl_bio'] and out['after'] == ['girl_bio', 'girl_face'], \
            f'сброс не пересчитал открытого workflow: {out}'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой.

    ⚠ Тот же приём, что у `test_workflow_variables_node.py`. Без него уборка
    сессии в `conftest` приезжает на закрытый цикл: «Event loop is closed» —
    тест при этом зелёный, а прогон файла красный.
    """
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestTheLauncherNamesReachTheIndex:
    """⚠⚠ Три четверти «дырок» оказались живыми именами запускающего.

    Правило зовёт дыркой имя, которое шаги читают, а положить некому. Реестр
    знает только заведённое руками, и по нему выходило, что 26 workflow из 64
    читают 74 несуществующих имени. Разобрали все 74 — живых 40:

    | откуда приходит | сколько | где лежит |
    |---|---|---|
    | словарь запускающего (`task_id`, `subtask_branch`) | 35 | `variables_start` прогона |
    | входящие подпрогона (`w_project_id`) | 3 | `inputs_map` родительского шага |

    Оба источника есть в базе, и оба ручка обязана сложить в `hiddenNames`.
    Проверка идёт **от базы**: ожидание считается тем же запросом, а не вписано
    числом — иначе тест старел бы вместе с данными.
    """

    def test_the_handler_asks_the_runs_for_launch_names(self):
        """⚠ Имена запускающего берутся у трассы. Без этого источника правило
        кричит на `task_shell_session` в каждом workflow конвейера.
        """
        code = _source(ai_workflow_undefined.ai_workflow_undefined_index)

        assert 'agent_workflow_trace' in code, 'сбор больше не спрашивает прогоны'
        assert 'JSON_KEYS' in code, \
            'ключи снова считаются в питоне — тяжёлый variables_start поедет по сети'

    async def test_both_launchers_land_in_hidden_names(self):
        """⚠⚠ Оба источника — одним тестом и одной сессией.

        Пул соединений привязан к циклу, в котором заведён, и второй тест с
        базой приезжал бы на закрытый: «Event loop is closed». Ровно об эти
        грабли спотыкались в `test_workflow_variables_node.py`, и лечение то же —
        один поход, а не два.

        Проверяется:

        * **подпрогон** — scope у него изолирован (`ai_framework_manager`, шаг
          `workflow_invoke`): внутрь попадают только `inputs_map`, умолчания и
          служебные. Значит ключи карты и есть входящие ребёнка;
        * **прогон** — единственная запись того, что кладёт питон при старте:
          в базе этих имён нет больше нигде.
        """
        async with mysql_get_db_async() as db:
            await db.execute("""
                SELECT workflow_id, JSON_KEYS(variables_start) AS variable_keys
                FROM agent_workflow_trace
                WHERE workflow_id IS NOT NULL AND JSON_VALID(variables_start)
                ORDER BY id DESC LIMIT 1
            """)
            run_row = await db.fetchone()

        workflows = await ai_workflow_undefined_index()

        expected = _parent_inputs_by_child(workflows)
        assert expected, 'на базе нет подпрогона с inputs_map — проверка ослабла'

        for child_id, names in expected.items():
            hidden = set(workflows[child_id]['hiddenNames'])
            assert names <= hidden, (
                f'входящие подпрогона {child_id} не попали в скрытые: '
                f'{sorted(names - hidden)}')

        assert run_row and run_row.get('variable_keys'), \
            'на базе нет прогона со словарём старта — проверка ослабла'

        hidden = set(workflows[str(run_row['workflow_id'])]['hiddenNames'])
        started = {str(one) for one in json.loads(run_row['variable_keys'])}

        assert started <= hidden, \
            f'имена старта не попали в скрытые: {sorted(started - hidden)}'


def _parent_inputs_by_child(workflows: dict) -> dict:
    """«Ребёнок → имена его входящих» по шагам `workflow_invoke` всех workflow.

    ⚠ Ключи карты, не значения: `{"w_project_id": "planning_project_id"}` —
    слева имя внутри ребёнка, справа имя у родителя. Перепутать их значит
    проверить не то и не там.
    """
    found = {}

    for entry in workflows.values():
        for step in entry['steps']:
            invoke = json_from_string(step.get('metadata') or {}).get('workflow_invoke') or {}
            inputs_map = invoke.get('inputs_map')
            if not isinstance(inputs_map, dict) or not inputs_map:
                continue
            child_id = str(invoke.get('workflow_id') or '')
            if child_id not in workflows:
                continue
            found.setdefault(child_id, set()).update(str(one) for one in inputs_map)

    return found


def _script(body: str, fetched: object = None, **tokens: str) -> str:
    """Скрипт: сырьё кэша (по умолчанию — пустой ответ), токены и тело теста."""
    script = (_JS_PRELUDE + body
              + "\nprocess.stdout.write(JSON.stringify(_out));")

    payload = {'result': {'workflows': RAW if fetched is None else fetched}}
    script = (script.replace('__EDITOR__', EDITOR_ID).replace('__INDEX__', INDEX)
              .replace('__STATE__', STATE)
              .replace('__FETCHED__', json.dumps(payload, ensure_ascii=False)))

    for token, value in tokens.items():
        script = script.replace(f'__{token.upper()}__', value)

    return script


def _run(script: str):
    """Гоняет скрипт на настоящем модуле кэша с заглушками сети и DOM."""
    if not shutil.which('node'):
        pytest.skip('node недоступен — кэш проверить нечем')

    done = subprocess.run(['node', '--input-type=module', '-e', script],
                          capture_output=True, text=True)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)

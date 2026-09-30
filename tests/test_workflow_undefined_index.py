"""Кэш индекса «Undefined переменные»: сеть один раз, свежее — из стейта.

`undefined-index.js` — сеть и кэш, правила в нём нет (оно — в `variable-group.js`).
Здесь проверяют именно его: «GET на первом открытии», «перечит на перезагрузке
без сети», «сохранение шага не кэширует». Тесты гоняют **настоящий модуль**
(`import`-ом, как его грузит браузер) на заглушках DOM и сети: что проверит
node, то и увидит браузер.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.core

INDEX = './data/uvicorn/public/js/workflow/undefined-index.js'
GROUP = './data/uvicorn/public/js/workflow/variable-group.js'
STATE = './data/uvicorn/public/js/workflow/state.js'

# Идентификатор workflow, открытого «в редакторе»: для заглушки это значение
# `document.getElementById('workflowId').value`, его и зовёт модуль в вызовы.
EDITOR_ID = '6'


def _js(value) -> str:
    """Python-значение → JS-литерал той же формы, что кладёт в стейт страница."""
    return json.dumps(value, ensure_ascii=False)


def _step(step_id: int, meta: dict) -> dict:
    """Шаг редакторской формы — той же, что кладёт в стейт страница."""
    return {'id': step_id, 'position': step_id, 'metadata': json.dumps(meta)}


def _step_js(step_id: int, meta: dict) -> str:
    """Тот же шаг, но прямо в JS-теле теста: один и тот же текст у заглушек."""
    return _js(_step(step_id, meta)).replace('"id"', 'id', 1).replace('"position"', 'position', 1)


# Сырьё чужого workflow, какое отдаёт бэкенд одним пакетом: `{steps,
# registryNames, hiddenNames}`. В тестах — workflow 9: открытому (6) редактор
# верит самому, чужому он верит пакет, и различие этих дорог тесты сверяют.
RAW = {'9': {'steps': [_step(900, {'agent_invoke': {'agent_id': 1,
                                                   'prompt': 'о %invite_name%'}})],
             'registryNames': [], 'hiddenNames': []}}

# Пакет, скачанный ДО правки шага: для 6 он знает шаг, читающий «invite_name».
# Стейт редактора ниже — с шагом, читающим «girl_bio»: кому верит модуль, того
# список и покажет.
RAW_STALE_6 = {EDITOR_ID: {'steps': [_step(900, {'agent_invoke': {'agent_id': 1,
                                                                  'prompt': 'о %invite_name%'}})],
                            'registryNames': [], 'hiddenNames': []}}

REGISTRY = _js([{'id': 901, 'name': 'girl_name'}])

# Шаги редакторской формы прямо в JS-теле тестов: его зовёт и стейт-адаптер,
# и заглушка сети — одним и тем же текстом, без второго «того же шага» на свете.
STEP_788 = _step_js(788, {'agent_invoke': {'agent_id': 3, 'prompt': 'о себе %girl_bio%'}})

STEP_788_AND_789 = (STEP_788 + ', '
                    + _step_js(789, {'agent_invoke': {'agent_id': 3,
                                                     'prompt': 'о себе %girl_face%'}}))

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

import {editorWorkflowId, hiddenNamesFor, ensureUndefinedIndex, undefinedIndexReady,
    invalidateUndefinedIndex, workflowUndefinedEntries, workflowUndefinedEntriesSync,
    onUndefinedIndexChange} from '__INDEX__';
import {state} from '__STATE__';
import {variableGroupIndex, undefinedVariables, stepResultVariables,
    stepReadVariables, stepMadeVariables} from '__GROUP__';

state.allWorkflows = [];
state.allAvailableTools = [];
state.allAgentVariables = [];
state.allNodes = [];
_out = {};
'''


def _script(body: str, fetched: object = None, **tokens: str) -> str:
    """Скрипт: сырьё кэса (по молчанию — пустой ответ), токены и тело теста."""
    script = (_JS_PRELUDE + body
              + "\nprocess.stdout.write(JSON.stringify(_out));")

    payload = {'result': {'workflows': RAW if fetched is None else fetched}}
    script = (script.replace('__EDITOR__', EDITOR_ID).replace('__INDEX__', INDEX)
              .replace('__STATE__', STATE).replace('__GROUP__', GROUP)
              .replace('__FETCHED__', _js(payload)))

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
await ensureUndefinedIndex();
const first = _fetches.length;
await ensureUndefinedIndex();
const again = _fetches.length;
_out = {first, again, urls: [..._fetches], ready: undefinedIndexReady()};
'''))

        assert out['first'] == 1 and out['again'] == 1, \
            f'индекс качают повторно: {out["urls"]}'
        assert out['urls'] == ['/workflow_variable/undefined_index'], \
            f'индекс просят не одним GET: {out["urls"]}'
        assert out['ready'] is True, 'индекс догрузился, а `ready` всё еще нет'

    def test_a_broken_load_is_not_cached(self):
        """⚠⚠ Сбой сети не отметка «готово»: пустой список после сбоя — ложь,
        которую человек не заметит. Сбой не кэшим, следующий вызов пробует снова.
        """
        out = _run(_script('''
globalThis.fetch = async () => {throw new Error('сеть легла');};
await ensureUndefinedIndex();
const afterFail = {ready: undefinedIndexReady(),
                   entries: (await workflowUndefinedEntries('9')) ? 1 : null,
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
        assert out['afterFail']['ready'] is False, \
            f'сбой сети отметился «индекс догрузился»: {out["afterFail"]["ready"]}'
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

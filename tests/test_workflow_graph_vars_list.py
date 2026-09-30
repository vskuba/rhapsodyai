"""Вкладка Graph: список показывает ВСЕ переменные, и у каждой — значок группы.

Панель переменных на вкладке Graph редактора `/admin/workflow` показывала только
имена, оставившие след в метаданных шагов: половины переменных workflow глаза не
доходили (трасса прогона — 25 имён, на графе — меньше десятка), и то, к какой
группе относится имя, угадывалось по цвету полосы. Теперь список строится по той
же карте групп, что список трассы (см. `test_workflow_trace_var_chips.py`), и
перед каждым именем стоит значок группы — тот же, что чип на трассе.

## ⚠⚠ Список идёт по полной карте групп, а не по одной только трассе

`variablesTrace` знает имена, которых коснулись шаги: реестр (входящие,
глобальные, node, workflow) для неё нем, и половину переменных ветки прежний
обход трассы просто не показывал. Имя, которого шаги не касаются, обязано быть
видна наравне с прочими — и число `0→0` на ней есть честный ответ «есть, живёт,
шаги её не трогают».

## ⚠ Правило то же, что везде — и приходит оно живым импортом

Карта групп общая для страницы трассы и редактора (`variable-group.js`), связка её
со стейтом — одна, в адаптере панели. Тест зовёт правило импортом, а не копией:
своя копия разошлась бы с правилом на первой правке, и одна переменная числилась
бы входящей в одном месте и динамической в другом.

## ⚠ Почему через node, а не браузером

Функции чистые: данные на входе, список узлов на выходе. Тот же приём, что у
`test_workflow_trace_var_chips.py`: живой модуль правила импортом, кусок страницы
вырезкой по якорным комментариям, DOM — заглушкой ровно того объёма, каким
функция живёт. Куски режутся вместе с `stepNumbersOf` — правый блок панели
ссылается на неё.
"""

import json
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.core

GRAPH = './data/uvicorn/public/js/workflow/graph.js'
GROUP = './data/uvicorn/public/js/workflow/variable-group.js'
VARS = './data/uvicorn/public/js/workflow/variables.js'
INDEX = './data/uvicorn/public/js/workflow/undefined-index.js'
STATE = './data/uvicorn/public/js/workflow/state.js'

# Шаги открытого в редакторе workflow (`.id`/`.metadata`, не прогонные
# `step_id`/`metadata_rendered`) и реестр переменных. Имена нарочно из всех
# групп сразу — половина их не встречается ни в одном следе шага.
REGISTRY = [
    {'id': 901, 'name': 'girl_name', 'type': 'input'},
    {'id': 902, 'name': 'talk_history_chat', 'type': 'workflow'},
    {'id': 903, 'name': 'timezone', 'type': 'global'},
    {'id': 904, 'name': 'agent_title', 'type': 'node'},
]

STEPS = [
    {'id': 524, 'metadata': json.dumps({
        'tool_invoke': {
            'tool_name': 'companion_bio',
            # ⚠ Второе имя нарочно ничьё: шаг его читает, а породить его некому —
            # шага 9 в ветке нет, да и `args.output` инструмента про `sheet` молчит.
            # Ровно так выглядят 117 имён из 2075 по всем workflow установки.
            'inputs_map': {'bio': 'companion_bio_524_result_bio',
                           'sheet': 'list_shift_9_result_sheet'},
            'outputs_map': {'bio': 'girl_bio'},
        }}, ensure_ascii=False)},
    {'id': 786, 'metadata': json.dumps(
        {'workflow_invoke': {'workflow_id': 5, 'next': 'talk_answer'}},
        ensure_ascii=False)},
    {'id': 787, 'metadata': json.dumps({
        'llm_to_json_variable': [{'variable': 'talk_topic', 'text': 'о себе'}]},
        ensure_ascii=False)},
]

TOOLS = [{'name': 'companion_bio',
          'args': json.dumps({'output': {'keys': {'bio': 'string'}}})}]
WORKFLOWS = [{'id': 5, 'name': 'dating_invite_one'}]

# Что обязан показать значок у каждого имени: знак группы в строке, название —
# подсказкой, ключ (из ключа рождён класс строки `graph-var-<ключ>`).
#
# ⚠ В подсказке `label`, а не `title`: тот несёт значок первым словом, и подсказка
# повторяла бы то, что и так нарисовано в строке.
EXPECTED = {
    'girl_name': {'key': 'input', 'icon': '📥', 'label': 'Входящие переменные'},
    'timezone': {'key': 'common', 'icon': '🇬', 'label': 'Глобальные переменные'},
    'agent_title': {'key': 'node', 'icon': '🇳', 'label': 'Node переменные'},
    'talk_history_chat': {'key': 'workflow', 'icon': '🇼', 'label': 'Workflow переменные'},
    'companion_bio_524_result_bio': {'key': 'tool', 'icon': '⚙️', 'label': 'Tool переменные'},
    'dating_invite_one_786_result_str': {'key': 'tool', 'icon': '⚙️', 'label': 'Tool переменные'},
    'girl_bio': {'key': 'dynamic', 'icon': '🌀', 'label': 'Dynamic переменные'},
    'talk_topic': {'key': 'dynamic', 'icon': '🌀', 'label': 'Dynamic переменные'},
    # Шаг читает переменную, которой нет ни в реестре, ни в следах шагов: имя
    # получает свою секцию «Undefined переменные» со значком предупреждения.
    'list_shift_9_result_sheet': {'key': 'undefined', 'icon': '⚠️',
                                  'label': 'Undefined переменные'},
}

# Имена, которых шаги не касаются вовсе: раньше их не было видно на графе.
SILENT = [name for name in EXPECTED
          if name not in ('companion_bio_524_result_bio', 'girl_bio', 'talk_topic',
                          'list_shift_9_result_sheet')]

# Якоря кусков панели: живой код вырезается, а не копируется в тест.
STEPNUMS_FROM = '* Номер шага так, как его видит человек'
LIST_FROM = '* Рисует список переменных workflow и вешает выбор'
LIST_TILL = 'Выбрать переменную: показать трассу'


class TestTheListIsWhole:
    """⚠⚠⚠ На графе видно ВСЕ переменные workflow, а не только следы шагов."""

    def test_every_variable_of_the_workflow_shows_up(self):
        got = {row['name'] for row in _rows()}

        assert got == set(EXPECTED), (
            'список графа снова ходит по одной трассе: '
            f'ждали {sorted(EXPECTED)}, показали {sorted(got)}')

    def test_a_name_the_steps_never_touch_are_visible_too(self):
        """⚠ Имя без следа — тоже переменная: `0→0` на ней есть честный ответ."""
        for row in _rows():
            if row['name'] not in SILENT:
                continue

            assert row['count'] == '0→0', (
                f'«{row["name"]}» не касаются шаги, и строка её врёт о шагах: '
                f'{row["count"]!r}')

    def test_the_list_stays_alphabetical(self):
        """Порядок тот же, что в остальных списках: имя ищут глазами по алфавиту."""
        names = [row['name'] for row in _rows()]

        assert names == sorted(names), f'список графа разъехался по алфавиту: {names}'


class TestEveryRowCarriesItsIcon:
    """⚠⚠ У каждой строки — значок группы перед именем, подпись — подсказкой."""

    def test_the_icon_stands_before_the_name(self):
        for row in _rows():
            assert row['icon_before_name'], \
                f'у «{row["name"]}» значок стоит не перед именем: {row["cls"]}'

    def test_icon_and_tooltip_sign_the_group_of_the_rule(self):
        """Значок и подсказка — та же карта групп, что у трассы и панели шагов."""
        for row in _rows():
            want = EXPECTED[row['name']]

            assert row['icon'] == want['icon'], (
                f'у «{row["name"]}» значок чужой группы: {row["icon"]!r}, '
                f'ждали {want["icon"]!r}')
            assert row['tip'] == want['label'], \
                f'у «{row["name"]}» подсказка молчит о группе: {row["tip"]!r}'
            assert row['cls'] == f"graph-var graph-var-{want['key']}", \
                f'у «{row["name"]}» строка в чужом классе: {row["cls"]}'

    def test_the_undefined_name_gets_the_warning_mark_of_the_shared_rule(self):
        """⚠⚠ Имя без группы получает `⚠️` своей секции, а не пустое место.

        Пустое место рядом с именем оставляет вопрос «откуда оно» ровно так же,
        как его оставляло отсутствие группы. Ответ один на обе страницы — секция
        «Undefined переменные» из модуля правила: и граф, и трасса берут её из
        одного `variableGroupIndex`, своего значка панель графа не выдумывает.
        """
        row = next(r for r in _rows() if r['name'] == 'list_shift_9_result_sheet')

        assert row['icon'] == '⚠️', \
            f'у имени без группы снова пусто вместо знака: {row["icon"]!r}'
        assert row['cls'] == 'graph-var graph-var-undefined', \
            f'неопределённая строка не несёт знака в классе: {row["cls"]}'

    def test_the_icon_and_the_name_sit_in_one_block(self):
        """⚠⚠ Значок — приставка к имени, а не третья колонка строки.

        Строка это flex с `space-between`: пока детей было двое, он разводил имя и
        счётчик по краям. Третий ребёнок встал между ними, и у короткого имени
        значок отъезжал от него на 67 пикселей. Обёртка держит их вместе.
        """
        for row in _rows():
            assert row['row_kids'] == ['graph-var-head', 'graph-var-count'], (
                f'у «{row["name"]}» строка снова из трёх детей подряд: '
                f'{row["row_kids"]} — значок оторвётся от имени')

    def test_the_icon_holds_no_text_name(self):
        """Значок текстом — половина строки: слово читает только подсказка."""
        for row in _rows():
            assert not re.search(r'[a-zA-Zа-яА-ЯёЁ]', row['icon']), \
                f'у «{row["name"]}» значок снова расписан текстом: {row["icon"]!r}'


class TestOneRuleForBothPages:
    """⚠ Graph берёт готовую карту групп, а не заводит свою четвёрку `state.*`."""

    def test_the_graph_takes_the_index_from_the_editor_adapter(self):
        code = _read(GRAPH)

        assert "import {editorVariableGroupIndex} from './variables.js'" in code, \
            'граф снова размечает имена сам — минуя адаптер панели'
        assert code.count('variableGroupIndex(') == 0, \
            'граф зовёт правило напрямую — четвёрка `state.*` разъедётся по файлам'

    def test_the_adapter_stays_the_only_state_binding(self):
        """Как и на трассе: связка правила со стейтом редактора живёт в одном месте."""
        assert 'export function editorVariableGroupIndex(' in _read(VARS), \
            'адаптер редактора пропал — привязка к стейту снова разойдётся по файлу'


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as file:
        return file.read()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _slice(path: str, anchor_from: str, anchor_till: str) -> str:
    code = _read(path)

    for anchor in (anchor_from, anchor_till):
        assert anchor in code, (
            f'якорь не найден в {path}: {anchor!r}.\n'
            'Куски вырезаются по этим комментариям — поправьте якоря в тесте либо '
            'верните комментарий на место.')

    return code[code.index(anchor_from):code.index(anchor_till)]


def _base_script() -> str:
    """Заглушки DOM того объёма, каким живёт панель, + живой импорт правила.

    ⚠ Карта групп и кэш неопределённых приезжают настоящими `import`-ами
    (`variable-group.js`, `undefined-index.js`), связка со стейтом — телом того
    же адаптера, что в `variables.js`: тест проверяет список панели, а не свою
    копию правила. Имена, которые вырезанные куски `graph.js` зовут со страницы,
    обязаны жить и в этой заглушке — иначе node падает на первом же `import`.
    """
    # ⚠ `variables.js` сюда не импортируем: его верхний строк лезит в DOM при
    # загрузке, а импорт исполняется прежде тела скрипта — node упал бы на нём.
    # Адаптер здесь повторяют телом; текстом его сверяют с `variables.js` другие
    # тесты этой же сюиты (TestTheRuleLivesInOneFile).
    stub = f'''
    let _varTrace = new Map(), _varPicked = null, _stepNumbers = new Map();
    let _varGroups = new Map(), _undefinedNames = new Map();

    const el = (tag) => ({{tag, kids: [], dataset: {{}}, style: {{}}, value: '',
        append(...one) {{ this.kids.push(...one); }},
        appendChild(one) {{ this.kids.push(one); }}}});
    const boxes = {{}};
    globalThis.document = {{createElement: el,
        getElementById: (id) => (boxes[id] ??= el('div'))}};
    globalThis.window = {{location: {{search: '?workflow_id=6'}},
        localStorage: {{getItem: () => null, setItem: () => {{}}}}}};
    globalThis.location = {{search: '?workflow_id=6'}};

    import {{variablesTrace, variableGroupIndex, VAR_GROUP_UNKNOWN}} from '{GROUP}';
    import {{editorWorkflowId, workflowUndefinedEntriesSync, hiddenNamesFor,
        ensureUndefinedIndex, invalidateUndefinedIndex,
        workflowUndefinedEntries}} from '{INDEX}';
    import {{state}} from '{STATE}';

    state.allCurrentVariables = {_json(REGISTRY)};
    state.allCurrentStepsData = {_json(STEPS)};
    state.allWorkflows = {_json(WORKFLOWS)};
    state.allAvailableTools = {_json(TOOLS)};

    const editorVariableGroupIndex = () => variableGroupIndex(
        state.allCurrentVariables || [], state.allCurrentStepsData,
        state.allWorkflows, state.allAvailableTools, hiddenNamesFor(editorWorkflowId()));
    '''

    # ⚠ `/**`…`*/` вокруг вырезок: куски начинаются и кончаются посреди чужих
    # docstring — без обрамления node прочитал бы код как комментарий.
    return (stub
            + '/**\n'
            + _slice(GRAPH, STEPNUMS_FROM, LIST_FROM)
            + _slice(GRAPH, LIST_FROM, LIST_TILL)
            + '\n*/')


def _node_run(script: str) -> subprocess.CompletedProcess:
    if not shutil.which('node'):
        pytest.skip('node недоступен — отрисовку панели проверить нечем')

    return subprocess.run(['node', '--input-type=module', '-e', script],
                          capture_output=True, text=True)


def _node(script: str, expr: str):
    done = _node_run(script + f'\nprocess.stdout.write(JSON.stringify({expr}));')

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)


def _rows() -> list:
    """Строки живого списка графа: имя, значок, подсказка, порядок детей — proof."""
    rows = _node(_base_script() + '\nrenderGraphVariables(null);',
                'boxes["graphVarList"].kids')

    out = []

    for row in rows:
        kids = row['kids']
        head = next((k for k in kids if k.get('className') == 'graph-var-head'), None)
        count = next((k for k in kids if k.get('className') == 'graph-var-count'), None)
        assert head is not None, f'у строки графа нет блока «значок + имя»: {row}'
        assert count is not None, f'у строки графа нет счётчика шагов: {row}'

        icon = next((k for k in head['kids'] if k.get('className') == 'graph-var-icon'), None)
        name = next((k for k in head['kids'] if k.get('className') == 'graph-var-name'), None)
        assert icon is not None, f'у строки графа нет значка группы: {row}'
        assert name is not None, f'у строки графа нет имени: {row}'

        out.append({'name': row['dataset']['name'],
                    'cls': row.get('className'),
                    'icon': icon['textContent'],
                    'tip': row.get('title'),
                    'count': count['textContent'],
                    'row_kids': [k.get('className') for k in kids],
                    'icon_before_name': head['kids'].index(icon) < head['kids'].index(name)})

    return out

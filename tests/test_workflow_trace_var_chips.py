"""Чипы групп у переменных на трассе: из строки видно, откуда имя пришло.

Списки страницы `/admin/workflow_trace` («Переменные», «Входящие workflow
переменные», «Вход (metadata)» у шага) показывали имя и значение — и молчали о
том, к какой группе имя относится: входящая ли переменная, из реестра workflow,
из шага инструмента, из sub-workflow. Теперь перед каждым именем стоит чип с
иконкой и названием группы («📥 Входящие переменные», «⚙️ Tool переменные»…), а
у имени, которое не нашлось ни в одной группе, — «не объявлена».

## ⚠⚠ Что здесь главное

Разбивает переменные по группам НЕ своя копия правил, а тот же модуль, что
раскладывает панель редактора (`js/workflow/variables.js`): тест зовёт живой
`variableGroupIndex` и живые функции шаблона. Своя копия разошлась бы с панелью
на первой правке — и одна переменная числилась бы входящей в одном месте и
динамической в другом. Отсюда проверки «правило живёт в одном месте» и
«редактор видит ту же группу, что и трасса».

## ⚠ Чип обязан стоять ПЕРЕД именем

Списки отсортированы по алфавиту (см. `test_workflow_trace_vars_sorted.py`):
позиция в списке ничего не значит, значит только подпись рядом с именем. Чип
после имени читался бы как часть подписи значения, а не группы.

## ⚠ Почему через node, а не браузером

Функции чистые: данные на входе, список узлов на выходе. Тот же приём и тот же
пропуск без node, что у `test_workflow_trace_vars_sorted.py`: куски вырезаются
из живых файлов по якорным комментариям — копия разошлась бы с оригиналом.
"""

import json
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.core

PAGE = './data/uvicorn/template/admin/workflow_trace.html'
VARS = './data/uvicorn/public/js/workflow/variables.js'
UTILS = './data/uvicorn/public/js/workflow/utils.js'

# Живой прогон ноды Dating: реестр ветки, шаги со следами и справочники, из
# которых имена собираются. Имена нарочно из всех групп сразу — по одной не
# проверить, что групп шесть, а не одна.
REGISTRY = [
    {'id': 901, 'name': 'girl_name', 'type': 'input', 'default': 'elena',
     'description': 'имя девушки'},
    {'id': 902, 'name': 'talk_history_chat', 'type': 'workflow'},
    {'id': 903, 'name': 'timezone', 'type': 'global'},
    {'id': 904, 'name': 'agent_title', 'type': 'node'},
]

STEPS = [
    {'step_id': 524, 'metadata_rendered': json.dumps({
        'tool_invoke': {
            'tool_name': 'companion_bio',
            'inputs_map': {'bio': '%companion_bio_524_result_bio%'},
            'outputs_map': {'bio': 'girl_bio'},
        }}, ensure_ascii=False)},
    {'step_id': 786, 'metadata_rendered': json.dumps(
        {'workflow_invoke': {'workflow_id': 5, 'next': 'talk_answer'}},
        ensure_ascii=False)},
    {'step_id': 787, 'metadata_rendered': json.dumps({
        'llm_to_json_variable': [{'variable': 'talk_topic', 'text': 'о себе'}]},
        ensure_ascii=False)},
]

TOOLS = [{'name': 'companion_bio',
          'args': json.dumps({'output': {'keys': {'bio': 'string'}}})}]
WORKFLOWS = [{'id': 5, 'name': 'dating_invite_one'}]

RUN = {'workflow_id': 5, 'steps': STEPS}

# Что обязан показать чип у каждого имени: подпись группы и её ключ (из ключа
# рождён класс чипа `var-group-<ключ>`).
EXPECTED = {
    'girl_name': ('input', '📥 Входящие переменные'),
    'timezone': ('common', '🇬 Глобальные переменные'),
    'agent_title': ('node', '🇳 Node переменные'),
    'talk_history_chat': ('workflow', '🇼 Workflow переменные'),
    'companion_bio_524_result_bio': ('tool', '⚙️ Tool переменные'),
    'dating_invite_one_786_result_str': ('tool', '⚙️ Tool переменные'),
    'girl_bio': ('dynamic', '🌀 Dynamic переменные'),
    'talk_topic': ('dynamic', '🌀 Dynamic переменные'),
    # ни в реестре, ни в следах шагов: имя обязано честно говорить об этом
    'prompt_user': ('unknown', 'не объявлена'),
}

VALUES = {name: f'значение:{name}' for name in EXPECTED}

# Якоря кусков: живой код файлов вырезается, а не копируется в тест.
PAGE_FROM = '// Строка списка переменных'
PAGE_TILL = '// Значения переменных, участвующих в metadata шага'
VARS_STEP_FROM = '// Поля, где лежит имя переменной, **в которую шаг пишет**'
VARS_STEP_TILL = '// Массивы, где ключ `variable` означает **чтение**'
VARS_GROUP_FROM = '// Распределяет переменные по группам'
VARS_GROUP_TILL = '// Заполняет селект опциями переменных'
VARS_RUN_FROM = '// «Имя → группа» для одного прогона'
VARS_RUN_TILL = '// Переменные запуска: снапшот на старте'
UTILS_FROM = 'export function parseMetadata'
UTILS_TILL = '// Ключ выбранной вкладки'


class TestEveryRowCarriesItsChip:
    """⚠⚠ У каждой строки списка — чип группы, и стоит он перед именем."""

    def test_every_name_gets_its_chip_before_it(self):
        for row in _render('values'):
            assert row['chip_before_name'], \
                f'у «{row["name"]}» чип группы стоит не перед именем: {row["cls"]}'

    def test_chip_signs_the_group_the_rule_picked(self):
        """⚠ Подпись чипа — группа того же правила, что раскладывает панель редактора."""
        for row in _render('values'):
            key, title = EXPECTED[row['name']]

            assert row['text'] == title, (
                f'у «{row["name"]}» чип подписан не своей группой: '
                f'{row["text"]!r}, ждали {title!r}')
            assert row['cls'] == f'var-group var-group-{key}', \
                f'у «{row["name"]}» чип в чужом классе: {row["cls"]}'

    def test_a_chip_text_is_clean(self):
        """⚠ Подпись с висящим пробелом — та же грязь, что пустое место у имени."""
        for row in _render('values'):
            assert row['text'] == row['text'].strip(), \
                f'у «{row["name"]}» подпись чипа обросла пробелами: {row["text"]!r}'

    def test_the_declared_list_gets_chips_too(self):
        """⚠ Правый список («Входящие workflow переменные») — теми же чипами."""
        for row in _render('declared'):
            assert row['text'] == EXPECTED[row['name']][1], \
                f'у объявленной «{row["name"]}» чип чужой: {row["text"]!r}'


class TestTheStepReadsFromTheSameMap:
    """⚠ Список «Вход (metadata)» у шага размечается той же картой."""

    def test_the_step_line_passes_the_same_groups_map(self):
        code = _read(PAGE)
        assert 'renderVariablesList(inputVariables, null, variableGroups)' in code, \
            'шаг отдаёт своему списку переменных свою карту групп — группы разъедутся'

    def test_the_step_values_get_the_same_chips(self):
        for row in _render('step'):
            assert row['text'] == EXPECTED[row['name']][1], \
                f'в «Вход (metadata)» у «{row["name"]}» чип чужой: {row["text"]!r}'


class TestOneRuleForBothPages:
    """⚠⚠⚠ Правило одно и живёт оно в модуле редактора, а не копией на трассе."""

    def test_the_rule_is_defined_once(self):
        """Разошедшаяся копия правил — переменная входящая тут, динамическая там."""
        everywhere = _read(VARS) + _read(UTILS) + _read(PAGE)

        assert everywhere.count('function groupWorkflowVariables(') == 1, \
            'правило разбора объявлено не один раз — копии разойдутся на правке'
        assert "import {variableGroupIndex} from '/static/js/workflow/variables.js'" \
            in _read(PAGE), 'трасса берёт разбор из модуля редактора, а не из копии'

    def test_the_editor_sees_the_same_group_as_the_trace_chip(self):
        """Одна карта на обе страницы: редактор и трасса показывают одну группу."""
        for name, (key, title) in EXPECTED.items():
            got = _editor_group(name)

            if key == 'unknown':
                assert got is None, \
                    f'редактор придумал «{name}» группу {got}, хотя её никто не заводил'
            else:
                assert got == {'key': key, 'title': title}, \
                    f'редактор видит «{name}» иначе, чем трасса: {got!r}'


class TestThePaintExists:
    """⚠ У каждого ключа группы есть свой акцент в стилях — иначе чип немой."""

    def test_every_group_key_has_a_rule(self):
        code = _read(PAGE)

        for key in {key for key, _ in EXPECTED.values()}:
            assert re.search(r'\.var-group-' + re.escape(key) + r'\s*\{', code), \
                f'для чипов «{key}» нет своего цвета — группу не отличить глазами'


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as file:
        return file.read()


def _slice(path: str, anchor_from: str, anchor_till: str) -> str:
    code = _read(path)

    for anchor in (anchor_from, anchor_till):
        assert anchor in code, (
            f'якорь не найден в {path}: {anchor!r}.\n'
            'Куски вырезаются по этим комментариям — поправьте якоря в тесте либо '
            'верните комментарий на место.')

    return code[code.index(anchor_from):code.index(anchor_till)]


def _base_script() -> str:
    """Заглушки DOM ровно того объёма, каким живут функции, + живые куски файлов."""
    stub = f'''
    const el = (tag, cls, text) => ({{tag, cls, text, kids: [],
        appendChild(one) {{ this.kids.push(one); }}}});
    const document = {{createElement: (tag) => el(tag)}};
    const state = {{workflows: {json.dumps(WORKFLOWS, ensure_ascii=False)},
                   tools: {json.dumps(TOOLS, ensure_ascii=False)},
                   allWorkflows: {json.dumps(WORKFLOWS, ensure_ascii=False)},
                   allAvailableTools: {json.dumps(TOOLS, ensure_ascii=False)},
                   allCurrentVariables: {json.dumps(REGISTRY, ensure_ascii=False)},
                   allCurrentStepsData: {json.dumps([{f'id': s['step_id'], 'metadata': s['metadata_rendered']} for s in STEPS], ensure_ascii=False)}}};
    const workflowVariablesCache = {{'5': {json.dumps(REGISTRY, ensure_ascii=False)}}};
    const RUN = {json.dumps(RUN, ensure_ascii=False)};
    '''

    return (stub
            + _slice(UTILS, UTILS_FROM, UTILS_TILL)
            + _slice(VARS, VARS_STEP_FROM, VARS_STEP_TILL)
            + _slice(VARS, VARS_GROUP_FROM, VARS_GROUP_TILL)
            + _slice(PAGE, PAGE_FROM, PAGE_TILL)
            + _slice(PAGE, VARS_RUN_FROM, VARS_RUN_TILL))


def _node(script: str, expr: str):
    if not shutil.which('node'):
        pytest.skip('node недоступен — отрисовку страницы проверить нечем')

    done = subprocess.run(['node', '--input-type=module', '-e',
                           script + f'\nprocess.stdout.write(JSON.stringify({expr}));'],
                          capture_output=True, text=True)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)


def _render(what: str) -> list:
    """Строки живого списка: имя, класс и подпись чипа, порядок детей узла — proof.

    Args:
        'values' — левый список («Переменные») прогона;
        'declared' — правый («Входящие workflow переменные»);
        'step' — «Вход (metadata)» шага: те же карты, часть имён.
    """
    script = _base_script()

    if what == 'values':
        script += f'\nconst vars = {json.dumps(VALUES, ensure_ascii=False)};'
        expr = 'renderVariablesList(vars, null, runVariableGroups(RUN))'
    elif what == 'declared':
        expr = 'renderWorkflowVariablesList(state.allCurrentVariables, {}, null, ' \
               'runVariableGroups(RUN))'
    else:
        subset = {name: VALUES[name] for name in
                  ('girl_name', 'agent_title', 'dating_invite_one_786_result_str')}
        script += f'\nconst subset = {json.dumps(subset, ensure_ascii=False)};'
        expr = 'renderVariablesList(subset, null, runVariableGroups(RUN))'

    out = []

    for li in _node(script, expr)['kids']:
        head = li['kids'][0]
        chip = next((k for k in head['kids'] if 'var-group' in (k['cls'] or '')), None)
        name = next((k for k in head['kids'] if k['cls'] == 'var-name'), None)
        assert chip is not None, f'у строки списка нет чипа группы: {li}'
        assert name is not None, f'у строки списка нет имени: {li}'
        out.append({'name': name['text'].strip('%'),
                    'cls': chip['cls'],
                    'text': chip['text'],
                    'key': chip['cls'].removeprefix('var-group var-group-'),
                    'chip_before_name':
                        head['kids'].index(chip) < head['kids'].index(name)})

    return out


def _editor_group(name: str):
    """Группу имени видит и редактор: variableGroupOf — та же карта, что у трассы."""
    got = _node(_base_script(), f'variableGroupOf({json.dumps(name, ensure_ascii=False)})')

    return got

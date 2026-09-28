"""Чипы групп у переменных на трассе: из строки видно, откуда имя пришло.

Списки страницы `/admin/workflow_trace` («Переменные» прогона и «Вход (metadata)»
у шага) показывали имя и значение — и молчали о том, к какой группе имя
относится: входящая ли переменная, из реестра workflow, из шага инструмента, из
sub-workflow. Теперь перед каждым именем стоит чип со **значком** группы (📥, 🇬,
🇳, ⚙️, 🇼, 🌀), а полное название группы живёт только подсказкой наведённой
мыши — в тесной строке списка оно съедало треть места. У имени, которое не
нашлось ни в одной группе, — чип «∅» с тем же честным «не объявлена» в подсказке.

## ⚠⚠ Что здесь главное

Разбивает переменные по группам НЕ своя копия правил, а **чистый модуль**
`js/workflow/variable-group.js` — тот же, которым размечает группы панель
редактора. Тест зовёт его живым импортом, а не вырезкой: своя копия разошлась бы
с панелью на первой правке, и одна переменная числилась бы входящей в одном месте
и динамической в другом.

## ⚠ Чистота модуля — не стиль, а условие задачи

Пока правило лежало внутри панели редактора (`variables.js`), страница трассы за
одной функцией тянула тысячу строк UI, `api.js`, `notification.js` и обработчик
`change`, который вешается прямо на импорте. Поэтому `TestTheRuleIsPure` заводит
модуль в голом node **без единой заглушки**: упал — значит правило снова приросло
к странице.

## ⚠ Чип обязан стоять ПЕРЕД именем

Списки отсортированы по алфавиту (см. `test_workflow_trace_vars_sorted.py`):
позиция в списке ничего не значит, значит только подпись рядом с именем. Чип
после имени читался бы как часть подписи значения, а не группы.

## ⚠ Почему через node, а не браузером

Функции чистые: данные на входе, список узлов на выходе. Тот же приём и тот же
пропуск без node, что у `test_workflow_trace_vars_sorted.py`. Куски страницы
по-прежнему вырезаются по якорным комментариям — у шаблона модулей нет.
"""

import json
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.core

PAGE = './data/uvicorn/template/admin/workflow_trace.html'
GROUP = './data/uvicorn/public/js/workflow/variable-group.js'
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

# Что обязан показать чип у каждого имени: значок группы в чипе, полная подпись —
# только подсказкой, и ключ (из ключа рождён класс чипа `var-group-<ключ>`).
EXPECTED = {
    'girl_name': {'key': 'input', 'icon': '📥', 'title': '📥 Входящие переменные'},
    'timezone': {'key': 'common', 'icon': '🇬', 'title': '🇬 Глобальные переменные'},
    'agent_title': {'key': 'node', 'icon': '🇳', 'title': '🇳 Node переменные'},
    'talk_history_chat': {'key': 'workflow', 'icon': '🇼', 'title': '🇼 Workflow переменные'},
    'companion_bio_524_result_bio': {'key': 'tool', 'icon': '⚙️', 'title': '⚙️ Tool переменные'},
    'dating_invite_one_786_result_str': {'key': 'tool', 'icon': '⚙️', 'title': '⚙️ Tool переменные'},
    'girl_bio': {'key': 'dynamic', 'icon': '🌀', 'title': '🌀 Dynamic переменные'},
    'talk_topic': {'key': 'dynamic', 'icon': '🌀', 'title': '🌀 Dynamic переменные'},
    # ни в реестре, ни в следах шагов: имя обязано честно говорить об этом
    'prompt_user': {'key': 'unknown', 'icon': '∅', 'title': 'не объявлена'},
}

VALUES = {name: f'значение:{name}' for name in EXPECTED}

# Якоря кусков страницы: живой код вырезается, а не копируется в тест.
# ⚠ Правило группировки здесь больше не режется — оно приходит настоящим импортом.
PAGE_FROM = '// Строка списка переменных'
PAGE_TILL = '// Значения переменных, участвующих в metadata шага'
PAGE_RUN_FROM = '// Разобранные группы по объекту прогона'
PAGE_RUN_TILL = '// Переменные запуска: снапшот на старте'


class TestTheRuleIsPure:
    """⚠⚠ Правило живёт чистым модулем: ни DOM, ни сети, ни стейта страницы."""

    def test_the_module_loads_with_no_browser_at_all(self):
        """Заводится в голом node без заглушек — иначе трасса снова тянет редактор."""
        done = _node_run(f'await import({_json(GROUP)});')

        assert done.returncode == 0, (
            'чистый модуль не заводится без браузера:\n' + done.stderr +
            '\nЗначит, в него вернулась привязка к странице — DOM, сеть или стейт.')

    def test_the_module_imports_nothing_but_helpers(self):
        """⚠ Импорт стейта или сети — та же привязка, только записанная строкой."""
        imported = re.findall(r"^import\s.*?from\s+'([^']+)'", _read(GROUP), re.M)

        assert imported == ['./utils.js'], \
            f'чистый модуль потянул к себе лишнее: {imported}'

    def test_the_module_never_reaches_for_page_state(self):
        forbidden = [word for word in ('state.', 'document.', 'window.', 'getData(')
                     if word in _read(GROUP)]

        assert not forbidden, \
            f'в правило вернулась привязка к странице: {forbidden}'


class TestEveryRowCarriesItsChip:
    """⚠⚠ У каждой строки списка прогона — чип со значком группы, перед именем."""

    def test_every_name_gets_its_chip_before_it(self):
        for row in _render('values'):
            assert row['chip_before_name'], \
                f'у «{row["name"]}» чип группы стоит не перед именем: {row["cls"]}'

    def test_chip_carries_the_sign_and_the_tooltip_the_name(self):
        """⚠ В чипе — значок своей группы, вся подпись переехала в подсказку."""
        for row in _render('values'):
            want = EXPECTED[row['name']]

            assert row['icon'] == want['icon'], (
                f'у «{row["name"]}» чип размечен не своей группой: '
                f'{row["icon"]!r}, ждали {want["icon"]!r}')
            assert row['tip'] == want['title'], (
                f'у «{row["name"]}» подсказка чипа молчит о группе: '
                f'{row["tip"]!r}, ждали {want["title"]!r}')
            assert row['cls'] == f"var-group var-group-{want['key']}", \
                f'у «{row["name"]}» чип в чужом классе: {row["cls"]}'

    def test_a_chip_holds_no_text_name(self):
        """⚠ Текстовое название в чипе — половина строки, съеденная подписью.

        Значок читается глазами, название перечитывали бы дважды: чип обязан
        нести одни лишь знаки, а слово — только подсказка.
        """
        for row in _render('values'):
            assert not re.search(r'[a-zA-Zа-яА-ЯёЁ]', row['icon']), \
                f'у «{row["name"]}» чип снова расписан текстом: {row["icon"]!r}'

    def test_a_chip_text_is_clean(self):
        """⚠ Значок с висящим пробелом — та же грязь, что пустое место у имени."""
        for row in _render('values'):
            assert row['icon'] == row['icon'].strip(), \
                f'у «{row["name"]}» значок чипа оброс пробелами: {row["icon"]!r}'


class TestTheDeclaredListStaysPlain:
    """⚠⚠ У правого списка («Входящие workflow переменные») чипа нет — и не должно.

    Он строится как `реестр.filter(type === 'input')`, а разбивка кладёт
    `type === 'input'` ровно в группу «Входящие»: чип у всех строк вышел бы один и
    тот же и лишь повторял бы заголовок аккордеона. Проверено на 334 прогонах —
    330 строк из 330 дали `input`, других не бывает **по построению**.
    """

    def test_the_declared_rows_carry_no_group_chip(self):
        for li in _node(_base_script() + f'\nconst declared = {_json(REGISTRY)};',
                        'renderWorkflowVariablesList(declared, {}, null)')['kids']:
            chips = [k for k in li['kids'][0]['kids'] if 'var-group' in (k['cls'] or '')]

            assert not chips, \
                f'в правом списке снова завёлся чип: {chips} — он там всегда один и тот же'

    def test_the_declared_list_takes_no_groups_argument(self):
        """Довод не должен и приезжать: мёртвый аргумент переживёт мёртвый чип."""
        assert 'renderWorkflowVariablesList(declared, values, sources)' in _read(PAGE), \
            'правому списку снова передают карту групп, хотя рисовать её нечем'


class TestTheStepReadsFromTheSameMap:
    """⚠ Список «Вход (metadata)» у шага размечается той же картой."""

    def test_the_step_line_passes_the_same_groups_map(self):
        assert 'renderVariablesList(inputVariables, null, variableGroups)' in _read(PAGE), \
            'шаг отдаёт своему списку переменных свою карту групп — группы разъедутся'

    def test_the_step_values_get_the_same_chips(self):
        for row in _render('step'):
            want = EXPECTED[row['name']]
            assert row['icon'] == want['icon'] and row['tip'] == want['title'], \
                f'в «Вход (metadata)» у «{row["name"]}» чип чужой: {row["icon"]!r}'


class TestOneRuleForBothPages:
    """⚠⚠⚠ Правило одно, и трасса берёт именно его, а не копию и не панель."""

    def test_the_rule_is_defined_once(self):
        """Разошедшаяся копия правил — переменная входящая тут, динамическая там."""
        everywhere = _read(GROUP) + _read(VARS) + _read(UTILS) + _read(PAGE)

        for name in ('groupWorkflowVariables', 'workflowVariableSections',
                     'getToolOutputKeys', 'variableGroupIndex'):
            assert everywhere.count(f'function {name}(') == 1, \
                f'«{name}» объявлена не один раз — копии разойдутся на правке'

    def test_the_trace_takes_the_rule_from_the_clean_module(self):
        page = _read(PAGE)

        assert "from '/static/js/workflow/variable-group.js'" in page, \
            'трасса берёт разбор не из чистого модуля'
        assert "/static/js/workflow/variables.js'" not in page, \
            'трасса снова импортирует панель редактора — вместе со всей её обвязкой'

    def test_the_editor_binds_the_page_state_in_one_place(self):
        """⚠ Стейт страницы подставляет редактор, и ровно в одном месте.

        Правило стейта не знает (им пользуется и трасса), но привязку надо где-то
        держать: четвёрка `state.*`, повторённая по вызовам, разойдётся молча —
        одному забудут справочник, и группа поедет.
        """
        code = _read(VARS)

        assert 'export function editorVariableGroups(' in code, \
            'адаптер редактора пропал — привязка к стейту снова разойдётся по файлу'

        # Каждую функцию правила панель зовёт ровно из своего адаптера: второй
        # вызов — это вторая четвёрка `state.*`, и разойдутся они молча.
        for name in ('groupWorkflowVariables', 'variableGroupIndex'):
            assert code.count(f'{name}(') == 1, \
                f'«{name}» зовут из панели больше одного раза — мимо адаптера'


class TestThePaintExists:
    """⚠ У каждого ключа группы есть свой акцент в стилях — иначе чип немой."""

    def test_every_group_key_has_a_rule(self):
        code = _read(PAGE)

        for key in {g['key'] for g in EXPECTED.values()}:
            assert re.search(r'\.var-group-' + re.escape(key) + r'\s*\{', code), \
                f'для чипов «{key}» нет своего цвета — группу не отличить глазами'


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
    """Заглушки DOM того объёма, каким живут функции страницы, + живой импорт правила.

    ⚠⚠ Правило приезжает `import`-ом, а не вырезкой: ради этого его и вынесли в
    отдельный модуль. Режется только то, у чего файла нет, — код внутри `<script>`
    самой страницы.
    """
    stub = f'''
    import {{variableGroupIndex}} from '{GROUP}';

    const el = (tag, cls, text) => ({{tag, cls, text, kids: [],
        appendChild(one) {{ this.kids.push(one); }}}});
    const document = {{createElement: (tag) => el(tag)}};
    const state = {{workflows: {_json(WORKFLOWS)}, tools: {_json(TOOLS)}}};
    const workflowVariablesCache = {{'5': {_json(REGISTRY)}}};
    const RUN = {_json(RUN)};
    '''

    return (stub
            + _slice(PAGE, PAGE_FROM, PAGE_TILL)
            + _slice(PAGE, PAGE_RUN_FROM, PAGE_RUN_TILL))


def _node_run(script: str) -> subprocess.CompletedProcess:
    if not shutil.which('node'):
        pytest.skip('node недоступен — отрисовку страницы проверить нечем')

    # ⚠ Без `cwd`: относительные пути в `import` node считает от текущей папки, а
    # сюита и так идёт из корня проекта — оттуда же собраны и константы путей.
    return subprocess.run(['node', '--input-type=module', '-e', script],
                          capture_output=True, text=True)


def _node(script: str, expr: str):
    done = _node_run(script + f'\nprocess.stdout.write(JSON.stringify({expr}));')

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)


def _render(what: str) -> list:
    """Строки живого списка: имя, класс и подпись чипа, порядок детей узла — proof.

    Args:
        'values' — список «Переменные» прогона;
        'step' — «Вход (metadata)» шага: та же карта, часть имён.
    """
    script = _base_script()

    if what == 'values':
        script += f'\nconst vars = {_json(VALUES)};'
    else:
        script += '\nconst vars = ' + _json(
            {name: VALUES[name] for name in
             ('girl_name', 'agent_title', 'dating_invite_one_786_result_str')}) + ';'

    out = []

    for li in _node(script, 'renderVariablesList(vars, null, runVariableGroups(RUN))')['kids']:
        head = li['kids'][0]
        chip = next((k for k in head['kids'] if 'var-group' in (k['cls'] or '')), None)
        name = next((k for k in head['kids'] if k['cls'] == 'var-name'), None)
        assert chip is not None, f'у строки списка нет чипа группы: {li}'
        assert name is not None, f'у строки списка нет имени: {li}'
        out.append({'name': name['text'].strip('%'),
                    'cls': chip['cls'],
                    'icon': chip['text'],
                    'tip': chip['title'],
                    'key': chip['cls'].removeprefix('var-group var-group-'),
                    'chip_before_name':
                        head['kids'].index(chip) < head['kids'].index(name)})

    return out

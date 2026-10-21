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
INDEX = './data/uvicorn/public/js/workflow/variable-undefined.js'
UTILS = './data/uvicorn/public/js/workflow/utils.js'
STATE = './data/uvicorn/public/js/workflow/state.js'

# Шаги открытого в редакторе workflow (`.id`/`.metadata`, не прогонные
# `step_id`/`metadata_rendered`) и реестр переменных. Имена нарочно из всех
# групп сразу — половина их не встречается ни в одном следе шага.
# ⚠ Умолчание нарочно длинное и со спецзнаками — это настоящая регулярка из
# `dating_mail_write`, на которой беду и заметили: обрезка делала её бесполезной.
DEFAULT_SAMPLE = r'\[\[([A-Za-z_][A-Za-z0-9_]*)\]\]'

REGISTRY = [
    {'id': 901, 'name': 'girl_name', 'type': 'input', 'default': DEFAULT_SAMPLE},
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
    # ⚠⚠ Шаг с циклом и присваиванием. `k`, `v` и `n` он связывает ПРЯМО В
    # ТЕКСТЕ, и в списке переменных им не место: они живут внутри одного поля
    # промпта, а не в прогоне. Источник цикла — наоборот, настоящее чтение, и
    # пропасть он не должен.
    #
    # ⚠ Источником взято имя, которое шаги читают и без цикла: возьми мы
    # нетронутое, оно выпало бы из `SILENT` и сломало соседний случай про
    # «0→0» — тот стережёт совсем другое.
    {'id': 788, 'metadata': json.dumps({
        'prompt_user': '[<for k,v in companion_bio_524_result_bio, start=1>]%k%. %v%'
                       '[<endfor>][<set n = 1>]%n%'},
        ensure_ascii=False)},
]

# Имена, связанные текстом шага: ни одного из них в списке быть не должно.
BOUND = ('k', 'v', 'n')

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
# Кусок панели переменной: строка «по умолчанию». ⚠ Режется отдельно от списка —
# между ними лежит выбор переменной, которому нужен живой граф.
DEFAULT_FROM = '* Строка «по умолчанию» в панели переменной'
DEFAULT_TILL = '* Трасса словами: кто кладёт, кто читает'


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


class TestTheLoopNamesStayInTheirText:
    """⚠⚠⚠ Счётчик цикла и присваивание в списке переменных НЕ показываются.

    `[<for k,v in …>]` и `[<set n = …>]` заводят имя внутри одного текстового
    поля; движок считает их в копии словаря и в прогон не отдаёт
    (`ai_workflow_set_render`). Показать их списком значило бы предложить
    человеку переменную, которой нигде, кроме строки промпта, не существует, —
    и ту ещё можно завести в реестре, молча перекрыв собою счётчик цикла.

    Поймано на живом: в `dating_mail_write` после первого же цикла в списке
    графа появилась строка `v` со значком «∅ не объявлена».
    """

    def test_no_bound_name_reaches_the_list(self):
        got = {row['name'] for row in _rows()}

        leaked = sorted(one for one in BOUND if one in got)

        assert not leaked, (
            f'имена, связанные текстом, протекли в список графа: {leaked}. '
            'Их вычитает `variablesTrace` пошагово — проверьте, что она зовёт '
            '`stepBoundVariables`.')

    def test_the_loop_source_is_still_read(self):
        """⚠ Вычитаются только связанные: источник цикла — обычное чтение."""
        got = {row['name'] for row in _rows()}

        assert 'companion_bio_524_result_bio' in got, (
            'вместе со счётчиком пропал источник цикла — вычитание задело лишнее')


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


class TestThePanelTellsWhereTheValueComesFrom:
    """⚠⚠⚠ У переменной реестра панель показывает ЗНАЧЕНИЕ ПО УМОЛЧАНИЮ.

    Без него строка «КЛАДУТ: —» оставляла вопрос без ответа: никто не кладёт, а
    значение откуда-то берётся. Поймано на живом — `mail_var_pattern` в
    `dating_mail_write`: умолчание есть, видно его было только на вкладке
    «Шаги», и то обрезанным до десяти знаков.

    ⚠ Три случая, и все три разные: значение есть, записи нет, запись есть —
    умолчания нет. Сливать последние два нельзя: «не пришлют — будет пусто» и
    «ищи, кто кладёт» чинятся по-разному.
    """

    def test_the_value_is_shown_whole(self):
        """⚠ Целиком, без обрезки: у переменной письма это регулярка."""
        got = _default_rows('girl_name')
        value = next((r for r in got if r['cls'] == 'trace-default'), None)

        assert value is not None, (
            f'панель не показала умолчание переменной реестра: {got}')
        assert value['text'] == DEFAULT_SAMPLE, (
            f'умолчание показано не целиком: {value["text"]!r} '
            f'вместо {DEFAULT_SAMPLE!r}')

    def test_a_registry_name_without_default_gets_a_dash(self):
        """⚠⚠ Прочерк, а не молчание: «записи нет» — другой ответ, не этот."""
        got = _default_rows('talk_history_chat')
        labels = [r['text'] for r in got if r['cls'] == 'trace-role']

        assert 'ПО УМОЛЧАНИЮ:' in labels, (
            f'у переменной реестра пропала сама строка умолчания: {got}')
        assert any(r['cls'] == 'trace-none' for r in got), (
            f'пустое умолчание показано не прочерком: {got}')

    def test_the_panel_actually_calls_it(self):
        """⚠⚠ Что строка РИСУЕТСЯ, а не просто умеет рисоваться.

        Случаи выше зовут `_appendDefault` напрямую — они стерегут саму строку.
        Убери кто-нибудь её вызов из панели, и они останутся зелёными, а
        человек снова не узнает, откуда берётся значение. Поэтому вызов
        проверяется отдельно и текстом: вырезать сюда `renderVariableTrace`
        целиком дороже — ему нужен живой граф и обработчики щелчка.
        """
        code = _read(GRAPH)
        panel = code[code.index(DEFAULT_TILL):]

        assert '_appendDefault(box, name)' in panel, (
            'панель переменной больше не зовёт `_appendDefault` — строка '
            '«ПО УМОЛЧАНИЮ» пропала с экрана, и «КЛАДУТ: —» снова оставляет '
            'вопрос без ответа')

    def test_a_name_outside_the_registry_gets_no_row(self):
        """⚠ У результата инструмента умолчания не бывает — строки нет вовсе."""
        got = _default_rows('companion_bio_524_result_bio')

        assert got == [], (
            f'панель завела строку умолчания имени без записи в реестре: {got}')


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
    (`variable-group.js`, `variable-undefined.js`), связка со стейтом — телом того
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
    import {{workflowUndefinedEntriesSync, hiddenNamesFor,
        ensureUndefinedIndex, invalidateUndefinedIndex,
        workflowUndefinedEntries}} from '{INDEX}';
    import {{editorWorkflowId}} from '{UTILS}';
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
            + '\n*/\n/**\n'
            + _slice(GRAPH, DEFAULT_FROM, DEFAULT_TILL)
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


def _default_rows(name: str) -> list:
    """Что кладёт в панель строка «по умолчанию» для этого имени."""
    return _node(_base_script() + f"\nconst box = document.getElementById('probe');"
                 f"\n_appendDefault(box, {json.dumps(name)});",
                 "boxes['probe'].kids.map(k => ({cls: k.className, text: k.textContent}))")


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

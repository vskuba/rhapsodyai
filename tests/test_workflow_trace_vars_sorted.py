"""Переменные на странице трасс: список по алфавиту, и ни одно имя не пропало.

Страница `/admin/workflow_trace` показывает у каждого прогона два списка — значения
переменных («Переменные») и объявленные входы workflow («Входящие workflow
переменные»), — плюс третий у каждого шага («Вход (metadata)»). Все три строит одна
из двух функций шаблона, и обе теперь сортируют имена.

## ⚠ Почему сортировка вообще понадобилась

Порядок вставки ничего не значил: слева он шёл от снапшота старта к тому, что дописали
шаги, справа — как отдала ручка реестра. В прогоне девятнадцать переменных, и найти
среди них нужную глазами можно было только перечитав список целиком.

## ⚠⚠ Что сортировка НЕ должна была сломать

**Происхождение значения.** Его несёт бейдж рядом с именем («старт» / «шаг #N» /
«умолчание»), а не позиция в списке, — потому сортировать и можно. Здесь это
проверяется прямо: бейдж обязан остаться при своём имени, а не при своём номере.

**Чужой кэш.** `declared` — массив из `workflowVariablesCache`, общий на все прогоны
одного workflow. `Array.sort` правит массив на месте, и без копии отрисовка одного
прогона перекладывала бы список, из которого читают остальные.

## ⚠ Почему через node, а не браузером

Функции чистые: объект на входе, список узлов на выходе. Браузерный тест стоил бы
живого Chromium и вкладки из общего пула, а проверял бы то же самое. Тот же приём и
тот же пропуск без node, что у `test_workflow_prompt_highlight.py`.

⚠⚠ Отличие от того теста: здесь код живёт **внутри HTML-шаблона**, а не отдельным
модулем ESM, и `import` его не возьмёт. Поэтому кусок вырезается по якорным
комментариям — и тест падает с внятными словами, если якоря съехали. Копировать
функции сюда нельзя: копия разошлась бы с оригиналом на первой правке, и тест стерёг
бы себя.
"""

import json
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.core

PAGE = './data/uvicorn/template/admin/workflow_trace.html'

# Якоря куска, который проверяется: от заголовка про порядок имён до следующей функции.
ANCHOR_FROM = '// Порядок имён в списках переменных'
ANCHOR_TILL = '// Значения переменных, участвующих в metadata шага'

# Живой снимок переменных прогона ноды Dating — имена и порядок как в базе.
#
# ⚠ Порядок здесь **нарочно неотсортированный**: это то, что приходит со страницы, и
# именно его функция обязана привести к алфавиту. Отсортируй его — тест перестал бы
# проверять что-либо.
LIVE = {
    'prompt_user': 'привет',
    'user_id': 170,
    'user_username': 'vova.tkachenko',
    'companion_id': 128282,
    'companion_name': 'dating_343_128282',
    'companion_title': 'Gerard',
    'agent_id': 184,
    'agent_name': 'dating_girl_universal',
    'girl_name': 'elena',
    'girl_title': 'Elena',
    'girl_id': '599939',
    'workflow_id': 5,
    'session_uuid': 'zz-1',
    'node_id': 3,
    'user_language': 'en',
}


class TestTheNamesAreSorted:
    """⚠ Оба списка — по алфавиту, и оба одним компаратором."""

    def test_the_values_list_is_sorted(self):
        got = _render('left')

        assert got == sorted(got), f'список значений не по алфавиту: {got}'

    def test_the_declared_list_is_sorted(self):
        got = _render('right')

        assert got == sorted(got), f'список объявленных не по алфавиту: {got}'

    def test_both_lists_use_one_comparator(self):
        """⚠⚠ Один компаратор на оба списка, а не два похожих.

        Две копии правила разошлись бы на первой правке — и левый список листался бы
        иначе, чем правый, в одном и том же ряду страницы.
        """
        code = _source()

        assert code.count('const byVarName') == 1, 'компаратор объявлен не один раз'
        assert code.count('byVarName(') == 2, \
            'компаратор зовут не оба списка (ждали ровно два вызова)'


class TestNothingIsLost:
    """⚠⚠⚠ Сортировка переставляет, а не отбирает: имён на выходе столько же."""

    def test_every_name_is_still_there(self):
        got = _render('left')

        assert sorted(got) == sorted(LIVE), (
            'состав списка изменился\n'
            f'   пропало:   {sorted(set(LIVE) - set(got))}\n'
            f'   появилось: {sorted(set(got) - set(LIVE))}')

    def test_the_badge_follows_its_name(self):
        """⚠⚠ Бейдж происхождения переехал вместе со своим именем.

        Это главное, что могла сломать сортировка: бейджи строятся из отдельного
        словаря `sources`, и привяжись они к позиции, а не к имени, — страница
        показывала бы «старт» у переменной, которую записал шаг. Ложь, которую по виду
        не отличить от правды.
        """
        pairs = _render('left', badges=True)

        for name, badge in pairs:
            assert badge == f'источник:{name}', \
                f'у «{name}» бейдж чужой: {badge}'


class TestTheSharedCacheIsNotTouched:
    """⚠⚠ `workflowVariablesCache` — общий на все прогоны одного workflow."""

    def test_the_declared_array_keeps_its_order(self):
        """⚠ `Array.sort` правит массив на месте. Отрисовка обязана сортировать копию:
        иначе показ одного прогона переложил бы список, из которого читают остальные, —
        и порядок на странице зависел бы от того, какие карточки успели раскрыть.
        """
        was, now = _render('cache')

        assert now == was, (f'кэш переложен отрисовкой\n'
                            f'   был:  {was}\n'
                            f'   стал: {now}')


def test_the_metadata_keys_are_left_alone():
    """⚠ Ключи metadata шага сортировать НЕ надо, и это не забывчивость.

    У них авторский порядок: `tool_name` стоит перед `inputs_map`, потому что так
    читается — сперва чем зовём, потом с чем. Это не список переменных, а настройка
    шага, и алфавит перемешал бы её без пользы.
    """
    code = _source()
    where = code.index('function renderMetadataBlock')
    body = code[where:where + 1200]

    assert 'byVarName' not in body, \
        'сортировка уехала в metadata шага — там нужен авторский порядок ключей'


def _source() -> str:
    with open(PAGE, encoding='utf-8') as file:
        return file.read()


def _slice() -> str:
    """Кусок шаблона с компаратором и двумя отрисовками — оригинал, не копия."""
    code = _source()

    for anchor in (ANCHOR_FROM, ANCHOR_TILL):
        assert anchor in code, (
            f'якорь не найден в {PAGE}: {anchor!r}.\n'
            'Кусок вырезается по этим комментариям — поправьте якоря в тесте либо '
            'верните комментарий на место.')

    return code[code.index(ANCHOR_FROM):code.index(ANCHOR_TILL)]


def _render(what: str, badges: bool = False):
    """Прогоняет настоящие функции страницы в node и отдаёт, что они построили.

    Args:
        what: `'left'` — список значений, `'right'` — объявленные входы,
            `'cache'` — порядок массива `declared` до и после отрисовки.
        badges: отдать пары «имя, бейдж» вместо одних имён.
    """
    if not shutil.which('node'):
        pytest.skip('node недоступен — отрисовку страницы проверить нечем')

    # Подделка DOM: функциям нужен только `appendChild`, и настоящий документ здесь
    # проверял бы браузер, а не сортировку.
    stub = '''
    const el = (tag, cls, text) => ({tag, cls, text, kids: [],
        appendChild(one) { this.kids.push(one); }});
    const varSourceBadge = (source) => ({className: 'src', text: source.label});
    const varListItem = (name, value, badges) => ({name,
        badge: (badges && badges[0]) ? badges[0].text : ''});
    '''

    # ⚠ Бейджи метим именем нарочно: «источник:girl_name» у другого имени сразу
    # виден. Настоящие подписи («старт», «шаг #3») такую путаницу спрятали бы —
    # половина имён получила бы одинаковый текст.
    tail = {
        'left': '''
        const sources = {};
        Object.keys(vars).forEach(name => sources[name] = {label: 'источник:' + name});
        const out = renderVariablesList(vars, sources).kids;
        process.stdout.write(JSON.stringify(
            SHOW_BADGES ? out.map(one => [one.name, one.badge]) : out.map(one => one.name)));
        ''',
        'right': '''
        const sources = {};
        Object.keys(vars).forEach(name => sources[name] = {label: 'источник:' + name});
        const declared = Object.keys(vars).map(name => ({name, default: null}));
        const out = renderWorkflowVariablesList(declared, vars, sources).kids;
        process.stdout.write(JSON.stringify(out.map(one => one.name)));
        ''',
        'cache': '''
        const sources = {};
        Object.keys(vars).forEach(name => sources[name] = {label: 'источник:' + name});
        const declared = Object.keys(vars).map(name => ({name, default: null}));
        const was = declared.map(one => one.name);
        renderWorkflowVariablesList(declared, vars, sources);
        process.stdout.write(JSON.stringify([was, declared.map(one => one.name)]));
        ''',
    }[what]

    script = (stub + _slice()
              + f'const vars = {json.dumps(LIVE, ensure_ascii=False)};'
              + tail.replace('SHOW_BADGES', 'true' if badges else 'false'))

    done = subprocess.run(['node', '--input-type=module', '-e', script],
                          capture_output=True, text=True)

    assert done.returncode == 0, f'node: {done.stderr}'

    got = json.loads(done.stdout)

    return [tuple(one) for one in got] if badges else got



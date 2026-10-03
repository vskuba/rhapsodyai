"""Число оборотов подпотока из переменной: режим в редакторе и его разбор.

## ⚠⚠⚠ ЗАЧЕМ: редактор молча затирал настройку, которую не умел показать

`repeat.count` у шага `workflow_invoke` бывает двух видов: число (`6`) человек
ставит руками, а метку переменной (`%invite_count%`) — тот, кому число известно
только в работе. Инвайты просят у агента столько реплик, сколько девушек сейчас
в сети, и обороты цикла задаёт именно метка.

Поле же было `type="number"`: метка в нём не показывалась вовсе, а сборка писала
`parseInt(...) || 1` — то есть **затирала метку единицей**. Сборка висит на
`change` любого поля блока, так что хватало открыть шаг и тронуть что угодно.

Цена, измеренная на проде 03.10.2026: цикл инвайтов стал давать один шаблон
вместо одиннадцати, все двенадцать анкет писали одно и то же, и нашлось это
глазами по журналу панели — ошибки не было ни одной.

⚠ Та же правка вернула вторую потерю: вход `invite_done`, которым цикл передаёт
ребёнку уже написанное, исчезал из `inputs_map` тем же нажатием — его не рисовали,
потому что у подпотока он объявлен `workflow`, а не `input` (`subflowInputsWithSaved`).

## Что проверяется

**Разбор метки** (`REPEAT_COUNT_VAR_RE`): что считается меткой, а что нет. Это
решает, в каком режиме откроется шаг и сохранится ли настройка.

⚠ Рисование (вкладки, подписи, видимость строк) проверяется глазами: у него нет
утверждения, которое не ломалось бы от смены отступа. Тот же довод, что в
`test_workflow_subflow_maps.py`.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

WIDGETS = (Path(__file__).resolve().parent.parent
           / 'data/uvicorn/public/js/workflow/step-widgets.js')

MAPS = (Path(__file__).resolve().parent.parent
        / 'data/uvicorn/public/js/workflow/subflow-maps.js')

# Заглушка окружения: модуль на импорте тянет браузерных соседей.
SHIM = '''
globalThis.document = {
    createElement: () => ({style: {}, classList: {toggle() {}}, append() {},
                           appendChild() {}, setAttribute() {},
                           querySelectorAll: () => [], remove() {}}),
    getElementById: () => null,
    body: {appendChild() {}},
    querySelectorAll: () => [],
};
globalThis.window = {};
'''


def _node(script: str):
    """Прогнать кусок модуля страницы через node и вернуть разобранный вывод."""
    if not shutil.which('node'):
        pytest.skip('node недоступен — разбор проверить нечем')

    done = subprocess.run(['node', '--input-type=module', '-e', SHIM + script],
                          capture_output=True, text=True)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)


def _parse(saved):
    """Что редактор увидит в сохранённом `repeat.count`: имя переменной или пусто.

    ⚠ Зовётся **настоящее** правило страницы, а не его копия здесь: копия
    разошлась бы с оригиналом на первой правке, и тест стерёг бы себя.
    """
    return _node(
        f"const {{REPEAT_COUNT_VAR_RE}} = await import('{WIDGETS}');\n"
        f'const saved = {json.dumps(saved)};\n'
        'const hit = REPEAT_COUNT_VAR_RE.exec('
        "    typeof saved === 'string' ? saved.trim() : '');\n"
        "process.stdout.write(JSON.stringify(hit ? hit[1] : ''));")


class TestTheMarkIsRecognised:
    """Метка переменной: по ней шаг открывается в своём режиме."""

    def test_a_plain_mark_gives_the_name(self):
        assert _parse('%invite_count%') == 'invite_count'

    def test_spaces_around_do_not_hide_it(self):
        """⚠ Пробелы по краям метку не отменяют: человек правит JSON руками."""
        assert _parse('  %invite_count%  ') == 'invite_count'

    def test_a_number_is_not_a_mark(self):
        assert _parse(6) == ''
        assert _parse('6') == ''

    def test_a_mark_with_text_around_is_not_a_mark(self):
        """⚠⚠ И это главное в правиле. Движок возвращает исходный тип значения
        только для строки, **равной одной метке**; `%invite_count% раз` осталось
        бы строкой, и прогон упал бы на `int()` — то есть цикл не сломался бы
        тихо, а свалил бы весь заход."""
        assert _parse('%invite_count% раз') == ''
        assert _parse('до %invite_count%') == ''

    def test_two_marks_are_not_a_mark(self):
        assert _parse('%a%%b%') == ''

    def test_empty_and_nothing_are_not_marks(self):
        assert _parse('') == ''
        assert _parse(None) == ''

    def test_a_name_must_look_like_a_variable(self):
        """Имя переменной — буквы, цифры и подчёркивание, не с цифры."""
        assert _parse('%invite_count_2%') == 'invite_count_2'
        assert _parse('%2count%') == ''
        assert _parse('%с-дефисом%') == ''


class TestTheCapIsThere:
    """⚠⚠ Предохранитель режима: число приходит снаружи."""

    def test_the_default_cap_is_declared(self):
        got = _node(f"const m = await import('{WIDGETS}');\n"
                    'process.stdout.write(JSON.stringify(m.REPEAT_COUNT_VAR_CAP));')

        assert got == 50, \
            'умолчание предохранителя разошлось с тем, на котором живёт прод'

    def test_the_widget_writes_the_cap_with_the_mark(self):
        """Опечатка вызывающего («800 девушек») обернулась бы восемьюстами
        прогонами подпотока, каждый ценой вызовов LLM."""
        # ⚠ Привязка к **сборке**, а не к первому упоминанию режима: имя режима
        # встречается и в показе строк, и первый же `index` уводил туда.
        code = WIDGETS.read_text(encoding='utf-8')
        at = code.index("=== 'count_var' && countVarSelect.value")
        tail = code[at:at + 500]

        assert 'max_iterations' in tail, 'режим из переменной остался без потолка'

    def test_an_unchosen_variable_saves_no_repeat(self):
        """⚠ Режим выбран, переменная нет — повтор не пишется вовсе.

        `count: ''` оставил бы в метаданных повтор, которого нет (движок счёл бы
        его одним оборотом), а пустую метку — уронил бы прогон на `int()`.
        """
        code = WIDGETS.read_text(encoding='utf-8')

        assert "=== 'count_var' && countVarSelect.value" in code, \
            'повтор пишется и без выбранной переменной'


class TestTheSavedInputSurvives:
    """⚠⚠ Вторая половина той же поломки: настроенный вход исчезал."""

    def test_a_saved_input_is_kept_even_if_not_declared(self):
        got = _node(
            f"const mod = await import('{MAPS}');\n"
            'process.stdout.write(JSON.stringify(mod.subflowInputsWithSaved('
            "  [{name: 'invite_avoid'}],"
            "  {inputs_map: {invite_done: 'invite_done',"
            "                invite_avoid: 'invite_avoid'}})"
            '  .map(one => one.name)));')

        assert got == ['invite_avoid', 'invite_done'], \
            'настроенный вход снова выпадает из списка — пара потеряется'

    def test_declared_inputs_are_not_doubled(self):
        got = _node(
            f"const mod = await import('{MAPS}');\n"
            'process.stdout.write(JSON.stringify(mod.subflowInputsWithSaved('
            "  [{name: 'invite_avoid'}], {inputs_map: {invite_avoid: 'x'}})"
            '  .map(one => one.name)));')

        assert got == ['invite_avoid']

    def test_no_saved_map_changes_nothing(self):
        got = _node(
            f"const mod = await import('{MAPS}');\n"
            'process.stdout.write(JSON.stringify(mod.subflowInputsWithSaved('
            "  [{name: 'a'}], null).map(one => one.name)));")

        assert got == ['a']

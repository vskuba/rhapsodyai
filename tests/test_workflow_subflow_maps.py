"""Карты переменных подпотока: что собирается из полей блока и уходит в метаданные.

## ⚠⚠⚠ ЗАЧЕМ: `outputs_map` правилась только через базу

Виджет шага-подпотока показывал под подписью «Выходящие параметры (Output
Mapping)» ровно одно автоимя — `%{подпоток}_{шаг}_result_str%`. Настоящей карты
выходов в UI не было **вовсе**: ни посмотреть, ни поправить. Хуже того, сборка
метаданных переписывала её саму в себя:

    outputs_map: (currentValue && currentValue.outputs_map) || {}

То есть правка была невозможна, а неправка — вечной.

Карту несут девять шагов установки, и у `dating_talk` через неё уходит правка
судьи (`photo_fixed` → `girl_response_fixed`). Потеряйся пара — человеку уедет
черновик вместо исправленного текста, и по ответу это не видно
(`tests_llm/dating_talk/test_outputs.py` стережёт тот конец).

## ⚠⚠ Проверяется сбор, а не рисование

Предмет здесь — `subflowMapsCollect`: что из полей попадёт в метаданные шага.
Рисование (вкладки, кнопки, подсказки) проверяется глазами — у него нет
утверждения, которое не ломалось бы от смены отступа.

⚠ DOM подменён объектами с тремя методами, а не настоящим: сбору нужны только
`querySelectorAll`, `querySelector` и `value`. Живой Chromium ради этого
поднимать незачем — он в `tests_browser/` и ходит только руками.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

# ⚠ Путь абсолютный и считается от файла теста: `import()` в ESM относительный
# путь мерит от **запускающего** скрипта, а он у node свой. Соседние node-тесты
# обходятся относительным, потому что импортируют не динамически.
MODULE = (Path(__file__).resolve().parent.parent
          / 'data/uvicorn/public/js/workflow/subflow-maps.js')

# Заглушка окружения: модуль на импорте тянет браузерных соседей (`variables.js`,
# `state.js`), и без `document` падает ещё до вызова.
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

# Фальшивые строки блока: класс строки и значения двух её полей.
ROWS = '''
const row = (cls, left, right) => ({
    cls,
    querySelector: (sel) => {
        const map = cls === 'subflow-input-row'
            ? {'.map-arg-select': left, '.map-var-select': right}
            : {'.map-child-select': left, '.map-parent-select': right};
        const found = map[sel];

        return found === undefined ? null : {value: found};
    },
});
const host = (rows) => ({
    querySelectorAll: (sel) => rows.filter(one => '.' + one.cls === sel),
});
'''


class TestBothMapsComeOutApart:
    """⚠⚠ Две карты из одного блока, и путать их нельзя.

    `inputs_map` — что уходит внутрь, `outputs_map` — что возвращается наружу.
    Смешай их, и подпоток получил бы на вход имя родительской переменной, а
    наружу не отдал бы ничего.
    """

    def test_input_and_output_rows_fill_their_own_map(self):
        got = _collect([
            ('subflow-input-row', 'girl_id', 'girl_id'),
            ('subflow-output-row', 'photo_fixed', 'girl_response_fixed'),
        ])

        assert got == {'inputs_map': {'girl_id': 'girl_id'},
                       'outputs_map': {'photo_fixed': 'girl_response_fixed'}}, got

    def test_the_real_branch_map_survives_a_round_trip(self):
        """⚠ Живая карта ветки «письма и фото» — та, что переименовывает."""
        got = _collect([
            ('subflow-output-row', 'photo_deal', 'photo_deal'),
            ('subflow-output-row', 'photo_response', 'girl_response'),
            ('subflow-output-row', 'photo_fixed', 'girl_response_fixed'),
        ])

        assert got['outputs_map'] == {'photo_deal': 'photo_deal',
                                      'photo_response': 'girl_response',
                                      'photo_fixed': 'girl_response_fixed'}, got


class TestTheHalfFilledRowIsDropped:
    """⚠⚠⚠ Недозаполненная строка в карту НЕ попадает.

    Человек нажал «+ Переменная наружу» и отвлёкся — строка осталась пустой. Уйди
    она в метаданные, движок написал бы в лог «переменная не найдена в scope» и
    на этом успокоился: `logger_info` в журнал ошибок не попадает, то есть беда
    была бы молчаливой.
    """

    @pytest.mark.parametrize('left, right', [
        ('', 'girl_response'),
        ('photo_fixed', ''),
        ('', ''),
    ])
    def test_an_empty_side_keeps_the_pair_out(self, left, right):
        got = _collect([('subflow-output-row', left, right)])

        assert got['outputs_map'] == {}, f'полупустая пара уехала в карту: {got}'

    def test_an_unset_input_keeps_the_pair_out(self):
        """То же у входящих: имя есть всегда, а переменной может не быть."""
        got = _collect([('subflow-input-row', 'topic', '')])

        assert got['inputs_map'] == {}, f'незаполненный вход уехал в карту: {got}'


class TestNothingSetMeansEmptyMaps:
    """⚠ Ни одной строки — две пустые карты, а не отсутствие ключей.

    Движок читает `inputs_map`/`outputs_map` без проверки на наличие, и шаг без
    карт — законный случай: подпоток зовут ради побочного действия.
    """

    def test_no_rows_give_two_empty_maps(self):
        assert _collect([]) == {'inputs_map': {}, 'outputs_map': {}}


class TestASavedInputSurvivesWithoutDeclaration:
    """⚠⚠⚠ Настроенный вход не исчезает оттого, что его не объявили входящим.

    Строки рисуются по объявлениям ребёнка (`type = 'input'`), а сборка идёт по
    нарисованным строкам. Значит пара, чья переменная у ребёнка объявлена иначе
    (`workflow`), пропадала из `inputs_map` от одного касания любого поля шага —
    без ошибки и без следа в журнале.

    ## ⚠⚠ Цена измерена: так сломался цикл инвайтов

    Миграция `20260918260000` задавала его прямо: «`invite_done` стоит и во
    входах, и в выходах — в этом весь цикл». Выход остался, вход исчез. Каждый
    оборот начинал с чистого листа, и вторая реплика сочинялась, не зная
    первой, — ровно то, против чего цикл и заведён.

    Опознали по улике: карта входов стала **в точности равна** списку
    объявленных входов ребёнка. Случайно так не бывает — миграции клали туда и
    `invite_done` (тип `workflow`), и переменную другого workflow.
    """

    def test_a_declared_input_is_listed_plainly(self):
        rows = _inputs([{'name': 'invite_avoid'}],
                       {'invite_avoid': 'invite_avoid'})

        assert rows == [{'name': 'invite_avoid'}], \
            f'объявленный вход изменился при сборке списка: {rows}'

    def test_a_saved_but_undeclared_input_is_kept(self):
        """⚠ Главное: пара остаётся строкой, значит переживёт сохранение."""
        rows = _inputs([{'name': 'invite_avoid'}],
                       {'invite_avoid': 'invite_avoid',
                        'invite_done': 'invite_done'})
        names = [one['name'] for one in rows]

        assert names == ['invite_avoid', 'invite_done'], \
            f'спасённая пара не попала в список строк: {rows}'

    def test_the_kept_one_is_marked(self):
        """⚠⚠ Помечена отдельным полем, а не наличием описания.

        Описание ручка отдаёт и у обычных переменных — пометка по нему
        покрасила бы весь список.
        """
        rows = _inputs([{'name': 'invite_avoid', 'description': 'чего избегать'}],
                       {'invite_done': 'invite_done'})
        marked = {one['name']: bool(one.get('undeclared')) for one in rows}

        assert marked == {'invite_avoid': False, 'invite_done': True}, \
            f'пометка необъявленного входа разошлась: {marked}'

    def test_nothing_saved_changes_nothing(self):
        """⚠ Пустая карта ничего не добавляет: список — ровно объявления."""
        rows = _inputs([{'name': 'invite_avoid'}], {})

        assert rows == [{'name': 'invite_avoid'}], f'список вырос на пустом: {rows}'


def _inputs(declared: list, saved_map: dict) -> list:
    """Строки вкладки «Входящие» живой функцией страницы.

    Args:
        declared: что ребёнок объявил входящим (как отдаёт ручка переменных).
        saved_map: `inputs_map`, уже сохранённый на шаге.
    """
    if not shutil.which('node'):
        pytest.skip('node недоступен — сборку списка проверить нечем')

    script = (SHIM
              + f"const {{subflowInputsWithSaved}} = await import('{MODULE}');\n"
              + f'process.stdout.write(JSON.stringify(subflowInputsWithSaved('
                f'{json.dumps(declared)}, '
                f'{json.dumps({"inputs_map": saved_map})})));')
    done = subprocess.run(['node', '--input-type=module', '-e', script],
                          capture_output=True, text=True)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)


def _collect(rows: list) -> dict:
    """Прогнать живой сбор через node и вернуть, что он собрал.

    Args:
        rows: тройки `(класс строки, левое поле, правое поле)`.

    ⚠ Зовётся **настоящая** функция страницы, а не её копия здесь: копия
    разошлась бы с оригиналом на первой правке, и тест стерёг бы себя.
    """
    if not shutil.which('node'):
        pytest.skip('node недоступен — сбор карт проверить нечем')

    listed = ', '.join(f'row({one!r}, {left!r}, {right!r})'
                       for one, left, right in rows).replace("'", '"')
    script = (SHIM
              + f"const {{subflowMapsCollect}} = await import('{MODULE}');\n"
              + ROWS
              + f'process.stdout.write(JSON.stringify('
                f'subflowMapsCollect(host([{listed}]))));')
    done = subprocess.run(['node', '--input-type=module', '-e', script],
                          capture_output=True, text=True)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)

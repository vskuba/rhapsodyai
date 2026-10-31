"""Описание жребия из переменной потока: редактор обязан его показывать.

## ⚠⚠⚠ ЗАЧЕМ: форма жребия была пуста у ВСЕХ шагов во ВСЕХ workflow

Описание жребия (`spec`) исторически клалось **литералом** — `_const_{…}` прямо
в `inputs_map`. Литерал с тех пор запрещён: движок отвечает на него отказом, а
значения переехали в переменные потока (`spec: "dice_photo_spec"`).

Читать после переезда виджет не научили, и `_specIn` отдавал пустоту всегда:
она проверяла `startsWith('_const_')` и на имени переменной возвращала `''`.
Человек открывал шаг — и видел форму без единого варианта при живом, работающем
описании.

⚠⚠ Хуже пустоты было то, что **сохранение такой формы затирало настройку**:
сборка писала в `inputs_map` новый литерал из пустых полей. Открыл посмотреть,
нажал «Сохранить» — и жребий потерян. Ровно та же история, что с
`repeat.count` (`test_workflow_repeat_count_var.py`): редактор затирал то,
чего не умел показать.

Цена, измеренная на проде 31.10.2026: шесть шагов жребия в четырёх workflow,
468 вариантов суммарно — все невидимы.

## Что проверяется

**Чтение описания** (`_specIn`): берётся ли оно из переменной, понимается ли
ещё литерал старых баз, и что происходит с именем, которого нет.

⚠ Рисование формы проверено глазами и прогоном по живым данным прода: у него
нет утверждения, которое не ломалось бы от смены отступа.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from js_.js_static import js_static_run

JS_ROOTS = [os.path.join(os.getcwd(), 'data', 'uvicorn', 'public'),
            os.path.join(os.getcwd(), 'dashboard')]

pytestmark = pytest.mark.core

WIDGET = (Path(__file__).resolve().parent.parent
          / 'data/uvicorn/public/js/workflow/dice-widget.js')

# ⚠ Берём из модуля **две функции целиком**, а не импортируем его: на импорте он
# тянет браузерных соседей, а чинится здесь только разбор. Тот же приём, что у
# соседнего теста, и по той же причине.
CUT = r"""
import {readFileSync} from 'node:fs';
const src = readFileSync(%s, 'utf8')
    .replace(/^import.*$/gm, '')
    .match(/function _specIn[\s\S]*?\n}\n[\s\S]*?function _specByName[\s\S]*?\n}/)[0];
globalThis.window = {allCurrentVariables: %s};
const mod = new Function('DICE_ARG', 'DICE_CONST',
    src + '; return {_specIn};')('spec', '_const_');
console.log(JSON.stringify(mod._specIn({inputs_map: %s})));
"""


def _spec(inputs: dict, variables: list):
    """Что редактор увидит в этом шаге при таких переменных потока."""
    if not shutil.which('node'):
        pytest.skip('node недоступен — разбор проверить нечем')

    script = CUT % (json.dumps(str(WIDGET)),
                    json.dumps(variables, ensure_ascii=False),
                    json.dumps(inputs, ensure_ascii=False))
    done = js_static_run(script, JS_ROOTS)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)


SPEC = {'dice_photo_length': {'a paragraph, 70-110 words': 45,
                              'two or three sentences': 25,
                              'two paragraphs': 30}}


class TestTheSpecComesFromTheVariable:
    """Главное: имя переменной разворачивается в её значение."""

    def test_it_reads_the_variable(self):
        got = _spec({'spec': 'dice_photo_spec'},
                    [{'name': 'dice_photo_spec',
                      'default': json.dumps(SPEC, ensure_ascii=False)}])

        assert got == SPEC, f'описание не прочиталось из переменной: {got}'

    def test_the_old_literal_still_works(self):
        """⚠ Литерал понимаем ради баз, которые ещё не переехали: запрет стоит
        в движке, а база могла остаться со старой записью."""
        got = _spec({'spec': '_const_' + json.dumps(SPEC, ensure_ascii=False)}, [])

        assert got == SPEC, f'литерал старой базы перестал читаться: {got}'

    def test_a_missing_variable_is_empty_not_a_crash(self):
        """⚠ Имени нет в списке — пустая форма, но без падения: список
        приезжает своим запросом, и до его ответа «не нашли» значит «ещё не
        знаем»."""
        assert _spec({'spec': 'нет_такой'}, []) == {}
        assert _spec({'spec': 'нет_такой'},
                     [{'name': 'другая', 'default': '{}'}]) == {}

    def test_the_percent_wrapper_is_stripped(self):
        """⚠ Имя встречается в двух записях — голым и в обёртке `%имя%`:
        обе живут в базах, и редактор обязан понимать обе."""
        got = _spec({'spec': '%dice_photo_spec%'},
                    [{'name': 'dice_photo_spec',
                      'default': json.dumps(SPEC, ensure_ascii=False)}])

        assert got == SPEC, f'обёртка `%…%` не снялась: {got}'

    def test_broken_json_does_not_crash(self):
        """⚠ Значение правят руками, и сломанный JSON — обычное дело. Пустая
        форма честнее падения: по ней видно, что описание не прочиталось."""
        assert _spec({'spec': 'bad'},
                     [{'name': 'bad', 'default': '{не json'}]) == {}

    def test_a_list_is_not_a_spec(self):
        """⚠ Описание — объект «переменная → варианты». Список на его месте
        читался бы как настройка и уехал бы в инструмент отказом."""
        assert _spec({'spec': 'arr'},
                     [{'name': 'arr', 'default': '[1, 2, 3]'}]) == {}


class TestTheSaveKeepsTheVariable:
    """⚠⚠ Сборка обязана писать **туда же, откуда читает**.

    Литерал движок отвергает отказом, и вернуть его при сохранении значило бы
    сломать шаг, который человек всего лишь открыл посмотреть.
    """

    def test_the_variable_name_is_kept(self):
        code = WIDGET.read_text(encoding='utf-8')

        assert 'const varName = wasSpec && !wasSpec.startsWith(DICE_CONST)' in code, (
            'имя переменной не сохраняется — сборка вернёт запрещённый литерал')
        assert 'inputs = {[DICE_ARG]: varName ||' in code, (
            'в `inputs_map` уезжает не имя переменной')

    def test_the_value_goes_to_the_page_row(self):
        """⚠⚠ Строку списка обновляет **та же** функция, что и правка руками
        (`syncHiddenRow`): общая кнопка «Сохранить workflow» читает её поля.
        Свой селектор был бы вторым знанием о разметке списка."""
        code = WIDGET.read_text(encoding='utf-8')

        assert 'syncHiddenRow(found)' in code, (
            'значение переменной не доедет до базы: кнопка сохранения читает '
            'поля строки, а их никто не обновил')

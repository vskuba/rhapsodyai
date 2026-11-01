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


SPEC = {'dice_photo_length': {'a paragraph, 70-110 words': 45,
                              'two or three sentences': 25,
                              'two paragraphs': 30}}


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

    def test_the_value_goes_to_the_save_queue(self):
        """⚠⚠⚠ Значение уходит в очередь (`variableValueStage`), а не в
        скрытую строку списка.

        Сперва здесь стояла `syncHiddenRow` — и проверка на неё же, то есть
        тест сторожил неверное. Строки в скрытом контейнере есть **только у
        входящих** переменных (`renderInputVariables` фильтрует
        `type === 'input'`), а описание жребия лежит в переменной рода
        `workflow`: обновлять было нечего, функция молча уходила ни с чем.

        Видно это не было ничем: форма показывала новое число, кнопка
        отвечала «Изменения успешно сохранены», и только перезагрузка
        возвращала старое. Поймано на проде 01.11.2026 — доля
        `dice_img_attach` в `dating_talk` менялась с 5 на 15 и возвращалась.
        """
        code = WIDGET.read_text(encoding='utf-8')

        assert 'variableValueStage(found, text)' in code, (
            'значение переменной не доедет до базы: правка не поставлена '
            'в очередь на сохранение')
        assert 'syncHiddenRow' not in code.split('## ⚠⚠⚠')[0].split('\n')[0], (
            'виджет снова пишет мимо очереди')

    def test_the_name_wrapper_is_stripped_on_write_too(self):
        """⚠⚠ Запись снимает обёртку `%…%` так же, как чтение.

        Чтение (`_specByName`) её снимало, запись — нет. На шаге, где в
        `inputs_map` записано `%имя%`, форма показывала бы доли, а сохранить
        их было бы нечем: поиск переменной промахивался.
        """
        code = WIDGET.read_text(encoding='utf-8')
        write = code.split('function _specToVariable')[1]

        assert ".replace(/^%/, '').replace(/%$/, '')" in write.split('\n}')[0], (
            'запись ищет переменную по имени с обёрткой — промахнётся там, '
            'где чтение её находит')


class TestTheQueueReachesTheBase:
    """Очередь правок доезжает до базы — и именно тем запросом.

    ⚠ Проверяется поведением, а не наличием строк: тест выше сторожит, что
    виджет **кладёт** в очередь, а этот — что положенное **уносится**. Без
    второго правка жила бы в памяти страницы до перезагрузки, то есть ровно
    так, как в найденной беде.
    """

    CUT_QUEUE = r"""
import {readFileSync} from 'node:fs';
const src = readFileSync(%s, 'utf8');
const stage = src.match(/export function variableValueStage[\s\S]*?\n}/)[0]
    .replace('export ', '');
const save = src.match(/export async function saveStagedVariableValues[\s\S]*?\n}/)[0]
    .replace('export ', '');

const state = {varValuePending: {}, varValuePendingFor: null};
const sent = [];
const putData = async (url, body) => { sent.push({url, body}); };
const editorWorkflowId = () => 5;
const syncHiddenRow = () => {};

const mod = new Function('state', 'putData', 'editorWorkflowId', 'syncHiddenRow',
    stage + '; ' + save + '; return {variableValueStage, saveStagedVariableValues};'
)(state, putData, editorWorkflowId, syncHiddenRow);

const variable = {id: 2818, name: 'dice_talk_spec', type: 'workflow', default: 'старое'};
mod.variableValueStage(variable, '{"dice_img_attach": {"0": "rest", "1": 15}}');

await mod.saveStagedVariableValues(5);

console.log(JSON.stringify({sent, left: state.varValuePending,
                            onVariable: variable.default}));
"""

    def _run(self):
        if not shutil.which('node'):
            pytest.skip('node недоступен — поведение проверить нечем')

        variables_js = WIDGET.parent / 'variables.js'
        done = js_static_run(self.CUT_QUEUE % json.dumps(str(variables_js)), JS_ROOTS)

        assert done.returncode == 0, f'node: {done.stderr}'

        return json.loads(done.stdout)

    def test_the_queue_is_put_to_the_api(self):
        got = self._run()

        assert len(got['sent']) == 1, f'запрос не ушёл либо ушёл не один: {got["sent"]}'
        assert got['sent'][0]['url'] == '/workflow/5/variable/2818', (
            f'правка уехала не туда: {got["sent"][0]["url"]}')
        assert json.loads(got['sent'][0]['body']['default'])['dice_img_attach']['1'] == 15, (
            f'уехало не новое значение: {got["sent"][0]["body"]}')

    def test_the_queue_is_emptied_after_the_save(self):
        """⚠ Иначе следующее «Сохранить» переписало бы переменную второй раз
        — тем же значением, но лишним запросом на каждое нажатие."""
        assert self._run()['left'] == {}

    def test_the_page_sees_the_new_value_at_once(self):
        """⚠ Список состояния правится сразу: из него виджет читает при
        следующем открытии формы, не дожидаясь сохранения."""
        assert '15' in self._run()['onVariable']

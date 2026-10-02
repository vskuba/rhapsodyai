"""Правило «Undefined переменные»: шаг читает то, что ему никто не давал.

Правило живёт в одном месте — `variable-group.js`, функция `undefinedVariables`.
Отсчётный список здесь не переписывается: тесты зовут **ту же** функцию, что
зовёт её браузер, и сверяют ответ с руками собранными fixtures. Модуль чистый
(ни DOM, ни сети, ни стейта — см. его шапку), поэтому тесты импортируют его
напрямую, без заглушек и подделок: что проверит node, то и увидит браузер.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.core

GROUP = './data/uvicorn/public/js/workflow/variable-group.js'

# Шаги по одному каждого вида, какие встречаются в workflow. Имена вокруг шагов
# взяты не «для красоты», а по месту в метаданных: довод «правило считает все
# виды» силён ровно настолько, насколько у каждого вида свой способ назвать
# переменную.
#
# ⚠ `metadata` — строка с JSON, как её отдаёт бэкенд: `parseMetadata` обязан
# разобрать её, а не угадать; заглушать его в тесте нечем — модуль чистый.
STEPS = [
    {'id': 524, 'position': 524, 'metadata': json.dumps({
        'tool_invoke': {'tool_name': 'companion_bio',
                        'inputs_map': {'bio': 'companion_bio_524_result_bio',
                                       'sheet': 'list_shift_9_result_sheet',
                                       'const': '_const_hello %girl_name%'},
                        'outputs_map': {'bio': 'girl_bio'}}}, ensure_ascii=False)},
    {'id': 786, 'position': 786, 'metadata': json.dumps(
        {'workflow_invoke': {'workflow_id': 5, 'next': 'talk_answer'}}, ensure_ascii=False)},
    {'id': 787, 'position': 787, 'metadata': json.dumps({
        'llm_to_json_variable': [{'variable': 'talk_topic', 'text': 'о себе %girl_face%'}]},
        ensure_ascii=False)},
    {'id': 788, 'position': 788, 'metadata': json.dumps({
        'agent_invoke': {'agent_id': 3,
                         'prompt': 'о себе %bio_style% про %girl_name% и '
                                   '%dating_invite_one_786_result_str% '
                                   'через %workflow_invoke_786_result_str%'}},
        ensure_ascii=False)},
    {'id': 789, 'position': 789, 'metadata': json.dumps({
        'if_else': [{'if': '[<if talk_history_chat>]', 'then': 787}]}, ensure_ascii=False)},
]

REGISTRY = [{'id': 901, 'name': 'girl_name'}, {'id': 902, 'name': 'talk_history_chat'}]
TOOLS = [{'name': 'companion_bio', 'args': json.dumps({'output': {'keys': {'bio': 'string'}}})}]
WORKFLOWS = [{'id': 5, 'name': 'dating_invite_one'}]


class TestTheRuleCountsEveryKindOfStep:
    """Правило зовёт `stepReadVariables` на шаге любого вида — не только LLM."""

    def test_every_kind_of_step_is_counted(self):
        """⚠⚠ Имя из довода шага любого вида — входящее, инструментное, шага
        подпрогона — находит отклик; шаги остальных видов правило не обходит.

        Проверка двусторонняя: имена, которых нет нигде, — в ответе; имена,
        которые workflow правда знает (реестр, выходы шагов, алиасы движка), —
        молчат. Иначе «своя область переменных» шага-подпрогона молча
        обзавелась бы значками, и хозяин увидел бы крик там, где движок
        раздает доводы сам.
        """
        out = _node(f'''
const steps = {_json(STEPS)};
const registry = {_json(REGISTRY)};
const tools = {_json(TOOLS)};
const workflows = {_json(WORKFLOWS)};
_out = [...undefinedVariables(registry, steps, workflows, tools, []).keys()];
''', 'undefinedVariables')

        assert out == ['bio_style', 'girl_face', 'list_shift_9_result_sheet'], (
            f'правило досчитало или недосчитало неопределённые: {out}')


class TestTheRuleStaysSilentOnWhatExists:
    """Ложь «в workflow нет таких переменных» — тот же баг с другой стороны."""

    def test_variables_the_workflow_has_are_never_flagged(self):
        """⚠⚠ Всё, что workflow правда знает, — без значка.

        Реестр, `outputs_map` и `variable` шага, доводы `inputs_map`, ключи
        ответа модели, алиас `workflow_invoke_<шаг>_result_str` — все они
        обеспечивают имя; домыслить их доводом — кричать на рабочих именах.
        """
        out = _node(f'''
const steps = {_json(STEPS)};
const registry = {_json(REGISTRY)};
const tools = {_json(TOOLS)};
const workflows = {_json(WORKFLOWS)};
const known = undefinedVariables(registry, steps, workflows, tools, []);
_out = [known.has('girl_name'), known.has('talk_history_chat'), known.has('girl_bio'),
        known.has('talk_topic'), known.has('companion_bio_524_result_bio'),
        known.has('dating_invite_one_786_result_str'),
        known.has('workflow_invoke_786_result_str')];
''', 'undefinedVariables')

        assert not any(out), f'правило кричит на обеспеченном имени: {out}'

    def test_the_alias_of_a_subflow_step_is_known(self):
        """Алиас `workflow_invoke_<шаг>_result_str` кладёт движок — в справочниках
        его нет нигде; без знания об этом панель катила бы значок на рабочей
        переменной на каждом шаге-подпрогоне.
        """
        out = _node(f'''
const steps = {_json(_steps((7, {'workflow_invoke': {'workflow_id': 99, 'next': 'x'}}),
                      (8, {'agent_invoke': {'agent_id': 1,
                                            'prompt': 'цитата %workflow_invoke_7_result_str%'}})))};
_out = [...undefinedVariables([], steps, [], [], []).keys()];
''', 'undefinedVariables')

        assert 'workflow_invoke_7_result_str' not in out, \
            f'алиас движка помечен неопределённым: {out}'


class TestTheHiddenNamesAreQuiet:
    """⚠⚠ Указание хозяина: proxy-переменные ноды и переменные агента — нигде."""

    def test_proxy_and_agent_variables_are_never_flagged(self):
        """Имя из прокси-ноды и `agent_variable` — рабочие, но показывать и
        помечать их нельзя; правило считает их обеспеченными и молчит.

        Проверка в обе стороны: без списка скрытых имён правило честит их
        (и тест это видит), с ним — скрытое имя молчит, а прочитанная рядом
        переменная агента остаётся помеченной: скрытие не сносит соседние.
        """
        out = _node(f'''
const steps = {_json(_steps((788, {'agent_invoke': {'agent_id': 3,
                                              'prompt': 'о себе %girl_face% про %proxy_12_bio%, '
                                                      'про %greeting%'}})))};
const without = undefinedVariables([], steps, [], [], []);
const withHidden = undefinedVariables([], steps, [], [], ['proxy_12_bio', 'greeting']);
_out = {{without: [...without.keys()], with: [...withHidden.keys()]}};
''', 'undefinedVariables')

        assert out['without'] == ['girl_face', 'greeting', 'proxy_12_bio'], \
            f'без скрытых имён правило не различает их (проверка слабеет): {out["without"]}'
        assert out['with'] == ['girl_face'], \
            f'скрытое имя помечено, или скрытие снесло соседнее: {out["with"]}'


class TestTheOpaqueToolIsNotADike:
    """⚠⚠ Инструмент, не объявивший ключей, — не дырка, а неизвестность.

    Мерено на живой базе: 37 инструментов из 121 объявляют выход как
    `{"type": "dict"}`, а движок раскладывает ответ в
    `{tool}_{шаг}_result_{ключ}` по тому, что инструмент вправду вернул.
    У `list_shift` объявлен `dict`, шаги читают `list_shift_137_result_greeting`,
    `…_name`, `…_sheet` — и все три движок кладёт. Считать их дырками значило
    кричать на рабочем: из 74 срабатываний по установке 31 было отсюда.
    """

    def test_a_dict_output_silences_the_whole_step(self):
        """Выход `{"type": "dict"}`: спрашивать ключи не с кого — молчим про все."""
        out = _node(f'''
const steps = {_json(_steps((137, {'tool_invoke': {'tool_name': 'list_shift', 'inputs_map': {}}}),
                      (138, {'agent_invoke': {'agent_id': 1,
                                              'prompt': 'дай %list_shift_137_result_greeting% '
                                                        'и %list_shift_137_result_sheet% '
                                                        'и ещё %girl_face%'}})))};
const tools = [{{name: 'list_shift', args: {json.dumps(json.dumps({'output': {'type': 'dict'}}))}}}];
_out = [...undefinedVariables([], steps, [], tools, []).keys()];
''', 'undefinedVariables')

        assert out == ['girl_face'], \
            f'ключи непрозрачного инструмента снова помечены дырками: {out}'

    def test_declared_keys_still_catch_a_stray_name(self):
        """⚠ Поблажка ровно для непрозрачных: у инструмента с `output.keys`
        лишний ключ по-прежнему находят — иначе поправка съела бы всё правило.
        """
        out = _node(f'''
const steps = {_json(_steps((524, {'tool_invoke': {'tool_name': 'companion_bio', 'inputs_map': {}}}),
                      (525, {'agent_invoke': {'agent_id': 1,
                                              'prompt': 'дай %companion_bio_524_result_bio% '
                                                        'и %companion_bio_524_result_nosuch%'}})))};
const tools = {_json(TOOLS)};
_out = [...undefinedVariables([], steps, [], tools, []).keys()];
''', 'undefinedVariables')

        assert out == ['companion_bio_524_result_nosuch'], \
            f'объявленные ключи перестали ловить лишнее имя: {out}'

    def test_a_tool_missing_from_the_reference_is_opaque_too(self):
        """⚠ Инструмента нет в справочнике — он переименован или снят. Доказать
        пустоту нечем, и правило молчит: так ушли `mysql_export_node_to_migration_*`.
        """
        out = _node(f'''
const steps = {_json(_steps((148, {'tool_invoke': {'tool_name': 'mysql_export_node_to_migration',
                                             'inputs_map': {}}}),
                      (149, {'agent_invoke': {'agent_id': 1,
                                              'prompt': 'отчёт %mysql_export_node_to_migration_148'
                                                        '_result_blocked%'}})))};
_out = [...undefinedVariables([], steps, [], [], []).keys()];
''', 'undefinedVariables')

        assert out == [], f'результат неизвестного инструмента помечен дыркой: {out}'


class TestTheDateFormatIsNotAVariable:
    """⚠⚠ `%Y%m%d%H%M%S` в промпте — формат даты, а не три переменные.

    Метка переменной ищется как `%имя%`, и в цепочке `%Y%m%d%` разбор честно
    видит `Y`, потом `d`, потом `M`. Переменных в один символ на установке нет
    ни одной (проверено по `agent_workflow_variable` и `node_variable`), а
    `date +%Y%m%d%H%M%S` в промптах ролей есть.
    """

    def test_single_letter_marks_are_not_counted(self):
        """Однобуквенное имя — не переменная; соседнее настоящее — переменная."""
        out = _node(f'''
const steps = {_json(_steps((1, {'agent_invoke': {'agent_id': 1,
                                            'prompt': 'миграция date +%Y%m%d%H%M%S, '
                                                      'ветка %task_branch%'}})))};
_out = [...undefinedVariables([], steps, [], [], []).keys()];
''', 'undefinedVariables')

        assert out == ['task_branch'], \
            f'формат даты снова разобран на переменные: {out}'


class TestTheConditionTellsWordsFromNames:
    """⚠⚠⚠ В условии справа от оператора кавычки решают: слово или переменная.

    Это правило движка (`_condition_value_resolve`), и здесь оно живёт в третьей
    копии: движок, подсветка, сбор переменных. Разойдись сбор — страница стала
    бы ругаться на каждое сравнение со строкой («переменной `chat` нет»), а
    настоящую опечатку в правом имени не заметила бы вовсе.
    """

    def test_a_quoted_word_is_not_a_variable(self):
        """`kind == 'chat'` — одна переменная, а не две."""
        out = self._names("[<if kind == 'chat'>]да[<endif>]")

        assert out == ['kind'], f'слово в кавычках сочли переменной: {out}'

    def test_a_bare_name_is_a_variable(self):
        """`kind == other` — две: сравнение двух переменных законно."""
        out = self._names('[<if kind == other>]да[<endif>]')

        assert out == ['kind', 'other'], f'правое имя не собрано: {out}'

    def test_a_number_is_not_a_variable(self):
        """⚠ `count > 5` — число под шаблон имени не попадает вовсе."""
        out = self._names("[<if count > 5 and kind == 'chat'>]да[<endif>]")

        assert out == ['count', 'kind'], f'число сочли переменной: {out}'

    def test_a_connective_in_quotes_is_still_a_word(self):
        """⚠⚠ `'and'` в кавычках — значение, а не связка и не переменная.

        Ловится тем, что строка в шаблоне стоит **первой** альтернативой: поймай
        её шаблон имени, и `and` ушло бы в переменные.
        """
        out = self._names("[<if kind == 'and'>]да[<endif>]")

        assert out == ['kind'], f'связка в кавычках сочтена переменной: {out}'

    @staticmethod
    def _names(prompt: str) -> list:
        """Неопределённые имена, которые правило нашло в промпте шага."""
        return _node(f'''
const steps = {_json(_steps((1, {'agent_invoke': {'agent_id': 1,
                                                  'prompt': prompt}})))};
_out = [...undefinedVariables([], steps, [], [], []).keys()];
''', 'undefinedVariables')


def _steps(*pairs) -> list:
    """Шаги редакторской формы `{id, position, metadata}` из пар `(id, метаданные)`.

    Той же формы, что `STEPS` выше, — но собранные по месту, когда виду шага
    хватает одного теста и заводить общий набор незачем.
    """
    return [{'id': sid, 'position': sid, 'metadata': json.dumps(meta, ensure_ascii=False)}
            for sid, meta in pairs]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _node(body: str, imports: str) -> object:
    """Гоняет код на живом правиле и возвращает то, что он выписал."""
    if not shutil.which('node'):
        pytest.skip('node недоступен — правило проверить нечем')

    script = (f"let _out;\nimport {{{imports}}} from '{GROUP}';\n"
              + body
              + '\nprocess.stdout.write(JSON.stringify(_out));')
    done = subprocess.run(['node', '--input-type=module', '-e', script],
                          capture_output=True, text=True)

    assert done.returncode == 0, f'node: {done.stderr}'

    return json.loads(done.stdout)

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


def _steps(*pairs) -> str:
    """JS-литерал шагов редакторской формы: `{id, position, metadata}`.

    `metadata` — строка с JSON, как её отдаёт бэкенд: `parseMetadata` обязан
    разобрать, а не угадать; заглушать его в тесте нечем — он чистый.
    """
    rows = ', '.join(
        f'{{id: {sid}, position: {sid}, metadata: {json.dumps(json.dumps(meta, ensure_ascii=False))}}}'
        for sid, meta in pairs)

    return f'[{rows}]'


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


# Шаги по одному каждого вида, какие встречаются в workflow. Имена вокруг шагов
# взяты не «для красоты», а по месту в метаданных: довод «правило считает все
# виды» силён ровно ровново, пока у каждого вида свой способ назвать переменную.
STEPS = _steps(
    (524, {'tool_invoke': {'tool_name': 'companion_bio',
                           'inputs_map': {'bio': 'companion_bio_524_result_bio',
                                          'sheet': 'list_shift_9_result_sheet',
                                          'const': '_const_hello %girl_name%'},
                           'outputs_map': {'bio': 'girl_bio'}}}),
    (786, {'workflow_invoke': {'workflow_id': 5, 'next': 'talk_answer'}}),
    (787, {'llm_to_json_variable': [{'variable': 'talk_topic', 'text': 'о себе %girl_face%'}]}),
    (788, {'agent_invoke': {'agent_id': 3,
                            'prompt': 'о себе %bio_style% про %girl_name% и '
                                     '%dating_invite_one_786_result_str% '
                                     'через %workflow_invoke_786_result_str%'}}),
    (789, {'if_else': [{'if': '[<if talk_history_chat>]', 'then': 787}]}),
)

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
const steps = {STEPS};
const registry = {json.dumps(REGISTRY)};
const tools = {json.dumps(TOOLS)};
const workflows = {json.dumps(WORKFLOWS)};
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
const steps = {STEPS};
const registry = {json.dumps(REGISTRY)};
const tools = {json.dumps(TOOLS)};
const workflows = {json.dumps(WORKFLOWS)};
const known = undefinedVariables(registry, steps, workflows, tools, []);
_out = [known.has('girl_name'), known.has('talk_history_chat'), known.has('girl_bio'),
        known.has('talk_topic'), known.has('companion_bio_524_result_bio'),
        known.has('dating_invite_one_786_result_str'),
        known.has('workflow_invoke_786_result_str')];
''', 'undefinedVariables')

        assert not any(out), f'правило кричит на обеспеченном имени: {out}'

    def test_the_alias_of_a_subflow_step_is_known(self):
        """Алиас `workflow_invoke_<шаг>_result_str` кладёт движок — в справочниках
        его нет нигде; без знания об этом панель катала бы значок на рабочей
        переменной на каждом шаге-подпрогоне.
        """
        out = _node(f'''
const steps = {_steps((7, {'workflow_invoke': {'workflow_id': 99, 'next': 'x'}}),
                      (8, {'agent_invoke': {'agent_id': 1,
                                            'prompt': 'цитата %workflow_invoke_7_result_str%'}}))};
_out = [...undefinedVariables([], steps, [], [], []).keys()];
''', 'undefinedVariables')

        assert 'workflow_invoke_7_result_str' not in out, \
            f'алиас движка помечен неопределённым: {out}'


class TestTheHiddenNamesAreQuiet:
    """⚠⚠ Указание хозяина: proxy-переменные ноды и переменные агента — нигде."""

    def test_proxy_and_agent_variables_are_never_flagged(self):
        """Имя из прокси-ноды и `agent_variable` — рабочие, но показывать и
        помечать их нельзя; правило считает их обеспеченными и молчит.

        Проверка в обе стороны: без списка скрытых имён правило честит на них
        (и тест это видит), с ним — скрытое имя молчит, а прочитанная рядом
        переменная агента остаётся помеченной: скрытие не сносит соседние.
        """
        out = _node(f'''
const steps = {_steps((788, {'agent_invoke': {'agent_id': 3,
                                              'prompt': 'о себе %girl_face% про %proxy_12_bio%, '
                                                      'про %greeting%'}}))};
const without = undefinedVariables([], steps, [], [], []);
const withHidden = undefinedVariables([], steps, [], [], ['proxy_12_bio', 'greeting']);
_out = {{without: [...without.keys()], with: [...withHidden.keys()]}};
''', 'undefinedVariables')

        assert out['without'] == ['girl_face', 'greeting', 'proxy_12_bio'], \
            f'без скрытых имён правило не различает их (проверка слабеет): {out["without"]}'
        assert out['with'] == ['girl_face'], \
            f'скрытое имя помечено, или скрытие снесло соседнее: {out["with"]}'

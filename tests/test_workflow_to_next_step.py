"""Переход «на следующий по номеру» — выбор шага, а не закон движка.

## ⚠⚠ Зачем понадобилось

Движок идёт по позициям: шаг, чей переход не сработал, утекает в следующий. Для
прямой цепочки это верно, а для развилки — нет: там следующий по номеру шаг это
**чужая ветка**.

Поймано живьём в `dating_talk`. Ветки сочинения стоят подряд, и «Письмо первым»
при несработавшем переходе уходило в «Ответ на письмо» — то есть письмо
писалось дважды. Держалось это на условии `girl_response exists`, истинном лишь
по случайности устройства: переменная объявлена у workflow, и движок кладёт её в
область видимости на старте.

Редактор при этом рисовал сплошную стрелку 13 → 14 **всем подряд**, не
спрашивая про переходы, — то есть показывал путь, которого может не быть.

## Что стережётся здесь

| | |
|---|---|
| ключа нет | идём дальше, как шли все шаги до появления галочки |
| галочка снята | отвечаем `no more step available` |
| снята, но переход сработал | переход сильнее: он и есть «куда идти» |
| снята у шага-ответа | ему галочка не нужна, он и так заканчивает прогон |

⚠ Тупик отвечает **словами**, а не пустотой: пустой ответ вызывающий читает как
«агент решил промолчать», и настроенный тупик выглядел бы обычной работой.
"""

import ast
import inspect
import pathlib
import textwrap

import pytest

from src.ai.framework.agent import ai_framework_manager as mod
from src.ai.framework.agent.ai_framework_manager import (
    AI_FRAMEWORK_NO_MORE_STEP, AI_FRAMEWORK_STEP_RETURNS,
    AI_FRAMEWORK_TO_NEXT_STEP, _to_next_step)

pytestmark = pytest.mark.core

WORKFLOW_JS = pathlib.Path('data/uvicorn/public/js/workflow')


class TestTheFlagIsRead:
    """⚠ Значение галочки: умолчание и приведение чужих написаний."""

    def test_no_key_means_allowed(self):
        """⚠⚠ Главное: ключа нет — переход разрешён.

        Ключа нет ни у одного прежнего шага, и любое другое умолчание оборвало
        бы все workflow разом.
        """
        assert _to_next_step({}) is True

    @pytest.mark.parametrize('raw', [True, 'true', '1', 'yes', 1])
    def test_truthy_allows(self, raw):
        assert _to_next_step({AI_FRAMEWORK_TO_NEXT_STEP: raw}) is True

    @pytest.mark.parametrize('raw', [False, 'false', '0', 'no', 'off', ''])
    def test_falsy_forbids(self, raw):
        """⚠ Строки приводим сами: метаданные приезжают из seed и правок руками,
        где `false` мог стать строкой — а `bool('false')` истина, то есть
        разрешение там, где поставили запрет."""
        assert _to_next_step({AI_FRAMEWORK_TO_NEXT_STEP: raw}) is False

    def test_a_broken_metadata_does_not_crash(self):
        """⚠ `None` вместо словаря — не повод ронять прогон."""
        assert _to_next_step(None) is True


class TestTheEngineObeys:
    """⚠⚠ Как решает сам движок — по его же выражению, а не по пересказу."""

    def test_the_decision_lives_in_the_loop(self):
        """Условие стоит там, где шаг уходит дальше, и смотрит на три вещи."""
        code = _source(mod.AiFrameworkAgentManager._workflow_steps_run)

        assert 'index_fallen' in code, \
            'движок перестал отличать «остался на месте» от «прыгнул»'
        assert '_to_next_step(step_meta)' in code, 'галочка не спрашивается'
        assert 'AI_FRAMEWORK_STEP_RETURNS' in code, \
            'шаги-ответы перестали быть исключением'
        assert 'AI_FRAMEWORK_NO_MORE_STEP' in code, 'тупик отвечает не словами'

    @pytest.mark.parametrize('meta,step_type,fired,want', [
        ({}, 'llm_to_json', False, 'next'),
        ({AI_FRAMEWORK_TO_NEXT_STEP: True}, 'llm_to_json', False, 'next'),
        ({AI_FRAMEWORK_TO_NEXT_STEP: False}, 'llm_to_json', False, 'stop'),
        ({AI_FRAMEWORK_TO_NEXT_STEP: False}, 'tool_invoke', False, 'stop'),
        ({AI_FRAMEWORK_TO_NEXT_STEP: False}, 'llm_to_json', True, 'jump'),
        ({AI_FRAMEWORK_TO_NEXT_STEP: False}, 'return_response_text', False, 'next'),
        ({AI_FRAMEWORK_TO_NEXT_STEP: False}, 'return_response_llm', False, 'next'),
    ])
    def test_every_case(self, meta, step_type, fired, want):
        """⚠ Развилка целиком, включая то, ради чего всё затевалось: снятая
        галочка обрывает поток, а сработавший переход сильнее её."""
        assert _decide(meta, step_type, fired) == want


class TestTheEditorAndGraphAgree:
    """⚠⚠ Три места читают одну галочку, и имя ключа у них общее.

    Разойдись оно — страница показывала бы одно, граф рисовал другое, а поток
    шёл бы третьим путём. Проверить это глазами нельзя: расхождение тихое.
    """

    @pytest.mark.parametrize('name', ['steps.js', 'graph.js'])
    def test_the_key_matches_the_engine(self, name):
        code = (WORKFLOW_JS / name).read_text(encoding='utf-8')

        assert f"const TO_NEXT_STEP = '{AI_FRAMEWORK_TO_NEXT_STEP}'" in code, \
            f'{name} зовёт галочку не тем именем, что движок'

    def test_the_graph_hides_the_arrow(self):
        """⚠ Стрелка «следующий по номеру» рисуется только при включённой."""
        code = (WORKFLOW_JS / 'graph.js').read_text(encoding='utf-8')

        assert 'next && meta[TO_NEXT_STEP] !== false' in code, \
            'граф снова рисует путь, которого может не быть'

    def test_the_editor_saves_it(self):
        """⚠ И сохраняет вместе с условиями: снятая, но незаписанная, она
        обещала бы тупик, которого в базе нет."""
        code = (WORKFLOW_JS / 'steps.js').read_text(encoding='utf-8')

        assert 'toNextStepShow(metadata)' in code, 'галочка не показывается'
        assert code.count('[TO_NEXT_STEP] = toNextStepValue()') >= 2, \
            'галочка сохраняется не на всех путях правки шага'

    def test_the_default_is_on_everywhere(self):
        """⚠⚠ Умолчание «включено» одинаково у всех троих.

        У движка это `.get(ключ, True)`, у страницы и графа — сравнение с
        `false`, а не с истиной: отсутствующий ключ не должен читаться как
        запрет.
        """
        for name in ('steps.js', 'graph.js'):
            code = (WORKFLOW_JS / name).read_text(encoding='utf-8')

            assert '!== false' in code, \
                f'{name} читает отсутствие ключа как запрет'


def _decide(meta: dict, step_type: str, transition_fired: bool) -> str:
    """Что сделает движок: `jump`, `stop` или `next`.

    ⚠ Повторяет **выражение** движка, а не его смысл: разойдись они, тест
    зеленел бы на сломанном коде. Сам движок здесь не позвать — он тянет за
    собой LLM, сессию и журнал.
    """
    if transition_fired:
        return 'jump'

    if not _to_next_step(meta) and step_type not in AI_FRAMEWORK_STEP_RETURNS:
        return 'stop'

    return 'next'


def _source(func) -> str:
    """Код функции без комментариев и docstring.

    ⚠ Нужен затем, чтобы сторож не ловил **объяснения**: причины правки названы
    в комментариях рядом, и поиск подстрокой находил бы их.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))

    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if not isinstance(body, list):
            continue
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body.pop(0)

    return ast.unparse(tree)

"""Подпоток видит только переданное: область видимости собирается заново.

## ⚠⚠ Правило (указание человека)

Единственная дорога значения из workflow в подпоток — **входящая переменная**:
`inputs_map` шага `workflow_invoke` кладёт её ребёнку, а объявленные
`input`-переменные ребёнка требуют, чтобы её передали. Общих переменных у разных
workflow нет — ни в реестре, ни в прогоне.

Половину правила держит схема: у переменной один владелец
(`agent_workflow_variable.workflow_id`), и одинаковое имя в двух workflow — две
независимые записи. Это проверяет `tests/test_workflow_crud.py`, описывает
`.claude/docs/workflow.md` §2.1.

## Что стережётся здесь

Вторая половина — сам прогон. Движок собирает ребёнку **новый** словарь, а не
копию родительского, и наполняет его только `inputs_map`, умолчаниями ребёнка и
коротким списком служебных имён. Начни кто-нибудь «для удобства» с
`dict(variables)` — изоляция исчезнет молча: прогоны продолжат проходить, а
подпоток просто начнёт видеть чужое. Ни один тест маршрута этого не заметит:
лишняя переменная в области видимости ничего не ломает, она ждёт своего часа.

⚠ Сторож читает **выражение** движка, а не пересказ: позвать
`_workflow_steps_run` нельзя — он тянет за собой LLM, сессию и журнал. Приём тот
же, что в `test_workflow_to_next_step.py`, и по той же причине.
"""

import ast
import inspect
import textwrap

import pytest

from src.ai.framework.agent import ai_framework_manager as mod

pytestmark = pytest.mark.core

# Имена, которые едут ребёнку помимо `inputs_map`. Список закрыт намеренно:
# каждое имя здесь — сквозная служебная величина, а не «удобная» переменная.
SUBFLOW_SERVICE_VARS = ('user_language', 'node_languages')


class TestTheScopeIsBuiltFromScratch:
    """⚠⚠ Главное: словарь ребёнка — новый, а не копия родительского."""

    def test_the_scope_starts_with_one_key(self):
        """Начало области видимости — сам `workflow_id`, и больше ничего."""
        code = _invoke_code()

        assert "child_scope = {'workflow_id': child_workflow_id}" in code, \
            'область видимости подпотока больше не собирается с нуля'

    @pytest.mark.parametrize('leak', [
        'dict(variables)', 'variables.copy()', '**variables',
        'child_scope.update(variables)', 'child_scope = variables',
    ])
    def test_the_parent_scope_is_not_poured_in(self, leak):
        """⚠⚠ Ровно тот способ сломать изоляцию, которого не видно на прогоне.

        Скопируй родительский словарь — и подпоток увидит всё, что есть у
        родителя: его внутренние переменные, ответы его шагов, его умолчания.
        Упадёт от этого не прогон, а доверие к контракту: `inputs_map` перестанет
        быть единственной дорогой, и однажды подпоток начнёт молча пользоваться
        чужим значением вместо непереданного своего.
        """
        assert leak not in _invoke_code(), \
            f'родительская область видимости утекает ребёнку через {leak}'

    def test_the_scope_is_rebuilt_on_every_repeat(self):
        """⚠ Повтор (`repeat.until`) собирает область видимости заново.

        Иначе вторая попытка видела бы переменные первой — неудачной, — и
        условие остановки читало бы вчерашний ответ.
        """
        code = _invoke_code()
        start = code.find('while iteration < max_iterations')

        assert start != -1, 'цикл повтора подпотока пропал'
        assert "child_scope = {'workflow_id': child_workflow_id}" in code[start:], \
            'область видимости собирается до цикла — повтор увидит прошлую попытку'


class TestTheOnlyRoadIn:
    """⚠⚠ Чем наполняется область видимости ребёнка — перечислено, а не «как вышло»."""

    def test_the_sources_are_exactly_three(self):
        """Все присваивания в `child_scope` и их источники — списком.

        Три и только три: служебное имя, вход по `inputs_map`, умолчание самого
        ребёнка. Четвёртый источник — это новая дорога внутрь, и заводить её
        может только человек, отдельным решением.
        """
        assert _child_scope_sources() == {
            'variables[service_var]',   # служебные, список закрыт
            'variables[parent_var]',    # вход по inputs_map
            "v.get('default')",         # умолчание переменной ребёнка
        }, 'у области видимости подпотока появился новый источник значений'

    def test_the_input_comes_from_the_map(self):
        """Вход берётся по карте, а не по совпадению имён."""
        code = _invoke_code()

        assert 'for child_var, parent_var in inputs_map.items()' in code, \
            'входы подпотока перестали читаться из inputs_map'
        assert 'child_scope[child_var] = variables[parent_var]' in code, \
            'значение входа кладётся ребёнку не по карте'

    def test_the_service_list_is_named_and_closed(self):
        """⚠ Сквозные служебные имена — короткий явный список.

        `user_language` одинаков во всех вложенных workflow, и требовать его в
        `inputs_map` на каждом шаге значило бы забыть его на одном. Но список
        именно список: добавление имени — правка кода, которую видно в диффе, а
        не побочный эффект чужой правки.
        """
        code = _invoke_code()
        literal = str(SUBFLOW_SERVICE_VARS)

        assert f'for service_var in {literal}' in code, \
            f'список сквозных служебных имён разошёлся с {literal}'
        assert 'if service_var in variables' in code, \
            'служебное имя кладётся ребёнку, даже когда его нет у родителя'


class TestTheContractIsChecked:
    """⚠ Объявленный вход обязателен: непереданный — отказ, а не пустота."""

    def test_the_declared_inputs_are_demanded(self):
        code = _invoke_code()

        assert 'await ai_workflow_variables_input_get(child_workflow_id)' in code, \
            'контракт входа подпотока больше не спрашивается'
        assert 'raise ValueError' in code, \
            'непереданный вход перестал быть отказом'

    def test_an_unknown_parent_variable_is_a_refusal(self):
        """⚠⚠ `inputs_map`, ссылающийся на несуществующее у родителя, — отказ.

        Подставь здесь `variables.get(parent_var)` — и ребёнок получил бы `None`
        там, где ждал значение: прогон пошёл бы дальше с пустой переменной, а
        искать причину пришлось бы в ответе модели.
        """
        code = _invoke_code()

        assert 'if parent_var not in variables' in code, \
            'ссылка на несуществующую переменную родителя больше не отказ'


class TestTheOnlyRoadOut:
    """⚠ Обратно — только `outputs_map` и результат прогона."""

    def test_the_outputs_map_is_the_road_back(self):
        code = _invoke_code()

        assert 'for child_var, parent_var in outputs_map.items()' in code, \
            'выходы подпотока перестали читаться из outputs_map'
        assert 'variables[parent_var] = child_scope[child_var]' in code, \
            'значение возвращается родителю не по карте'

    def test_nothing_else_of_the_child_reaches_the_parent(self):
        """⚠⚠ В родителя уходит **названное**, а не вся область видимости ребёнка.

        Источников три: значение по `outputs_map`, результат прогона и его
        безымянный алиас. Появись четвёртый — ребёнок снова пишет родителю
        мимо контракта.
        """
        assert _parent_scope_sources() == {
            'child_scope[child_var]',   # по outputs_map
            "child_result if child_result is not None else ''",
            'variables[result_var]',    # алиас на тот же результат
        }, 'подпоток пишет родителю чем-то ещё, кроме outputs_map и результата'


def _invoke_nodes() -> list:
    """Тело ветки `workflow_invoke` движка — узлами разбора.

    ⚠ Берём **ветку**, а не всю функцию: соседние шаги вправе делать с
    `variables` что угодно, и поиск подстрокой по функции целиком ловил бы их.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(
        mod.AiFrameworkAgentManager._workflow_steps_run)))

    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and ast.unparse(node.test) == "step_type == 'workflow_invoke'"):
            return node.body

    raise AssertionError('в движке больше нет ветки step_type == workflow_invoke')


def _invoke_code() -> str:
    """Та же ветка строкой — без комментариев и docstring.

    ⚠ `ast.unparse` возвращает код в едином написании: сторож не ловит
    **объяснения** рядом и не падает от переставленных кавычек.
    """
    return '\n'.join(ast.unparse(node) for node in _invoke_nodes())


def _child_scope_sources() -> set:
    """Что присваивается в `child_scope` — выражениями-источниками."""
    return _subscript_sources('child_scope')


def _parent_scope_sources() -> set:
    """Что присваивается в `variables` внутри ветки — то есть уходит родителю."""
    return _subscript_sources('variables')


def _subscript_sources(name: str) -> set:
    """Правые части всех `name[…] = …` внутри ветки подпотока."""
    found = set()
    for node in _invoke_nodes():
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Assign):
                continue
            for target in inner.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == name):
                    found.add(ast.unparse(inner.value))

    return found

"""Условие блока `[<if …>]`: связки `and`/`or` и сравнения.

Прежде условие было одним именем: `[<if var>]` и `[<if !var>]`. Теперь оно
понимает `== != > < >= <=` и связки — то есть стало выражением, и у выражения
появились собственные способы сломаться.

⚠⚠ Главное, что здесь стережётся, — **неразобранное условие не сворачивается**.
Блок остаётся в тексте целиком и достаётся сторожу (`ai_workflow_marks_check`).
Сверни мы его как ложное, опечатка (`[<if a && b>]`) молча съедала бы кусок
промпта: ни ошибки, ни следа, а модель получила бы задание без половины.

⚠ Сравнение здесь и сравнение в переходах — **одна функция**
(`ai_workflow_variable_compare`). Поэтому часть проверок смотрит на неё прямо:
разойдись эти два места, `>` в переходе и `>` в блоке однажды дали бы разное.

Базы тут нет вовсе: разбор условия — чистая функция от текста и словаря.
"""
import pytest

from src.ai.ai_workflow import (ai_workflow_condition_check,
                                ai_workflow_if_blocks_render,
                                ai_workflow_variable_compare)

pytestmark = pytest.mark.ai

VARIABLES = {
    'yes': '1',
    'also': '1',
    'zero': '0',
    'empty': '',
    'untrue': 'false',
    'count': '7',
    'kind': 'chat',
    'name': 'John Smith',
    'number': 1,
}


def _render(source: str) -> str:
    return ai_workflow_if_blocks_render(source, VARIABLES)


class TestTruthyStaysAsItWas:
    """Старая запись обязана работать прежним образом."""

    @pytest.mark.parametrize('source, expected', [
        ('[<if yes>]ДА[<endif>]', 'ДА'),
        ('[<if zero>]ДА[<else>]НЕТ[<endif>]', 'НЕТ'),
        ('[<if empty>]ДА[<else>]НЕТ[<endif>]', 'НЕТ'),
        ('[<if untrue>]ДА[<else>]НЕТ[<endif>]', 'НЕТ'),
        ('[<if !zero>]ДА[<endif>]', 'ДА'),
        ('[<if missing>]ДА[<else>]НЕТ[<endif>]', 'НЕТ'),
        ('до [<if yes>]внутри[<endif>] после', 'до внутри после'),
    ])
    def test_single_name(self, source, expected):
        assert _render(source) == expected


class TestConnectives:
    @pytest.mark.parametrize('source, expected', [
        ('[<if yes and also>]ОБА[<endif>]', 'ОБА'),
        ('[<if yes and zero>]ОБА[<else>]НЕТ[<endif>]', 'НЕТ'),
        ('[<if zero or also>]ХОТЬ[<endif>]', 'ХОТЬ'),
        ('[<if zero or empty>]ХОТЬ[<else>]НИ[<endif>]', 'НИ'),
        ('[<if yes and also and count>]ТРИ[<endif>]', 'ТРИ'),
    ])
    def test_and_or(self, source, expected):
        assert _render(source) == expected

    def test_and_binds_tighter_than_or(self):
        """⚠ `a and b or c` читается как `(a and b) or c`, как в любом языке.

        Левая часть истинна — ответ истина независимо от `c`.
        """
        assert _render('[<if yes and also or zero>]ДА[<endif>]') == 'ДА'

    def test_or_branch_saves_false_and(self):
        """Та же запись, но истинна правая часть: `(zero and also) or yes`."""
        assert _render('[<if zero and also or yes>]ДА[<endif>]') == 'ДА'

    def test_name_with_or_inside_is_not_a_connective(self):
        """⚠ Связка — слово в пробелах, иначе `oregon` развалился бы надвое."""
        assert ai_workflow_condition_check('oregon', {'oregon': '1'}) is True


class TestComparison:
    @pytest.mark.parametrize('source, expected', [
        ('[<if count > 5>]БОЛЬШЕ[<endif>]', 'БОЛЬШЕ'),
        ('[<if count > 50>]Б[<else>]МЕНЬШЕ[<endif>]', 'МЕНЬШЕ'),
        ('[<if count < 10>]МЕНЬШЕ[<endif>]', 'МЕНЬШЕ'),
        ('[<if count >= 7>]НЕ МЕНЬШЕ[<endif>]', 'НЕ МЕНЬШЕ'),
        ('[<if count <= 7>]НЕ БОЛЬШЕ[<endif>]', 'НЕ БОЛЬШЕ'),
        ("[<if kind == 'chat'>]ЧАТ[<endif>]", 'ЧАТ'),
        ('[<if kind == "chat">]ДВОЙНЫЕ ТОЖЕ[<endif>]', 'ДВОЙНЫЕ ТОЖЕ'),
        ("[<if kind == 'mail'>]П[<else>]НЕ ПОЧТА[<endif>]", 'НЕ ПОЧТА'),
        ("[<if kind != 'mail'>]НЕ ПОЧТА[<endif>]", 'НЕ ПОЧТА'),
        ('[<if number == 1>]ЧИСЛОМ[<endif>]', 'ЧИСЛОМ'),
    ])
    def test_operators(self, source, expected):
        assert _render(source) == expected

    def test_numbers_compare_as_numbers(self):
        """⚠⚠ `str(10) > str(5)` лексикографически ЛОЖЬ: «1» меньше «5».

        Правило живёт в `ai_workflow_variable_compare` и общее с переходами.
        """
        assert ai_workflow_variable_compare({'n': '10'}, 'n', '>', '5') is True

    def test_quoted_value_keeps_spaces(self):
        """Значение с пробелом берут в кавычки — иначе оборвётся на первом."""
        assert _render('[<if name == "John Smith">]ИМЯ[<endif>]') == 'ИМЯ'

    def test_quotes_make_it_a_word(self):
        """⚠⚠⚠ В кавычках — слово, даже если переменная с таким именем есть."""
        got = ai_workflow_condition_check("kind == 'chat'", {'kind': 'chat',
                                                             'chat': 'mail'})

        assert got is True

    def test_bare_name_is_a_variable(self):
        """⚠⚠⚠ Без кавычек справа — ПЕРЕМЕННАЯ, а не слово.

        Правило выбрано человеком и лучше прежнего: спорить, слово это или
        переменная, не приходится — кавычки видны.
        """
        same = ai_workflow_condition_check('kind == other', {'kind': 'chat',
                                                             'other': 'chat'})
        differ = ai_workflow_condition_check('kind == other', {'kind': 'chat',
                                                               'other': 'mail'})

        assert same is True and differ is False

    def test_numbers_compare_by_variable_too(self):
        """Справа тоже бывает число переменной, а не только литерал."""
        got = ai_workflow_condition_check('count > limit', {'count': '7',
                                                            'limit': '5'})

        assert got is True

    def test_missing_right_variable_is_false(self):
        """⚠ Правой переменной нет — условие ложно, а не «текст непонятен».

        Имя написано верно, значения пока нет: ругаться не на что, сравнивать
        не с чем.
        """
        assert _render('[<if kind == missing>]Х[<else>]НЕТ[<endif>]') == 'НЕТ'

    def test_right_variable_none_is_emptiness(self):
        """⚠⚠ `None` у заполненной переменной — пустота, а не слово «None».

        Сравнение приводит правую часть к строке, и без приведения `str(None)`
        дал бы `'None'` — значение, с которым никто не сравнивает нарочно.
        Ключ в словаре есть, поэтому это не «переменной нет».
        """
        empty = ai_workflow_condition_check('kind == other', {'kind': '',
                                                              'other': None})
        word = ai_workflow_condition_check('kind == other', {'kind': 'None',
                                                             'other': None})

        assert empty is True and word is False

    def test_empty_string_is_comparable(self):
        """⚠ `''` — законное сравнение с пустотой, а не «переменной нет»."""
        assert ai_workflow_condition_check("empty == ''", {'empty': ''}) is True

    def test_missing_variable_is_false_not_broken(self):
        """⚠ Переменной нет — условие ложно, а не «текст непонятен».

        Иначе промпт с условием по ещё не заполненной переменной уехал бы к
        модели с разметкой внутри.
        """
        assert _render('[<if missing == 5>]Х[<else>]НЕТ[<endif>]') == 'НЕТ'

    def test_mixed_with_connective(self):
        source = "[<if count > 5 and kind == 'chat'>]ОБА[<endif>]"

        assert _render(source) == 'ОБА'


class TestNesting:
    def test_inner_block_resolves(self):
        """⚠⚠ Регрессия, на которой ловилась первая редакция регулярки.

        Условие ловилось нежадным `.+?`, и он перескакивал через `>]` к
        следующему: на этой строке условием становилось `yes>][<if count > 5`,
        а внешний блок пропадал целиком.
        """
        source = '[<if yes>][<if count > 5>]ВНУТРИ[<endif>][<endif>]'

        assert _render(source) == 'ВНУТРИ'

    def test_outer_else_wins(self):
        source = '[<if zero>][<if yes>]Х[<endif>][<else>]ВНЕШНИЙ[<endif>]'

        assert _render(source) == 'ВНЕШНИЙ'


class TestBrokenStaysWhole:
    """⚠⚠⚠ Непонятое не сворачивается — иначе опечатка съедает промпт молча."""

    @pytest.mark.parametrize('source', [
        '[<if yes && also>]Х[<endif>]',
        '[<if >]Х[<endif>]',
        '[<if yes or ???>]Х[<endif>]',
        '[<if 5var>]Х[<endif>]',
    ])
    def test_stays_as_is(self, source):
        assert _render(source) == source

    def test_negation_with_comparison_is_refused(self):
        """`!a == b` читается двояко — «не(a == b)» или «(!a) == b».

        Вместо догадки отдаём сторожу: пишущему остаётся `!=`.
        """
        assert _render('[<if !yes == 1>]Х[<endif>]') == '[<if !yes == 1>]Х[<endif>]'

    def test_broken_part_poisons_the_whole_condition(self):
        """⚠ Непонятная часть справа от истинной тоже замечается.

        Короткого замыкания нет намеренно: иначе опечатка живёт, пока левая
        половина истинна, и проявляется в тот день, когда она станет ложной.
        """
        assert ai_workflow_condition_check('yes or ???', VARIABLES) is None


class TestEmptyAndNotEmpty:
    """`empty` / `not_empty`: что считается содержимым, а что — пустотой.

    ⚠⚠ Эти операторы живут только в **переходах**. В условном блоке их нет и не
    нужно: `[<if var>]` уже спрашивает истинность, то есть почти то же самое.
    Почти — потому что `truthy` считает ложью ещё `0` и `false`, а `not_empty`
    смотрит только на наличие знаков.
    """

    # ⚠ Пустым считается всё, что `strip()` сводит к нулю: один пробел, пачка
    # пробелов, табы и переводы строки. Текст из одних разделителей — это
    # «ничего не написано», и ветка «есть содержимое» на нём срабатывать не
    # должна.
    BLANK = ('', ' ', '    ', '\n', '\n\n', '  \n  ', '\t', ' \t\n ')

    @pytest.mark.parametrize('value', BLANK)
    def test_whitespace_only_is_empty(self, value):
        assert ai_workflow_variable_compare({'v': value}, 'v', 'empty', '') is True

    @pytest.mark.parametrize('value', BLANK)
    def test_whitespace_only_is_not_a_content(self, value):
        assert ai_workflow_variable_compare({'v': value}, 'v', 'not_empty', '') is False

    @pytest.mark.parametrize('value', ['x', ' x ', '0', 'false', '\nтекст\n', '-'])
    def test_any_character_is_a_content(self, value):
        """⚠ `0` и `false` — содержимое: пустоту спрашивают, а не истинность."""
        assert ai_workflow_variable_compare({'v': value}, 'v', 'not_empty', '') is True
        assert ai_workflow_variable_compare({'v': value}, 'v', 'empty', '') is False

    def test_missing_variable_is_empty(self):
        """Переменной нет вовсе — она пуста и непустой быть не может."""
        assert ai_workflow_variable_compare({}, 'нет', 'empty', '') is True
        assert ai_workflow_variable_compare({}, 'нет', 'not_empty', '') is False

    def test_none_is_empty(self):
        """⚠ `None` приходит от инструмента, не заполнившего ключ."""
        assert ai_workflow_variable_compare({'v': None}, 'v', 'empty', '') is True
        assert ai_workflow_variable_compare({'v': None}, 'v', 'not_empty', '') is False

    def test_not_empty_is_not_the_same_as_ne_empty_string(self):
        """⚠⚠ Ради этого отличия оператор и заводили.

        `!= ''` на отсутствующей переменной отвечает `None` — «не знаю», и
        переход молча пропускается. `not_empty` отвечает `False`: ветка не
        срабатывает честно, без предупреждения в журнале.
        """
        assert ai_workflow_variable_compare({}, 'нет', '!=', '') is None
        assert ai_workflow_variable_compare({}, 'нет', 'not_empty', '') is False

    def test_empty_and_not_empty_are_opposite(self):
        """Два оператора обязаны отвечать противоположно — всегда."""
        cases = ({'v': 'x'}, {'v': ''}, {'v': '   '}, {'v': None}, {})

        for variables in cases:
            empty = ai_workflow_variable_compare(variables, 'v', 'empty', '')
            filled = ai_workflow_variable_compare(variables, 'v', 'not_empty', '')

            assert empty is not filled, f'{variables}: {empty} и {filled}'

    def test_value_field_is_ignored(self):
        """⚠ Поле «Значение» редактор у них прячет, но из метаданных не трёт.

        Старый переход мог сохранить текст в `value`, а человек потом сменить
        оператор — ответ не должен от этого зависеть.
        """
        for given in ('', 'мусор', '0', None):
            assert ai_workflow_variable_compare(
                {'v': 'x'}, 'v', 'not_empty', given) is True

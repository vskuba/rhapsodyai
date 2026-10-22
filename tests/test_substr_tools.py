"""Подстрока: вырезать, сосчитать, найти, заменить — **как в PHP**.

## ⚠⚠ Почему именно PHP

Имена и доводы взяты один в один: `substr`, `substr_count`, `substr_replace`,
`str_contains`, `str_starts_with`, `strpos`, `strrpos`, `str_replace`, `strlen`.

Знакомое имя обязано делать знакомое дело. Прежде функция звалась `text_substr`
и **искала** подстроку, тогда как `substr` в PHP **вырезает кусок** строки —
читающий подставил бы чужое поведение и ошибся молча. На этом уже спотыкались с
`array_diff_key`.

⚠ Этот файл и есть сверка с PHP: каждая проверка повторяет пример из его
руководства. Разойдись поведение — покраснеет здесь, а не в чужом workflow через
месяц.

⚠ В базу не ходим — функции чистые.
"""

import pytest

import src.tool.substr.substr_ as S

# ⚠ Две метки: `core` — группа прогона (без неё файл не попадает ни в один
# маркер и молча не запускается, `test_marks.py`), `asyncio` — род самих тестов.
pytestmark = [pytest.mark.core, pytest.mark.asyncio]


class TestSubstr:
    async def test_a_part_from_the_offset(self):
        assert (await S.substr('abcdef', 1, 3))['str'] == 'bcd'

    async def test_negative_offset_counts_from_the_end(self):
        assert (await S.substr('abcdef', -2))['str'] == 'ef'

    async def test_negative_length_cuts_the_tail(self):
        """Как в PHP: отрицательная длина отрезает столько знаков с конца."""
        assert (await S.substr('abcdef', 1, -1))['str'] == 'bcde'

    async def test_empty_length_means_to_the_end(self):
        """⚠ В workflow число приходит строкой и часто пустым, и «ноль знаков»
        было бы ловушкой."""
        assert (await S.substr('abcdef', 3))['str'] == 'def'
        assert (await S.substr('abcdef', 3, ''))['str'] == 'def'


class TestSubstrCount:
    async def test_counts_every_occurrence(self):
        assert await S.substr_count('a b a b a', 'a') == {'qty': 3}

    async def test_overlaps_are_not_counted(self):
        """⚠ Как в PHP: «аа» в «ааа» даёт один, а не два."""
        assert await S.substr_count('ааа', 'аа') == {'qty': 1}

    async def test_the_search_is_literal(self):
        """⚠ Ни регулярок, ни границ слова: `кот` найдётся внутри `котлеты`."""
        assert await S.substr_count('котлеты', 'кот') == {'qty': 1}

    async def test_case_matters_by_default(self):
        assert await S.substr_count('Abc abc', 'abc') == {'qty': 1}
        assert await S.substr_count('Abc abc', 'abc', True) == {'qty': 2}


class TestPosition:
    async def test_first_occurrence(self):
        assert await S.substr_position('abc', 'b') == {'found': '1', 'pos': 1}

    async def test_last_occurrence(self):
        """С `last` — как `strrpos` в PHP."""
        got = await S.substr_position('aba', 'a', last=True)

        assert got == {'found': '1', 'pos': 2}, got

    async def test_the_first_character_is_not_empty(self):
        """⚠⚠ Судить — по `found`, а не по `pos`: вхождение в самом начале даёт
        ноль, а условие на пустое значение считает его за «пусто»."""
        got = await S.substr_position('abc', 'a')

        assert got == {'found': '1', 'pos': 0}, got

    async def test_absent(self):
        assert await S.substr_position('abc', 'z') == {'found': '0', 'pos': -1}


class TestChecks:
    async def test_contains(self):
        assert (await S.substr_contains('abc', 'b'))['found'] == '1'
        assert (await S.substr_contains('abc', 'z'))['found'] == '0'

    async def test_starts_and_ends(self):
        assert (await S.substr_starts_with('abc', 'ab'))['found'] == '1'
        assert (await S.substr_ends_with('abc', 'bc'))['found'] == '1'
        assert (await S.substr_starts_with('abc', 'bc'))['found'] == '0'

    async def test_an_empty_needle_is_not_a_match(self):
        """⚠ В PHP пустая строка считается началом любой, но для workflow это
        ложное «да» на незаполненной переменной."""
        assert (await S.substr_starts_with('abc', ''))['found'] == '0'
        assert (await S.substr_contains('abc', ''))['found'] == '0'


class TestReplace:
    async def test_replace_by_position(self):
        got = await S.substr_replace('abcdef', 'X', 1, 3)

        assert got['str'] == 'aXef', got

    async def test_replace_cuts_when_nothing_given(self):
        assert (await S.substr_replace('abcdef', '', 1, 3))['str'] == 'aef'

    async def test_replace_all_occurrences(self):
        got = await S.substr_str_replace('a b a', 'a', 'X')

        assert got == {'str': 'X b X', 'qty': 2}, got

    async def test_replace_ignoring_case(self):
        """⚠ Меняется сам текст, а не его нижний вид: остальное уцелело."""
        got = await S.substr_str_replace('A b a', 'a', 'X', True)

        assert got['str'] == 'X b X', got

    async def test_an_empty_needle_changes_nothing(self):
        """⚠⚠ `''.replace` вставил бы замену между каждой парой знаков."""
        got = await S.substr_str_replace('abc', '', 'X')

        assert got == {'str': 'abc', 'qty': 0}, got


class TestLength:
    async def test_counts_characters_not_bytes(self):
        """⚠ Текст у нас юникодный, и «байт» ответил бы не на тот вопрос."""
        assert await S.substr_length('абв') == {'len': 3}

    async def test_empty(self):
        assert await S.substr_length('') == {'len': 0}
        assert await S.substr_length(None) == {'len': 0}


class TestTheNakedMarkCase:
    """⚠⚠⚠ Тот случай, ради которого семья и понадобилась.

    Агент письма написал имя переменной без скобок. Поиском этого не узнать:
    имя встречается и **внутри** метки. Спрашивается счётом — числа обязаны
    совпасть.
    """

    async def test_a_naked_name_breaks_the_balance(self):
        text = 'companion_name, the kettle — [[companion_name]]'

        naked = (await S.substr_count(text, 'companion_name'))['qty']
        marked = (await S.substr_count(text, '[[companion_name]]'))['qty']

        assert (naked, marked) == (2, 1), (naked, marked)

    async def test_a_proper_mark_balances(self):
        text = "Hi [[companion_name]], I'm [[girl_name]]."

        naked = (await S.substr_count(text, 'companion_name'))['qty']
        marked = (await S.substr_count(text, '[[companion_name]]'))['qty']

        assert naked == marked == 1, (naked, marked)

"""Массивы: разница, пересечение и прочее — **как в PHP**.

## ⚠⚠ Почему именно PHP

Имена и поведение взяты у него один в один: `array_diff`, `array_diff_key`,
`array_diff_assoc`, `array_intersect`, `array_merge`, `array_flip`…

Знакомое имя обязано делать знакомое дело. Назови мы функцию `array_diff_key`, а
сравнивай по значениям — читающий подставит чужое поведение и ошибётся молча.
Поэтому своих доводов к сигнатурам не добавляем: два массива на входе, массив на
выходе, и всё.

⚠ Этот файл и есть сверка с PHP: каждая проверка повторяет пример из его
руководства. Разойдись поведение — покраснеет здесь, а не в чужом workflow через
месяц.

## ⚠⚠ Ради чего семья появилась

Сравнить два списка движок workflow не умеет: цикл читает поля, но попарно
пройти два списка нечем. Понадобилось это, когда агент письма написал имя
переменной **без скобок** — «companion_name, the kettle clicked off» вместо
`[[companion_name]]`. Ловится парой счётов и `array_diff_assoc`.

⚠ В базу не ходим — инструменты её не касаются.
"""

import pytest

import src.tool.array.array_ as A

# ⚠ Две метки: `core` — группа прогона (без неё файл не попадает ни в один
# маркер и молча не запускается, `test_marks.py`), `asyncio` — род самих тестов.
pytestmark = [pytest.mark.core, pytest.mark.asyncio]


class TestDiff:
    async def test_diff_by_values(self):
        got = await A.array_diff(['a', 'b', 'c'], ['b'])

        assert got['list'] == ['a', 'c'], got

    async def test_diff_key_compares_keys(self):
        """⚠ `diff_key` смотрит **ключи**, значения в счёт не идут."""
        got = await A.array_diff_key({'a': 1, 'b': 2}, {'a': 9})

        assert got['dict'] == {'b': 2}, got

    async def test_diff_assoc_compares_pairs(self):
        """⚠⚠ Тот самый случай: ключи те же, значения те же, расходится **пара**.

        Ни `diff`, ни `diff_key` такого не ловят — проверено ниже.
        """
        got = await A.array_diff_assoc({'a': 1, 'b': 1}, {'a': 1, 'b': 0})

        assert got['dict'] == {'b': 1}, got

    async def test_only_assoc_catches_the_broken_mark(self):
        """⚠⚠⚠ Доказательство, что нужен именно `diff_assoc`."""
        naked = {'girl_name': 1, 'companion_name': 1}
        marked = {'girl_name': 1, 'companion_name': 0}

        assert (await A.array_diff(naked, marked))['qty'] == 0, 'diff вдруг ловит'
        assert (await A.array_diff_key(naked, marked))['qty'] == 0, 'diff_key вдруг ловит'
        assert (await A.array_diff_assoc(naked, marked))['dict'] == {'companion_name': 1}


class TestIntersect:
    async def test_intersect_by_values(self):
        got = await A.array_intersect(['a', 'b'], ['b', 'c'])

        assert got['list'] == ['b'], got

    async def test_intersect_key(self):
        got = await A.array_intersect_key({'a': 1, 'b': 2}, {'a': 9})

        assert got['dict'] == {'a': 1}, got

    async def test_intersect_assoc(self):
        got = await A.array_intersect_assoc({'a': 1, 'b': 2}, {'a': 1})

        assert got['dict'] == {'a': 1}, got


class TestMerge:
    async def test_numeric_keys_are_appended(self):
        """⚠ Как в PHP: числовые ключи **дописываются**, а не замещают. Иначе
        два массива по три элемента слились бы в три."""
        got = await A.array_merge(['a'], ['b'])

        assert got['list'] == ['a', 'b'], got

    async def test_string_keys_overwrite(self):
        got = await A.array_merge({'a': 1}, {'a': 2})

        assert got['dict'] == {'a': 2}, got


class TestShape:
    async def test_unique_keeps_the_first(self):
        got = await A.array_unique(['a', 'b', 'a'])

        assert got['list'] == ['a', 'b'], got

    async def test_keys_and_values(self):
        assert (await A.array_keys({'a': 1, 'b': 2}))['list'] == ['a', 'b']
        assert (await A.array_values({'a': 1, 'b': 2}))['list'] == [1, 2]

    async def test_keys_come_as_string_too(self):
        """⚠ Строкой через запятую — так их читает промпт."""
        assert (await A.array_keys({'a': 1, 'b': 2}))['str'] == 'a,b'

    async def test_flip(self):
        got = await A.array_flip({'a': 'x'})

        assert got['dict'] == {'x': 'a'}, got

    async def test_reverse(self):
        assert (await A.array_reverse(['a', 'b']))['list'] == ['b', 'a']

    async def test_slice(self):
        assert (await A.array_slice(['a', 'b', 'c', 'd'], 1, 2))['list'] == ['b', 'c']

    async def test_slice_from_the_end(self):
        assert (await A.array_slice(['a', 'b', 'c'], -2))['list'] == ['b', 'c']

    async def test_zero_length_means_to_the_end(self):
        """⚠ В workflow число приходит строкой и часто пустым, и «ноль
        элементов» было бы ловушкой."""
        assert (await A.array_slice(['a', 'b'], 0, 0))['qty'] == 2
        assert (await A.array_slice(['a', 'b'], 0, ''))['qty'] == 2


class TestBuild:
    async def test_column_with_index(self):
        rows = [{'id': 1, 'n': 'a'}, {'id': 2, 'n': 'b'}]
        got = await A.array_column(rows, 'n', 'id')

        assert got['dict'] == {'1': 'a', '2': 'b'}, got

    async def test_column_skips_rows_without_the_field(self):
        """⚠ Как в PHP: запись без нужного поля пропускается."""
        got = await A.array_column([{'n': 'a'}, {'x': 1}], 'n')

        assert got['list'] == ['a'], got

    async def test_combine(self):
        got = await A.array_combine(['a', 'b'], [1, 2])

        assert got['dict'] == {'a': 1, 'b': 2}, got

    async def test_combine_takes_the_shorter(self):
        """⚠ Длины не сошлись — берём по короткому, а не роняем прогон:
        половинчатый ответ честнее отказа посреди цепочки."""
        got = await A.array_combine(['a', 'b'], [1])

        assert got['dict'] == {'a': 1}, got

    async def test_fill_keys(self):
        got = await A.array_fill_keys(['a', 'b'], 'z')

        assert got['dict'] == {'a': 'z', 'b': 'z'}, got


class TestLookup:
    async def test_search_finds_the_key(self):
        got = await A.array_search(['a', 'b'], 'b')

        assert (got['found'], got['key'], got['list']) == ('1', '1', ['b']), got

    async def test_the_first_element_is_not_empty(self):
        """⚠⚠ Судить — по `found`, а не по `key`: у первого элемента ключ `0`,
        а условие на пустое значение считает ноль за «пусто». Та же грабля,
        что у `substr_position`."""
        got = await A.array_search(['a'], 'a')

        assert (got['found'], got['key']) == ('1', '0'), got

    async def test_search_absent(self):
        got = await A.array_search(['a'], 'z')

        assert (got['found'], got['key'], got['qty']) == ('0', '', 0), got

    async def test_search_takes_only_the_first(self):
        """⚠ Как в PHP: `array_search` отвечает «где лежит», а не «сколько
        их» — на это есть `array_count_values`."""
        got = await A.array_search(['a', 'b', 'a'], 'a')

        assert got['qty'] == 1 and got['key'] == '0', got

    async def test_count_values(self):
        got = await A.array_count_values(['a', 'b', 'a'])

        assert got['dict'] == {'a': 2, 'b': 1}, got

    async def test_count(self):
        assert (await A.array_count(['a', 'b']))['qty'] == 2


class TestTheShapeIsAlwaysOne:
    """⚠⚠⚠ Ответ одной формы у **всей** семьи.

    Форм было четыре: `list/dict/qty` у большинства, `list/qty/str` у `keys` и
    `values`, `found/key` у `search`, один `qty` у `count`. Вызывающий не мог
    знать, что придёт, и в workflow это всплывало переменной в «Undefined».

    ⚠ Проверяем **каждую** функцию: добавится двадцатая со своим набором
    ключей — покраснеет здесь.
    """

    KEYS = ['dict', 'found', 'key', 'list', 'qty', 'str']

    CASES = {
        'array_diff': (['a'], ['b']),
        'array_diff_key': ({'a': 1}, {'b': 1}),
        'array_diff_assoc': ({'a': 1}, {'a': 2}),
        'array_intersect': (['a'], ['a']),
        'array_intersect_key': ({'a': 1}, {'a': 9}),
        'array_intersect_assoc': ({'a': 1}, {'a': 1}),
        'array_merge': (['a'], ['b']),
        'array_unique': (['a', 'a'],),
        'array_keys': ({'a': 1},),
        'array_values': ({'a': 1},),
        'array_flip': ({'a': 'x'},),
        'array_column': ([{'n': 'a'}], 'n'),
        'array_combine': (['a'], [1]),
        'array_fill_keys': (['a'], 'z'),
        'array_slice': (['a', 'b'], 0, 1),
        'array_reverse': (['a', 'b'],),
        'array_search': (['a'], 'a'),
        'array_count_values': (['a', 'a'],),
        'array_count': (['a'],),
    }

    async def test_every_tool_answers_the_same_keys(self):
        for name, args in self.CASES.items():
            got = await getattr(A, name)(*args)

            assert sorted(got) == self.KEYS, (name, sorted(got))

    async def test_an_empty_answer_keeps_the_shape(self):
        """⚠ Пустой ответ — те же ключи, а не их отсутствие."""
        got = await A.array_diff([], ['a'])

        assert sorted(got) == self.KEYS, got
        assert (got['found'], got['key'], got['qty']) == ('0', '', 0), got

    async def test_found_tells_emptiness(self):
        """⚠⚠ В условии workflow судят по `found` или `qty`: у первого элемента
        ключ `0`, и проверка на пустоту сочла бы его отсутствием."""
        assert (await A.array_diff(['a'], []))['found'] == '1'
        assert (await A.array_diff([], ['a']))['found'] == '0'


class TestTheEdges:
    async def test_empty_is_empty(self):
        """⚠ Пусто — пустой массив, а не массив из пустоты: `[""]` дал бы
        ложный элемент, и разница посчиталась бы не по тому."""
        assert (await A.array_diff('', ['a']))['qty'] == 0
        assert (await A.array_diff(None, ['a']))['qty'] == 0

    async def test_json_strings_are_understood(self):
        """⚠ Из workflow массив приезжает строкой JSON."""
        got = await A.array_diff('["a","b"]', '["b"]')

        assert got['list'] == ['a'], got

    async def test_numbers_and_strings_match(self):
        """⚠ Из JSON число приезжает числом, из переменной — строкой, и
        `1 != "1"` развалило бы сравнение молча."""
        got = await A.array_diff([1, 2], ['1'])

        assert got['list'] == [2], got

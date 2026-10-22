"""Сравнение двух списков: разница, пересечение и поиск разошедшихся пар.

## ⚠⚠ Ради чего заведены

Агент письма написал имя переменной **без скобок** — «companion_name, the kettle
clicked off» вместо `[[companion_name]]`. Такое письмо уходит получателю как
есть, и прежние проверки его не видели: регулярка меток ищет только `[[…]]`, а
поиск по голому имени находит его и внутри метки.

Ловится **парой счётов** (`text_substr` со списком): сколько раз имя встречается
голым и сколько — в скобках. Числа обязаны совпасть, потому что каждое вхождение
имени должно быть внутри метки. Свести два ответа было нечем — отсюда эти
инструменты.

⚠ Сравнить два списка движок workflow не умеет: цикл читает поля, но попарно
пройти два списка нельзя. Значит это работа инструмента, а не промпта.

⚠ В базу не ходим — инструменты её не касаются.
"""

import pytest

from src.tool.list.list_ import array_diff, array_intersect, array_diff_key

# ⚠ Две метки: `core` — группа прогона (без неё файл не попадает ни в один
# маркер и молча не запускается, `test_marks.py`), `asyncio` — род самих тестов.
pytestmark = [pytest.mark.core, pytest.mark.asyncio]


class TestArrayDiff:
    async def test_what_is_missing_in_the_second(self):
        got = await array_diff(['a', 'b', 'c'], ['b'])

        assert got == {'list': ['a', 'c'], 'qty': 2}, got

    async def test_json_strings_are_understood(self):
        """⚠ Из workflow список приезжает строкой JSON."""
        got = await array_diff('["a","b"]', '["b"]')

        assert got['list'] == ['a'], got

    async def test_empty_first_is_empty(self):
        """⚠ Пусто — пустой список, а не список из пустоты: `[""]` дал бы
        ложный элемент, и разница посчиталась бы не по тому."""
        assert await array_diff([], ['b']) == {'list': [], 'qty': 0}
        assert await array_diff('', ['b']) == {'list': [], 'qty': 0}

    async def test_empty_second_keeps_everything(self):
        got = await array_diff(['a', 'b'], [])

        assert got['list'] == ['a', 'b'], got

    async def test_by_key_for_dicts(self):
        """⚠⚠ `key` сравнивает записи по одному полю: остальные в счёт не идут."""
        one = [{'substr': 'a', 'qty': 1}, {'substr': 'b', 'qty': 9}]
        two = [{'substr': 'b', 'qty': 0}]
        got = await array_diff(one, two, key='substr')

        assert [x['substr'] for x in got['list']] == ['a'], got

    async def test_numbers_and_strings_match(self):
        """⚠ Из JSON число приезжает числом, из переменной — строкой, и
        `1 != "1"` развалило бы сравнение молча."""
        got = await array_diff([1, 2], ['1'])

        assert got['list'] == [2], got


class TestArrayIntersect:
    async def test_what_is_common(self):
        got = await array_intersect(['a', 'b', 'c'], ['b', 'c', 'd'])

        assert got == {'list': ['b', 'c'], 'qty': 2}, got

    async def test_order_follows_the_first(self):
        got = await array_intersect(['c', 'a'], ['a', 'c'])

        assert got['list'] == ['c', 'a'], got

    async def test_nothing_common_is_empty(self):
        assert await array_intersect(['a'], ['b']) == {'list': [], 'qty': 0}


class TestArrayPairsDiffer:
    """⚠⚠⚠ Тот самый случай: голое имя переменной вместо метки."""

    async def test_the_broken_mark_is_named(self):
        naked = [{'substr': 'girl_name', 'qty': 1},
                 {'substr': 'companion_name', 'qty': 1}]
        marked = [{'substr': '[[girl_name]]', 'qty': 1},
                  {'substr': '[[companion_name]]', 'qty': 0}]

        got = await array_diff_key(naked, marked, key='', value='qty',
                                       name='substr')

        assert got['list'] == ['companion_name'], got
        assert got['str'] == 'companion_name', got

    async def test_all_balanced_is_empty(self):
        naked = [{'substr': 'girl_name', 'qty': 1}]
        marked = [{'substr': '[[girl_name]]', 'qty': 1}]

        got = await array_diff_key(naked, marked, key='', value='qty',
                                       name='substr')

        assert got == {'list': [], 'qty': 0, 'str': ''}, got

    async def test_pairs_by_place_when_no_key(self):
        """⚠ Без `key` пары берутся **по месту**: так сводятся ответы одного
        инструмента, спрошенного двумя наборами в одном порядке. Значения у них
        разные (`имя` против `[[имя]]`), а порядок один."""
        one = [{'v': 1}, {'v': 2}]
        two = [{'v': 1}, {'v': 5}]

        got = await array_diff_key(one, two, key='', value='v')

        assert got['list'] == ['1'], got

    async def test_a_missing_pair_is_a_mismatch(self):
        """⚠ Элементу нет пары — это расхождение, а не «совпало»."""
        one = [{'n': 'a', 'v': 1}, {'n': 'b', 'v': 1}]
        two = [{'n': 'a', 'v': 1}]

        got = await array_diff_key(one, two, key='n', value='v')

        assert got['list'] == ['b'], got

    async def test_by_key_finds_the_pair(self):
        """С `key` порядок неважен — пара ищется по полю."""
        one = [{'n': 'a', 'v': 1}, {'n': 'b', 'v': 2}]
        two = [{'n': 'b', 'v': 2}, {'n': 'a', 'v': 9}]

        got = await array_diff_key(one, two, key='n', value='v')

        assert got['list'] == ['a'], got

    async def test_name_falls_back_to_the_place(self):
        """⚠ Без `name` и без `key` остаётся номер места — он читается плохо,
        и это последнее средство, а не умолчание на каждый день."""
        got = await array_diff_key([{'v': 1}], [{'v': 2}], key='', value='v')

        assert got['list'] == ['0'], got

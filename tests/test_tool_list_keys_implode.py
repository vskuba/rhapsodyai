"""Отбор элементов списка по номерам: `list_keys_implode`.

⚠⚠ Что здесь стережётся. Судья пачки инвайтов отбирает годные реплики, и
просить его **воспроизвести** их текстом оказалось ненадёжно: на живом прогоне
он писал «line 5 is the best and is kept», а в ответ клал строку line 2 — то
есть терял работу молча, без единой ошибки в журнале. Номер модель держит
точно, текст по номеру берёт код.

⚠ Отсюда и терпимость разбора: номера приезжают от модели, и она пишет их
по-всякому — «2,5», «line 2, line 5», «2 and 5». Требовать чистый список
значило бы терять работу на форме ответа, а не на его сути.
"""
import json

import pytest

from src.tool.list.list_ import list_keys_implode

pytestmark = pytest.mark.core

ROWS = ['первая', 'вторая', 'третья', 'четвёртая', 'пятая']


class TestWhatIsPicked:
    async def test_numbers_count_from_one(self):
        got = await list_keys_implode(ROWS, '1,3')

        assert got['str'] == 'первая\n---\nтретья'
        assert got['qty'] == 2

    async def test_the_order_stays_the_original_one(self):
        """⚠ Отбор не перетасовывает пачку: реплики писались под приём со
        своим номером, и перестановка развязала бы их с ним."""
        assert (await list_keys_implode(ROWS, '5,2'))['str'] == 'вторая\n---\nпятая'

    async def test_a_repeat_takes_the_item_once(self):
        got = await list_keys_implode(ROWS, '2,2,2')

        assert got['qty'] == 1

    async def test_the_separator_is_given(self):
        got = await list_keys_implode(ROWS, '1,2', separator=' | ')

        assert got['str'] == 'первая | вторая'


class TestTheNumbersComeFromAModel:
    @pytest.mark.parametrize('given', ['2,5', ' 2 , 5 ', '2;5', 'line 2, line 5',
                                       '2 and 5', '[2, 5]'])
    def test_any_spelling_is_read(self, given):
        """⚠ Модель пишет номера по-всякому; суть ответа от формы не зависит."""
        import asyncio

        got = asyncio.run(list_keys_implode(ROWS, given))

        assert got['str'] == 'вторая\n---\nпятая', given

    async def test_a_number_out_of_range_is_dropped(self):
        got = await list_keys_implode(ROWS, '2,99')

        assert got['qty'] == 1

    async def test_a_negative_number_is_not_a_number(self):
        """⚠⚠ «-3» не должен стать третьим элементом.

        Пока номера вытаскивались как «цифры из куска», минус отбрасывался —
        и заведомо негодный номер молча оказывался законным.
        """
        got = await list_keys_implode(ROWS, '-3')

        assert got['qty'] == 0

    @pytest.mark.parametrize('given', ['', '   ', None, 'abc', 'ничего'])
    async def test_nothing_to_pick_is_empty(self, given):
        got = await list_keys_implode(ROWS, given)

        assert got == {'str': '', 'qty': 0}


class TestTheListComesFromTheEngine:
    async def test_a_json_string_is_read(self):
        """⚠ Массив от `llm_to_json` доезжает сюда JSON-строкой."""
        got = await list_keys_implode(json.dumps(ROWS, ensure_ascii=False), '1,2')

        assert got['qty'] == 2

    async def test_an_empty_list_is_not_a_failure(self):
        assert (await list_keys_implode([], '1,2')) == {'str': '', 'qty': 0}

    async def test_blank_items_are_skipped(self):
        """Пустая строка в пачке — не реплика, и в отбор она не идёт."""
        got = await list_keys_implode(['a', '', '   ', 'b'], '1,2,3,4')

        assert got['qty'] == 2


class TestTheLimitOfRender:
    """`list_implode(limit=…)` — обрезка набранного до заказанного."""

    async def test_the_limit_cuts_the_tail(self):
        from src.tool.list.list_ import list_implode

        assert await list_implode(ROWS, separator=',', limit=2) == 'первая,вторая'

    async def test_the_limit_arrives_as_text(self):
        from src.tool.list.list_ import list_implode

        assert await list_implode(ROWS, separator=',', limit='2') == 'первая,вторая'

    @pytest.mark.parametrize('given', ['', None, 0, 'мусор', -3, 99])
    async def test_no_limit_keeps_everything(self, given):
        from src.tool.list.list_ import list_implode

        got = await list_implode(ROWS, separator=',', limit=given)

        assert got.count(',') == len(ROWS) - 1, given

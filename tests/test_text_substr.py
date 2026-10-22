"""Поиск подстроки: счёт вхождений и список подстрок одним вызовом.

## ⚠⚠ Ради чего появился счёт

Агент письма написал имя переменной **без скобок** — «companion_name, the kettle
clicked off» вместо `[[companion_name]]`. Такое письмо уходит получателю как
есть, и прежние проверки его не видели: регулярка меток ищет только `[[…]]`, а
поиск по голому имени находит его и внутри метки.

Ловится **парой счётов**: сколько раз имя встречается голым и сколько — в
скобках. Числа обязаны совпасть, потому что каждое вхождение имени должно быть
внутри метки; разошлись — метка оформлена неверно.

⚠ Список на входе даёт список на выходе: пять ключей проверяются одним шагом, а
не пятью. Без этого в workflow пришлось бы заводить шаг на каждый ключ.

⚠ В базу не ходим — инструмент её не касается.
"""

import pytest

from src.tool.text.text_ import text_substr

# ⚠ Две метки: `core` — группа прогона (без неё файл не попадает ни в один
# маркер и молча не запускается, `test_marks.py`), `asyncio` — род самих тестов.
pytestmark = [pytest.mark.core, pytest.mark.asyncio]


class TestTheCount:
    async def test_limit_one_by_default(self):
        """⚠ Умолчание `1` бережёт время: обычно спрашивают «есть или нет», и
        полный счёт на длинном тексте был бы лишней работой."""
        got = await text_substr('a b a b a', 'a')

        assert got == {'found': '1', 'pos': 0, 'qty': 1}, got

    async def test_zero_counts_all(self):
        got = await text_substr('a b a b a', 'a', limit=0)

        assert got['qty'] == 3, got

    async def test_limit_stops_counting(self):
        got = await text_substr('a b a b a', 'a', limit=2)

        assert got['qty'] == 2, got

    async def test_overlaps_are_not_counted(self):
        """⚠⚠ Считаем непересекающиеся вхождения, как `str.count`: иначе «аа» в
        «ааа» дало бы два, и счёт перестал бы отвечать на вопрос «сколько раз
        это написано»."""
        got = await text_substr('ааа', 'аа', limit=0)

        assert got['qty'] == 1, got

    async def test_absent_is_zero(self):
        got = await text_substr('abc', 'z', limit=0)

        assert got == {'found': '0', 'pos': -1, 'qty': 0}, got


class TestTheList:
    """⚠ Массив на входе — массив на выходе, в том же порядке."""

    async def test_list_answers_with_list(self):
        got = await text_substr('Hi there', ['Hi', 'Bye'], limit=0)

        assert got['qty'] == 2, got
        assert [one['substr'] for one in got['list']] == ['Hi', 'Bye']
        assert got['list'][0]['found'] == '1'
        assert got['list'][1]['found'] == '0'

    async def test_the_needle_travels_back(self):
        """⚠ Сама подстрока лежит в ответе: вызывающий читает его, не сверяясь
        со своим списком по месту."""
        got = await text_substr('abc', ['b'])

        assert got['list'][0]['substr'] == 'b', got

    async def test_empty_list_is_empty(self):
        got = await text_substr('abc', [])

        assert got == {'list': [], 'qty': 0}, got


class TestTheNakedMarkCase:
    """⚠⚠⚠ Живой случай, ради которого всё и делалось."""

    async def test_naked_name_breaks_the_balance(self):
        """Имя написано без скобок — голых больше, чем в скобках."""
        text = "companion_name, the kettle clicked off — I'm [[girl_name]]."
        got = await text_substr(text, ['companion_name', '[[companion_name]]'],
                                limit=0)
        naked, marked = got['list'][0]['qty'], got['list'][1]['qty']

        assert naked != marked, f'расхождение не замечено: {naked} и {marked}'
        assert (naked, marked) == (1, 0), got

    async def test_a_proper_mark_balances(self):
        """Метка оформлена верно — числа сходятся."""
        text = "Hi [[companion_name]], I'm [[girl_name]]."
        got = await text_substr(text, ['companion_name', '[[companion_name]]'],
                                limit=0)

        assert got['list'][0]['qty'] == got['list'][1]['qty'] == 1, got

    async def test_naked_after_a_mark_is_caught(self):
        """⚠ Голое имя **после** правильной метки — числа всё равно разойдутся.

        Сравнение позиций такого не ловит: первое вхождение у обоих совпадает.
        Поэтому и нужен счёт, а не `pos`.
        """
        text = "Hi [[companion_name]], and companion_name again."
        got = await text_substr(text, ['companion_name', '[[companion_name]]'],
                                limit=0)

        assert (got['list'][0]['qty'], got['list'][1]['qty']) == (2, 1), got

    async def test_absent_mark_balances_too(self):
        """⚠ Метки нет вовсе — это не ошибка оформления: оба счёта нули."""
        text = "Hi there, I'm [[girl_name]]."
        got = await text_substr(text, ['companion_name', '[[companion_name]]'],
                                limit=0)

        assert got['list'][0]['qty'] == got['list'][1]['qty'] == 0, got

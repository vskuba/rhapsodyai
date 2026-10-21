"""Каких кусков из списка в тексте нет: множественный `text_substr`.

⚠⚠ Что здесь стережётся. Модель на вопрос «все ли обязательные вставки на
месте?» отвечает утвердительно почти всегда — сверку знак за знаком она не
делает. Замер на 601 прогоне шаблонов писем: недостача нашлась в **220**
случаях, то есть в каждом третьем. Цена промаха — письмо, задуманное разным для
каждого, уходит всем одинаковым.

⚠ Инструмент заменил предметный `text_marks_missing`, который клеил скобки сам
(`'[[%s]]' % name`) и этим знал про чужой предмет — про «метки письма». Здесь
предмета нет: ищутся куски как есть, а обрамление задаёт вызывающий.

⚠ В базу не ходим — инструмент её не касается.
"""

import pytest

from src.tool.text.text_ import text_substr_missing

# ⚠ Две метки: `core` — группа прогона (без неё файл не попадает ни в один
# маркер и молча не запускается, `test_marks.py`), `asyncio` — род самих тестов.
pytestmark = [pytest.mark.core, pytest.mark.asyncio]


class TestItFindsWhatIsMissing:
    async def test_missing_is_listed(self):
        got = await text_substr_missing('Hi [[name]], nice to meet you',
                                        '[[name]],[[city]]')

        assert got == {'list': ['[[city]]'], 'qty': 1, 'str': '[[city]]'}, got

    async def test_all_present_is_empty(self):
        got = await text_substr_missing('Hi [[name]] from [[city]]',
                                        '[[name]],[[city]]')

        assert got == {'list': [], 'qty': 0, 'str': ''}, got

    async def test_order_follows_the_list(self):
        """⚠ Порядок — списка, а не текста: по нему вызывающий и читает ответ."""
        got = await text_substr_missing('nothing here', '[[b]],[[a]]')

        assert got['list'] == ['[[b]]', '[[a]]'], got


class TestTheEdges:
    async def test_empty_list_checks_nothing(self):
        """⚠ Пусто — проверять нечего, а не «всё пропало»."""
        got = await text_substr_missing('Hi there', '')

        assert got == {'list': [], 'qty': 0, 'str': ''}, got

    async def test_blank_parts_are_dropped(self):
        """⚠⚠ Пустые части списка отбрасываются: `'a,,b'` — это два куска, а не
        три. Иначе пустая часть считалась бы недостающей всегда — `'' not in
        text` ложно, но в список она попала бы как пустая строка."""
        got = await text_substr_missing('has a', 'a,,b')

        assert got['list'] == ['b'], got

    async def test_duplicates_are_reported_once(self):
        got = await text_substr_missing('nothing', 'a,a,b')

        assert got['list'] == ['a', 'b'], got

    async def test_other_separator(self):
        """⚠ Разделитель задаёт вызывающий — и он же склеивает ответ."""
        got = await text_substr_missing('has one', 'one|two', separator='|')

        assert got == {'list': ['two'], 'qty': 1, 'str': 'two'}, got


class TestItKnowsNothingAboutMarks:
    async def test_it_works_on_plain_words(self):
        """⚠ Про скобки и метки инструмент не знает ничего."""
        got = await text_substr_missing('the quick fox', 'quick,lazy')

        assert got['list'] == ['lazy'], got

    async def test_ignore_case(self):
        got = await text_substr_missing('The Quick Fox', 'quick', ignore_case=True)

        assert got['list'] == [], got

    async def test_case_matters_by_default(self):
        """⚠ По умолчанию регистр **значим**, как и у `text_substr`: вставка
        `[[Name]]` и `[[name]]` — разные вставки."""
        got = await text_substr_missing('The Quick Fox', 'quick')

        assert got['list'] == ['quick'], got

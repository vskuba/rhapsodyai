"""Мерка длины против вилки: что считается попаданием и что — поломкой настройки.

⚠⚠ Что здесь стережётся. Инструмент заменяет собой оценку длины, которую делала
LLM и делала плохо: в живых отказах судьи писем есть и «exceeds the allowed
20–30» о письме внутри вилки, и «only 20 words… too short» при вилке ровно
«20–30». Цена промаха — круг переписывания с вызовом модели, поэтому мерка
обязана быть однозначной, а её углы — зафиксированы.

⚠ Второе: вилки жребия набраны **коротким тире**, а не дефисом. Инструмент,
знающий один дефис, не разобрал бы ни одной из них и пропускал бы любую длину,
выглядя при этом рабочим.

⚠ В базу не ходим — инструмент её не касается; фикстура пула не нужна.
"""
import pytest

from src.tool.string.string_ import string_length_range_check

pytestmark = pytest.mark.core


class TestWordsAreTheDefault:
    async def test_inside_the_range(self):
        got = await string_length_range_check('one two three', '2-4')

        assert got['fits'] == 1
        assert got['length'] == 3
        assert got['why'] == ''

    async def test_shorter_than_asked(self):
        got = await string_length_range_check('one two three', '5-7')

        assert got['fits'] == 0
        assert got['length'] == 3
        assert '3 words' in got['why'] and '5-7' in got['why']

    async def test_longer_than_asked(self):
        got = await string_length_range_check('one two three four five', '2-3')

        assert got['fits'] == 0
        assert got['length'] == 5

    async def test_line_breaks_do_not_glue_words(self):
        """Абзацы письма не должны слипаться в одно слово при счёте."""
        got = await string_length_range_check('one two\n\nthree four', '4-4')

        assert got['fits'] == 1
        assert got['length'] == 4


class TestEdgesAreIncluded:
    @pytest.mark.parametrize('text, given', [
        ('one two', '2-4'),
        ('one two three four', '2-4'),
    ])
    async def test_both_ends_fit(self, text, given):
        """⚠ «2-4» — это и ровно 2, и ровно 4: иначе вилка молча сужается."""
        got = await string_length_range_check(text, given)

        assert got['fits'] == 1, got['why']


class TestRangeSpelling:
    @pytest.mark.parametrize('given', ['20-30', '20–30', '20 – 30', '20—30',
                                       'approximately 20-30 words'])
    async def test_dashes_and_words_around(self, given):
        """⚠⚠ Короткое тире обязано читаться: именно им набраны вилки жребия."""
        got = await string_length_range_check(' '.join(['w'] * 25), given)

        assert got['fits'] == 1, f'{given}: {got["why"]}'

    async def test_single_number_is_the_upper_bound(self):
        """Одно число читается как «не больше», а не как точная длина."""
        assert (await string_length_range_check('one two', '5'))['fits'] == 1
        assert (await string_length_range_check(' '.join(['w'] * 6), '5'))['fits'] == 0


class TestBrokenSettingDoesNotReject:
    @pytest.mark.parametrize('given', ['', '   ', 'слов побольше', None, '30-20'])
    async def test_unreadable_range_passes_with_a_reason(self, given):
        """⚠⚠ Поломку настройки нельзя превращать в вечное переписывание.

        Верни инструмент `fits = 0`, workflow уходил бы на повтор бесконечно, и
        каждый заход стоил бы вызова модели. Причина при этом обязана быть
        видна — иначе молчаливый пропуск не отличить от исправной работы.
        """
        got = await string_length_range_check('one two three', given)

        assert got['fits'] == 1
        assert got['why'], 'причина пропуска обязана быть названа'

    async def test_reversed_range_is_not_silently_fixed(self):
        """Перевёрнутую вилку не чиним перестановкой: опечатку надо увидеть."""
        got = await string_length_range_check('one two three', '30-20')

        assert got['fits'] == 1
        assert 'not readable' in got['why']


class TestEmptyTextIsMeasurable:
    async def test_empty_text_misses_the_range(self):
        """⚠ Пустота — честный ноль, а не поломка настройки."""
        got = await string_length_range_check('', '20-30')

        assert got['fits'] == 0
        assert got['length'] == 0

    async def test_empty_text_fits_a_range_starting_at_zero(self):
        got = await string_length_range_check('', '30')

        assert got['fits'] == 1


class TestOtherUnits:
    async def test_chars(self):
        got = await string_length_range_check('  abcde  ', '5-5', 'chars')

        assert got['fits'] == 1
        assert got['length'] == 5

    async def test_paragraphs_count_non_empty_lines(self):
        """⚠ Разделитель абзацев бросается жребием: «\\n» и «\\n\\n» дают одно число."""
        single = await string_length_range_check('a\nb\nc', '3-3', 'paragraphs')
        double = await string_length_range_check('a\n\nb\n\nc', '3-3', 'paragraphs')

        assert single['length'] == double['length'] == 3
        assert single['fits'] == double['fits'] == 1

    async def test_unknown_unit_falls_back_to_words(self):
        """Неизвестная единица — слова, как и умолчание: шаг не должен падать."""
        got = await string_length_range_check('one two three', '3-3', 'sentences')

        assert got['length'] == 3
        assert got['fits'] == 1


class TestArrivesFromWorkflow:
    async def test_arguments_come_as_text(self):
        """⚠ Доводы приезжают workflow-переменными, то есть строками."""
        got = await string_length_range_check(
            text=' '.join(['w'] * 25), length_range='20-30', unit='words')

        assert got['fits'] == 1

    async def test_why_is_english_with_numbers(self):
        """⚠⚠ Претензия едет в промпт генератора: английская и с числами.

        Русская вставка в английском промпте — повод ответить не на том языке,
        а «too short» без чисел модель исполняет как угодно.
        """
        got = await string_length_range_check(' '.join(['w'] * 52), '20-30')

        assert got['fits'] == 0
        assert '52 words' in got['why'] and '20-30' in got['why']
        assert got['why'].isascii(), 'в промпт едет английский текст'

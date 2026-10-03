"""Текущее время словами: часовой пояс и язык ответа.

⚠ Текст уезжает **в промпт**, а не на экран: модели нужно знать, что сейчас
поздний вечер пятницы, чтобы не писать «доброе утро». Поэтому стережётся не
формат как таковой, а то, из-за чего промпт портится, — чужой язык в ответе и
потерянное смещение пояса.

⚠ Сравнивать с «сейчас» точным временем нельзя: между вызовом и проверкой
проходят миллисекунды, а на границе часа — и целый час. Проверяем приметы
языка, смещение и устойчивость к мусору.
"""
import pytest

from src.tool.datetime_.datetime_ import (DATETIME_DAY_PARTS,
                                          DATETIME_LANGUAGES,
                                          datetime_current_get)

pytestmark = pytest.mark.ai

# Примета языка в ответе: слово, которого нет в двух других.
#
# ⚠ Не месяц и не день недели — они меняются от прогона к прогону, и тест
# краснел бы раз в неделю. Эти слова стоят в шаблоне и есть в ответе всегда.
LANGUAGE_MARKS = {
    'en': 'Today is',
    'ru': 'Сегодня',
    'uk': 'Сьогодні',
}


class TestLanguage:
    @pytest.mark.parametrize('language, mark', sorted(LANGUAGE_MARKS.items()))
    async def test_language_is_respected(self, language, mark):
        """Каждый из трёх языков отвечает на себе."""
        got = await datetime_current_get('+3', language)

        assert mark in got

    @pytest.mark.parametrize('language, mark', sorted(LANGUAGE_MARKS.items()))
    async def test_no_other_language_leaks(self, language, mark):
        """⚠ В ответе ровно один язык.

        Самая вероятная поломка правки — забытая строка таблицы: шаблон на
        одном языке, месяц на другом. Для промпта это хуже, чем чужой язык
        целиком: модель получает смесь и отвечает смесью.
        """
        got = await datetime_current_get('+3', language)
        others = [other for code, other in LANGUAGE_MARKS.items()
                  if code != language]

        assert all(other not in got for other in others)

    @pytest.mark.parametrize('language', ['RU', 'Uk', ' ru '])
    async def test_case_and_spaces_do_not_matter(self, language):
        """Язык приходит из workflow-переменной — регистр и пробелы бывают."""
        got = await datetime_current_get('+3', language)

        assert LANGUAGE_MARKS[language.strip().lower()] in got

    @pytest.mark.parametrize('language', ['fr', '', 'bogus', None])
    async def test_unknown_language_falls_back_to_english(self, language):
        """⚠ Незнакомый язык — английский, а не отказ и не пустая строка.

        Шаг workflow не должен падать из-за опечатки в переменной: время в
        промпте полезнее отсутствия времени.
        """
        got = await datetime_current_get('+3', language)

        assert LANGUAGE_MARKS['en'] in got

    async def test_default_is_english(self):
        """Умолчание — английский: так объявлено в сигнатуре."""
        got = await datetime_current_get('+3')

        assert LANGUAGE_MARKS['en'] in got


class TestTimezone:
    @pytest.mark.parametrize('given, expected', [
        ('0', 'UTC+0'),
        ('+3', 'UTC+3'),
        ('-5', 'UTC-5'),
        ('UTC+2', 'UTC+2'),
        ('UTC-3', 'UTC-3'),
    ])
    async def test_offset_is_shown(self, given, expected):
        """Смещение разбирается во всех принятых формах и видно в ответе."""
        got = await datetime_current_get(given, 'en')

        assert expected in got

    async def test_garbage_offset_is_utc(self):
        """⚠ Мусор в поясе — UTC+0, а не падение: шаг обязан доработать."""
        got = await datetime_current_get('abc', 'ru')

        assert 'UTC+0' in got
        assert LANGUAGE_MARKS['ru'] in got


class TestTables:
    """Таблицы языков обязаны быть одной длины — иначе слова разъедутся."""

    @pytest.mark.parametrize('language', sorted(DATETIME_LANGUAGES))
    def test_tables_match(self, language):
        words = DATETIME_LANGUAGES[language]

        assert len(words['days']) == 7
        assert len(words['months']) == 12
        assert len(words['parts']) == len(DATETIME_DAY_PARTS), (
            'слов времени суток столько же, сколько границ часов, иначе '
            'описание начнёт отвечать не про тот час')

    @pytest.mark.parametrize('language', sorted(DATETIME_LANGUAGES))
    def test_template_keys_are_filled(self, language):
        """В шаблоне заполняются все подстановки, и лишних в нём нет."""
        words = DATETIME_LANGUAGES[language]

        filled = words['template'].format(
            day_of_week='D', day=1, month='M', year=2026, tz='UTC+0',
            time='00:00:00', part='P')

        assert '{' not in filled

    def test_every_language_has_its_mark(self):
        """⚠ Новый язык в таблице — новая примета здесь, иначе он не проверен.

        Без этого четвёртый язык добавили бы, а тесты остались бы про три — и
        молчали бы про него навсегда.
        """
        assert set(DATETIME_LANGUAGES) == set(LANGUAGE_MARKS)

"""Стоит ли вставка отдельным абзацем: универсальный предикат вместо предметного.

⚠⚠ Что здесь стережётся. Значение, которое само является предложением, обязано
стоять своим абзацем: встроенное в чужую фразу, оно даёт «What are What kind of
hobbies do you enjoy??». Правило простое, но LLM понимает его через раз — замер
на 506 прогонах шаблонов писем: модель ставила такую вставку внутрь фразы в 90
случаях, почти в каждом пятом, **при том что промпт просил обратного**.

⚠ Предикат заменил предметный `text_marks_inline`, который знал про «метки» и
принимал их списком. Этот не знает ничего: две строки на входе. Зовущий сам
решает, что именно обязано стоять абзацем, — и в workflow это видно в графе,
а не приезжает данными со стороны.

⚠⚠ Ответов три, а не один: «нет вовсе» и «есть, но внутри фразы» — разные беды
с разным лечением, и сливать их в «не стоит отдельно» нельзя.

⚠ В базу не ходим — инструмент её не касается.
"""

import pytest

from src.tool.text.text_ import text_paragraph_has

# ⚠ Две метки: `core` — группа прогона (без неё файл не попадает ни в один
# маркер и молча не запускается, `test_marks.py`), `asyncio` — род самих тестов.
pytestmark = [pytest.mark.core, pytest.mark.asyncio]


class TestTheMarkStandsAlone:
    async def test_alone_is_alone(self):
        """Строка из одной вставки — это отдельный абзац."""
        got = await text_paragraph_has('Hi,\n\n[[q]]\n\nBye', '[[q]]')

        assert got == {'found': 1, 'alone': 1, 'inline': 0}, got

    async def test_spaces_around_do_not_spoil_it(self):
        """⚠ Пробелы вокруг — всё ещё отдельный абзац: их ставит вёрстка текста,
        а не автор."""
        got = await text_paragraph_has('Hi,\n\n   [[q]]   \n\nBye', '[[q]]')

        assert got['alone'] == 1, got


class TestTheMarkIsInline:
    async def test_inside_a_phrase_is_caught(self):
        """Ради этого всё и затевалось."""
        got = await text_paragraph_has('Hi,\n\nWhat are [[q]]?\n\nBye', '[[q]]')

        assert got == {'found': 1, 'alone': 0, 'inline': 1}, got

    async def test_punctuation_next_to_it_counts_as_inline(self):
        """⚠⚠ Знак препинания рядом — **не** отдельный абзац: значение уже несёт
        свой знак, и `[[q]]?` даст два вопросительных подряд."""
        got = await text_paragraph_has('Hi,\n\n[[q]]?\n\nBye', '[[q]]')

        assert got['inline'] == 1, got


class TestTheMarkIsAbsent:
    async def test_absent_is_not_inline(self):
        """⚠⚠ «Нет вовсе» — это не «встроена»: вставку чинят вписыванием, а не
        переносом. Слей мы их, причина отказа звала бы вынести в абзац то, чего
        в тексте нет.
        """
        got = await text_paragraph_has('Hi,\n\nBye', '[[q]]')

        assert got == {'found': 0, 'alone': 0, 'inline': 0}, got

    async def test_empty_needle_finds_nothing(self):
        """⚠⚠ Пустой довод — «искать нечего», а не «нашлось везде».

        `'' in text` истинно всегда, и без отдельной ветки пустая вставка
        отвечала бы «всё в порядке» на любом тексте — то есть проверка молча
        перестала бы работать, выглядя рабочей.
        """
        got = await text_paragraph_has('Hi,\n\nBye', '')

        assert got == {'found': 0, 'alone': 0, 'inline': 0}, got


class TestItKnowsNothingAboutMarks:
    async def test_it_works_on_a_plain_word(self):
        """⚠ Предикат универсален: ни про `[[…]]`, ни про письма он не знает."""
        got = await text_paragraph_has('one\n\nhello\n\ntwo', 'hello')

        assert got == {'found': 1, 'alone': 1, 'inline': 0}, got

    async def test_a_word_inside_a_sentence_is_inline(self):
        got = await text_paragraph_has('one\n\nsay hello there\n\ntwo', 'hello')

        assert got['inline'] == 1, got

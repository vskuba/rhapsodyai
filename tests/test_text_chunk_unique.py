"""`text_chunk_unique` — убрать повторы из текста, разрезанного разделителем.

Повод измерен на живом. За сутки в пачках инвайтов (`dating_invite_write`,
215 прогонов, 3771 реплика) **47% прогонов содержали точный дубликат**, лишних
реплик 203 — пять процентов всего написанного.

Рождает их модель: промпт правилом №1 просит «строки не должны походить друг на
друга», и она всё равно пишет одинаковые — в одном заходе из девятнадцати реплик
попадалось до трёх повторов. Судья-LLM их не отсеивает, потому что отвечает на
другой вопрос: он называет номера годных строк, а сверять названные между собой
его никто не просил. Разбор прогона #161884: на втором витке судья оставил
номера `4,6,10,11,13,14,15`, и под двумя из них лежала одна и та же реплика.

⚠⚠ Поэтому сверку делает код. Точное совпадение строк — признак однозначный, и
модель для него не нужна: «однозначный признак считает код, решение по нему
принимает переход workflow» (`tools.md`).

⚠ Перефразированный повтор здесь не ловится намеренно: это другая задача с
другой ценой (нечёткое сравнение, порог, ошибки в обе стороны).
"""
import pytest

from src.tool.text.text_ import text_chunk_unique

pytestmark = [pytest.mark.core, pytest.mark.asyncio]


class TestTheRepeatIsDropped:
    """Повторное вхождение выбрасывается, остальное цело."""

    async def test_a_repeat_in_the_middle_goes(self):
        got = await text_chunk_unique('да---нет---да', separator='---')

        assert got['str'] == 'да---нет'
        assert got['qty'] == 2
        assert got['dropped'] == 1

    async def test_clean_text_is_untouched(self):
        """⚠ Чистому тексту функция не должна делать ничего."""
        got = await text_chunk_unique('a,b,c', separator=',')

        assert got['str'] == 'a,b,c'
        assert got['dropped'] == 0

    async def test_three_of_a_kind_leave_one(self):
        got = await text_chunk_unique('x|x|x', separator='|')

        assert got['list'] == ['x']
        assert got['dropped'] == 2


class TestTheOrderSurvives:
    """⚠⚠⚠ Остаётся ПЕРВОЕ вхождение, порядок прочих не меняется.

    Иначе текст перетасовался бы: у нумерованного списка сбилась бы нумерация, а
    у пачки реплик — соответствие «строка N написана приёмом N», на котором
    держится весь промпт инвайтов.
    """

    async def test_the_first_one_stays(self):
        got = await text_chunk_unique('первый,второй,первый,третий', separator=',')

        assert got['list'] == ['первый', 'второй', 'третий']

    async def test_nothing_is_resorted(self):
        got = await text_chunk_unique('в,б,а,в', separator=',')

        assert got['list'] == ['в', 'б', 'а'], \
            'список пересортирован — нумерация в промпте разъедется'


class TestTheCaseIsAskedFor:
    """Регистр различается, пока не попросили иначе."""

    async def test_by_default_case_matters(self):
        got = await text_chunk_unique('Да,да', separator=',')

        assert got['dropped'] == 0, 'регистр схлопнут без спроса'

    async def test_ignore_case_merges_them(self):
        got = await text_chunk_unique('Да,да', separator=',', ignore_case=True)

        assert got['qty'] == 1
        assert got['dropped'] == 1

    async def test_the_kept_text_keeps_its_own_spelling(self):
        """⚠ Сравнение без регистра не меняет САМ текст: остаётся как было."""
        got = await text_chunk_unique('Да,ДА,да', separator=',', ignore_case=True)

        assert got['str'] == 'Да', f'написание первого вхождения потеряно: {got["str"]!r}'


class TestItCutsLikeItsNeighbour:
    """⚠⚠ Режет так же, как `text_split`: края обрезаны, пустые отброшены.

    Инструменты, режущие один и тот же текст, обязаны резать одинаково —
    разойдись они, их `qty` перестали бы сходиться в одном workflow.
    """

    async def test_empty_parts_are_dropped(self):
        got = await text_chunk_unique('a,,b,,a', separator=',')

        assert got['list'] == ['a', 'b']

    async def test_edges_are_trimmed(self):
        got = await text_chunk_unique(' a , a , b ', separator=',')

        assert got['list'] == ['a', 'b'], 'пробелы по краям сделали повтор разным'

    async def test_a_multiline_separator_works(self):
        """⚠ Разделителем бывает не только знак: у пачки реплик это `\\n---\\n`."""
        got = await text_chunk_unique('A\n---\nB\n---\nA', separator='\n---\n')

        assert got['str'] == 'A\n---\nB'
        assert got['dropped'] == 1


class TestTheEdgesAreSafe:
    """Пустота и отсутствие разделителя не роняют инструмент."""

    async def test_empty_text_gives_empty_answer(self):
        got = await text_chunk_unique('', separator=',')

        assert got == {'str': '', 'list': [], 'qty': 0, 'dropped': 0}

    async def test_none_is_treated_as_empty(self):
        """⚠ Переменная workflow бывает пустой — ронять на этом нельзя."""
        got = await text_chunk_unique(None, separator=',')

        assert got['qty'] == 0

    async def test_without_a_separator_the_text_is_one_item(self):
        """⚠ Резать нечем — значит элемент один, а не ноль."""
        got = await text_chunk_unique('один текст', separator='')

        assert got['list'] == ['один текст']
        assert got['dropped'] == 0


class TestTheCountsAddUp:
    """`qty` и `dropped` вместе отвечают «сколько было» — на них стоит переход."""

    async def test_kept_plus_dropped_is_what_came_in(self):
        got = await text_chunk_unique('a,b,a,c,b', separator=',')

        assert got['qty'] + got['dropped'] == 5

    async def test_qty_matches_the_list(self):
        got = await text_chunk_unique('a,b,a', separator=',')

        assert got['qty'] == len(got['list'])

    async def test_dropped_is_zero_when_nothing_repeats(self):
        """⚠ Ноль — законный ответ, и на него ставят развилку «чинить не надо»."""
        got = await text_chunk_unique('a,b,c', separator=',')

        assert got['dropped'] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

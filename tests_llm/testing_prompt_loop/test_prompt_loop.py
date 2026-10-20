"""Цикл `[<for k,v in …>]` и присваивание `[<set …>]` в промпте.

⚠⚠ Фича движка, а не боевого сценария. Заведена из-за того, что в промпте
инвайтов стояло `%dice_invite_angle%` — одна метка, за которой пряталась
нумерованная простыня, собранная инструментом. Ни того, что это список, ни
откуда взялась нумерация, человек в промпте не видел: её делал код жребия, за
три файла оттуда.

Два шага: «Список» строит текст циклом и кладёт его в переменную, «Финал»
показывает остальные приёмы разом. Данные меняет тест, текст шагов не трогает
никто — поэтому сюита не краснеет от правки промпта.

## ⚠⚠ Что здесь стережётся в первую очередь

**Область видимости `[<set …>]`.** Присваивание живёт только внутри своего
текстового поля и не доживает до следующего шага. Протеки оно в прогон — имя
пришлось бы показывать в списке переменных страницы, а случайное совпадение со
счётчиком цикла молча перезаписало бы чужое значение.
"""
import pytest

from tests_llm.testing_prompt_loop.conftest import AGENT, STEP_FINAL, STEP_LIST

pytestmark = pytest.mark.llm

ITEMS = '["альфа", "бета", "гамма"]'
PAIRS = '{"chat": "беседа", "mail": "письмо"}'
TEXT = 'первая\nвторая'


def _probe(**over):
    """Полный набор входов; тест меняет только то, что проверяет."""
    return {'loop_items': ITEMS, 'loop_pairs': PAIRS, 'loop_text': TEXT,
            'loop_count': '3', 'loop_word': 'голова', **over}


class TestTheLoopWalksTheList:
    """Цикл по списку: тело повторяется на каждый элемент."""

    async def test_every_item_gets_its_line(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        for one in ('альфа', 'бета', 'гамма'):
            assert one in said, f'элемент «{one}» не попал в промпт: {said!r}.{got}'

    async def test_the_counter_numbers_the_lines(self, ask):
        """⚠⚠ Главный случай: нумерация задаётся в промпте, а не в коде.

        `[<set k = k + 1>]` превращает счёт с нуля в счёт с единицы прямо там,
        где список и читают.
        """
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        assert '1. альфа' in said, f'нумерация не сработала: {said!r}.{got}'
        assert '2. бета' in said, f'второй номер не тот: {said!r}.{got}'
        assert '3. гамма' in said, f'третий номер не тот: {said!r}.{got}'

    async def test_the_counter_stays_whole(self, ask):
        """⚠ Номер целым, а не «1.0»: арифметика считает во float."""
        got = await ask(AGENT, 'probe', variables=_probe())

        assert '1.0' not in got.prompt_of(STEP_FINAL), \
            f'номер показан дробью.{got}'

    async def test_an_empty_list_leaves_nothing(self, ask):
        """⚠ Пустой список — законный исход: повторять нечего, блок исчезает."""
        got = await ask(AGENT, 'probe', variables=_probe(loop_items='[]'))

        said = got.prompt_of(STEP_FINAL)

        assert 'альфа' not in said, f'пустой список что-то напечатал: {said!r}.{got}'
        assert '[<for' not in said, f'разметка цикла осталась: {said!r}.{got}'


class TestTheKeyStartsAtZeroUnlessAsked:
    """⚠⚠⚠ Ключ идёт с НУЛЯ, как во всех языках; `start=` смещает нумерацию.

    Умолчание менять нельзя: человек, знающий любой язык, ждёт нуля. Но промпт
    почти всегда просит «line 1», и писать ради этого `[<set k = k + 1>]` в
    каждом цикле — обряд. Поэтому смещение живёт в заголовке цикла.
    """

    async def test_without_start_the_key_is_zero_based(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        assert 'пары вложенно' in said, f'промпт не собрался.{got}'
        assert 'первый: альфа' in said, \
            f'условие `k == 0` не сработало — ключ не с нуля: {said!r}.{got}'

    async def test_start_shifts_the_numbering(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        assert 'со старта: 1:альфа 2:бета 3:гамма' in said, \
            f'`start=1` не сместил нумерацию: {said!r}.{got}'

    async def test_start_may_be_a_variable(self, ask):
        """⚠ Смещение переменной, а не только числом — как доли у жребия."""
        got = await ask(AGENT, 'probe', variables=_probe(loop_count='7'))

        said = got.prompt_of(STEP_FINAL)

        assert 'старт из переменной: 7:альфа 8:бета 9:гамма' in said, \
            f'`start=` из переменной не сработал: {said!r}.{got}'


class TestTheLoopWalksOtherShapes:
    """По чему ещё умеет ходить цикл: словарь, текст строками, одно имя."""

    async def test_a_dictionary_gives_key_and_value(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        assert 'chat=беседа' in said, f'пара словаря не собралась: {said!r}.{got}'
        assert 'mail=письмо' in said, f'вторая пара не собралась: {said!r}.{got}'

    async def test_plain_text_walks_line_by_line(self, ask):
        """⚠⚠ Текст строками — ради того, с чего всё начиналось.

        Инструменты отдают серию готовой простынёй, и цикл обязан работать по
        тому, что лежит в переменной сегодня, а не после их переделки.
        """
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        assert '<первая>' in said, f'строка текста не стала элементом: {said!r}.{got}'
        assert '<вторая>' in said, f'вторая строка не стала элементом: {said!r}.{got}'

    async def test_one_name_binds_the_value(self, ask):
        """⚠ `[<for v in …>]` — одно имя означает ЗНАЧЕНИЕ, как в Python."""
        got = await ask(AGENT, 'probe', variables=_probe(loop_text='одна'))

        assert '<одна>' in got.prompt_of(STEP_FINAL), \
            f'одно имя связалось не со значением.{got}'


class TestTheAssignmentComputes:
    """`[<set …>]`: арифметика и склейка текста."""

    async def test_arithmetic_respects_precedence(self, ask):
        """⚠⚠ Старшинство настоящее: `3 * 2 + 1` — семь, а не девять.

        Слева направо дало бы девять, и человек споткнулся бы об это молча:
        ответ-то число.
        """
        got = await ask(AGENT, 'probe', variables=_probe(loop_count='3'))

        assert 'счёт: 7' in got.prompt_of(STEP_FINAL), \
            f'выражение посчитано не по старшинству.{got}'

    async def test_text_is_glued_by_plus(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe(loop_word='голова'))

        assert 'склейка: голова-хвост' in got.prompt_of(STEP_FINAL), \
            f'склейка текста не вышла.{got}'

    async def test_the_tag_leaves_no_trace(self, ask):
        """⚠ Тег не оставляет после себя ни пробела, ни перевода строки."""
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        assert '[<set' not in said, f'разметка присваивания осталась: {said!r}.{got}'


class TestTheAssignmentStaysInItsField:
    """⚠⚠⚠ Область видимости: `[<set …>]` не выходит за своё текстовое поле.

    Шаг «Список» присваивает `loop_leak` в тексте одной из своих переменных.
    Шаг «Финал» спрашивает, видно ли её. Ответ обязан быть «НЕТ».

    Протеки присваивание в прогон — имя пришлось бы показывать в списке
    переменных страницы, а совпадение имени со счётчиком соседнего цикла молча
    перезаписало бы чужое значение.
    """

    async def test_the_name_does_not_reach_the_next_step(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        assert 'утечка: НЕТ' in said, \
            f'присваивание пережило свой шаг: {said!r}.{got}'

    async def test_the_name_is_not_in_the_run_variables(self, ask):
        """⚠ И в переменных прогона его тоже нет — ни под каким видом."""
        got = await ask(AGENT, 'probe', variables=_probe())

        assert 'loop_leak' not in got.vars, \
            f'имя из присваивания попало в переменные прогона: {got.vars}.{got}'

    async def test_the_step_that_assigned_still_worked(self, ask):
        """⚠ Изоляция не означает «шаг не отработал»: своё дело он сделал."""
        got = await ask(AGENT, 'probe', variables=_probe())

        assert got.ran(STEP_LIST), f'шаг присваивания не отработал.{got}'
        assert '1. альфа' in got.prompt_of(STEP_FINAL), \
            f'переменная, построенная циклом, до финала не доехала.{got}'


class TestTheLoopCarriesItsNamesInside:
    """Связанные имена видны внутри тела — и вложенным блокам тоже."""

    async def test_a_condition_inside_sees_the_bound_name(self, ask):
        """⚠⚠ Потому циклы и разворачиваются раньше условий.

        Возьмись условия первыми, `[<if k == 0>]` проверяло бы переменную,
        которой нет ни у кого, и блок достался бы сторожу на ровном месте.
        """
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        assert 'первый: альфа' in said, \
            f'условие внутри цикла не увидело счётчик: {said!r}.{got}'
        assert 'первый: альфабета' not in said, \
            f'условие сработало на каждом витке: {said!r}.{got}'


    async def test_a_nested_loop_sees_both_names(self, ask):
        """⚠ Внутренний цикл видит и своё имя, и имя внешнего."""
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        for pair in ('альфа/chat', 'альфа/mail', 'гамма/mail'):
            assert pair in said, \
                f'вложенный цикл не дал пары «{pair}»: {said!r}.{got}'


class TestTheAssignmentMayShadowAnInput:
    """⚠⚠ Присваивание поверх ВХОДЯЩЕЙ переменной — та же область видимости.

    Внутри своего поля видно новое значение, снаружи — прежнее. Иначе промпт
    молча переписывал бы вход прогона, и следующий шаг получал бы не то, что
    ему передали.
    """

    async def test_the_new_value_is_visible_in_place(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe(loop_count='3'))

        assert 'перекрыто: 300' in got.prompt_of(STEP_FINAL), \
            f'перекрытие не сработало внутри поля.{got}'

    async def test_the_input_itself_stays_intact(self, ask):
        """⚠ Входящая переменная прогона осталась прежней — её не переписали.

        Проверяется соседней строкой того же промпта: `счёт` считается от
        `loop_count` ВЫШЕ перекрытия и обязан остаться семёркой (3 * 2 + 1).
        Достань присваивание до словаря прогона — вышло бы 601.

        ⚠⚠ Смотрим на промпт, а не на `vars`: трасса пишет **изменённые**
        переменные, и входящей там нет вовсе ни при каком исходе. Тест по
        `vars` зеленел бы и тогда, когда перекрытие вправду протекло.
        """
        got = await ask(AGENT, 'probe', variables=_probe(loop_count='3'))

        said = got.prompt_of(STEP_FINAL)

        assert 'счёт: 7' in said, \
            f'перекрытие ниже по тексту достало до строки выше: {said!r}.{got}'
        assert str(got.vars.get('loop_count', '3')) == '3', \
            f'перекрытие ушло в переменные прогона: {got.vars.get("loop_count")!r}.{got}'


class TestTheCounterMayShareAName:
    """⚠⚠⚠ Счётчик, названный как живая переменная, ничего не портит.

    Главный страх при вводе приёма: человек пишет `[<for k,v in …>]`, а `v` уже
    занята переменной прогона — и цикл молча её перезаписывает. Здесь счётчик
    назван именем входящей `loop_word` нарочно.

    Внутри цикла видно элемент, после цикла — исходное значение. Словарь
    прогона не трогается вовсе.
    """

    async def test_inside_the_loop_the_counter_wins(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe(loop_word='голова'))

        said = got.prompt_of(STEP_FINAL)

        assert 'затенение: альфа бета гамма' in said, \
            f'счётчик не затенил переменную внутри цикла: {said!r}.{got}'

    async def test_after_the_loop_the_variable_is_back(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe(loop_word='голова'))

        said = got.prompt_of(STEP_FINAL)

        assert 'после: голова' in said, \
            f'переменная не вернулась после цикла: {said!r}.{got}'

    async def test_the_rest_of_the_prompt_is_untouched(self, ask):
        """⚠ И строка выше цикла тоже цела — затенение не достаёт назад."""
        got = await ask(AGENT, 'probe', variables=_probe(loop_word='голова'))

        assert 'склейка: голова-хвост' in got.prompt_of(STEP_FINAL), \
            f'затенение достало до строки выше по тексту.{got}'


class TestNothingLeaksIntoTheModel:
    """Сторож: ни метки, ни разметки в готовом промпте."""

    async def test_no_markup_survives(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe())

        said = got.prompt_of(STEP_FINAL)

        for one in ('[<for', '[<endfor>]', '[<set', '[<if', '[<endif>]'):
            assert one not in said, f'разметка «{one}» уехала в модель: {said!r}.{got}'

    async def test_no_marks_survive(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe())

        assert '%' not in got.prompt_of(STEP_FINAL), \
            f'в промпте осталась метка.{got}'

    async def test_the_run_reaches_the_end(self, ask):
        got = await ask(AGENT, 'probe', variables=_probe())

        assert got.ran(STEP_FINAL), f'финальный шаг не отработал.{got}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

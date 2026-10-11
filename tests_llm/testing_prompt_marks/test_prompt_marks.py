"""Подстановка в промпт: метки `%var%` и секции `[<if>]`.

⚠⚠ Фича движка. Раньше её проверяли через «секции жребия» боевого `dating_talk`
и промпты писем — тесты падали от каждой правки текста, хотя подстановка
работала.

Здесь один шаг: он показывает метку и две взаимоисключающие секции.
"""
import pytest

from tests_llm.testing_prompt_marks.conftest import AGENT, STEP_FINAL

pytestmark = pytest.mark.llm


class TestTheMarkIsSubstituted:
    """Значение переменной попадает в текст вместо метки."""

    async def test_the_value_replaces_the_mark(self, ask):
        got = await ask(AGENT, 'probe', variables={'mark_word': 'zz-mark',
                                                   'mark_section': ''})

        said = got.prompt_of(STEP_FINAL)

        assert 'слово=zz-mark' in said, \
            f'метка не заменилась значением: {said!r}.{got}'

    async def test_nothing_is_left_unsubstituted(self, ask):
        """⚠⚠ Незаменённая метка уехала бы в модель словами задания.

        Движок такое ловит сторожем и роняет прогон, но проверить это надо и
        здесь: сторож стоит не на всех родах шагов.
        """
        got = await ask(AGENT, 'probe', variables={'mark_word': 'zz-mark',
                                                   'mark_section': 'zz-sec'})

        said = got.prompt_of(STEP_FINAL)

        assert '%' not in said, f'в промпте осталась метка: {said!r}.{got}'


class TestTheSectionOpensAndCloses:
    """Секция `[<if>]` показывается по значению и прячется без него."""

    async def test_a_filled_variable_opens_its_section(self, ask):
        got = await ask(AGENT, 'probe', variables={'mark_word': 'zz',
                                                   'mark_section': 'zz-sec'})

        said = got.prompt_of(STEP_FINAL)

        assert 'секция=zz-sec' in said, f'секция не открылась: {said!r}.{got}'
        assert 'секции нет' not in said, f'открылись обе секции разом.{got}'

    async def test_an_empty_variable_hides_its_section(self, ask):
        """⚠ Пустая переменная прячет свой кусок, а не показывает пустоту.

        Иначе промпт уедет с «секция=» — и модель сочтёт пустоту частью
        задания.
        """
        got = await ask(AGENT, 'probe', variables={'mark_word': 'zz',
                                                   'mark_section': ''})

        said = got.prompt_of(STEP_FINAL)

        assert 'секции нет' in said, f'ветка отрицания не сработала: {said!r}.{got}'
        assert 'секция=' not in said, f'пустая секция всё же показалась.{got}'

    async def test_the_step_runs_either_way(self, ask):
        got = await ask(AGENT, 'probe', variables={'mark_word': 'zz',
                                                   'mark_section': ''})

        assert got.ran(STEP_FINAL), f'шаг не отработал.{got}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

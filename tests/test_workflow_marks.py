"""Переменная без значения не уезжает в LLM — ни меткой, ни словом «None».

⚠⚠ **Две дыры, и вторая опаснее первой.** Обе найдены на живых инвайтах, где
промпт ссылался на переменную, заведённую типом `workflow` без умолчания — то
есть необязательную.

**Первая: метка переживает подстановку.** Подставляются только те имена, что есть
в словаре; чужое остаётся в тексте как есть, и модель читает `%invite_angle%` как
часть задания.

**Вторая: пустое умолчание превращалось в слово «None».** `defaults_apply` клал в
scope `None`, подстановка делала `str(None)` — и в промпт уходило:

    === Метки в тексте ===
    None

Это хуже: метка выглядит поломкой, и её замечают, а «None» читается как
осмысленное указание. Модель исполняет его и отвечает правдоподобно — в журнале
всё зелено, ответ построен на слове, которого никто не писал. На инвайтах оно ещё
и случайно читалось верно («никаких меток»), поэтому беда не всплывала.

⚠ **Проверять можно только на прогоне, а не при сохранении.** Переменные приходят
из четырёх мест, и три невидимы из базы: запрос клиента, переменные узла и
результаты предыдущих шагов (`{инструмент}_{шаг}_result_{ключ}`). Замер по живой
базе: статическая проверка объявила бы сломанными 26 workflow из 66, почти все —
ложно.
"""

import pytest

from src.ai.ai_workflow import (AiWorkflowMarkError, ai_workflow_marks_check,
                                ai_workflow_marks_left,
                                ai_workflow_variables_defaults_apply,
                                ai_workflow_variables_render)

pytestmark = pytest.mark.ai


class TestDanglingMark:
    """Метка, пережившая подстановку, — отказ, а не мелочь."""

    def test_it_is_found(self):
        assert ai_workflow_marks_left('=== Приём ===\n%invite_angle%') == ['invite_angle']

    def test_a_filled_prompt_is_clean(self):
        assert ai_workflow_marks_left('=== Приём ===\nдерзкий вызов') == []

    def test_the_check_raises_and_names_the_step(self):
        """⚠ В отказе должны стоять и метка, и шаг: без них человек ищет глазами."""
        with pytest.raises(AiWorkflowMarkError) as got:
            ai_workflow_marks_check('%invite_angle% и %invite_length%', 'Черновик')

        text = str(got.value)
        assert '%invite_angle%' in text and '%invite_length%' in text
        assert 'Черновик' in text

    def test_a_clean_prompt_passes(self):
        ai_workflow_marks_check('всё подставлено', 'Черновик')


class TestNoFalseAlarms:
    """⚠⚠ Процент — обычный знак в тексте, и сторож не смеет его трогать.

    Промпты пишут люди: «выполнено на 100%», «скидка 50%», формат даты `%Y-%m-%d`.
    Сторож, ловящий любой процент, сделал бы невозможными сами промпты — и его
    выключили бы в первый же день.

    Отсюда правило: между знаками должен стоять **идентификатор** — буквы, цифры,
    подчёркивание, и не с цифры.
    """

    def test_percentages_in_text_are_not_marks(self):
        assert ai_workflow_marks_left('выполнено на 100% людьми и на 0% роботами') == []

    def test_a_date_format_is_not_a_mark(self):
        assert ai_workflow_marks_left('дата в виде %Y-%m-%d') == []

    def test_a_lone_percent_is_not_a_mark(self):
        assert ai_workflow_marks_left('скидка 50% сегодня') == []

    def test_block_leftovers_are_not_counted_as_variables(self):
        """⚠ `%endif%` без пары — сломанный блок, а не забытая переменная.

        Беда разная, и чинится по-разному: одно правят в промпте, другое — в
        вызове. Свалив их в одну кучу, мы отправили бы человека не туда.
        """
        assert ai_workflow_marks_left('%endif% хвост') == []


class TestEmptyDefault:
    """⚠⚠ Пустое умолчание — пустая строка, а не `None`."""

    def test_a_missing_default_becomes_empty_text(self):
        got = ai_workflow_variables_defaults_apply({}, [{'name': 'x', 'default': None}])

        assert got['x'] == '', 'в scope снова попал None — в промпт уйдёт слово «None»'

    def test_the_word_none_never_reaches_the_prompt(self):
        """Тот самый случай: переменная есть, значения нет, а промпт осмысленный."""
        variables = ai_workflow_variables_defaults_apply(
            {}, [{'name': 'invite_slots', 'default': None}])

        assert ai_workflow_variables_render('Метки: %invite_slots%',
                                            variables) == 'Метки: '

    def test_an_empty_value_hides_its_section(self):
        """⚠ И условный блок читает пустоту как «нечего показывать».

        Ради этого пустая строка и выбрана вместо пропуска переменной: секция
        `%if var%…%endif%` исчезает целиком, как и задумано.
        """
        variables = ai_workflow_variables_defaults_apply(
            {}, [{'name': 'avoid', 'default': None}])

        assert ai_workflow_variables_render('%if avoid%секция%endif%хвост',
                                            variables) == 'хвост'

    def test_a_real_default_survives(self):
        got = ai_workflow_variables_defaults_apply({}, [{'name': 'x', 'default': 'значение'}])

        assert got['x'] == 'значение'

    def test_a_given_value_wins_over_the_default(self):
        """Умолчание дозаполняет, а не перезаписывает: переданное сильнее."""
        got = ai_workflow_variables_defaults_apply(
            {'x': 'из запроса'}, [{'name': 'x', 'default': 'умолчание'}])

        assert got['x'] == 'из запроса'

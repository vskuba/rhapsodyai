"""Переход, чья цель не нашлась, пропускается — а не роняет прогон.

## ⚠⚠ Что здесь стережётся и какой ценой узнано

14.10.2026 в `dating_talk_intention` удалили шаг #819, а два перехода на него
остались. Движок доставал индекс цели прямым обращением к словарю —
`workflow_steps_mapping[target_step_id]`, — и это `KeyError` на ровном месте:

    KeyError: 819
      ai_framework_manager.py:634  step_index = workflow_steps_mapping[target_step_id]

⚠⚠ Падал **каждый** прогон, дошедший до шага с висячим переходом, а не только
тот, где условие истинно: индекс цели доставался **до** проверки условия. За
восемнадцать минут — десять прогонов в `error`, пять верхнего уровня
`dating_talk`, то есть столько же неотвеченных собеседников.

⚠ Заставы теперь две, и они о разном. Первая (ручка удаления шага, `409`) не
даёт висячей ссылке появиться. Эта — вторая, про то, что ссылка всё же
появилась: переносом между базами, правкой метаданных руками, импортом. Одна
застава на входе не отменяет мягкости на исполнении: прогон обязан пережить
испорченные данные, иначе один кривой переход останавливает разговор целиком.

⚠⚠ Пропуск — **не тишина**: помеха пишется в трассу шага полем `error` при
зелёном статусе, и в журнал строкой. Иначе прогон молча пойдёт не той дорогой,
а разбирать будут вёрстку промпта.

⚠ Сторож читает **выражение** движка, а не пересказ: позвать
`_workflow_steps_run` нельзя — он тянет за собой LLM, сессию и журнал. Приём
тот же, что в `test_workflow_to_next_step.py`, и по той же причине.
"""
import pytest

from tests_.tests_guard import tests_guard_code as _source

from src.ai.framework.agent import ai_framework_manager as mod
from src.ai.framework.agent.ai_framework_manager import (
    AI_FRAMEWORK_TRANSITION_GONE, _transition_step_index)

pytestmark = pytest.mark.core

# Карта «номер шага → его место в списке», как её строит движок: ключи — номера
# из базы, то есть целые.
MAPPING = {713: 0, 729: 1, 744: 2}


class TestTheTargetIsResolved:
    """Что считается найденной целью."""

    def test_number_is_found(self):
        assert _transition_step_index(MAPPING, 729) == 1

    def test_string_is_found(self):
        """⚠ Редактор кладёт число, перенос между базами — строку."""
        assert _transition_step_index(MAPPING, '729') == 1

    def test_zero_index_is_not_nothing(self):
        """⚠⚠ Первый шаг имеет индекс `0`, и это **найденная** цель.

        Отличать «не нашлось» от нуля обязан вызывающий (`is None`), а не
        истинность значения: `if not step_index` увёл бы переход на первый шаг
        в ветку «цели нет».
        """
        assert _transition_step_index(MAPPING, 713) == 0


class TestTheMissingTargetIsNotACrash:
    """⚠⚠ Главное: нет цели — `None`, а не исключение."""

    def test_deleted_step_gives_nothing(self):
        assert _transition_step_index(MAPPING, 819) is None

    @pytest.mark.parametrize('raw', ['', None, 'abc', '  ', {}, []])
    def test_broken_step_id_gives_nothing(self, raw):
        """⚠ Испорченное значение — тоже «цели нет».

        `int('')` и `int(None)` бросают, и прежний код бросал бы ими так же
        громко, как `KeyError`: прогон останавливается из-за одной строки в
        метаданных.
        """
        assert _transition_step_index(MAPPING, raw) is None

    def test_empty_mapping_gives_nothing(self):
        assert _transition_step_index({}, 713) is None


class TestTheEngineAsksSoftly:
    """⚠⚠ Как решает сам движок — по его же выражению, а не по пересказу."""

    def test_the_mapping_is_never_subscripted(self):
        """⚠⚠ Сторож против возврата `KeyError`: прямого обращения быть не должно."""
        code = _source(mod.AiFrameworkAgentManager._workflow_steps_run)

        assert 'workflow_steps_mapping[' not in code, \
            'движок снова достаёт цель перехода прямым обращением — висячая ' \
            'ссылка опять уронит весь прогон'

    def test_both_phases_ask_the_same_way(self):
        """⚠ Переходов два рода (before и after), и мягкость нужна обоим.

        Прежде падали оба; починить один — значит оставить вторую половину
        поломки, и видно это станет только на живом разговоре.
        """
        code = _source(mod.AiFrameworkAgentManager._workflow_steps_run)

        assert code.count('_transition_step_index(') == 2, \
            'мягкое разрешение цели стоит не в обоих родах переходов'

    def test_the_skip_is_written_down(self):
        """⚠⚠ Пропущенный переход обязан быть виден в трассе шага.

        Молчаливый пропуск — это прогон, ушедший не той дорогой без следа.
        """
        code = _source(mod.AiFrameworkAgentManager._workflow_steps_run)

        assert 'AI_FRAMEWORK_TRANSITION_GONE' in code, \
            'помеха перестала помечаться — найти её в трассе станет нечем'
        assert 'trace_broken' in code, \
            'помеха больше не доезжает до записи шага'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

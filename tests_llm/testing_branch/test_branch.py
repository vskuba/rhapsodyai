"""Развилка движка: идёт ровно одна ветка, соседние не исполняются.

## ⚠⚠⚠ Почему этот тест живёт на СВОЁМ workflow, а не на боевом

Развилку раньше проверяли на `dating_talk` — рабочем сценарии знакомств из
тридцати с лишним шагов. Предмет проверки (переходы движка) там тонул в чужом
содержании: тест падал, когда правили промпт, переименовывали шаг или меняли
порядок веток, — то есть сообщал о правке, к развилке отношения не имеющей.

Здесь `testing_branch` — четыре шага, заведённые ради одной фичи:

    Ветка: красная   ─┐ не моя краска → уходит к следующей (transitions_before)
    Ветка: зелёная   ─┤
    Ветка: синяя     ─┘ своя → помечает переменную и прыгает в финал (after)
    Финал              отдаёт метку ответом

Менять его будут, только когда меняется **движок переходов**. Правка промптов
Dating его не касается вовсе.

⚠ Модель здесь не нужна ни разу: ни одного шага с LLM. Прогон — доли секунды.

⚠⚠ Нода `Testing` держит единственную модель `fake/echo`: даже появись тут шаг
с моделью, наружу не уйдёт ни один запрос. Это свойство **ноды**, а не
глобального режима процесса.
"""
import pytest

from tests_llm.testing_branch.conftest import (AGENT, BRANCH_OF, STEP_BRANCHES,
                                               STEP_FINAL)

pytestmark = pytest.mark.llm


class TestOnlyItsOwnBranchRuns:
    """Выбранная краска ведёт в свою ветку — и только в неё."""

    @pytest.mark.parametrize('colour', sorted(BRANCH_OF))
    async def test_the_chosen_branch_runs(self, ask, colour):
        """⚠ Каждая из трёх красок доводит до своей ветки.

        Перебором, а не одним случаем: ветки стоят подряд, и ошибка в переходе
        средней не видна, пока проверяешь только крайнюю.
        """
        got = await ask(AGENT, f'probe {colour}', variables={'branch_pick': colour})

        assert got.ran(BRANCH_OF[colour]), \
            f'краска «{colour}» не довела до своей ветки.{got}'

    @pytest.mark.parametrize('colour', sorted(BRANCH_OF))
    async def test_the_neighbours_stay_out(self, ask, colour):
        """⚠⚠ Главное в развилке: соседняя ветка не отработала.

        «Шаг был на маршруте» и «шаг отработал» — разное: покинутый
        `transitions_before` тоже попадает в трассу. Спрашиваем про работу
        (`ran`), иначе тест зеленел бы на любом проходе подряд.
        """
        got = await ask(AGENT, f'probe {colour}', variables={'branch_pick': colour})

        worked = [step for step in STEP_BRANCHES if got.ran(step)]

        assert worked == [BRANCH_OF[colour]], \
            f'краска «{colour}»: отработали ветки {worked}.{got}'

    async def test_the_answer_carries_the_mark(self, ask):
        """⚠ Метка ветки доезжает до ответа — значит переменная дожила до финала.

        Без этого «ветка отработала» ничего не значит: шаг мог сработать, а
        значение потеряться по дороге.
        """
        got = await ask(AGENT, 'probe green', variables={'branch_pick': 'green'})

        said = got.prompt_of(STEP_FINAL).strip()

        assert said == 'ветка: green', \
            f'метка ветки не доехала до финала: {said!r}.{got}'


class TestAnUnknownColourFallsThrough:
    """Краска, которой нет ни у одной ветки."""

    async def test_no_branch_runs(self, ask):
        """⚠⚠ Незнакомая краска не поднимает ни одной ветки.

        Иначе развилка «на всякий случай» отработала бы последней — и ошибка в
        значении выглядела бы как обычная работа.
        """
        got = await ask(AGENT, 'probe none', variables={'branch_pick': 'violet'})

        worked = [step for step in STEP_BRANCHES if got.ran(step)]

        assert not worked, f'неизвестная краска подняла ветки {worked}.{got}'

    async def test_the_run_still_reaches_the_end(self, ask):
        """⚠ Прогон всё равно доходит до финала: мимо веток — не значит в обрыв."""
        got = await ask(AGENT, 'probe none', variables={'branch_pick': 'violet'})

        assert got.ran(STEP_FINAL), f'прогон не дошёл до финала.{got}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

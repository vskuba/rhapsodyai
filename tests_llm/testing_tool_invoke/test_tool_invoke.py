"""Вызов инструмента из workflow: карты входа, литералы, имя результата.

⚠⚠ Фича движка. Три её части ломаются порознь и молча:

* **карта входа** — значение берётся из названной переменной, а не из текста;
* **литерал `_const_`** — то, что подаётся числом, а не переменной;
* **автоимя результата** — `{инструмент}_{шаг}_result_{тип}`, по нему результат
  и читают (`outputs_map` для нечисловых и несловарных результатов молчит —
  `workflow.md`, §4a-bis).
"""
import pytest

from tests_llm.testing_tool_invoke.conftest import (AGENT, STEP_FINAL,
                                                    STEP_TOOL, TOOL_STEP)

pytestmark = pytest.mark.llm


class TestTheToolIsCalled:
    """Инструмент зовётся и отдаёт результат в переменную."""

    async def test_the_step_runs(self, ask):
        got = await ask(AGENT, 'probe', variables={'count_from': '10'})

        assert got.ran(STEP_TOOL), f'шаг инструмента не отработал.{got}'

    async def test_the_input_map_feeds_the_argument(self, ask):
        """⚠⚠ Довод берётся из переменной, названной картой.

        Подай карта текст вместо имени — инструмент получил бы строку «пять» и
        посчитал бы её нулём; ошибки при этом не будет.
        """
        got = await ask(AGENT, 'probe', variables={'count_from': '10'})

        said = got.prompt_of(STEP_FINAL)

        assert f'счёт={10 + TOOL_STEP}' in said, \
            f'довод не доехал из переменной: {said!r}.{got}'

    async def test_a_literal_reaches_the_tool(self, ask):
        """⚠ Литерал `_const_5` — число, а не имя переменной.

        Проверяется разницей: сменив вход, ответ обязан сдвинуться ровно на
        пять. Так видно, что второй довод вправду пятёрка.
        """
        first = await ask(AGENT, 'probe', variables={'count_from': '0'})
        second = await ask(AGENT, 'probe', variables={'count_from': '100'})

        assert f'счёт={TOOL_STEP}' in first.prompt_of(STEP_FINAL), \
            f'литерал не доехал.{first}'
        assert f'счёт={100 + TOOL_STEP}' in second.prompt_of(STEP_FINAL), \
            f'литерал подменился переменной.{second}'

    async def test_the_result_has_its_own_name(self, ask):
        """⚠⚠ Результат читается автоименем с номером шага.

        Имя собирается движком, и промпт финала ссылается ровно на него.
        Разойдись шаблон — в ответе осталась бы незаменённая метка.
        """
        got = await ask(AGENT, 'probe', variables={'count_from': '1'})

        said = got.prompt_of(STEP_FINAL)

        assert '%' not in said, \
            f'автоимя результата не сошлось: {said!r}.{got}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Подпоток: что в него входит и что из него выходит.

⚠⚠ Фича движка. У подпотока **изолированный scope**: он видит только то, что
назвала `inputs_map`, и отдаёт только то, что названо в `outputs_map` — причём
выход может приехать под другим именем.

Раньше это проверялось на ветке «письма и фото» боевого `dating_talk`, и тесты
трижды ломались от переписывания самой ветки, хотя карты работали.
"""
import pytest

from tests_llm.testing_subflow_io.conftest import (AGENT, STEP_CALL,
                                                   STEP_CHILD_FINAL,
                                                   STEP_CHILD_MOVE, STEP_FINAL)

pytestmark = pytest.mark.llm


class TestTheSubflowRuns:
    """Зов подпотока и его шаги в маршруте."""

    async def test_the_call_step_runs(self, ask):
        got = await ask(AGENT, 'probe', variables={'parent_value': 'привет'})

        assert got.ran(STEP_CALL), f'шаг зова не отработал.{got}'

    async def test_the_child_steps_are_in_the_route(self, ask):
        """⚠ Шаги подпотока попадают в **подпрогоны**, а не в главный маршрут.

        Проверять их надо `went_through`/`ran` по полному пути: иначе «подпоток
        отработал» и «шаг зова был» неразличимы.
        """
        got = await ask(AGENT, 'probe', variables={'parent_value': 'привет'})

        assert got.ran(STEP_CHILD_MOVE), f'шаг подпотока не отработал.{got}'
        assert got.ran(STEP_CHILD_FINAL), f'подпоток не дошёл до конца.{got}'


class TestTheMapsCarryTheValues:
    """Карты входа и выхода — и переименование между ними."""

    async def test_the_input_reaches_the_child(self, ask):
        """⚠⚠ Значение родителя доезжает в подпоток под именем карты.

        У подпотока своё имя переменной (`child_in`), и связывает их только
        `inputs_map`. Разойдись она — подпоток получил бы пустоту, а прогон
        прошёл бы насквозь.
        """
        got = await ask(AGENT, 'probe', variables={'parent_value': 'zz-вход'})

        said = got.prompt_of(STEP_FINAL)

        assert 'zz-вход' in said, f'вход не доехал в подпоток: {said!r}.{got}'

    async def test_the_output_comes_back_renamed(self, ask):
        """⚠⚠ Выход приезжает под **именем родителя**, а не подпотока.

        `child_out` → `parent_got`. Финал читает второе имя и о первом не знает:
        потеряйся карта — он отдал бы умолчание «нет», и это выглядело бы как
        обычный ответ.
        """
        got = await ask(AGENT, 'probe', variables={'parent_value': 'zz-вход'})

        said = got.prompt_of(STEP_FINAL).strip()

        assert said == 'родитель получил: из подпотока: zz-вход', \
            f'выход не переименовался: {said!r}.{got}'
        assert str(got.vars.get('parent_got') or '').endswith('zz-вход'), \
            f'переменная родителя не получила выход.{got}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

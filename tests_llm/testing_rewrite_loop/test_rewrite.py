"""Переписывание по вердикту и потолок попыток.

⚠⚠ Фича движка: переход **назад** по номеру шага. Две её половины ломаются
порознь:

* отказ вправду **возвращает** на переписывание, а не идёт дальше;
* потолок держит — иначе заход крутится до предела шагов движка (300) и съедает
  минуты, а выглядит как «модель сегодня медленная».

Раньше это проверялось тремя боевыми workflow писем разом, и каждый падал от
правки своего промпта.
"""
import json

import pytest

from tests_llm.testing_rewrite_loop.conftest import (AGENT, STEP_COUNT,
                                                     STEP_FINAL, STEP_JUDGE)

pytestmark = pytest.mark.llm


class TestAPassGoesStraightThrough:
    """Вердикт «годится» — один заход и конец."""

    async def test_one_try_is_enough(self, ask, llm_answers):
        await llm_answers([], default=json.dumps({'verdict': 'ok'}))

        got = await ask(AGENT, 'probe', variables={'tries_max': '3'})

        said = got.prompt_of(STEP_FINAL)

        assert 'попыток=1' in said, f'годный ответ переписывали: {said!r}.{got}'

    async def test_it_reaches_the_end(self, ask, llm_answers):
        await llm_answers([], default=json.dumps({'verdict': 'ok'}))

        got = await ask(AGENT, 'probe', variables={'tries_max': '3'})

        assert got.ran(STEP_FINAL), f'прогон не дошёл до финала.{got}'


class TestARefusalSendsItBack:
    """Вердикт «негодно» возвращает на переписывание."""

    async def test_the_judge_runs_again(self, ask, llm_answers):
        """⚠⚠ Судья отработал больше одного раза — значит возврат вправду был.

        «Шаг был на маршруте» тут ничего не значит: он на нём и так. Считаем
        отрисовки.
        """
        await llm_answers([], default=json.dumps({'verdict': 'bad'}))

        got = await ask(AGENT, 'probe', variables={'tries_max': '3'})

        runs = len(got.prompts_each.get(STEP_JUDGE) or [])

        assert runs > 1, f'судья отработал {runs} раз — возврата не было.{got}'

    async def test_the_counter_runs_again_too(self, ask, llm_answers):
        """⚠ Возврат ведёт на начало круга, а не на шаг перед судьёй."""
        await llm_answers([], default=json.dumps({'verdict': 'bad'}))

        got = await ask(AGENT, 'probe', variables={'tries_max': '3'})

        runs = len(got.outputs_each.get(STEP_COUNT) or [])

        assert runs > 1, f'счётчик отработал {runs} раз — круг не замкнулся.{got}'


class TestTheCeilingHolds:
    """Потолок попыток — защита от вечного круга."""

    @pytest.mark.parametrize('ceiling', (2, 3))
    async def test_it_stops_at_the_ceiling(self, ask, llm_answers, ceiling):
        """⚠⚠ Кругов ровно столько, сколько позволено, и ни одним больше.

        Перебором по двум потолкам: число, зашитое в движок вместо настоящего
        предела, прошло бы проверку на одном значении.
        """
        await llm_answers([], default=json.dumps({'verdict': 'bad'}))

        got = await ask(AGENT, 'probe', variables={'tries_max': str(ceiling)})

        said = got.prompt_of(STEP_FINAL)

        assert f'попыток={ceiling}' in said, \
            f'потолок {ceiling} не удержал: {said!r}.{got}'

    async def test_the_run_ends_successfully(self, ask, llm_answers):
        """⚠ Упёршись в потолок, заход **заканчивается**, а не обрывается.

        Негодный текст — не причина терять ответ: наружу уезжает последнее, что
        вышло.
        """
        await llm_answers([], default=json.dumps({'verdict': 'bad'}))

        got = await ask(AGENT, 'probe', variables={'tries_max': '2'})

        assert got.status == 'success', f'заход оборвался: {got.status}.{got}'
        assert got.ran(STEP_FINAL), f'финал не отработал.{got}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

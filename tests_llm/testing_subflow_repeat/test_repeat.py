"""Цикл подпотока: сколько витков заказали и что видит второй виток.

⚠⚠ Фича движка, и её вторая половина важнее первой. Число витков проверить
легко; настоящая беда — **накопитель**: второй виток обязан видеть сделанное
первым. Пропади это, цикл стал бы N одинаковыми заходами, и по ответу разницы
не видно.

Раньше проверялось на инвайтах (`dating_invite_write`), где виток — сочинение
реплики, и каждая правка промпта инвайта роняла тесты цикла.
"""
import pytest

from tests_llm.testing_subflow_repeat.conftest import (AGENT, STEP_CHILD_ADD,
                                                       STEP_CHILD_FINAL,
                                                       STEP_FINAL, STEP_LOOP)

pytestmark = pytest.mark.llm


class TestTheLoopRunsItsRounds:
    """Витков столько, сколько заказано меткой `repeat.count`."""

    @pytest.mark.parametrize('count', (1, 3, 5))
    async def test_the_pile_grows_by_one_each_round(self, ask, count):
        """⚠ Перебором по числам: единица и много — разные случаи.

        Цикл, сорвавшийся после первого витка, на `count=1` выглядел бы
        исправным.
        """
        got = await ask(AGENT, 'probe', variables={'loop_count': str(count)})

        pile = got.prompt_of(STEP_FINAL).replace('накоплено:', '').strip()

        assert pile.count('x') == count, \
            f'витков не {count}, а {pile.count("x")}: {pile!r}.{got}'

    async def test_the_loop_step_runs(self, ask):
        got = await ask(AGENT, 'probe', variables={'loop_count': '2'})

        assert got.ran(STEP_LOOP), f'шаг цикла не отработал.{got}'

    async def test_the_child_runs_once_per_round(self, ask):
        """⚠⚠ Шаг подпотока отработал столько же раз, сколько витков.

        Трасса пишет каждое исполнение, и число отрисовок — прямое
        доказательство: «цикл был» и «цикл прокрутился трижды» разное.
        """
        got = await ask(AGENT, 'probe', variables={'loop_count': '3'})

        runs = len(got.outputs_each.get(STEP_CHILD_ADD) or [])

        assert runs == 3, f'шаг подпотока отработал {runs} раз вместо трёх.{got}'


class TestEachRoundSeesThePreviousOne:
    """⚠⚠⚠ Главное в цикле: накопленное переживает виток."""

    async def test_the_second_round_adds_to_the_first(self, ask):
        """Второй виток дописывает к первому, а не начинает заново.

        Разделитель запятой и есть доказательство: `x,x` значит «второй виток
        увидел первый», а `x` — что накопитель обнулился между витками.
        """
        got = await ask(AGENT, 'probe', variables={'loop_count': '2'})

        pile = got.prompt_of(STEP_FINAL).replace('накоплено:', '').strip()

        assert pile == 'x,x', f'накопитель не пережил виток: {pile!r}.{got}'

    async def test_each_round_sees_a_longer_pile(self, ask):
        """⚠ Накопитель растёт **на каждом** витке, а не только на последнем.

        Смотрим, что подпоток **возвращал** по очереди: длина обязана расти.

        ⚠⚠ По финалу витка, а не по шагу приписывания: `variable_conversion`
        меняет переменные и в трассу `output` не кладёт вовсе — меряя по нему,
        тест сравнивал бы пустые строки и зеленел бы на сломанном цикле.
        """
        got = await ask(AGENT, 'probe', variables={'loop_count': '3'})

        seen = [str(one) for one in (got.outputs_each.get(STEP_CHILD_FINAL) or [])]
        lengths = [one.count('x') for one in seen]

        assert lengths == sorted(lengths) and len(set(lengths)) == len(lengths), \
            f'накопитель не рос по виткам: {seen}.{got}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

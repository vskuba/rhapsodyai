"""Раскладка ответа модели по именованным переменным (`llm_to_json_variable`).

⚠⚠ Фича движка, а не содержание workflow: шаг просит у модели ключи и кладёт их
в переменные под своими именами. Раньше это проверялось восемью парами боевого
«Анализа сообщения» — и падало, когда правили его промпт.

Здесь два шага: спросить и показать. Менять их будут, только когда меняется
раскладка в движке.
"""
import pytest

from tests_llm.testing_llm_json.conftest import (AGENT, ANSWER, STEP_ASK,
                                                 STEP_FINAL)

pytestmark = pytest.mark.llm


class TestTheAnswerIsSpreadIntoVariables:
    """Каждый ключ ответа ложится в свою переменную."""

    async def test_every_key_reaches_its_variable(self, ask, llm_answers):
        """⚠⚠ Все три ключа разом, а не один для примера.

        Раскладка ломается по одной паре: проверь мы одну, остальные молча
        разъехались бы.
        """
        await llm_answers([], default=_json(ANSWER))

        got = await ask(AGENT, 'probe')

        missed = {name: (value, got.vars.get(name))
                  for name, value in ANSWER.items()
                  if str(got.vars.get(name) or '') != str(value)}

        assert not missed, f'раскладка разошлась: {missed}.{got}'

    async def test_the_values_reach_the_answer(self, ask, llm_answers):
        """⚠ Переменные доживают до финала — иначе «положено» ничего не значит."""
        await llm_answers([], default=_json(ANSWER))

        got = await ask(AGENT, 'probe')

        said = got.prompt_of(STEP_FINAL).strip()

        assert said == 'слово=zz-word число=42 флаг=1', \
            f'значения не доехали до финала: {said!r}.{got}'

    async def test_the_step_really_asked_the_model(self, ask, llm_answers):
        """⚠ Шаг вправду отработал, а не был пропущен переходом."""
        await llm_answers([], default=_json(ANSWER))

        got = await ask(AGENT, 'probe')

        assert got.ran(STEP_ASK), f'шаг вопроса не отработал.{got}'


def _json(values: dict) -> str:
    """Ответ подмены строкой JSON — так его отдаёт настоящая модель."""
    import json

    return json.dumps(values, ensure_ascii=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

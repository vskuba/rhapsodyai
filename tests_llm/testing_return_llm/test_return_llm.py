"""Ответ `return_response_llm`: в переменную, по маршруту и через границы сообщений.

⚠⚠ Фича движка целиком: финальный шаг с ответом модели кладёт его в названную
workflow-переменную (`output_variable`), а с галочкой `continue_workflow` не
кончает беседу, а ждёт следующую реплику — мастер продолжается с следующего
шага, и переменная переживает границу сообщения.

Проверяются маршрут и переменные; сама формулировка ответа — всегда заготовка
подмены, живой речи здесь нет вовсе.
"""

import pytest

from tests_llm.testing_return_llm.conftest import (AGENT, ANSWER, CANCEL,
                                                   ECHO_ANSWER, STEP_ASK,
                                                   STEP_ECHO, STEP_FINAL,
                                                   VAR_ANSWER)

pytestmark = pytest.mark.llm

# Сценарий папки: «Вопрос» отвечает ANSWER, «Эхо» — ECHO_ANSWER.
PLAN = [('probe:', ANSWER), ('Повтори:', ECHO_ANSWER)]


class TestTheAnswer:
    """Один заход: что вернула ручка и что осталось в переменных."""

    async def test_the_answer_lands_in_the_variable(self, ask, llm_answers):
        await llm_answers(PLAN)

        got = await ask(AGENT, 'probe', variables={'probe_text': 'первый'})

        assert got.ran(STEP_ASK), f'шаг вопроса не отработал.{got}'
        assert got.output_of(STEP_ASK) == ANSWER, \
            f'ответ шага не доехал до трассы: {got.output_of(STEP_ASK)!r}.{got}'
        assert got.vars.get(VAR_ANSWER) == ANSWER, \
            f'ответ не лёг в переменную: {got.vars!r}.{got}'

    async def test_continuation_waits_for_the_next_message(self, ask, llm_answers):
        """⚠ `continue_workflow` не тянет следующий шаг в этот же запрос.

        Иначе «продолжить workflow» слилось бы с обычным `to_next_step` и
        мастер не имел бы смысла: реплика человека между шагами — вся его суть.
        """
        await llm_answers(PLAN)

        got = await ask(AGENT, 'probe', variables={'probe_text': 'тихий'})

        assert not got.went_through(STEP_ECHO), \
            f'мастер уехал с шага внутри одного запроса.{got}'


class TestTheWizard:
    """Мастер через границы сообщений: продолжение, переменная, конец, откат."""

    async def test_the_next_message_picks_up_after_the_step(self, ask, llm_answers):
        """⚠ Главное обещание галочки: следующая реплика — со **следующего** шага.

        Без продолжения движение стартовало бы с «Вопроса» на каждой реплике,
        и ответ человека тратился бы на повтор пройденного.
        """
        await llm_answers(PLAN)

        first = await ask(AGENT, 'probe', variables={'probe_text': 'мастер'})
        got = await ask(AGENT, 'again', session=first.session)

        assert not got.ran(STEP_ASK), \
            f'продолжение переспросило с первого шага.{got}'
        assert got.ran(STEP_ECHO), f'шаг после продолжения не отработал.{got}'

    async def test_the_variable_survives_the_message(self, ask, llm_answers):
        """⚠ Пережившая границу значения — в отрисовке следующего шага.

        Снимок `workflow_variables_saved` — половина механизма продолжения:
        без него следующий шаг видел бы пустой `%answer_stored%`.
        """
        await llm_answers(PLAN)

        first = await ask(AGENT, 'probe', variables={'probe_text': 'граница'})
        got = await ask(AGENT, 'again', session=first.session)

        assert ANSWER in got.prompt_of(STEP_ECHO), \
            f'ответ не дошёл до промпта следующего шага: {got.prompt_of(STEP_ECHO)!r}.{got}'
        assert got.output_of(STEP_ECHO) == ECHO_ANSWER, \
            f'шаг продолжения ответил не сценарием.{got}'

    async def test_a_step_without_variable_rewrites_nothing(self, ask, llm_answers):
        """Без `output_variable` шаг ничего не пишет: значение — с первого шага.

        Иначе сосед по мастеру затёр бы ответ молча, и проверить это было бы
        нечем до первой поломки на проде.
        """
        await llm_answers(PLAN)

        first = await ask(AGENT, 'probe', variables={'probe_text': 'тишина'})
        await ask(AGENT, 'again', session=first.session)
        got = await ask(AGENT, 'third', session=first.session)

        assert got.ran(STEP_FINAL), f'мастер не дошёл до финала.{got}'
        assert ANSWER in got.output_of(STEP_FINAL) and ECHO_ANSWER not in got.output_of(STEP_FINAL), \
            f'«Эхо» без переменной затёр ответ: {got.output_of(STEP_FINAL)!r}.{got}'

    async def test_the_last_step_ends_the_session(self, ask, llm_answers):
        """Последний шаг без галочки — мастер закончен; новая реплика с начала.

        Иначе сессия застревала бы на прогнанном мастере и больше не спрашивала.
        """
        await llm_answers(PLAN)

        first = await ask(AGENT, 'probe', variables={'probe_text': 'финал'})
        for reply in ('again', 'third'):
            await ask(AGENT, reply, session=first.session)

        got = await ask(AGENT, 'fourth', session=first.session)

        assert got.ran(STEP_ASK), f'после финала мастер не начался заново.{got}'
        assert not got.ran(STEP_ECHO), \
            f'новый заход провалился в середину старого мастера.{got}'

    async def test_the_cancel_word_stops_it(self, ask, llm_answers, say):
        """⚠ Слово отмены гасит мастер: следующая реплика — снова первый шаг.

        Галочка без отката превращала бы диалог в односторонний конвейер:
        человек обязан уметь выйти из середины одним словом.
        """
        await llm_answers(PLAN)

        first = await ask(AGENT, 'probe', variables={'probe_text': 'откат'})
        said = await say(AGENT, CANCEL, first.session)
        assert said.status_code == 200, \
            f'ручка отвергла реплику отмены ({said.status_code}): {said.text[:200]}'

        got = await ask(AGENT, 'after', session=first.session)

        assert got.ran(STEP_ASK), f'отмена не откатила мастер на начало.{got}'
        assert not got.ran(STEP_ECHO), \
            f'после отмены мастер пошёл с середины.{got}'

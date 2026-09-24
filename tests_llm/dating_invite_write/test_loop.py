"""Цикл инвайтов: сколько просили — столько и проходов, и каждый видит прежние.

## ⚠⚠ Зачем этот файл отдельно от маршрута

Цикл — **половина замысла инвайтов**, и половина дорогая. Один текст на весь пул
означал, что дюжина наших анкет пишет разным людям слово в слово одно и то же —
примета агентства вернее любой другой. Дюжина отдельных вызовов вернула бы прежнюю
цену. Поэтому тексты просятся **одним вызовом**, по числу девушек в сети, а
непохожесть держат две вещи:

1. каждый следующий черновик **видит уже написанные** (`invite_done` в промпте);
2. судья сверяет новый текст **с ними же**.

Сломайся любая — прогон останется зелёным, ответ придёт, пул наберётся. И будет
пулом одинаковых реплик.

## ⚠ Почему проверок непохожести здесь нет

«Похожи ли два текста» — вопрос к человеку либо к модели, и ответ на него плавает.
Тест стережёт **вход**: что второму проходу показали первый. Вышло ли у модели
разное — смотрят глазами по трассе.
"""

import pytest

from tests_llm.dating_invite_write.conftest import (HEAD_DONE_DRAFT,
                                                    HEAD_DONE_JUDGE, STEP_DRAFT,
                                                    STEP_JUDGE, STEP_TIME)

pytestmark = pytest.mark.llm_live

# Сколько реплик просим в проверках цикла. ⚠ Две, а не пять: каждая — вызов
# модели и вызов судьи, то есть секунды прогона. Двух довольно, чтобы отличить
# «цикл идёт» от «цикл не идёт», а всё остальное — та же арифметика.
TWICE = '2'


class TestTheLoopRunsPerReply:
    """Сколько текстов просили, столько раз и сочиняли."""

    async def test_two_replies_mean_two_drafts(self, invite):
        got = await invite(invite_count=TWICE)

        assert got.times(STEP_DRAFT) == 2, \
            f'просили две реплики, а черновиков {got.times(STEP_DRAFT)}.{got}'

    async def test_each_reply_gets_its_own_judge(self, invite):
        """⚠ Судья идёт **на каждую**, а не на пул разом.

        Судить их вместе было бы дешевле на вызов, но тогда брак одной топил бы
        весь заход: вердикт-то один.
        """
        got = await invite(invite_count=TWICE)

        assert got.times(STEP_JUDGE) == got.times(STEP_DRAFT), \
            (f'черновиков {got.times(STEP_DRAFT)}, а судей'
             f' {got.times(STEP_JUDGE)}.{got}')

    async def test_one_reply_means_one_pass(self, invite):
        """Обратный случай: просили одну — цикл не крутится лишний раз.

        ⚠ Проверка не праздная: `repeat.count` берётся из переменной
        (`%invite_count%`), и пустое значение когда-то означало бы `max_iterations
        = 50` — полсотни вызовов модели на один заход.
        """
        got = await invite(invite_count='1')

        assert got.times(STEP_DRAFT) == 1, \
            f'просили одну реплику, а черновиков {got.times(STEP_DRAFT)}.{got}'


class TestEachReplySeesThePreviousOnes:
    """⚠⚠ Главное в цикле: второй проход знает о первом."""

    async def test_the_first_pass_has_nothing_to_avoid(self, invite):
        """Первому показывать нечего — и блока в его промпте быть не должно.

        ⚠ Пустой заголовок «Это ты уже написала ===» без строк под ним модель
        читает как факт: «написала, но что — не показали». Оттого он под `%if%`.
        """
        got = await invite(invite_count=TWICE)
        first = got.prompt_each(STEP_DRAFT)[:1]

        assert first, f'черновиков на маршруте нет вовсе.{got}'
        assert HEAD_DONE_DRAFT not in first[0], \
            f'первому проходу показали накопленное, которого ещё нет.{got}'

    async def test_the_second_pass_sees_the_first(self, invite):
        """⚠⚠ Тот самый вход, ради которого цикл и заведён."""
        got = await invite(invite_count=TWICE)
        drafts = got.prompt_each(STEP_DRAFT)

        assert len(drafts) >= 2, \
            f'второго прохода не было, проверять нечего.{got}'
        assert HEAD_DONE_DRAFT in drafts[1], \
            f'вторая реплика сочинялась, не зная о первой.{got}'

    async def test_the_second_judge_sees_the_first_reply_too(self, invite):
        """⚠ Судье накопленное нужно не меньше: сравнивать он обязан **с ними**.

        Покажи текст только сочинителю — и судья пропустит близнеца, потому что
        сравнивать ему будет не с чем.
        """
        got = await invite(invite_count=TWICE)
        judges = got.prompt_each(STEP_JUDGE)

        assert len(judges) >= 2, f'второго суда не было.{got}'
        assert HEAD_DONE_JUDGE in judges[1], \
            f'второй текст судили, не показав ему первый.{got}'


class TestTheClockIsAskedOncePerReply:
    """⚠ Время снимается внутри подпрогона, то есть на каждую реплику.

    Это не расточительство и не ошибка: цикл может идти минуту, и час, снятый
    один раз на входе, к последней реплике устарел бы. Но знать об этом стоит —
    отсюда тест, а не умолчание.
    """

    async def test_the_clock_runs_for_every_reply(self, invite):
        got = await invite(invite_count=TWICE)

        assert got.times(STEP_TIME) == got.times(STEP_DRAFT), \
            (f'часы спрошены {got.times(STEP_TIME)} раз(а) на'
             f' {got.times(STEP_DRAFT)} реплик.{got}')

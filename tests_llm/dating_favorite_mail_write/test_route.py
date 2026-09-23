"""Маршрут письма избранному: судья, правка и конверт ответа.

⚠⚠ Утверждения — **только по трассе**: маршрут, шаги, промпт после
подстановки. Текст ответа модели не проверяется никогда. Правило и цена,
которой оно куплено, — `.claude/docs/testing_llm.md`.
"""

import pytest

from tests_llm.datingai import ENVELOPE
from tests_llm.dating_favorite_mail_write.conftest import (STEP_DRAFT, STEP_FIX,
                                                           STEP_JUDGE, STEP_OUT,
                                                           STEP_TIME)

pytestmark = pytest.mark.llm


class TestTheRunGoesThrough:
    """Первое: письмо вообще сочиняется."""

    async def test_the_run_ends_with_success(self, favorite):
        got = await favorite()

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'

    async def test_the_draft_goes_through_the_judge(self, favorite):
        """⚠⚠ Судья обязателен по той же причине, что у инвайтов: шаблон один на
        заход и уходит десяткам людей без человеческого взгляда."""
        got = await favorite()

        assert got.went_through(STEP_DRAFT), f'черновик не сочинялся.{got}'
        assert got.went_through(STEP_JUDGE), \
            f'черновик уходит в пул, минуя судью.{got}'

    async def test_the_clock_is_read_before_the_draft(self, favorite):
        """Часы снимаются первым шагом — иначе подставлять в промпт нечего."""
        got = await favorite()

        assert got.went_through(STEP_TIME), f'часы не спрошены вовсе.{got}'
        assert got.route.index(STEP_TIME) < got.route.index(STEP_DRAFT), \
            f'часы спрошены после того, как письмо написано.{got}'


class TestTheVerdictAndTheRouteAgree:
    """⚠⚠ Проверяется **согласованность**, а не вердикт.

    Утверждать «судья ответил одним из трёх слов» нельзя: слово выбирает модель.
    Зато связь «вердикт ⇔ пройденные шаги» держит переход шага
    (`transitions_after`), и от удачи она не зависит.
    """

    async def test_a_fix_follows_a_refusal(self, favorite):
        got = await favorite()
        verdict = str(got.vars.get('fav_ok'))

        if verdict == 'fixed':
            assert got.went_through(STEP_FIX), \
                f'вердикт «fixed», а шага правки на маршруте нет.{got}'
        elif verdict == 'yes':
            assert not got.went_through(STEP_FIX), \
                f'судья пропустил черновик, а правка всё равно шла.{got}'

    async def test_the_fix_is_told_what_was_wrong(self, favorite):
        """⚠ Правка без замечания бессмысленна: переписывать пришлось бы наугад.

        Проверка условная — правка идёт не всегда, — но когда идёт, замечание
        судьи обязано быть у неё в промпте.
        """
        got = await favorite()

        if not got.went_through(STEP_FIX):
            pytest.skip('судья не забраковал черновик — правки не было')

        assert 'Замечание редактора' in got.prompt_of(STEP_FIX), \
            f'шаг правки не получил замечания судьи.{got}'


class TestTheEnvelope:
    """⚠⚠ Конверт — договор с DatingAi, и рвётся он молча.

    Панель разбирает ответ по трём меткам (`mail_agent`): пропала любая — разбор
    вернёт пустоту, и пул не наберётся **без единой ошибки в журнале**.
    """

    async def test_the_answer_carries_all_three_marks(self, favorite):
        got = await favorite()
        envelope = got.prompt_of(STEP_OUT)

        assert envelope, f'шага ответа панели на маршруте нет.{got}'
        for mark in ENVELOPE:
            assert mark in envelope, \
                f'в конверте нет метки {mark!r}: {envelope[:200]!r}.{got}'

    async def test_the_verdict_mark_comes_first(self, favorite):
        got = await favorite()

        assert got.prompt_of(STEP_OUT).lstrip().startswith('VERDICT:'), \
            f'конверт начинается не с вердикта.{got}'

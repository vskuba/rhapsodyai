"""Маршрут инвайта: цикл, судья и конверт ответа.

⚠⚠ Утверждения — **только по трассе**: маршрут, шаги, промпт после
подстановки. Текст ответа модели не проверяется никогда. Правило и цена,
которой оно куплено, — `.claude/docs/testing_llm.md`.
"""

import pytest

from tests_llm.plan import plan_load
from tests_llm.dating_invite_write.fixtures import (DRAFT_GOOD, DRAFT_WEAK,
                                                    PLAN_JUDGE_REFUSES, PLAN_OK)

from tests_llm.datingai import ENVELOPE
from tests_llm.dating_invite_write.conftest import (STEP_DICE, STEP_DRAFT,
                                                    STEP_JUDGE, STEP_KEEP,
                                                    STEP_LOOP, STEP_OUT,
                                                    VERDICT_OK)

pytestmark = pytest.mark.llm


class TestTheRunGoesThrough:
    """Первое, что должно работать: шаблон вообще сочиняется."""

    async def test_the_run_ends_with_success(self, invite):
        got = await invite()

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'

    async def test_the_draft_and_the_judge_both_run(self, invite):
        """⚠⚠ **Судья — не украшение, а условие затеи.**

        Шаблон один на весь пул и уходит десяткам людей **без человеческого
        взгляда**. Отказ модели («I can't help with crafting flirt messages»)
        уехал бы в чат всем разом — поймано на живом прогоне первого же дня.

        Поэтому проверка «черновик прошёл через судью» стоит отдельно от проверки
        «прогон удался»: удаться он может и в обход.
        """
        got = await invite()

        assert got.went_through(STEP_DRAFT), f'черновик не сочинялся.{got}'
        assert got.went_through(STEP_JUDGE), \
            f'черновик ушёл в пул, минуя судью.{got}'

    async def test_the_reply_is_collected(self, invite):
        """Шаг накопления обязателен: им реплика попадает в `invite_done`."""
        got = await invite()

        assert got.went_through(STEP_KEEP), \
            f'реплика не накоплена — следующая не узнает о ней.{got}'

    async def test_the_writing_happens_in_the_subworkflow(self, invite):
        """⚠ Обёртка сама ничего не сочиняет — она крутит подпрогон.

        Различие видно по двум спискам трассы: `route` — только верхний уровень,
        `route_all` — вместе с подпрогонами. Черновик обязан быть во втором и не
        быть в первом.

        ⚠⚠ Проверка не праздная: перенеси кто-нибудь сочинение в саму обёртку —
        и цикл перестал бы повторяться, а прогон остался бы зелёным. Пул при этом
        набирался бы одним текстом на всех.
        """
        got = await invite()

        assert STEP_LOOP in got.route, \
            f'обёртка не дошла до шага цикла.{got}'
        assert STEP_DRAFT not in got.route, \
            f'черновик сочиняется в самой обёртке, а не в подпрогоне.{got}'
        assert got.went_through(STEP_DRAFT), \
            f'черновика нет и в подпрогонах.{got}'


class TestTheJudgeVerdict:
    """⚠⚠ Здесь проверяется **согласованность маршрута**, а не вердикт.

    Утверждать «судья ответил одним из трёх слов» нельзя: слово выбирает модель,
    и такой тест краснел бы от её оговорки, а не от поломки. Стеречь можно только
    связь, которую держит движок: вердикт и пройденные шаги обязаны сходиться.

    ⚠ Обе проверки ниже верны при **любом** решении модели — и когда судья
    пропустил с первого раза, и когда забраковал пять черновиков подряд. Потому
    они и годятся для живого прогона (`llm_live`), где решение не задать.
    """

    async def test_every_draft_is_judged(self, invite):
        """Сколько черновиков написано, столько раз работал и судья.

        ⚠⚠ Это и есть смысл затеи: шаблон уходит полусотне людей без
        человеческого взгляда, и черновик, проскочивший мимо судьи, уедет им
        как есть. Отвались переход — счётчики разойдутся, и разойдутся молча:
        прогон останется удачным.
        """
        got = await invite()

        assert got.times_ran(STEP_DRAFT) == got.times_ran(STEP_JUDGE), \
            (f'черновиков {got.times_ran(STEP_DRAFT)},'
             f' а судья работал {got.times_ran(STEP_JUDGE)} раз.{got}')

    async def test_a_finished_run_ends_on_a_pass(self, invite):
        """⚠ У дошедшего до конца прогона вердикт — `yes`, и иначе не бывает.

        Дорога `yes` — единственный выход из подпрогона: любое другое слово
        возвращает заход к жребию. Значит «прогон удался, а вердикт не `yes`»
        означает, что переход брака пропускает брак дальше.
        """
        got = await invite()

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'
        assert str(got.vars.get('invite_ok')) == VERDICT_OK, \
            (f'прогон удался с вердиктом {got.vars.get("invite_ok")!r}:'
             f' брак прошёл мимо развилки.{got}')


class TestTheEnvelope:
    """⚠⚠ Конверт ответа — договор с DatingAi, и рвётся он молча.

    Панель разбирает ответ по трём меткам (`mail_agent.INVITE_*_MARK`): пропала
    любая — разбор вернёт пустоту, и пул не наберётся **без единой ошибки в
    журнале**. Стеречь это некому, кроме теста: у соседа прогон удачен.
    """

    async def test_the_answer_carries_all_three_marks(self, invite):
        got = await invite()

        envelope = got.prompt_of(STEP_OUT)

        assert envelope, f'шага ответа панели на маршруте нет.{got}'
        for mark in ENVELOPE:
            assert mark in envelope, \
                f'в конверте нет метки {mark!r}: {envelope[:200]!r}.{got}'

    async def test_the_verdict_mark_comes_first(self, invite):
        """⚠ Порядок важен: панель читает вердикт **до** текста, и метка `TEXT:`
        внутри реплики не должна попасться разбору раньше настоящей."""
        got = await invite()
        envelope = got.prompt_of(STEP_OUT)

        assert envelope.lstrip().startswith('VERDICT:'), \
            f'конверт начинается не с вердикта: {envelope[:120]!r}.{got}'


class TestARefusalStartsOver:
    """⚠⚠ Брак вправду **возвращает** заход к жребию, а не идёт дальше.

    Соседний класс сверяет счётчики «по факту»: как решила модель, так и сверяем.
    Это верно для живого прогона, но одного этого мало — отвались переход брака,
    судья продолжит выносить вердикты, а брак поедет в пул, и счётчики сойдутся:
    черновик один, судья один.

    Здесь вердикт **задан**: первый черновик бракуется, второй проходит. Живой
    моделью так не поставишь — забракует она или нет, решает сама.

    ## ⚠ Почему сценарий однократный

    Примета правила — кусок промпта, а у двух проходов одного шага промпт **один
    и тот же**. Судья, бракующий всегда, гонял бы круг «жребий → черновик →
    судья» до предела шагов движка (300): прогон обрывался бы, ничего не
    проверив. Поэтому оба правила `PLAN_JUDGE_REFUSES` помечены «сработать один
    раз», и второй круг достаётся заготовке (`plan.py`, `plan_load`).
    """

    @pytest.fixture
    async def refused(self, invite, llm_answers):
        """Заход, где судья забраковал первый черновик.

        ⚠ Сценарий кладётся **до** вызова: заготовка папки уступает своему
        (`ask`), и без этого порядка судья пропустил бы черновик сразу.
        """
        await llm_answers(plan_load(PLAN_JUDGE_REFUSES, PLAN_OK))

        return await invite()

    async def test_the_dice_is_rolled_again(self, refused):
        """⚠⚠ Главное: брак уводит **назад, к жребию**, а не вперёд.

        Новый приём — весь смысл переделки: текст не чинят по замечанию, его
        пишут заново, с другого захода. Веди переход брака куда-нибудь ещё —
        второй черновик вышел бы тем же самым, и судья забраковал бы его снова.
        """
        assert refused.times(STEP_DICE) == 2, \
            (f'жребий бросали {refused.times(STEP_DICE)} раз(а), а после брака'
             f' их должно быть два.{refused}')

    async def test_the_second_draft_is_written(self, refused):
        """Забракованный черновик переписывается, а не досылается как есть."""
        assert refused.times_ran(STEP_DRAFT) == 2, \
            (f'черновиков {refused.times_ran(STEP_DRAFT)}, а после брака'
             f' их должно быть два.{refused}')
        assert refused.times_ran(STEP_JUDGE) == 2, \
            f'второй черновик не показали судье.{refused}'

    async def test_the_refused_text_stays_out_of_the_pool(self, refused):
        """⚠⚠ То, ради чего судья заведён: брак не должен уехать людям.

        Проверяем не маршрут, а **накопленное** — то, что уйдёт в пул. Шаг
        накопления работает только на дороге `yes`, и забракованный текст обязан
        остаться за бортом целиком.
        """
        kept = refused.output_of(STEP_KEEP) + refused.prompt_of(STEP_OUT)

        assert DRAFT_GOOD in kept, \
            f'годный черновик до пула не доехал.{refused}'
        assert DRAFT_WEAK not in kept, \
            f'забракованный черновик всё равно уехал в пул.{refused}'

    async def test_only_the_accepted_reply_is_kept(self, refused):
        """⚠ Накопление — ровно одно: реплика в пуле одна, а не две.

        Сработай оно и на браке, пул набрался бы вдвое, и половина его была бы
        тем, что судья отверг.
        """
        assert refused.times_ran(STEP_KEEP) == 1, \
            (f'накопление сработало {refused.times_ran(STEP_KEEP)} раз(а),'
             f' а годная реплика одна.{refused}')

    async def test_a_pass_goes_straight_through(self, invite):
        """⚠ Обратная сторона: судья пропустил — второго круга быть не должно.

        Лишний круг стоит двух вызовов модели на каждый инвайт, а пул набирают
        полусотней.
        """
        got = await invite()

        assert str(got.vars.get('invite_ok')) == VERDICT_OK, \
            f'заготовка должна давать вердикт «{VERDICT_OK}».{got}'
        assert got.times(STEP_DICE) == 1, \
            (f'судья пропустил черновик, а жребий бросали'
             f' {got.times(STEP_DICE)} раз(а).{got}')

"""Маршрут инвайта: цикл, судья и конверт ответа.

⚠⚠ Утверждения — **только по трассе**: маршрут, шаги, промпт после
подстановки. Текст ответа модели не проверяется никогда. Правило и цена,
которой оно куплено, — `.claude/docs/testing_llm.md`.
"""

import pytest

from tests_llm.plan import plan_load
from tests_llm.dating_invite_write.fixtures import (PLAN_JUDGE_FIXES,
                                                    PLAN_OK)

from tests_llm.datingai import ENVELOPE
from tests_llm.dating_invite_write.conftest import (STEP_DRAFT, STEP_FIX,
                                                    STEP_JUDGE, STEP_KEEP,
                                                    STEP_LOOP, STEP_OUT)

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
    """

    async def test_a_fix_means_the_judge_refused(self, invite):
        """⚠ Связь двусторонняя, и проверяется она **по факту**, а не по ожиданию.

        Ждать «судья забракует» нельзя: забракует он или нет, решает модель.
        Зато связь «вердикт `fixed` ⇔ шаг правки пройден» держит переход шага
        (`transitions_after`), и от удачи она не зависит вовсе.

        ⚠⚠ Вердикт здесь — **не предмет проверки, а развилка самой проверки**.
        Пришло неизвестное слово — обе ветки молчат, и тест не притворяется, что
        что-то проверил.
        """
        got = await invite()
        verdict = str(got.vars.get('invite_ok'))

        if verdict == 'fixed':
            assert got.went_through(STEP_FIX), \
                f'вердикт «fixed», а шага правки на маршруте нет.{got}'
        elif verdict == 'yes':
            assert not got.went_through(STEP_FIX), \
                f'судья пропустил черновик, а правка всё равно шла.{got}'


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


class TestTheJudgeSendsItToTheFix:
    """⚠⚠ Судья вправду **уводит** брак на правку, а не просто стоит на пути.

    Соседний класс проверяет согласованность вердикта и маршрута «по факту»: как
    решила модель, так и сверяем. Это верно для живого прогона, но одного этого
    мало — если переход отвалится, судья продолжит выносить вердикты, брак пойдёт
    дальше, и связь «fixed ⇔ правка» станет проверять пустоту: вердикта `fixed`
    просто не появится.

    Здесь вердикт **задан**: судья бракует, правка исправляет. Живой моделью так
    не поставишь — забракует она или нет, решает сама.

    ## ⚠ Почему брак и правка одним сценарием

    Оба шага отвечают **теми же ключами** (`invite_draft`, `invite_ok`), а подмена
    берёт первое совпавшее правило. Разложи их по разным сценариям — правка
    получила бы вердикт судьи и вернула `no` вместо `fixed`, то есть цикл пошёл бы
    вечно (`fixtures.PLAN_JUDGE_FIXES`).
    """

    @pytest.fixture
    async def refused(self, invite, llm_answers):
        """Заход, где судья забраковал черновик.

        ⚠ Сценарий кладётся **до** вызова: заготовка папки уступает своему
        (`ask`), и без этого порядка судья пропустил бы черновик.
        """
        await llm_answers(plan_load(PLAN_JUDGE_FIXES, PLAN_OK))

        return await invite()

    async def test_a_refusal_goes_to_the_fix(self, refused):
        assert refused.went_through(STEP_FIX), \
            (f'судья забраковал черновик, а шага правки на маршруте нет —'
             f' брак уехал бы полусотне людей.{refused}')

    async def test_the_fix_sees_what_was_wrong(self, refused):
        """⚠ Правка обязана **видеть** замечание: без него она переписывала бы
        наугад, и второй черновик вышел бы не лучше первого."""
        said = refused.prompt_of(STEP_FIX)

        assert said, f'шаг правки ничего не получил на вход.{refused}'
        assert 'слишком похоже на шаблон' in said, \
            f'правка не знает, чем плох черновик.{refused}'

    async def test_the_verdict_becomes_fixed(self, refused):
        """⚠⚠ Вердикт после правки — `fixed`, и это не украшение отчёта.

        По нему DatingAi отличает «шаблон исправлен» от «прошёл сразу», а
        соседний класс держит на нём свою развилку. Останься `no` — цикл пошёл бы
        на второй круг правки.
        """
        assert str(refused.vars.get('invite_ok')) == 'fixed', \
            (f'после правки вердикт {refused.vars.get("invite_ok")!r},'
             f' а ждали «fixed».{refused}')

    async def test_a_pass_skips_the_fix(self, invite):
        """⚠ Обратная сторона: судья пропустил — правки быть не должно.

        Лишний заход правки стоит вызова модели на каждый инвайт, а пул набирают
        полусотней.
        """
        got = await invite()

        assert str(got.vars.get('invite_ok')) == 'yes', \
            f'заготовка должна давать вердикт «yes».{got}'
        assert not got.went_through(STEP_FIX), \
            f'судья пропустил черновик, а правка всё равно шла.{got}'

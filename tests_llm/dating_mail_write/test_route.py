"""Маршрут черновика письма: пять ворот, цикл переписывания и конверт.

⚠⚠ Утверждения — **только по трассе**: маршрут, шаги, промпт после
подстановки. Текст ответа модели не проверяется никогда. Правило и цена,
которой оно куплено, — `.claude/docs/testing_llm.md`.

## ⚠ Почему проверки маршрута здесь важнее, чем у других workflow

Ворот пять, и четверо из них — обычные инструменты, а не модель: они считают
метки и ищут неизвестные имена. Отключись любые — прогон останется зелёным,
письмо придёт, и брак заметит только человек. Или не заметит: шаблон уходит в
рассылку сотням людей.
"""

import pytest

from tests_llm.datingai import TITLE_MARK
from tests_llm.plan import plan_load
from tests_llm.dating_mail_write.conftest import (STEP_INLINE, STEP_LANG,
                                                  STEP_MISSING, STEP_OUT,
                                                  STEP_SAME, STEP_VARS,
                                                  STEP_WHY, STEP_WRITE,
                                                  TRIES_MAX)
from tests_llm.dating_mail_write.fixtures import (PLAN_INLINE, PLAN_LANG_BAD,
                                                  PLAN_NO_MARKS, PLAN_OK,
                                                  PLAN_SAME, PLAN_SOME_MARKS,
                                                  PLAN_UNKNOWN_MARK)

pytestmark = pytest.mark.llm


class TestTheRunGoesThrough:
    """Первое: черновик вообще сочиняется."""

    async def test_the_run_ends_with_success(self, letter):
        got = await letter()

        assert got.status == 'success', f'прогон не дошёл до конца.{got}'

    async def test_the_letter_is_written(self, letter):
        got = await letter()

        assert got.went_through(STEP_WRITE), f'письмо не сочинялось.{got}'


class TestEveryGateIsPassed:
    """⚠⚠ Все пять проверок обязаны стоять на пути, а не половина.

    Каждая заведена по живому случаю, и каждая ловит своё:

    | Ворота | Что ловят |
    |---|---|
    | Переменные | выдуманную метку — уедет человеку прямо в скобках |
    | Язык верный? | чужой язык — фильтр сайта письмо отклонит |
    | Вопрос отдельно? | живую метку внутри фразы: «What are What do you enjoy??» |
    | Все ли метки? | имена, написанные словами вместо переменных |
    | Судья: не повтор ли? | четвёртое письмо подряд про плед и дождь |
    """

    async def test_the_unknown_marks_are_checked(self, letter):
        got = await letter()

        assert got.went_through(STEP_VARS), \
            f'выдуманные метки никто не ищет.{got}'

    async def test_the_language_is_checked(self, letter):
        got = await letter()

        assert got.went_through(STEP_LANG), \
            f'язык письма никто не проверяет.{got}'

    async def test_the_inline_marks_are_checked(self, letter):
        got = await letter()

        assert got.went_through(STEP_INLINE), \
            f'встроенные в фразу живые метки никто не ищет.{got}'

    async def test_the_missing_marks_are_checked(self, letter):
        """⚠ Эти ворота заведены последними и отвечают на четвёртый вопрос.

        Шаблон, где половина имён написана словами, проходил все прежние
        проверки: лишнего в нём нет, язык верен, живой метки нет — значит она «не
        встроена». Полноту спросить было некому.
        """
        got = await letter()

        assert got.went_through(STEP_MISSING), \
            f'полноту меток никто не проверяет.{got}'

    async def test_the_repeat_judge_runs(self, letter):
        got = await letter()

        assert got.went_through(STEP_SAME), \
            f'повтор прошлых писем никто не судит.{got}'


# ⚠⚠ **Здесь был класс `TestTheRewriteLoop`, и он проверял цикл впустую.**
#
# Три теста: два вызывали `pytest.skip`, если цикла не случилось, а третий
# утверждал `times(STEP_WRITE) <= 3`. С годной заготовкой цикла не случается
# никогда — значит первые два **всегда** пропускались, а третий был верен
# тривиально (один заход из трёх возможных).
#
# То есть класс выглядел покрытием, а не был им: путь брака оставался
# непроверенным, и оба пропуска висели в отчёте прогона как норма.
#
# Цикл теперь проверяет `TestEachGateSendsItBack` ниже — каждыми воротами
# отдельно и без пропусков. Там же и потолок: изъян неисправим, поэтому заходов
# ровно три.


class TestTheEnvelope:
    """⚠⚠ Название и текст приходят одной строкой — это договор с DatingAi.

    Разбирает его `mail_agent._letter_named`: метка `TITLE:`, перенос, письмо.
    JSON тут не годится — в письме переносы строк, а `%letter%` их не
    экранирует, и первый же порвал бы разбор.
    """

    async def test_the_answer_starts_with_the_title_mark(self, letter):
        got = await letter()
        envelope = got.prompt_of(STEP_OUT)

        assert envelope, f'шага ответа на маршруте нет.{got}'
        assert envelope.lstrip().startswith(TITLE_MARK), \
            f'ответ начинается не с метки названия: {envelope[:120]!r}.{got}'

    async def test_the_title_and_the_letter_are_separated(self, letter):
        """⚠ Разделитель — пустая строка: по первому переносу режет разбор, и
        слипшись, название уехало бы в текст письма."""
        got = await letter()
        envelope = got.prompt_of(STEP_OUT)

        head, _, tail = envelope.partition('\n')

        assert head.strip() != envelope.strip(), \
            f'название и письмо не разделены переносом.{got}'
        assert tail.strip(), f'после названия письма нет вовсе.{got}'


class TestEachGateSendsItBack:
    """⚠⚠ Каждые ворота **вправду возвращают** негодное письмо на переписывание.

    Соседний класс проверяет, что ворота стоят на пути. Этого мало: ворота могут
    стоять и ни на что не влиять — условие перехода отвалилось, письмо идёт
    дальше, и брак уезжает в рассылку сотням людей. Зелёный прогон при этом
    остаётся зелёным.

    Здесь каждая проверка **ломается намеренно**, и утверждение одно: заход
    вернулся к сочинению.

    ## ⚠ Пятеро ворот, и изъян у каждого свой

    | Ворота | Чем ломаем | Кто решает |
    |---|---|---|
    | Переменные | метка `favourite_song`, которой нет в реестре | инструмент |
    | Вопрос отдельно? | живая метка внутри фразы | инструмент |
    | Все ли метки? | письмо без меток вовсе | инструмент |
    | Язык верный? | вердикт `letter_lang_ok = 0` | модель |
    | Судья: не повтор ли? | вердикт `letter_same = yes` | модель |

    ⚠⚠ Общим негодным письмом это не проверить: оно упёрлось бы в **первые**
    ворота, и остальные четверо снова остались бы без проверки. Поэтому у каждого
    теста свой изъян, а прочее в письме верно.

    ## ⚠⚠ Дойти до потолка — часть проверки, а не побочный итог

    Изъян никуда не девается: модель отвечает тем же на каждом заходе. Значит
    письмо сочиняется трижды и уходит как есть — ровно то поведение, которое
    задумано (`write_try < 3`). Живой моделью этого не проверить: заставить её
    забраковать письмо трижды подряд нельзя.
    """

    async def _rejected(self, letter, llm_answers, plan, step: str):
        """Заход с одним изъяном: вернулся ли он к сочинению.

        ⚠ Сценарий кладётся **до** вызова: заготовка папки уступает своему
        (`ask`), и без этого порядка тест получил бы годное письмо.
        """
        await llm_answers(plan_load(plan, PLAN_OK))

        got = await letter()

        assert got.times(STEP_WRITE) > 1, \
            (f'{step}: письмо с изъяном прошло с первого раза — ворота стоят,'
             f' но никуда не возвращают.{got}')
        assert got.went_through(STEP_WHY), \
            f'{step}: письмо переписывали, а замечания никто не собрал.{got}'

        return got

    async def test_an_unknown_mark_goes_back(self, letter, llm_answers):
        await self._rejected(letter, llm_answers, PLAN_UNKNOWN_MARK, STEP_VARS)

    async def test_an_inline_mark_goes_back(self, letter, llm_answers):
        await self._rejected(letter, llm_answers, PLAN_INLINE, STEP_INLINE)

    async def test_a_letter_without_any_marks_goes_back(self, letter, llm_answers):
        """⚠⚠ Письмо без единой метки отсеивают **первые** ворота, а не «Все ли
        метки?»: у шага «Переменные» два условия, и второе — `found_qty == 0`.

        Разница не формальная. Шаблон без меток уходит всем сорока девушкам одним
        текстом, и заметить это по одному письму нельзя.
        """
        await self._rejected(letter, llm_answers, PLAN_NO_MARKS, STEP_VARS)

    async def test_missing_marks_go_back(self, letter, llm_answers):
        """⚠ Здесь метки есть, все известны, вопрос отдельно — не хватает одной
        обязательной. Только так заход доходит до ворот «Все ли метки?»."""
        await self._rejected(letter, llm_answers, PLAN_SOME_MARKS, STEP_MISSING)

    async def test_a_wrong_language_goes_back(self, letter, llm_answers):
        await self._rejected(letter, llm_answers, PLAN_LANG_BAD, STEP_LANG)

    async def test_a_repeat_verdict_goes_back(self, letter, llm_answers):
        await self._rejected(letter, llm_answers, PLAN_SAME, STEP_SAME)

    async def test_the_reason_reaches_the_next_pass(self, letter, llm_answers):
        """⚠ Второй заход обязан **видеть**, чем плох первый.

        Не увидит — будет переписывать наугад, и три захода дадут три одинаково
        негодных письма вместо одного исправленного.
        """
        got = await self._rejected(letter, llm_answers, PLAN_LANG_BAD, STEP_LANG)
        passes = got.prompt_each(STEP_WRITE)

        assert len(passes) > 1, f'второго захода не было вовсе.{got}'
        assert 'НЕ ГОДИТСЯ:' in passes[1], \
            f'второй заход сочинял, не зная, чем плох первый.{got}'

    async def test_the_ceiling_holds_when_nothing_improves(self, letter,
                                                           llm_answers):
        """⚠⚠ Изъян неисправим — значит потолок обязан остановить цикл.

        Без потолка заход крутился бы до таймаута движка, и человек получил бы
        `504` вместо письма с изъяном. Здесь модель отвечает одним и тем же, то
        есть условие выхода наступить не может — остаётся только предел.
        """
        got = await self._rejected(letter, llm_answers, PLAN_LANG_BAD, STEP_LANG)

        assert got.times(STEP_WRITE) == TRIES_MAX, \
            (f'неисправимое письмо сочинялось {got.times(STEP_WRITE)} раз,'
             f' а предел {TRIES_MAX}.{got}')
        assert got.status == 'success', \
            f'упёрлись в потолок и уронили прогон вместо выдачи письма.{got}'

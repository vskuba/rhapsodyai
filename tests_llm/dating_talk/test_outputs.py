"""Ответ модели доезжает до переменной, которую workflow по нему назвал.

## ⚠⚠ ЗАЧЕМ: это проводка, и она была не проверена вовсе

Шаг `llm_to_json` не просто спрашивает модель — он **раскладывает** её ответ по
переменным workflow. Раскладка описана в `llm_to_json_variable`: список пар «о чём
спросить» → «в какую переменную положить». У «Анализа сообщения» таких пар **восемь**.

Подпоток раскладывает иначе — `outputs_map` шага вызова. У ветки «письма и фото» там
две пары, и одна из них переименовывает:

    {"photo_deal": "photo_deal",
     "draft_response": "girl_response"}

⚠ Пар было три: ветка отдавала ещё и правку судьи (`photo_fixed →
girl_response_fixed`). Судью переделали на вердикт с перегенерацией, и правка
исчезла из карты вместе со своим смыслом.

До этого файла ни один тест не утверждал, что хоть одно значение **доехало**.
`photo_deal` вообще встречался в сюите только как вход подмены, никогда как предмет
проверки.

## ⚠⚠⚠ Две раскладки, и молчит только одна — проверено диверсией

**`llm_to_json_variable` защищён движком.** Переименуй пару у «Анализа сообщения» —
и заход падает сам, назвав виновника: «В ответе LLM отсутствуют обязательные ключи
воркфлоу: ['tags_renamed']». Проверено подменой имени в базе: тест краснеет, и
причина в первой же строке отказа.

Отсюда честная оценка: тесты этого файла для `llm_to_json` — **не единственный
сторож, а второй**. Польза от них в том, что они называют беду своими словами
(«раскладка разошлась») и покрывают все восемь пар разом, а не ту одну, что
попалась под руку прогону.

**`outputs_map` подпотока не защищён ничем, и вот это тихо.** Убрал пару
`photo_fixed` — заход прошёл насквозь, статус `success`, ответ правдоподобный, и
поймала потерю только проверка ниже. А теряется там **правка судьи**: человеку
уезжает черновик вместо исправленного текста (`test_branches.py`,
`TestThePhotoBranchAnswersInCommon`).

То есть из четырёх тестов файла три страхуют, а один — единственный сторож.

## ⚠⚠ Значения задаёт тест, и в этом весь смысл

Здесь не спрашивают у модели, что она думает, — ей **велят** ответить. Предмет
проверки не её суждение, а наша раскладка: сказала столько-то — значит в
переменной обязано лежать столько же.

Суждение модели (правда ли просьба о фото поднимает тему) проверяется отдельно и
живьём: `test_judgement.py`. Это два разных вопроса, и путать их нельзя.

## ⚠⚠ Значения — НЕ как умолчание, иначе тест пуст

`got.vars` собирается из `variables_changed` трассы, то есть из того, что шаги
**поменяли**. Положи значение, равное прежнему, — записи не будет вовсе, и
`vars.get(...)` вернёт `None` при исправной раскладке.

Поймано пробой: `prompt_user_ignore = '0'` в трассе не появился, а `'1'` появился.
Отсюда правило: приметы здесь нарочные и не совпадают ни с умолчанием, ни друг с
другом.
"""

import pytest

from tests_llm.dating_talk.conftest import (ANYWAY, ASK_ANALYSE,
                                            FACTS_MAN, FACTS_TALK, STEP_BRANCH,
                                            analyse_answer,
                                            photo_answer, talk_plan)

pytestmark = pytest.mark.llm

# Нарочные значения: ни одно не совпадает с умолчанием заготовки (см. ⚠⚠ выше).
#
# ⚠ Приметы редкие и разные между собой: увидев `zz-tags` в переменной, тест знает,
# что туда попало **наше** значение, а не совпадение с чем-то из промпта.
#
# ⚠⚠ Два поля фактов — **готовые записи**, а не строки: их читает подпрогон
# сохранения, и на строке он падает «не удалось распарсить как валидный
# JSON-массив». Заход при этом обрывается целиком, и красное говорит «агент не
# ответил» — про формат ни слова. Поймано здесь же, первым прогоном.
#
# ⚠⚠ Собирается `analyse_answer`, а не пишется словарём: ключи шага живут в самом
# шаге и меняются вместе с промптом. Здесь перечислено только то, что этот тест
# **проверяет** — приметы на выходе, — остальное доберётся заглушкой.
#
# ⚠⚠⚠ `filler` здесь нарочный, а не пустой: тест проверяет **доезд** значений, а
# трасса пишет только изменённое — пустая строка в неё не попадёт. С приметой
# ключ, добавленный в шаг завтра, проверится сам, без правки этого файла.
ANALYSED = analyse_answer(
    filler='zz-filler',
    session_messages_result_processed='zz-summary',
    prompt_user_category='zz-category',
    prompt_user_tags='zz-tags',
    prompt_user_question='1',
    search_query='zz-query',
    prompt_user_facts_companion=FACTS_MAN,
    prompt_user_facts_talk=FACTS_TALK,
    prompt_user_ignore='0')

# Придуманное подпрогоном — тоже готовая запись, и по той же причине.
FACTS_GIRL = ('[{"language": "en", "tags": "weather", '
              '"document": "She watches storms from the lighthouse."}]')

# Ответы ветки «письма и фото»: два выхода, и один из них переименовывается.
#
# ⚠⚠⚠ Выходов стало два, а было три. Ветку переписали вместе с судьёй: вместо
# правки текста (`photo_fixed → girl_response_fixed`) она теперь отдаёт черновик
# и вердикт, а правит перегенерацией. `photo_response` при этом стал
# `draft_response`. Старые имена держались здесь руками — и уронили тест
# молчанием «агент не ответил».
BRANCHED = {'photo_deal': 'zz-deal',
            'draft_response': 'zz-response'}

# Умолчание ветки со своими значениями поверх общего: сами выходы нам нужны
# нарочные, остальное — как у всех (`photo_answer` в `conftest.py` папки).
PHOTO_ANSWERS = photo_answer(**BRANCHED)


class TestTheTopicArrives:
    """Текст, в котором шаг темы ищет метки, обязан нести пришедшую реплику.

    ## ⚠⚠ Здесь живёт поломка, которую код не показывает

    Шагу называют переменную с историей, а пришедшее сообщение лежит отдельно,
    в `prompt_user`. Подай шагу `talk_history_chat` — и реплика «Can you send me
    your photos?» в текст не попадёт: метки `send` и `photos` искать будет
    негде, тема не поднимется ни разу, и выглядеть это будет как обычный ответ.
    Ровно так и случилось при переводе шага на новый род.

    Поэтому проверяется склейка: `talk_history_topic` содержит слова реплики.
    """

    async def test_the_history_carries_the_incoming_line(self, talk, llm_answers):
        await llm_answers(talk_plan(), default=PHOTO_ANSWERS)

        got = await talk('Can you send me your photos?', variables=ANYWAY)

        history = str(got.vars.get('talk_history_topic') or '')
        assert 'send me your photos' in history, \
            f'пришедшая реплика не попала в текст для меток: {history!r}.{got}'


class TestTheAnalysisVariablesArrive:
    """⚠⚠ Восемь пар раскладки у одного шага — и все восемь чего-то держат.

    `prompt_user_tags` — вход поиска фактов. `prompt_user_question` — развилка к
    подпрогону выдумывания. `prompt_user_facts_*` — вход сохранения. `search_query` —
    запрос к Qdrant. Потеряйся любая, беда будет тихой и разной.
    """

    async def test_every_named_variable_gets_its_value(self, talk, llm_answers):
        """⚠ Проверяются **все** пары разом, а не две на выбор.

        Прежде живьём проверялись две (`prompt_user_tags`, `prompt_user_question`) —
        и проверялось в них не это, а сообразительность модели.
        """
        # ⚠ `prompt_user_question = '1'` уводит в подпрогон выдумывания фактов —
        # значит ему нужен ответ, иначе заход обрывается на нём.
        await llm_answers(talk_plan(extra=[(ASK_ANALYSE, ANALYSED)],
                                    facts_girl=FACTS_GIRL),
                          default=PHOTO_ANSWERS)

        got = await talk('I work as a carpenter and I love fishing.',
                         variables=ANYWAY)

        missed = {name: (value, got.vars.get(name))
                  for name, value in ANALYSED.items()
                  # ⚠ `prompt_user_ignore` здесь `'0'` — то же, что умолчание, и в
                  # трассу он не попадёт. Проверять его надо заходом, где он `'1'`,
                  # а такой уводит в «Тишину»: это делает `test_route.py`.
                  if name != 'prompt_user_ignore'
                  and got.vars.get(name) != value}

        assert not missed, ('раскладка ответа по переменным разошлась с '
                            f'`llm_to_json_variable`: {missed}.{got}')


class TestTheBranchOutputsArrive:
    """⚠⚠⚠ Выходы подпотока: здесь живёт единственная **молчаливая** поломка.

    `outputs_map` ветки переименовывает одно значение из двух, и потеря ответа
    (`draft_response → girl_response`) по ответу человека не видна: общий шаг
    отдал бы пустоту либо прошлое значение, а выглядело бы это как обычный
    ответ.
    """

    async def test_both_outputs_come_out(self, talk, llm_answers):
        await llm_answers(talk_plan(), default=PHOTO_ANSWERS)

        got = await talk('Can you send me your photos?', variables=ANYWAY)

        assert got.ran(STEP_BRANCH), f'ветка не сработала — проверять нечего.{got}'

        # ⚠ Имя слева — переменная **подпотока**, и в переменных родителя её
        # может не быть вовсе: `draft_response` приезжает под именем
        # `girl_response`. Поэтому сверяем по карте, а не по ключу вслепую.
        assert got.vars.get('photo_deal') == BRANCHED['photo_deal'], \
            f'выход `photo_deal` не доехал: {got.vars.get("photo_deal")!r}.{got}'

    async def test_the_draft_is_renamed_on_the_way_out(self, talk, llm_answers):
        """⚠⚠ Пара `outputs_map` **переименовывает**, и проверяется именно это.

        `draft_response → girl_response`. Общий шаг «Ответ» читает второе имя и
        ничего не знает о первом: разойдись карта — он отдал бы пустоту либо
        прошлое значение.

        ⚠ Прежде пар было две: ветка отдавала ещё и правку судьи
        (`photo_fixed → girl_response_fixed`). Судью переделали на вердикт с
        перегенерацией, и правка исчезла из карты вместе со своим смыслом.
        """
        await llm_answers(talk_plan(), default=PHOTO_ANSWERS)

        got = await talk('Can you send me your photos?', variables=ANYWAY)

        assert got.vars.get('girl_response') == BRANCHED['draft_response'], \
            f'`draft_response` не переименовался в `girl_response`.{got}'

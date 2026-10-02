"""Ответ модели доезжает до переменной, которую workflow по нему назвал.

## ⚠⚠ ЗАЧЕМ: это проводка, и она была не проверена вовсе

Шаг `llm_to_json` не просто спрашивает модель — он **раскладывает** её ответ по
переменным workflow. Раскладка описана в `llm_to_json_variable`: список пар «о чём
спросить» → «в какую переменную положить». У «Анализа сообщения» таких пар **восемь**.

Подпоток раскладывает иначе — `outputs_map` шага вызова. У ветки «письма и фото» там
три пары, и одна из них переименовывает:

    {"photo_deal": "photo_deal",
     "photo_response": "girl_response",
     "photo_fixed": "girl_response_fixed"}

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
проверки не её суждение, а наша раскладка: сказала `photo_mail` — значит в
`talk_topic` обязано лежать `photo_mail`.

Суждение модели (правда ли просьба о фото — это `photo_mail`) проверяется отдельно и
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

from tests_llm.dating_talk.conftest import (ANSWER_PHOTO, ANYWAY, ASK_ANALYSE,
                                            FACTS_MAN, FACTS_TALK, STEP_BRANCH,
                                            STEP_TOPIC, analyse_answer,
                                            talk_plan)

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

# Ответы ветки «письма и фото»: три выхода, и два из них переименовываются.
BRANCHED = {'photo_deal': 'zz-deal',
            'photo_response': 'zz-response',
            'photo_fixed': 'zz-fixed'}

# Умолчание ветки со своими значениями поверх общего: сами выходы нам нужны нарочные,
# остальное — как у всех (`ANSWER_PHOTO` в `conftest.py` папки).
PHOTO_ANSWERS = {**ANSWER_PHOTO, **BRANCHED}


class TestTheTopicArrives:
    """⚠ Одна пара раскладки, и на ней держится вся развилка веток."""

    async def test_the_topic_reaches_its_variable(self, talk, llm_answers):
        """Сказала `photo_mail` — значит в `talk_topic` лежит `photo_mail`."""
        await llm_answers(talk_plan(topic='photo_mail'), default=PHOTO_ANSWERS)

        got = await talk('Can you send me your photos?', variables=ANYWAY)

        assert got.ran(STEP_TOPIC), f'шаг темы не отработал.{got}'
        assert got.vars.get('talk_topic') == 'photo_mail', \
            f'ответ шага темы не доехал до `talk_topic`.{got}'


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

    `outputs_map` ветки переименовывает два значения из трёх, и потеря правки судьи
    (`photo_fixed → girl_response_fixed`) по ответу не видна: человеку уедет
    черновик, правдоподобный и непроверенный.
    """

    async def test_all_three_outputs_come_out(self, talk, llm_answers):
        await llm_answers(talk_plan(topic='photo_mail'), default=PHOTO_ANSWERS)

        got = await talk('Can you send me your photos?', variables=ANYWAY)

        assert got.ran(STEP_BRANCH), f'ветка не сработала — проверять нечего.{got}'

        for name, value in BRANCHED.items():
            assert got.vars.get(name) == value, \
                f'выход ветки `{name}` не доехал: {got.vars.get(name)!r}.{got}'

    async def test_the_judges_fix_is_renamed_on_the_way_out(self, talk, llm_answers):
        """⚠⚠ Две пары `outputs_map` **переименовывают**, и проверяется именно это.

        `photo_response → girl_response`, `photo_fixed → girl_response_fixed`.
        Общий шаг «Ответ» читает вторые имена и ничего не знает о первых: разойдись
        карта — он отдал бы пустоту либо прошлое значение.
        """
        await llm_answers(talk_plan(topic='photo_mail'), default=PHOTO_ANSWERS)

        got = await talk('Can you send me your photos?', variables=ANYWAY)

        assert got.vars.get('girl_response') == BRANCHED['photo_response'], \
            f'`photo_response` не переименовался в `girl_response`.{got}'
        assert got.vars.get('girl_response_fixed') == BRANCHED['photo_fixed'], \
            f'правка судьи не доехала до `girl_response_fixed`.{got}'

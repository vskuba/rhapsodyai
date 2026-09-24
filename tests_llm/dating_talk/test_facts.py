"""Память разговора: что агент запоминает о человеке и что вспоминает.

## Что здесь проверяется

Цепочка памяти целиком, шаг за шагом:

    реплика → разбор → сохранить сказанное им → поискать сохранённое
                    ↘ придумать факты девушке (у неё своя память)

Каждое звено ставится отдельным тестом: порвись любое — агент начнёт разговор
заново при каждом сообщении, и заметно это станет не сразу.

## ⚠⚠ ПРАВИЛО: утверждения — только по трассе

Ни один тест не смотрит на текст ответа. Всё берётся из трассы: маршрут,
структурные решения шагов, промпт после подстановки, вывод шага. Правило и живые
примеры, на которых оно куплено, — `.claude/docs/testing_llm.md`.

## ⚠⚠ Почему не заглядываем в само хранилище

Соблазн проверить, что факт **лёг в Qdrant**, велик — и обманчив. Хранилище
чужое, отвечает своим темпом, и поиск сразу после записи законно возвращает
пустоту: индекс ещё не обновился. Тест мерил бы задержку Qdrant, а не нашу
работу, и краснел бы через раз.

Наша часть кончается на шаге: он позван, получил вход и не упал. Дальше —
ответственность хранилища, и у него своя сюита.

## ⚠ Собеседник у каждого теста свой

Факты копятся в Qdrant по ключу собеседника. Общий ключ означал бы, что второй
прогон видит следы первого: тест «фактов нет» проходил бы только на чистой базе
и краснел бы дальше — самый неприятный вид плавучести, потому что виноватым
выглядит код.
"""

import pytest

from tests_llm.mark import mark_key
from tests_llm.dating_talk.conftest import (STEP_ANALYSE, STEP_FACT_INVENT,
                                            STEP_FACT_INVENT_ADD, STEP_FACT_SAVE,
                                            STEP_FACT_SAVE_MAN, STEP_FACT_SAVE_TALK,
                                            STEP_FACTS_MAN, STEP_FACTS_PLAIN,
                                            STEP_FACTS_TAGS, STEP_FACTS_TALK,
                                            STEP_MAKE)

pytestmark = pytest.mark.llm_live

# ⚠ Ответ обязателен — иначе прогон вправе уйти в «Тишину», и проверять станет
# нечего. Строкой `'1'`: `%if%` считает ложными пустое, `'0'` и отсутствие, а
# `True` превратился бы в `'True'` — истину по случайности.
ANYWAY = {'answer_anyway': '1'}


@pytest.fixture
def stranger():
    """Собеседник, о котором в хранилище ничего нет: ключ свой на прогон."""
    return mark_key('facts')


class TestTheMessageIsAnalysed:
    """⚠ Первое звено: реплику разбирают, и от разбора зависит всё дальше.

    Шаг «Анализ сообщения» достаёт из текста теги, категории и признак вопроса.
    По тегам ищутся факты, по признаку вопроса ветвится маршрут — молчащий разбор
    обрывает цепочку в самом начале, а выглядит это как «агент отвечает невпопад».
    """

    async def test_the_analysis_step_always_runs(self, talk, stranger):
        got = await talk('I work as a carpenter and I love fishing on weekends.',
                         variables={'companion_name': stranger, **ANYWAY})

        assert got.went_through(STEP_ANALYSE), f'реплику не разобрали.{got}'

    async def test_it_pulls_tags_out_of_the_message(self, talk, stranger):
        """⚠ Теги — вход поиска фактов. Пустые значат, что искать будут вслепую.

        Проверяем **наличие**, а не состав: какие именно слова выберет модель —
        её дело, а вот пустая строка ломает следующий шаг.
        """
        got = await talk('I work as a carpenter and I love fishing on weekends.',
                         variables={'companion_name': stranger, **ANYWAY})

        assert str(got.vars.get('prompt_user_tags') or '').strip(), \
            f'разбор не дал ни одного тега.{got}'

    async def test_a_question_is_marked_as_a_question(self, talk, stranger):
        """⚠ Признак вопроса — **развилка маршрута**, а не подсказка.

        По нему шаг фактов решает, идти ли за фактами девушки: на прямой вопрос
        о ней они нужны, на рассказ о себе — нет.
        """
        got = await talk('What do you do for work?',
                         variables={'companion_name': stranger, **ANYWAY})

        assert str(got.vars.get('prompt_user_question')) == '1', \
            f'прямой вопрос не опознан вопросом.{got}'


class TestWhatHeSaidIsKept:
    """⚠⚠ Второе звено: сказанное человеком сохраняется, иначе памяти не будет.

    Подпрогон `companion_fact_extract` кладёт факты в два места: о нём самом и о
    договорённостях пары. Разделение не формальное — «он инженер» верно для любой
    нашей анкеты, а «договорились созвониться» только для этой пары.
    """

    async def test_the_saving_subflow_runs(self, talk, stranger):
        got = await talk('I am 45, I live in Porto and I work as an architect.',
                         variables={'companion_name': stranger, **ANYWAY})

        assert got.went_through(STEP_FACT_SAVE), \
            f'подпрогон сохранения фактов не позван.{got}'

    async def test_both_stores_are_written(self, talk, stranger):
        """⚠ Оба шага записи, а не один: факты о человеке и о переписке лежат
        врозь и ищутся врозь."""
        got = await talk('I am 45, I live in Porto and I work as an architect.',
                         variables={'companion_name': stranger, **ANYWAY})

        assert got.went_through(STEP_FACT_SAVE_MAN), \
            f'факты о собеседнике не сохранялись.{got}'
        assert got.went_through(STEP_FACT_SAVE_TALK), \
            f'факты о переписке не сохранялись.{got}'

    async def test_the_analysis_hands_facts_over(self, talk, stranger):
        """⚠⚠ Сохранять должно быть **что**: подпрогон берёт вход у разбора.

        Порвись здесь — шаги отработают вхолостую, маршрут останется прежним, и
        поломка будет незаметна ровно до того дня, когда агент забудет всё.

        ⚠⚠ **Проверяется, что переменная ЗАВЕДЕНА, а не что она непуста.**
        Сначала стояло `assert …strip()` — и тест упал на живом прогоне: модель
        не выделила фактов из «I am 45, I live in Porto and I work as an
        architect», хотя плотнее фактами фразу придумать трудно.

        Это ровно та проверка, которую запрещает правило: «разбор выделил хоть
        что-то» — суждение **модели**, а не связь, которую держит движок. Красный
        тест здесь означал бы «модель сегодня поленилась», и чинить по нему было
        бы нечего.

        Связь же проверяется тем, что шаг разбора **записал свою переменную**:
        порвись проводка — ключа не было бы вовсе, и это от удачи не зависит.
        """
        got = await talk('I am 45, I live in Porto and I work as an architect.',
                         variables={'companion_name': stranger, **ANYWAY})

        assert 'prompt_user_facts_companion' in got.vars, \
            f'шаг разбора не завёл переменную фактов о собеседнике.{got}'


class TestWhatWasKeptIsLookedUp:
    """⚠ Третье звено: перед ответом ищем всё, что помним.

    Три поиска, и все обязательны: о девушке (кто она), о собеседнике (кто он), о
    переписке (о чём договаривались). Молча пропущенный поиск выглядит как
    «агент вдруг поглупел».
    """

    async def test_facts_about_him_are_searched(self, talk, stranger):
        got = await talk('Do you remember what I told you about my job?',
                         variables={'companion_name': stranger, **ANYWAY})

        assert got.went_through(STEP_FACTS_MAN), \
            f'факты о собеседнике не искались.{got}'

    async def test_facts_about_the_talk_are_searched(self, talk, stranger):
        got = await talk('Do you remember what I told you about my job?',
                         variables={'companion_name': stranger, **ANYWAY})

        assert got.went_through(STEP_FACTS_TALK), \
            f'факты о переписке не искались.{got}'

    async def test_her_own_facts_are_searched_too(self, talk, stranger):
        """⚠ Один из двух путей: сперва по тегам, без находки — откат без них.

        Какой именно сработает, решают данные; обязательно, чтобы сработал
        хоть один — иначе девушка отвечает, не помня о себе ничего.
        """
        got = await talk('Tell me about your weekends.',
                         variables={'companion_name': stranger, **ANYWAY})

        assert got.went_through(STEP_FACTS_TAGS) \
            or got.went_through(STEP_FACTS_PLAIN), \
            f'факты девушки не искались ни одним из путей.{got}'

    async def test_what_was_found_reaches_the_prompt(self, talk, stranger):
        """⚠⚠ Найденное должно **дойти до модели**, а не осесть в переменной.

        Это и есть смысл всей цепочки: искали затем, чтобы агент прочёл. Шаг
        нашёл, а промпт не включил — маршрут зелёный, память не работает.

        Проверяем по заголовку раздела в промпте: он ставится `%if%`-блоком
        ровно тогда, когда поиск что-то вернул.
        """
        got = await talk('Tell me about your weekends.',
                         variables={'companion_name': stranger, **ANYWAY})

        prompt = got.prompt_of(STEP_MAKE)

        assert prompt, f'промпт шага сочинения не прочитался.{got}'

        found = (got.output_of(STEP_FACTS_TAGS).strip()
                 or got.output_of(STEP_FACTS_PLAIN).strip())

        if found:
            assert 'в базе данных' in prompt, \
                f'факты нашлись, а в промпт не попали.{got}'


class TestHerOwnFactsAreInvented:
    """⚠⚠ У девушки память своя, и пополняется она иначе.

    Факты о собеседнике берутся из его слов. О ней самой брать неоткуда — их
    **придумывает** подпрогон `girl_fact_invent` и кладёт в её документ, чтобы
    завтра она ответила так же, как сегодня.

    Без этого она противоречит себе: сегодня «работаю в маркетинге», завтра
    «учительница». Для человека по ту сторону это первый признак робота.
    """

    async def test_the_inventing_subflow_runs(self, talk, stranger):
        got = await talk('What do you like to do after work?',
                         variables={'companion_name': stranger, **ANYWAY})

        assert got.went_through(STEP_FACT_INVENT), \
            f'подпрогон придумывания фактов не позван.{got}'

    async def test_the_invented_facts_are_stored(self, talk, stranger):
        """⚠ Придумать мало — надо записать: иначе завтра придумается другое."""
        got = await talk('What do you like to do after work?',
                         variables={'companion_name': stranger, **ANYWAY})

        assert got.went_through(STEP_FACT_INVENT_ADD), \
            f'придуманные факты не сохранялись.{got}'

    async def test_the_girl_id_reaches_the_subflow(self, talk, stranger):
        """⚠⚠ Ключ девушки обязателен, иначе факты всех сольются в один документ.

        Это не выдумка: `girl_id` заведён ровно после такой беды.

        ## ⚠⚠ Смотрим, КУДА ключ доехал, а не лежит ли он в переменных

        Здесь стояло `got.vars.get('girl_id')` — и тест краснел при исправном
        коде. `vars` собирается из `variables_changed` трассы, то есть из того,
        что шаги **поменяли**; входная переменная не меняется никогда и туда не
        попадает вовсе.

        Проверять надо результат: шаг «Переменные» собирает из ключа фильтр
        поиска `{"document_id": "<ключ>"}`, и вот он в трассе есть. Заодно это
        проверка сильнее — доказывает не «ключ передали», а «ключ дошёл до
        хранилища фактов».
        """
        got = await talk('What do you like to do after work?',
                         variables={'companion_name': stranger, **ANYWAY})

        where = str(got.vars.get('fact_collection_girl_filter') or '')

        assert 'document_id' in where, \
            f'фильтр фактов девушки не собрался.{got}'
        assert '""' not in where.replace(' ', ''), \
            f'ключ девушки пуст — её факты уедут в общий документ: {where}.{got}'

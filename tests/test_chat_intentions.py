"""Намерения прогона доезжают от инструмента до ручки `/chat/ask`.

## ⚠⚠ Что здесь стережётся

`chat_intention_add` сам ничего не хранит: он отдаёт намерение словом, а копит
их движок — в `model.chat_intentions`, узнавая инструмент **по имени**
(`AI_FRAMEWORK_INTENTION_TOOL`). Ручка читает поле и отдаёт ключом
`intentions`.

Связка на строковом имени — осознанный размен: движок зовёт инструменты
динамически, по реестру путей, и ни разу не импортирует из `src.tool`. Цена
названа прямо: переименуй инструмент — движок промолчит, намерения перестанут
доезжать, **ошибки не будет**. Пустой список законен (намерений могло не быть),
поэтому поломка и штатная тишина выглядят одинаково — сторож нужен на самой
связи, а не на поведении.

Тот же счёт уже оплачен номером обмена: дорога наружу переделывалась дважды и
обе прежние ломались молча — `test_companion_session_message_id.py`, шапка.
Здесь повторён её итог, а не третья попытка.

⚠ Самого ключа `intentions` в ответе здесь нет: он стоит в наборе
`CHAT_ASK_KEYS` соседнего файла, и там его проверяют на **всех** возвратах
ручки разбором исходника. Второй копии того обходчика быть не должно.

⚠ Тесты чистые — ни базы, ни прогона workflow.
"""
import inspect
from pathlib import Path

import pytest

from src.ai.framework.agent.ai_framework_manager import AI_FRAMEWORK_INTENTION_TOOL
from src.ai.framework.agent.ai_framework_model import AiFrameworkAgentModel
from src.tool.chat import chat_intention

# Группа — `ai`, как у соседнего сторожа ручки (`test_chat_variables_allowed.py`):
# стережётся контракт движка и инструмента, а не настройки с журналами.
pytestmark = pytest.mark.ai


def test_the_engine_knows_the_real_tool_name():
    """⚠⚠ Главный сторож: имя в движке совпадает с именем инструмента.

    Это и есть расплата за дубль имени строкой в движке. Разойдись они — шаг
    workflow отработает, инструмент ответит, движок пройдёт мимо, и в ответе
    будет пустой список: исход, ничем не отличимый от «намерений не было».
    """
    assert hasattr(chat_intention, AI_FRAMEWORK_INTENTION_TOOL), \
        (f'движок ждёт инструмент «{AI_FRAMEWORK_INTENTION_TOOL}», '
         f'а в `chat_intention` такой функции нет')

    assert inspect.iscoroutinefunction(
        getattr(chat_intention, AI_FRAMEWORK_INTENTION_TOOL)), \
        'имя занято не той функцией'


def test_the_tool_returns_the_word_under_intention():
    """⚠ Движок берёт намерение ключом `intention` — инструмент обязан отдавать.

    Проверяем договор по объявлению, а не работой: ломается здесь имя ключа.
    """
    said = inspect.getdoc(chat_intention.chat_intention_add) or ''

    assert '`intention` — принятое намерение' in said, \
        'инструмент больше не обещает отдавать намерение ключом `intention`'


@pytest.mark.asyncio
async def test_the_tool_answers_with_the_key_the_engine_reads():
    """⚠ То же, но живым вызовом: ключ есть и несёт сказанное слово.

    Вызов дёшев — инструмент без состояния, ни базы, ни сети.
    """
    answer = await chat_intention.chat_intention_add('she_promised_send_photo')

    assert answer.get('intention') == 'she_promised_send_photo'
    assert answer.get('saved') == 1


@pytest.mark.asyncio
async def test_the_tool_keeps_nothing_of_its_own():
    """⚠⚠ Инструмент не копит: накопитель один, и он на модели прогона.

    Завёлся бы здесь свой словарь на процесс — намерения потекли бы между
    запросами, и чистить его было бы некому. Признак такой заначки простой:
    два вызова подряд, и второй отвечает только своим.
    """
    first = await chat_intention.chat_intention_add('she_promised_send_photo')
    second = await chat_intention.chat_intention_add('he_asked_to_wait')

    assert first.get('intention') == 'she_promised_send_photo'
    assert second.get('intention') == 'he_asked_to_wait'


@pytest.mark.asyncio
async def test_the_empty_word_is_refused_with_a_reason():
    """⚠ Пустое намерение — отказ словами, а не тихое «ок».

    Шаг мог подать пустую переменную: промпт не дал метки, карта входа смотрит
    не туда. Молчаливое согласие превратило бы это в «намерений не было».
    """
    answer = await chat_intention.chat_intention_add('   ')

    assert answer.get('saved') == 0
    assert answer.get('intention') == ''
    assert answer.get('why'), 'отказ без причины — нечего читать в трассе'


def test_the_model_starts_with_an_empty_dict():
    """⚠ Пусто до прогона — законное «намерений не было», а не «не знаем».

    Поле обязано быть заведено **словарём**, а не `None`: ручка отдаёт его
    наружу как JSON-объект, и `None` уехал бы вместо `{}`.
    """
    model = AiFrameworkAgentModel(framework_class='x', title='x',
                                  description='x', specialization='x')

    assert model.chat_intentions == {}
    assert isinstance(model.chat_intentions, dict)


def test_each_model_gets_its_own_pool():
    """⚠⚠ Накопитель — на экземпляр, а не на класс.

    Стой словарь значением по умолчанию в объявлении класса, он был бы один на
    все прогоны процесса: намерения одного разговора приехали бы в ответ
    другому. Для чата это утечка между пользователями, и тихая.
    """
    first = AiFrameworkAgentModel(framework_class='x', title='x',
                                  description='x', specialization='x')
    second = AiFrameworkAgentModel(framework_class='x', title='x',
                                   description='x', specialization='x')

    first.chat_intentions['she_promised_send_photo'] = {}

    assert second.chat_intentions == {}, \
        'накопитель общий на модели — намерения потекут между прогонами'


def test_the_engine_accumulates_and_skips_repeats():
    """⚠⚠ Движок КОПИТ намерения и отсевает повторы, а не присваивает.

    Присваивание — приём соседнего перехвата (номер обмена): там шага два, и
    они взаимоисключающие ветки, поэтому «побеждает последний» верно. Здесь за
    прогон законны несколько намерений, и присваивание оставило бы последнее.

    Отсев нужен из-за места шага: он может стоять внутри `repeat`-цикла или
    подпотока, который зовут по разу на тему, — без отсева одно намерение
    приехало бы трижды. Со словарём отсев даётся самим ключом, но запись
    обязана быть **условной**: безусловная затёрла бы уже собранный контекст.

    ⚠ Проверяем разбором исходника: довести вызов до прогона значило бы поднять
    модель — ту же, что отвечает живым людям.
    """
    source = Path('src/ai/framework/agent/ai_framework_manager.py').read_text(
        encoding='utf-8')

    assert 'not in model.chat_intentions' in source, \
        'пропал отсев повторов: метка затрёт уже собранный контекст'
    assert 'model.chat_intentions[intention] = {}' in source, \
        'движок больше не заводит намерение пустым контекстом'


def test_the_engine_fills_the_context_under_the_same_name():
    """⚠⚠ Контекст ложится **под то же имя**, что и метка, и дополняет её.

    Разойдись имена — контекст уехал бы отдельным ключом, и читающая сторона
    получила бы намерение без контекста рядом с контекстом без намерения.

    ⚠ `update`, а не присваивание: подпоток вправе собирать контекст по частям
    (текст письма одним шагом, теги другим), и второй вызов не должен стирать
    первый.
    """
    source = Path('src/ai/framework/agent/ai_framework_manager.py').read_text(
        encoding='utf-8')

    assert 'AI_FRAMEWORK_INTENTION_CONTEXT_TOOL' in source, \
        'движок не слушает инструмент контекста'
    assert 'setdefault(intention, {}).update(context)' in source, \
        'контекст кладётся не дополнением — части соберутся с потерей'


def test_the_engine_knows_the_context_tool_name():
    """⚠⚠ Имя инструмента контекста — строкой, и связка держится только им.

    Переименуй инструмент, и движок промолчит: контекст просто перестанет
    доезжать, а ошибки не будет — пустой контекст законен. Та же цена, что у
    метки, и тот же сторож.
    """
    from src.ai.framework.agent.ai_framework_manager import (
        AI_FRAMEWORK_INTENTION_CONTEXT_TOOL)
    from src.tool.chat import chat_intention

    assert hasattr(chat_intention, AI_FRAMEWORK_INTENTION_CONTEXT_TOOL), \
        'движок ждёт инструмент, которого нет в модуле намерений'


def test_the_handler_reads_the_model_not_the_variables():
    """⚠ Ручка берёт намерения полем модели, а не из переменных прогона.

    Обе дороги через переменные уже ломались молча — псевдоним в `outputs_map`
    (его стирает редактор workflow) и склеенное имя
    `{инструмент}_{шаг}_result_{ключ}`, чей шаблон нигде не объявлен
    контрактом. Вернись чтение переменных, поломка вернётся вместе с ним.
    """
    source = Path('src/uvicorn/routers/chat/chat.py').read_text(encoding='utf-8')

    assert 'framework_model.chat_intentions' in source, \
        'ручка больше не читает намерения из модели'
    assert '_result_intention' not in source, \
        'вернулся разбор склеенного имени переменной'


class TestTheQueueOfContexts:
    """Выдача намерений подпотоку: по одному, пока у них нет контекста.

    ## ⚠⚠ Что здесь стережётся

    Цикл сбора контекстов крутится по признаку `more`, а выход из него даёт
    то, что подпоток **положил контекст**. Сломайся любая половина — цикл либо
    не начнётся, либо не кончится: второе хуже, оно съедает прогон молча.
    """

    async def test_an_empty_pool_asks_for_nothing(self):
        got = await chat_intention.chat_intention_get({})

        assert got['intention'] == ''
        assert got['more'] == '0', 'пустой накопитель просит продолжать'

    async def test_a_fresh_intention_comes_first(self):
        got = await chat_intention.chat_intention_get({'she_promised_send_photo': {}})

        assert got['intention'] == 'she_promised_send_photo'
        assert got['more'] == '0', 'оно одно — продолжать нечего'
        assert got['left'] == '1'

    async def test_more_stays_on_while_others_wait(self):
        """`more` говорит про **остальных**: выданное уже в работе."""
        got = await chat_intention.chat_intention_get({'a': {}, 'b': {}, 'c': {}})

        assert got['intention'] == 'a'
        assert got['more'] == '1'
        assert got['left'] == '3'

    async def test_a_filled_intention_is_not_offered_again(self):
        """⚠⚠ Главное: намерение с контекстом из очереди уходит.

        На этом стоит выход из цикла. Выдавай мы по порядку — подпоток получал
        бы то же намерение вечно, и прогон не кончился бы никогда.
        """
        got = await chat_intention.chat_intention_get({'done': {'letter': 'текст'}, 'wait': {}})

        assert got['intention'] == 'wait'
        assert got['more'] == '0'

    async def test_all_filled_means_the_loop_is_over(self):
        got = await chat_intention.chat_intention_get({'a': {'letter': 'x'}, 'b': {'tags': ['dress']}})

        assert got['intention'] == ''
        assert got['more'] == '0', 'все контексты собраны, а цикл продолжается'

    async def test_a_stranger_shape_is_not_a_crash(self):
        """⚠ Накопитель приходит переменной workflow и бывает чем угодно.

        Движок кладёт туда объект, но шаг может передать строку или пусто —
        это не повод ронять прогон живого разговора.
        """
        for raw in (None, '', 'строка', 42, []):
            got = await chat_intention.chat_intention_get(raw)

            assert got['intention'] == '' and got['more'] == '0'


class TestTheContextGoesUnderItsName:
    """Запись контекста: под именем намерения и только непустая."""

    async def test_the_context_keeps_its_shape(self):
        """⚠ Форма свободная: письму нужен текст, звонку — время.

        Закрой мы набор полей, каждое новое намерение требовало бы выкладки.
        """
        got = await chat_intention.chat_intention_context_set(
            'she_promised_send_photo',
            {'letter': 'Hi! Here is the photo I promised.', 'tags': ['dress', 'studio']})

        assert got['saved'] == 1
        assert got['intention'] == 'she_promised_send_photo'
        assert got['context']['tags'] == ['dress', 'studio']

    async def test_a_nameless_context_is_refused_with_a_reason(self):
        """Класть контекст не под что — отказ словами, а не молчание."""
        got = await chat_intention.chat_intention_context_set('', {'letter': 'x'})

        assert got['saved'] == 0
        assert got['why'], 'отказ без причины — нечего читать в трассе'

    async def test_an_empty_context_is_refused(self):
        """⚠ Пустой контекст — не запись: иначе «собрал» и «нечего собирать»
        стали бы одним ответом, и цикл счёл бы работу сделанной."""
        for raw in ({}, None, 'строка'):
            got = await chat_intention.chat_intention_context_set('she_promised_send_photo', raw)

            assert got['saved'] == 0, f'пустое принято как контекст: {raw!r}'
            assert got['why']

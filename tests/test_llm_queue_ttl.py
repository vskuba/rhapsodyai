"""Срок ожидания в очереди агента: настройка вместо прибитой константы.

## ⚠⚠ Что здесь стережётся

Прежде срок жил числом в общем слое — `AI_FRAMEWORK_QUEUE_TTL = 60.0`
(`py_modules/ai/ai_thread.py`) — и мерил одной меркой два разных случая:

* **чат с человеком** — дольше минуты ждать вправду незачем: HTTP-запрос уже
  отвалился по 504, а запоздалый ответ выдаёт бота;
* **пакетный прогон** — шаблон инвайтов просит несколько реплик одним вызовом и
  внутри крутит цикл «черновик → судья» на каждую. При одном слоте на агента
  (`node.llm_parallel_per_agent_max` = 1 у ноды Dating) второй такой вызов встаёт
  в очередь целиком и минуты не дожидается никогда.

Живой случай: прогон `dating_invite_write` упал через 60,1 с с «Агент
'invite_ladadate' занят: запрос отброшен по TTL очереди» (трасса #37291).

## ⚠ Модель здесь не зовётся

Проверяется чтение настройки и то, что срок доезжает до диспетчера, — ни то, ни
другое LLM не требует. Оттого файл в обычной сюите, а не в `tests_llm/`.

## ⚠⚠ Настройку правим ручкой, а не запросом в базу

Первая версия звала `setting_set` напрямую — и уборка всей сюиты падала с
«Task … attached to a different loop». Пул `mysql_` модульный и привязывается к
циклу событий, в котором создан; `pytest-asyncio` даёт каждому тесту свой, и
сессионная фикстура `cleanup_test_tasks` в своём цикле получала чужой пул.

⚠ Падало при этом **после зелёного теста**, в teardown, и виноватым выглядел кто
угодно. Та же ловушка описана в `testing_llm.md` про чтение трассы.
"""

import inspect

import httpx
import pytest

from ai.ai_thread import AI_FRAMEWORK_QUEUE_TTL
from ai.framework.ai_framework_model import AiFrameworkModel

from tests.conftest import BASE_URL
from tests.constants import TEST_AUTH

from src.ai.ai_llm import (AI_LLM_QUEUE_TTL_DEFAULT, AI_LLM_QUEUE_TTL_KEY,
                           ai_llm_queue_ttl_get, ai_llm_queue_ttl_value)

pytestmark = pytest.mark.ai


@pytest.fixture
async def ttl_setting():
    """Подменяет настройку на время теста и возвращает прежнее значение.

    ⚠ База рабочая: не вернув значение, тест менял бы поведение установки после
    себя — и следующий прогон ждал бы в очереди не столько, сколько человек
    настроил.

    ⚠ Пустая строка у ручки означает «удалить», и это как раз то, что нужно,
    когда настройки не было вовсе.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=30.0) as client:
        await client.post('/auth/login', json=TEST_AUTH)

        listed = (await client.get('/setting/list')).json().get('result') or []
        was = next((one.get('value') for one in listed
                    if one.get('key') == AI_LLM_QUEUE_TTL_KEY
                    and not one.get('node_id')), None)

        async def _put(value) -> None:
            await client.post('/setting', json={'key': AI_LLM_QUEUE_TTL_KEY,
                                                'value': str(value)})

        yield _put

        # ⚠ Возвращаем как было: `''` удаляет строку — ровно то, что нужно, если
        # настройки до теста не существовало.
        await client.post('/setting', json={'key': AI_LLM_QUEUE_TTL_KEY,
                                            'value': '' if was is None else was})


class TestTheValueIsParsed:
    """Разбор значения — чистая работа, база здесь ни при чём.

    ⚠ Значения в `setting` лежат **строками** (`setting_set` делает `str`), так
    что разбору всегда приходит текст, даже когда человек вводил число.
    """

    def test_a_number_is_taken_as_is(self):
        assert ai_llm_queue_ttl_value('240') == 240.0

    def test_a_fractional_value_is_kept(self):
        """⚠ Срок — дробное число: диспетчер сравнивает его с `time.monotonic()`,
        а не с целыми секундами."""
        assert ai_llm_queue_ttl_value('90.5') == 90.5

    def test_spaces_do_not_break_it(self):
        """Поле ввода на странице — свободный текст, и пробел в нём обычное дело."""
        assert ai_llm_queue_ttl_value('  120  ') == 120.0


class TestBadValuesFallBack:
    """⚠⚠ Негодное значение — не повод остановить очередь.

    Настройку правит человек в текстовом поле. Опечатка не должна ни подвесить
    заявки навсегда, ни заставить диспетчер отбрасывать их сразу: и то, и другое
    чинилось бы потом по журналу, а выглядело бы как поломка агентов.
    """

    def test_words_give_the_default(self):
        assert ai_llm_queue_ttl_value('минута') == AI_LLM_QUEUE_TTL_DEFAULT

    def test_zero_is_a_typo_not_infinity(self):
        """⚠ Ноль читается как «не ждать вовсе» — но так настройку не выражают:
        это описка. Ждать ноль секунд значит отбрасывать всё, что не попало в
        свободный слот мгновенно."""
        assert ai_llm_queue_ttl_value('0') == AI_LLM_QUEUE_TTL_DEFAULT

    def test_negative_gives_the_default(self):
        assert ai_llm_queue_ttl_value('-30') == AI_LLM_QUEUE_TTL_DEFAULT

    def test_a_missing_setting_gives_the_default(self):
        """Настройки нет вовсе — случай ненастроенной установки."""
        assert ai_llm_queue_ttl_value(None) == AI_LLM_QUEUE_TTL_DEFAULT

    def test_an_empty_string_gives_the_default(self):
        assert ai_llm_queue_ttl_value('') == AI_LLM_QUEUE_TTL_DEFAULT


class TestTheSettingIsRead:
    """⚠ Один проход до базы: значение со страницы доезжает до кода.

    Проверок здесь **одна**, и это не лень. Разбор уже покрыт выше без базы, а
    каждый такой тест создаёт пул в своём цикле событий — второй падал бы с
    «attached to a different loop» после зелёного первого.
    """

    async def test_the_value_from_the_page_reaches_the_code(self, ttl_setting):
        from mysql_.mysql_ import mysql_pool_close

        await ttl_setting('240')

        try:
            assert await ai_llm_queue_ttl_get() == 240.0
        finally:
            # ⚠⚠ Пул закрываем за собой. Он модульный и привязывается к циклу
            # событий, в котором создан; `pytest-asyncio` даёт каждому тесту
            # свой, и сессионная уборка в своём цикле получала бы чужой пул —
            # прогон падал бы «Event loop is closed» **после зелёного теста**.
            await mysql_pool_close()


class TestTheDefaultsAgree:
    """⚠⚠ Два умолчания об одном сроке, и они обязаны совпадать.

    Одно в общем слое (`AI_FRAMEWORK_QUEUE_TTL`) — им пользуется проект, который
    поле заявки не заполняет. Второе здесь (`AI_LLM_QUEUE_TTL_DEFAULT`) — ответ на
    «настройки нет».

    Разойдись они — ненастроенная установка вела бы себя иначе, чем установка с
    пустой базой, и разницу искали бы в агентах.
    """

    def test_both_defaults_are_the_same(self):
        assert AI_LLM_QUEUE_TTL_DEFAULT == AI_FRAMEWORK_QUEUE_TTL, \
            (f'умолчания разошлись: проект берёт {AI_LLM_QUEUE_TTL_DEFAULT},'
             f' общий слой — {AI_FRAMEWORK_QUEUE_TTL}')

    def test_the_model_carries_the_same_default(self):
        """⚠ И у самой заявки — тоже: она едет в диспетчер с этим полем."""
        assert AiFrameworkModel.llm_workflow_queue_ttl == AI_FRAMEWORK_QUEUE_TTL


class TestItReachesTheDispatcher:
    """⚠⚠ Сторож проводки: срок обязан доехать от настройки до очереди.

    Порвись цепочка — диспетчер молча возьмёт умолчание, настройка на странице
    перестанет на что-либо влиять, и заметить это будет нечем: заявки по-прежнему
    отбрасываются, только по прежним 60 секундам.
    """

    def test_the_model_has_the_field(self):
        assert hasattr(AiFrameworkModel, 'llm_workflow_queue_ttl'), \
            'у заявки нет поля срока — диспетчеру нечего читать'

    def test_the_builder_fills_it(self):
        """Модель заявки собирает `ai_framework_manager`, и он же кладёт срок."""
        from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager

        code = inspect.getsource(AiFrameworkAgentManager)

        assert 'llm_workflow_queue_ttl' in code, \
            'сборка модели перестала класть срок ожидания'
        assert 'ai_llm_queue_ttl_get' in code, \
            'срок кладётся не из настройки'

    def test_the_dispatcher_reads_it_from_the_model(self):
        """⚠⚠ И диспетчер берёт его **из заявки**, а не из своей константы.

        Прежняя версия сравнивала с `AI_FRAMEWORK_QUEUE_TTL` прямо в условии.
        Оставь её там — настройка читалась бы, ехала бы в модели и не
        использовалась.
        """
        from ai import ai_thread

        code = inspect.getsource(ai_thread.ai_thread_framework_run)

        assert 'llm_workflow_queue_ttl' in code, \
            'диспетчер не читает срок из заявки'
        assert 'queued_at < ttl' in code, \
            'сравнение идёт не с сроком заявки'

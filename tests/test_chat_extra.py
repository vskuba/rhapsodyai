"""Решения прогона доезжают от инструмента до ручки `/chat/ask`.

## ⚠⚠ Что здесь стережётся

`chat_response_extra_set` сам ничего не хранит: он отдаёт пару «ключ →
значение», а копит их движок — в `model.chat_extra`, узнавая инструмент **по
имени** (`AI_FRAMEWORK_EXTRA_TOOL`). Ручка читает поле и отдаёт ключом `extra`.

Связка на строковом имени — осознанный размен: движок зовёт инструменты
динамически, по реестру путей, и ни разу не импортирует из `src.tool`. Цена
названа прямо: переименуй инструмент — движок промолчит, решения перестанут
доезжать, **ошибки не будет**. Пустой `extra` законен (решений могло не быть),
поэтому поломка и штатная тишина выглядят одинаково — сторож нужен на самой
связи, а не на поведении.

Третий раз тот же счёт: его уже оплатили номер обмена и намерения. Здесь
повторён их итог, а не четвёртая попытка.

## ⚠⚠ Зачем всё это заведено

Жребий «прикладывать ли снимок» жил в **панели**, а доля — в её настройке. Это
повторяло уже исправленную ошибку: доли жили в двух местах разом и
складывались — приём «писать первой неловко» выпадал девяти заготовкам из
двадцати при ожидаемых четырёх. Решение принято: жребий живёт в workflow, а
панель читает исход.

⚠ Тесты чистые — ни базы, ни прогона workflow.
"""

import ast
import inspect
from pathlib import Path

import pytest

from src.ai.framework.agent.ai_framework_manager import AI_FRAMEWORK_EXTRA_TOOL
from src.tool.chat.chat_extra import (CHAT_EXTRA_KEY_MAX,
                                      CHAT_EXTRA_VALUE_MAX,
                                      chat_response_extra_set)

pytestmark = pytest.mark.ai


class TestTheToolAnswersWhatTheEngineReads:
    """Поля ответа — те, что ищет движок."""

    async def test_it_gives_back_key_and_value(self):
        got = await chat_response_extra_set('img_attach', '1')

        assert got['key'] == 'img_attach'
        assert got['value'] == '1'
        assert got['saved'] == 1

    async def test_a_number_arrives_as_text(self):
        """⚠ Значение уезжает строкой: приводит его **читающая** сторона.
        Сегодня это «да/нет», завтра «сколько снимков», и форму выбирает тот,
        кто по ней работает."""
        got = await chat_response_extra_set('img_attach', 2)

        assert got['value'] == '2', 'число не привелось к строке'

    async def test_an_empty_value_is_still_saved(self):
        """⚠ «Шаг отработал, а решения нет» — законный исход, и отличать его
        от «ключа не было» читающей стороне незачем."""
        got = await chat_response_extra_set('img_attach', None)

        assert got['saved'] == 1 and got['value'] == ''

    async def test_no_key_is_refused_in_words(self):
        """⚠ Отказ не бросается исключением: шаг жребия мог отдать пустоту, и
        ронять из-за этого весь прогон незачем."""
        got = await chat_response_extra_set('', '1')

        assert got['saved'] == 0
        assert 'ключ не назван' in got['why']

    async def test_a_long_key_is_refused(self):
        got = await chat_response_extra_set('x' * (CHAT_EXTRA_KEY_MAX + 1), '1')

        assert got['saved'] == 0 and 'длиннее' in got['why']

    async def test_a_long_value_is_refused(self):
        """⚠ Текст ответа едет своей дорогой (`result`); дублировать его здесь
        незачем."""
        got = await chat_response_extra_set('img_attach',
                                            'x' * (CHAT_EXTRA_VALUE_MAX + 1))

        assert got['saved'] == 0 and 'длиннее' in got['why']


class TestTheLinkHoldsOnOneName:
    """⚠⚠ Движок зовёт инструмент по имени, и переименование молчит."""

    def test_the_name_matches_the_function(self):
        assert AI_FRAMEWORK_EXTRA_TOOL == chat_response_extra_set.__name__, (
            'имя в движке разошлось с функцией — решения перестанут доезжать, '
            'и ошибки не будет')

    def test_the_engine_reads_the_tool_answer(self):
        """Движок обязан брать **оба** поля и смотреть на `saved`."""
        from src.ai.framework.agent import ai_framework_manager

        code = inspect.getsource(ai_framework_manager)

        assert 'AI_FRAMEWORK_EXTRA_TOOL' in code, (
            'движок про инструмент не знает')
        assert 'model.chat_extra[said]' in code, (
            'ответ инструмента никуда не кладётся')
        assert "int(raw_result.get('saved') or 0)" in code, (
            'движок кладёт и отказ инструмента — вызывающему уедет враньё')

    def test_the_model_holds_it_as_a_dict(self):
        """⚠ Пустой словарь, а не `None`: поле уезжает наружу как JSON-объект.

        ⚠ Читаем файл, а не `inspect.getsource`: модель собирается
        динамически, и исходник класса по ней не достаётся.
        """
        path = (Path(__file__).resolve().parent.parent
                / 'src/ai/framework/agent/ai_framework_model.py')
        code = path.read_text(encoding='utf-8')

        assert 'self.chat_extra: dict[str, str] = {}' in code, (
            'накопителя на модели нет либо он заведён не словарём')


class TestTheLastCallWins:
    """⚠⚠ Присваивает, а не дополняет — в отличие от контекста намерения.

    Два вызова с одним ключом значат, что ветка workflow переменила решение, и
    взять надо последнее. Сложи мы их, переменить решение было бы нечем.
    """

    def test_the_engine_assigns_not_updates(self):
        from src.ai.framework.agent import ai_framework_manager

        code = inspect.getsource(ai_framework_manager)
        at = code.index('AI_FRAMEWORK_EXTRA_TOOL \\')
        near = code[at:at + 500]

        assert 'model.chat_extra[said] = ' in near, (
            'решение кладётся не присваиванием — переменить его будет нечем')
        assert 'setdefault' not in near, (
            'решение накапливается, как контекст намерения: последний вызов '
            'перестанет побеждать')


class TestTheHandlerGivesItBack:
    """⚠ Ключ отдаётся всегда, пустым объектом в том числе: пропажа слилась бы
    со штатной тишиной, и поломка прожила бы незамеченной."""

    def test_the_response_carries_extra(self):
        path = (Path(__file__).resolve().parent.parent
                / 'src/uvicorn/routers/chat/chat.py')
        code = path.read_text(encoding='utf-8')

        assert '"extra": framework_model.chat_extra' in code, (
            'ручка решения прогона не отдаёт')

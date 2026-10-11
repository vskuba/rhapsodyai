"""Номер записанного обмена доезжает от инструмента до ручки `/chat/ask`.

## ⚠⚠ Что здесь стережётся и какой ценой узнано

`companion_session_add` возвращает номер строки, которую только что записал.
Этот номер нужен DatingAi: им отмечается доставка, и без него агент не узнает,
что его слова дошли, — продолжит разговор от непрочитанного.

Дорога номера наружу переделывалась дважды, и обе прежние ломались **молча**:

1. Псевдоним `talk_message_id`, который надо было завести шагу в
   `tool_invoke.outputs_map`. Редактор workflow пишет `outputs_map` пустым
   безусловно — первое же сохранение шага человеком стёрло псевдоним, и отметок
   доставки не было **с 03.10.2026 по 08.10.2026, 486 обменов**.
2. Чтение переменной `{инструмент}_{шаг}_result_id`, то есть разбор склеенного
   имени, чей шаблон нигде не объявлен контрактом.

Теперь движок кладёт номер в `model.companion_session_message_id` прямо из
ответа инструмента, а ручка читает поле. Завязка осталась одна — **имя
инструмента**, и она здесь под сторожем.

⚠ Ломается это по-прежнему тихо: пустой номер — законный исход (агент промолчал,
прогон ушёл в «Тишину»). Поломка и штатная тишина выглядят одинаково, поэтому
сторож нужен на самой связи, а не на поведении.

⚠ Тесты чистые — ни базы, ни прогона workflow.
"""
import ast
import inspect
from pathlib import Path

import pytest

from src.ai.framework.agent.ai_framework_manager import AI_FRAMEWORK_SESSION_TOOL
from src.ai.framework.agent.ai_framework_model import AiFrameworkAgentModel
from src.tool.companion import companion_session

pytestmark = pytest.mark.core

# Ключи, которые ручка `/chat/ask` обязана отдать при любом исходе прогона.
#
# ⚠ Набор общий, а не про номер обмена: `intentions` доезжает тем же приёмом —
# полем модели, которое движок копит по ответу инструмента
# (`tests/test_chat_intentions.py`), — и пропадает так же тихо.
CHAT_ASK_KEYS = {'result', 'message_id', 'intentions'}


def _chat_ask_returns() -> list:
    """Все словари, которые возвращает `chat_ask_ai`, — разбором исходника.

    ⚠⚠ Разбором, а не прогоном, и это не лень. Довести вызов до модели нельзя:
    она одна на тесты и на прод, та же, что отвечает живым людям на сайте
    знакомств, — соседний `test_chat_variables_allowed.py` объявляет это
    правилом файла и делит проверки надвое именно по нему. Цена одного прогона
    умножается на число прогонов сюиты.

    ⚠ Берём только `return` самой ручки, не заходя во вложенные функции: у неё
    внутри есть свои, и их возвраты к контракту отношения не имеют.
    """
    source = Path('src/uvicorn/routers/chat/chat.py').read_text(encoding='utf-8')

    door = next((node for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.AsyncFunctionDef)
                 and node.name == 'chat_ask_ai'), None)
    assert door is not None, 'ручки `chat_ask_ai` в файле нет'

    inner = {node for child in ast.iter_child_nodes(door)
             if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
             for node in ast.walk(child)}

    return [node.value for node in ast.walk(door)
            if isinstance(node, ast.Return) and node not in inner
            and isinstance(node.value, ast.Dict)]


def test_the_engine_knows_the_real_tool_name():
    """⚠⚠ Главный сторож: имя в движке совпадает с именем инструмента.

    Движок зовёт инструменты динамически, по реестру путей, и ни разу не
    импортирует из `src.tool` — поэтому имя записи обмена он держит своей
    постоянной. Цена такого дубля ровно одна: переименуй инструмент, и движок
    промолчит, а номер перестанет доезжать. Этот тест и есть расплата за дубль.
    """
    assert hasattr(companion_session, AI_FRAMEWORK_SESSION_TOOL), \
        (f'движок ждёт инструмент «{AI_FRAMEWORK_SESSION_TOOL}», '
         f'а в `companion_session` такой функции нет')

    assert inspect.iscoroutinefunction(
        getattr(companion_session, AI_FRAMEWORK_SESSION_TOOL)), \
        'имя занято не той функцией'


def test_the_tool_returns_the_number_under_id():
    """⚠ Движок берёт номер ключом `id` — значит инструмент обязан его отдавать.

    Проверяем договор по объявлению, а не прогоном: вызов пишет в базу, а
    ломается здесь именно **имя ключа**, а не запись.
    """
    said = inspect.getdoc(companion_session.companion_session_add) or ''

    assert "`id` — номер строки" in said, \
        'инструмент больше не обещает отдавать номер ключом `id`'


def test_the_model_starts_with_no_number():
    """⚠ Ноль до прогона — законное «обмена не записали», а не «не знаем».

    Поле обязано быть заведено **нулём**, а не `None`: ручка отдаёт его наружу
    как `message_id`, и `None` уехал бы в ответ вместо числа.
    """
    model = AiFrameworkAgentModel(framework_class='x', title='x',
                                  description='x', specialization='x')

    assert model.companion_session_message_id == 0
    assert isinstance(model.companion_session_message_id, int)


def test_the_handler_always_answers_with_the_contract_keys():
    """⚠⚠ `message_id` отдаётся **всегда**, а не только когда он непустой.

    Сторож стоит здесь, у отдающей стороны, потому что принимающая его не
    заменит: панель умеет пережить отсутствие ключа и превращает его в `0`
    (`rhapsody_api_chat_talk`, тест `test_the_key_is_simply_absent`). А `0` —
    законное «агент промолчал». То есть защита на том конце **гасит** пропажу,
    делая её неотличимой от штатной тишины: ровно так поломка и прожила шесть
    дней незамеченной.

    ⚠ Проверяются **все** словарные возвраты ручки, а не первый: появись у неё
    второй выход в обход контракта, он бы и стал дырой.
    """
    answers = _chat_ask_returns()

    assert answers, 'ручка больше не возвращает словарь — контракт не проверить'

    for answer in answers:
        keys = {node.value for node in answer.keys
                if isinstance(node, ast.Constant)}

        assert CHAT_ASK_KEYS <= keys, \
            (f'возврат ручки несёт {sorted(keys)}, '
             f'а контракт требует {sorted(CHAT_ASK_KEYS)}')


def test_the_number_comes_from_the_model_not_from_variables():
    """⚠ Номер берётся полем модели, а не из переменных прогона.

    Обе прежние дороги читали переменные — псевдоним `talk_message_id` и
    склеенное имя `{инструмент}_{шаг}_result_id`, — и обе ломались молча.
    Вернись чтение переменных, поломка вернётся вместе с ним.
    """
    source = Path('src/uvicorn/routers/chat/chat.py').read_text(encoding='utf-8')

    assert 'framework_model.companion_session_message_id' in source, \
        'ручка больше не читает номер из модели'
    assert 'talk_message_id' not in source, \
        'вернулось чтение псевдонима из `outputs_map`'
    assert '_result_id' not in source, \
        'вернулся разбор склеенного имени переменной'

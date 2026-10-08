"""Номер обмена наружу: ручка `/chat/ask` берёт его из переменных прогона.

## ⚠⚠ Что здесь стережётся и какой ценой узнано

Движок сам кладёт каждый ключ ответа инструмента в переменную вида
`{инструмент}_{шаг}_result_{ключ}` — номер записанного обмена **уже лежит** в
`companion_session_add_743_result_id`, без единой настройки.

Прежде ручка читала не его, а псевдоним `talk_message_id`, который заводился шагу
в `tool_invoke.outputs_map` миграцией. Цена вышла такая: редактор workflow пишет
`outputs_map` пустым **безусловно**, и первое же сохранение шага 743 человеком
стёрло псевдоним. Номер перестал выходить наружу, DatingAi стал получать `0`, и
отметок доставки не было **с 03.10.2026 по 08.10.2026 — 486 обменов, ни одного
отмеченного**.

⚠ Не заметил этого никто, и не мог: нулевой номер — **законный исход** (агент
промолчал, прогон ушёл в «Тишину»). Поломка и штатная тишина выглядят одинаково,
поэтому сторож нужен именно здесь, на самом добывании номера.

⚠ Тесты чистые — ни базы, ни прогона: проверяется разбор словаря переменных.
"""
import pytest

from src.tool.companion.companion_session import (COMPANION_SESSION_TOOL,
                                                  chat_message_id_of)

pytestmark = pytest.mark.core

# Имена переменных так, как их кладёт движок: шаг 743 пишет ответ, 744 — тишину.
ANSWER_VAR = f'{COMPANION_SESSION_TOOL}_743_result_id'
SILENCE_VAR = f'{COMPANION_SESSION_TOOL}_744_result_id'


def test_answer_branch_gives_its_number():
    """Обычный случай: агент ответил, обмен записан, номер уехал наружу."""
    assert chat_message_id_of({ANSWER_VAR: '1094'}) == 1094


def test_silence_branch_gives_its_number_too():
    """⚠ Тишина тоже пишет строку, и её номер законен.

    Отправлять при этом нечего, и DatingAi отметку не поставит — он зовёт её
    только после удачной отправки. Прятать номер здесь незачем: это сделало бы
    функцию умнее, чем она знает.
    """
    assert chat_message_id_of({SILENCE_VAR: '77'}) == 77


def test_silence_is_not_a_failure():
    """⚠ Ноль — законный исход, а не отказ: обмена не записали вовсе."""
    assert chat_message_id_of({}) == 0
    assert chat_message_id_of(None) == 0


def test_the_stale_alias_is_ignored():
    """⚠⚠ Главный сторож: старый псевдоним больше не выбирается.

    `talk_message_id` может лежать в переменных прогона — его кладёт
    `outputs_map`, если тот у шага уцелел, — и значение в нём может быть любым.
    Читать надо то, что вернул инструмент, а не то, что кто-то настроил.
    """
    assert chat_message_id_of({'talk_message_id': '9', ANSWER_VAR: '1094'}) == 1094


def test_other_tools_are_not_mistaken_for_it():
    """⚠ Рядом стоят шаги `companion_session_history` — их номера не наши.

    Имя инструмента сверяется целиком с приставкой до `_`, и «похожее начало»
    чужого инструмента сюда не попадает.
    """
    variables = {'companion_session_history_741_result_id': '5',
                 'companion_session_incoming_9_result_id': '6',
                 ANSWER_VAR: '1094'}

    assert chat_message_id_of(variables) == 1094


def test_both_branches_give_the_freshest():
    """⚠ Ветки взаимоисключающие, но правило на случай обеих задано.

    Берём наибольший номер: свежая строка и есть та, которую отправляют.
    """
    assert chat_message_id_of({SILENCE_VAR: '77', ANSWER_VAR: '1094'}) == 1094


def test_junk_does_not_raise():
    """⚠ Нечисловое значение — ноль, а не исключение.

    Ручка отдаёт ответ агента, уже сочинённый и оплаченный вызовом модели;
    падать на разборе номера значило бы потерять его из-за мелочи.
    """
    assert chat_message_id_of({ANSWER_VAR: 'нет'}) == 0
    assert chat_message_id_of({ANSWER_VAR: None}) == 0
    assert chat_message_id_of({ANSWER_VAR: '0'}) == 0

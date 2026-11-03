"""Не дождавшись ответа, ждущий **отменяет прогон**, а не одно своё ожидание.

## ⚠⚠ Зачем понадобилось

`asyncio.wait_for` гасит `future`, то есть ожидание. Задача прогона при этом
жива: она идёт дальше, дожигает модель, дописывает в журнал `success` и кладёт
реплику в `companion_session` — ту, которую уже никто не отправит. Снаружи это
выглядит противоречием: на странице трассы у одного прогона и текст ответа, и
`status: 504` в контракте.

Цена измерена на проде 03.11.2026, пара Natalia → Kazimierz (`dating_talk`,
агент «Письма: ответы», прогон #190754). Срок 240 секунд, прогон шёл 498:
зовущий ушёл на 240-й, реплика в 1802 знака легла в базу на 498-й и осталась
недоставленной (`delivered_at IS NULL`). Человеку ушёл ответ **другого**
прогона, посчитанного заново.

Движок об этом предупреждал докстрингом `framework_workflow_run` — «кто ставит
таймаут, тот и отменяет задачу», — но предупреждение в докстринге соблюдали
пятеро из двадцати: конвейер задач держал задачу и отменял, двери HTTP её
выбрасывали.

## Что стережётся здесь

| | чем проверено |
|---|---|
| по сроку задача прогона отменена, а не только ожидание | живым прогоном |
| успевший прогон отдаёт ответ и не отменяется | живым прогоном |
| дверь чата ждёт **дверью менеджера**, а не своим `wait_for` | исходником |

⚠ Второй случай нужен не меньше первого: отмена, сработавшая на уложившемся
прогоне, выглядела бы как молчание агента — самый незаметный из возможных
отказов.
"""

import asyncio

import pytest

from tests_.tests_guard import tests_guard_code as _source

from src.ai.framework.agent import ai_framework_manager as mod
from src.uvicorn.routers.chat import chat as chat_mod

pytestmark = pytest.mark.ai


class TestTheRunIsCancelled:
    """Поведение двери: что происходит с задачей прогона."""

    async def test_a_late_run_is_cancelled(self):
        """⚠⚠ Главное здесь: по сроку отменена **задача**, а не только ожидание.

        Без этой отмены прогон дожил бы до своего конца и дописал ответ в
        журнал — ровно случай #190754.
        """
        door = _Door(seconds=5)

        with pytest.raises(asyncio.TimeoutError):
            await door.framework_workflow_wait(object(), timeout=0.05)

        # Отмена доезжает до задачи не мгновенно — отдаём ей оборот цикла.
        await asyncio.sleep(0.05)

        assert door.task.cancelled() or door.task.done(), \
            'прогон остался жить после таймаута — он дожжёт модель в пустоту'

    async def test_a_run_in_time_keeps_its_answer(self):
        """Уложившийся прогон отдаёт ответ, и отменять его нечем и незачем."""
        door = _Door(seconds=0.01, answer='Привет')

        assert await door.framework_workflow_wait(object(), timeout=5) == 'Привет'
        assert not door.task.cancelled(), 'отменили прогон, который успел'


class TestTheChatDoorUsesIt:
    """⚠ Дверь чата — та, на которой беда и всплыла."""

    def test_chat_waits_through_the_manager(self):
        source = _source(chat_mod.chat_ask_ai)

        assert 'framework_workflow_wait' in source, \
            'чат снова ждёт сам — значит снова не отменяет прогон'
        assert 'asyncio.wait_for' not in source, \
            'в ручке вернулось своё ожидание поверх двери менеджера'


# ── Приватное ────────────────────────────────────────────────────────────────

class _Door:
    """Дверь менеджера на подменённом прогоне: сам движок здесь не нужен.

    ⚠ Метод берётся **с настоящего класса**, а не переписывается: сторож обязан
    проверять ту строку кода, что пойдёт на прод.
    """

    framework_workflow_wait = mod.AiFrameworkAgentManager.framework_workflow_wait

    def __init__(self, seconds: float, answer: str = 'ответ'):
        self.seconds = seconds
        self.answer = answer
        self.task = None

    def framework_workflow_run(self, framework_model, future, loop):
        self.task = asyncio.create_task(self._run(future))

        return self.task

    async def _run(self, future):
        """Прогон: спит, потом отвечает. Отмену принимает молча, как движок."""
        try:
            await asyncio.sleep(self.seconds)
        except asyncio.CancelledError:
            if not future.done():
                future.set_result('')
            raise

        if not future.done():
            future.set_result(self.answer)

"""Остановленный и безысходный прогон отвечает пустотой, а не строкой статуса.

## ⚠⚠ Зачем понадобилось

Вызывающий ответ прогона **не разбирает, он его отправляет**. Значит любая
строка, которой движок отвечает вместо текста, — это письмо живому человеку.

Так и случилось в `dating`: прогон письма упёрся в таймаут ожидающего, отмена
ответила «⏹ Workflow остановлен», и этот статус ушёл адресату двумя письмами
(dating: favorite_mail id 801, 1005, по 33 символа). Тем же каналом могла утечь
фраза «Воркфлоу успешно завершен.» — ею отвечает прогон, дорезавший до конца
списка шагов без return-шага.

Правило уже было в движке: тупик после правки 2026-10 отвечает пустотой, а
слова остаются в журнале и трассе (см. `test_workflow_to_next_step.py`, там же
пережила свою правку старый докстринг). Отмена и успех-без-ответа просто
отставали от правила.

## Что стережётся здесь

| исход прогона | ответ | где видно, что случилось |
|---|---|---|
| отмена («Стоп» или таймаут ожидающего) | `''` | журнал `status='stopped'`, трасса |
| прогон кончился списком шагов без return | `''` | журнал `result=NULL`, трасса |
| тупик `to next step` снят, переходы молчат | `''` | журнал ⛔, `trace_output` шага |

Пустой ответ вызывающий читает как «агент решил промолчать» — единственный
исход, к которому готовы все дороги: чат молчит, письмо не заводится, пара
пропускается (`DatingAi: answer.py`, `favorite_mail.py`, `mail_reply.py`).
"""

import pytest

from tests_.tests_guard import tests_guard_code as _source

from src.ai.framework.agent import ai_framework_manager as mod

pytestmark = pytest.mark.core

RUN = _source(mod.AiFrameworkAgentManager._framework_workflow_run)
LOOP = _source(mod.AiFrameworkAgentManager._workflow_steps_run)


class TestTheContractIsInSource:
    """⚠⚠ Ни один выход прогона не отвечает человеку словами."""

    def test_cancelled_answers_empty(self):
        """Отмена: в future ложится пустая строка, а не «⏹ Workflow остановлен»."""
        assert "future.set_result, ''" in RUN, \
            'отмена снова отвечает вызывающему текстом — он его отправит'
        assert "set_result, '⏹" not in RUN, \
            'строка статуса осталась аргументом set_result'

    def test_finished_without_answer_answers_empty(self):
        """Успех без return-шага: `result is None` ведёт к пустоте, не к фразе."""
        assert 'Воркфлоу успешно завершен' not in RUN, \
            'строка журнала вернулась в текст ответа'
        assert "result if result is not None else ''" in RUN, \
            'хвост успеха перестал сводить отсутствие ответа к пустоте'

    def test_dead_end_answers_empty(self):
        """Тупик: пустота в ответе, слова — в трассе. (Стерёж парный.)"""
        assert 'return AI_FRAMEWORK_NO_MORE_STEP' not in LOOP, \
            'тупик снова диктует вызывающему фразу'
        assert 'trace_output = AI_FRAMEWORK_NO_MORE_STEP' in LOOP, \
            'без слов в трассе тупик не отличить от молчания агента'

    def test_the_status_still_reaches_the_journal(self):
        """⚠ Пустота в ответе не должна стоить журналу причины останова."""
        assert "trace_run_id, 'stopped'" in RUN, \
            'останов перестал помечаться в журнале — трасса остолбенела бы'


class TestTheConventionIsWhole:
    """⚠ Строки-статусы живут только там, где их читают люди, а не каналы."""

    def test_no_status_strings_reach_the_answer(self):
        """Ни одна прежняя фраза-ответ не вернулась в аргументы set_result."""
        code = _source(mod)

        assert 'Воркфлоу успешно завершен' not in code, \
            'фраза вернулась в модуль — её опять отдадут человеку'
        assert "set_result, '⏹" not in code, \
            '«⏹ Workflow остановлен» снова доедет до вызывающего'

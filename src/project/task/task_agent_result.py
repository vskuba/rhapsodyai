"""
Общая часть разбора ответа агента: отличить работу от несостоявшегося прогона.

У Developer, QA и багфиксера свои `_result_parse` — форма отчёта у каждого своя.
Общее у них одно: до контракта `{"ok", "report", "error"}` ответ может вообще не
дойти. Тогда в шаге `return_response_text` оказывается не отчёт агента, а объект
ошибки провайдера — llama.cpp на GX10 отвечает так, например, на переполненный
контекст:

    {"code": 400, "type": "exceed_context_size_error",
     "message": "request (134521 tokens) exceeds the available context size (131072 tokens)"}

Разбор такого ответа по общим правилам врал дважды. `ok` в объекте нет, и
умолчание `parsed.get('ok', True)` давало `ok = True`: конвейер считал круг
состоявшимся и отправлял нетронутый код на проверку QA. `report` там тоже нет,
поэтому в журнал попыток уходил сырой JSON ошибки вместо отчёта. Круг сгорал,
хотя агент не получил даже промпта.

Правильный исход — `env_ok = False`: работы не было, и жечь попытку не за что,
`task_pipeline` уводит такой ответ в повтор (`task_retry`) вместе с перезапуском
оболочки. Ровно тот же путь, что у таймаута и мёртвого Claude Code.
"""

# Ключи, по которым ответ опознаётся как ошибка провайдера, а не отчёт агента.
# Проверяем пару признаков, а не один: `message` бывает и в осмысленном отчёте,
# а вот `message`/`error` вместе с `code`/`type` и без `ok`/`report` — это уже
# чужой объект, до контракта агента дело не дошло.
TASK_AGENT_RESULT_CONTRACT_KEYS = ('ok', 'report')
TASK_AGENT_RESULT_ERROR_TEXT_KEYS = ('message', 'error')
TASK_AGENT_RESULT_ERROR_MARK_KEYS = ('code', 'type', 'status_code')

# Сообщение провайдера режем: в нём бывает и трейсбек, и целый промпт обратно.
TASK_AGENT_RESULT_ERROR_MAX = 300


def task_agent_result_provider_error(parsed: dict) -> str:
    """
    Ответ — объект ошибки провайдера, а не отчёт агента?

    Args:
        parsed: разобранный JSON ответа шага `return_response_text`.

    Returns:
        Текст ошибки для журнала попыток, если это ошибка провайдера; иначе пустая
        строка. Пустая строка ложна — вызывающему хватает `if`, отдельной проверки
        на тип не нужно.
    """
    if not isinstance(parsed, dict) or not parsed:
        return ''
    if any(key in parsed for key in TASK_AGENT_RESULT_CONTRACT_KEYS):
        return ''
    if not any(key in parsed for key in TASK_AGENT_RESULT_ERROR_MARK_KEYS):
        return ''

    text = ''
    for key in TASK_AGENT_RESULT_ERROR_TEXT_KEYS:
        text = ' '.join(str(parsed.get(key) or '').split())
        if text:
            break
    if not text:
        return ''

    kind = ' '.join(str(parsed.get('type') or '').split())
    if kind and kind not in text:
        text = f'{kind}: {text}'

    return text[:TASK_AGENT_RESULT_ERROR_MAX]

"""Кирпичики печатного журнала прогона: значение, длительность, бейдж, метка времени.

Самый низ сборки документа: ни про шаги, ни про прогон здесь не знают — только
про то, как показать одно значение на бумаге. Выше лежат `..._pdf_step`
(шаг и подпоток) и `..._pdf` (документ целиком).

⚠ Форматы длительности и даты повторяют экранную страницу (`fmtDuration`,
`fmtDateParts` в `admin/workflow_trace.html`) намеренно: один и тот же прогон
смотрят то там, то тут, и «66.2 s» против «1m 6s» читается как разные числа.
"""
import html
import json

from datetime_.datetime_ import datetime_offset_apply

# Потолок одного значения в документе.
#
# ⚠⚠ Обрезка здесь обязательна, и причина арифметическая. Трасса пишет значения
# до `TRACE_VALUE_MAX_LEN` (20 000 знаков), у шага таких значений три, а у
# живого `dating_talk` бывает 170 шагов — это 10 МБ текста в одном документе,
# то есть сотни страниц и минуты работы Chrome. Шесть тысяч знаков — это ~2
# страницы на значение: достаточно, чтобы прочитать, чем шаг кормили и что он
# ответил. Срез всегда назван вслух (`_cut`), молча не теряем ничего.
AI_WORKFLOW_TRACE_PDF_TEXT_MAX = 6000

# Потолок значения в строке таблицы переменных: там важен не текст целиком, а
# «что это за значение» — таблица на сотню имён из многострочных значений
# перестаёт быть таблицей.
AI_WORKFLOW_TRACE_PDF_TEXT_INLINE_MAX = 300


def ai_workflow_trace_pdf_text_escape(value) -> str:
    """Любое значение — безопасным текстом внутри HTML-документа."""
    return html.escape('' if value is None else str(value), quote=True)


def ai_workflow_trace_pdf_text_json(raw):
    """Значение разложенным JSON, если это JSON; иначе — как пришло.

    Возвращает строку (или None у пустого входа): разбирать JSON ради показа —
    это про читаемость, а не про смысл, и несостоявшийся разбор не ошибка.
    """
    if raw is None or raw == '':
        return None
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False, indent=2)
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except (ValueError, TypeError):
        return str(raw)


def ai_workflow_trace_pdf_text_block(value, limit: int = AI_WORKFLOW_TRACE_PDF_TEXT_MAX) -> str:
    """Значение блоком `<pre>`: пусто — прочерк, длинное — обрезано с пометкой."""
    if value is None or value == '' or value == '{}':
        return '<pre class="v-empty">—</pre>'
    text = str(value)
    cut = ''
    if len(text) > limit:
        cut = (f'<div class="cut">… обрезано: показано {limit} из {len(text)} знаков, '
               f'целиком — на странице «Логи → Workflow Trace»</div>')
        text = text[:limit]
    return f'<pre>{ai_workflow_trace_pdf_text_escape(text)}</pre>{cut}'


def ai_workflow_trace_pdf_text_inline(value, limit: int = AI_WORKFLOW_TRACE_PDF_TEXT_INLINE_MAX) -> str:
    """Значение одной строкой для ячейки таблицы: переводы строк сжаты в пробел."""
    if value is None or value == '':
        return '<span class="v-empty">пусто</span>'
    if isinstance(value, (dict, list)):
        kind = f'list · {len(value)}' if isinstance(value, list) else f'dict · {len(value)}'
        value = f'[{kind}] ' + json.dumps(value, ensure_ascii=False)
    text = ' '.join(str(value).split())
    tail = '' if len(text) <= limit else ' <span class="cut">…</span>'
    return ai_workflow_trace_pdf_text_escape(text[:limit]) + tail


def ai_workflow_trace_pdf_text_duration(ms) -> str:
    """Длительность в миллисекундах словами страницы: `66.2 s`, `3m 7s`, `2h 14m`."""
    if ms is None:
        return ''
    if ms <= 100:
        return f'{ms} ms'
    sec = ms / 1000
    if sec <= 100:
        return f'{sec:.1f} s'
    minutes = int(sec // 60)
    if minutes <= 100:
        return f'{minutes}m {round(sec % 60)}s'
    return f'{minutes // 60}h {minutes % 60}m'


def ai_workflow_trace_pdf_text_badge(status) -> str:
    """Состояние цветным бейджем; неизвестное состояние — серым, а не без цвета."""
    known = ('success', 'error', 'running', 'stopped', 'retry')
    name = str(status or '')
    kind = name if name in known else 'stopped'
    return (f'<span class="badge badge-{kind}">'
            f'{ai_workflow_trace_pdf_text_escape(name or "—")}</span>')


def ai_workflow_trace_pdf_text_moment(value, offset) -> str:
    """Метка времени в часовом поясе установки: `2026-11-09 05:04:11`.

    ⚠ Смещение передаётся доводом, а не читается из настройки: меток в
    документе сотни, и запрос на каждую превратил бы выгрузку в обход базы.
    """
    local = datetime_offset_apply(value, offset)
    return local.strftime('%Y-%m-%d %H:%M:%S') if local else '—'

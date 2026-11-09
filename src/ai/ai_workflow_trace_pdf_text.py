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
import re

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

# Приметы, которые в тексте промпта ищут глазами: подстановка движка
# (`[[имя]]`, `%имя%`) и рамка раздела (`=== Заголовок ===`). Подсветка нужна
# ровно потому, что текст длинный и сплошной: без неё место подстановки ищут
# перечитыванием абзаца.
#
# ⚠ Образцы применяются к УЖЕ экранированному тексту, поэтому в разметку они
# подставляют только свои же совпадения — чужой `<` до них не доживает.
# Подряд идущие пустые строки, сжимаемые до одной пустой (то есть до абзаца).
#
# ⚠⚠ Это НЕ косметика. Живой `dating_mail_write` присылает в промпте серии до
# восьми переносов подряд (замер на проде: 12 таких серий в одном значении), и
# на бумаге каждая — дыра в треть листа посреди текста. Абзац при этом обязан
# выжить: ради него вся правка и делалась, схлопывать переносы в пробел нельзя.
AI_WORKFLOW_TRACE_PDF_TEXT_BLANKS = re.compile(r'\n{3,}')

AI_WORKFLOW_TRACE_PDF_TEXT_MARKS = (
    (re.compile(r'\[\[[^\[\]\n]{1,80}\]\]'), 'mark-var'),
    (re.compile(r'%[A-Za-z_][\w.]{0,60}%'), 'mark-var'),
    (re.compile(r'={2,}[^=\n]{1,120}={2,}'), 'mark-section'),
)


def ai_workflow_trace_pdf_text_pairs(raw, limit: int = AI_WORKFLOW_TRACE_PDF_TEXT_MAX) -> str:
    """
    Объект — таблицей «ключ → значение», а не JSON-простынёй.

    Так показывают вход и выход шага. JSON там читать невозможно: значение
    промпта — это тысячи знаков в одну строку, и единственное, что человек
    хочет увидеть, — какому ключу что досталось.

    ⚠⚠ **Переносы строк настоящие, а не `\\n` знаками.** Прежний рендер делал
    `json.dumps(json.loads(...))`, то есть разбирал строку и тут же
    сериализовал её обратно — экранируя переносы заново. В документ уезжала
    стена текста, где абзацы письма были видны как пунктуация `\\n`. Значения
    берутся прямо из разбора, и переносы в них уже настоящие; на бумаге их
    держит `white-space: pre-wrap`.

    Не объект (список, число, не-JSON) — отдаётся обычным блоком: таблицы
    «ключ → значение» из списка не выйдет, а врать формой нельзя.
    """
    if raw is None or raw == '' or raw == '{}':
        return '<pre class="v-empty">—</pre>'

    data = raw if isinstance(raw, dict) else None
    if data is None:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None
    if not isinstance(data, dict) or not data:
        return ai_workflow_trace_pdf_text_block(ai_workflow_trace_pdf_text_json(raw), limit)

    rows = ''.join(
        f'<tr><td class="kv-key">{ai_workflow_trace_pdf_text_escape(key)}</td>'
        f'<td class="kv-val">{_value_cell(value, limit)}</td></tr>'
        for key, value in data.items())
    return f'<table class="kv">{rows}</table>'


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


# ── детали показа ──────────────────────────────────────────────────────────

def _value_cell(value, limit: int) -> str:
    """Значение одного ключа: текст как текст, вложенный объект — JSON-ом.

    ⚠ Текстовое значение НЕ проходит через `json.dumps`: именно он превращал
    абзацы письма в `\\n` посреди строки. Вложенные list/dict сериализовать
    по-прежнему надо — у них иначе нет письменной формы, — но внутри них
    переносов и не бывает.
    """
    if value is None:
        return '<span class="v-empty">пусто</span>'
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    if isinstance(value, (dict, list)):
        text, nested = json.dumps(value, ensure_ascii=False, indent=2), True
    else:
        # Серия пустых строк сжимается до одной: восемь переносов подряд — это
        # треть листа пустоты, а абзац читается и от одного.
        text, nested = AI_WORKFLOW_TRACE_PDF_TEXT_BLANKS.sub('\n\n', str(value)), False
    if text == '':
        return '<span class="v-empty">пусто</span>'

    cut = ''
    if len(text) > limit:
        cut = (f'<div class="cut">… обрезано: показано {limit} из {len(text)} знаков, '
               f'целиком — на странице «Логи → Workflow Trace»</div>')
        text = text[:limit]

    body = ai_workflow_trace_pdf_text_escape(text)
    if not nested:
        body = _marks(body)
    return f'<div class="kv-text">{body}</div>{cut}'


def _marks(escaped: str) -> str:
    """Подсветить в уже экранированном тексте подстановки и рамки разделов.

    ⚠⚠ Работает по экранированному тексту и ровно по своим образцам, поэтому
    добавить в документ чужую разметку не может: к этому моменту `<` из данных
    уже стал `&lt;`. Порядок замен не важен — образцы не пересекаются.
    """
    out = escaped
    for pattern, css in AI_WORKFLOW_TRACE_PDF_TEXT_MARKS:
        out = pattern.sub(lambda m: f'<span class="{css}">{m.group(0)}</span>', out)
    return out

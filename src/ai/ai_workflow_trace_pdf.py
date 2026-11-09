"""Прогон workflow печатным документом: обложка, содержание, шаги, переменные.

Выгрузка отвечает на вопрос, на который экранная страница ответить не умеет:
**отдать прогон целиком тому, у кого нет доступа к панели** — в задачу, в
письмо, в разбор жалобы. Поэтому документ самодостаточен: в нём и паспорт
прогона, и контракт вызова, и каждый шаг с входом, выходом и переходом, и
значения переменных.

Печатает Chrome (`pdf_print_html` общего слоя) — тот же движок, которым
страницу печатает браузер: документ выходит векторным, текст остаётся текстом,
а ссылки внутри документа (содержание → шаг, переход → шаг-цель, подпоток →
шаг-родитель) превращаются во внутренние ссылки PDF и работают в любом
просмотрщике.

⚠⚠ **Своего HTML у страницы `/admin/workflow_trace` не берём.** Соблазн
«напечатать то, что на экране» стоил бы головы браузера с сессией, прокруткой
и раскрытыми аккордеонами; документ собирается из тех же данных, что приходят
в `GET /workflow_trace/run/{run_uuid}`, и ни во что не ходит.

⚠ Разбивку переменных по группам (чипы 📥/🇬/⚙️ на странице) документ **не
повторяет**: правило разбора живёт одним модулем `js/workflow/variable-group.js`
и намеренно не продублировано на сервере — своя копия разошлась бы с панелью на
первой правке. Вместо группы у строки стоит источник значения (`старт` или
`шаг #N`), и он считается из самой трассы, без правил.
"""
import json
import os
import tempfile

from pdf_.pdf_ import pdf_print_html

from src.ai.ai_workflow_trace_pdf_step import (
    ai_workflow_trace_pdf_step_child_html,
    ai_workflow_trace_pdf_step_html,
    ai_workflow_trace_pdf_step_plan,
)
from src.ai.ai_workflow_trace_pdf_style import AI_WORKFLOW_TRACE_PDF_CSS
from src.ai.ai_workflow_trace_pdf_text import (
    ai_workflow_trace_pdf_text_badge,
    ai_workflow_trace_pdf_text_block,
    ai_workflow_trace_pdf_text_duration,
    ai_workflow_trace_pdf_text_escape,
    ai_workflow_trace_pdf_text_inline,
    ai_workflow_trace_pdf_text_json,
    ai_workflow_trace_pdf_text_moment,
)

# Потолок печати одного документа, секунды.
#
# ⚠ Тридцати (умолчание `pdf_print_html`) мало: прогон на полторы сотни шагов —
# это сотни страниц вёрстки, и Chrome их честно считает. Потолок всё равно
# нужен: зависший headless закрыть некому, а ручка держит соединение пула.
AI_WORKFLOW_TRACE_PDF_TIMEOUT = 180


def ai_workflow_trace_pdf_build(run: dict, icons: dict, offset) -> bytes:
    """
    Напечатать прогон workflow в PDF; вернуть готовый документ байтами.

    Args:
        run: дерево прогона из `GET /workflow_trace/run/{run_uuid}` — с `steps`
            и вложенными `children`.
        icons: `{имя типа шага: значок}` из `agent_workflow_step_type`.
        offset: часовой пояс установки (настройка `timezone`) — метки времени
            показываются в нём, а хранятся в UTC.

    Returns:
        bytes: содержимое PDF.

    Raises:
        RuntimeError: Chrome не нашёлся или не записал документ — текст
            причины приходит из его stderr.

    ⚠ Функция блокирующая (запуск Chrome подпроцессом). Из async-ручки звать
    через `asyncio.to_thread`, иначе на время печати встанет весь событийный
    цикл процесса — а это секунды.
    """
    html = ai_workflow_trace_pdf_html(run, icons, offset)
    with tempfile.TemporaryDirectory(prefix='trace-pdf-') as folder:
        page = os.path.join(folder, 'trace.html')
        out = os.path.join(folder, 'trace.pdf')
        with open(page, 'w', encoding='utf-8') as fh:
            fh.write(html)
        pdf_print_html(page, out, timeout_s=AI_WORKFLOW_TRACE_PDF_TIMEOUT)
        with open(out, 'rb') as fh:
            return fh.read()


def ai_workflow_trace_pdf_html(run: dict, icons: dict, offset) -> str:
    """
    Документ прогона целиком одной HTML-строкой — то, что уйдёт в печать.

    Отдельная от печати функция не ради чистоты: разметку проверяют тестом и
    смотрят глазами в браузере, а это дешевле делать без запуска Chrome.
    """
    plan = ai_workflow_trace_pdf_step_plan(run)
    body = ''.join([
        _cover(run, plan, offset),
        _contents(run, plan, icons),
        _summary(run),
        _variables(run),
        _steps(run, plan, icons),
    ])
    title = ai_workflow_trace_pdf_text_escape(
        f'Workflow Trace #{run.get("id")} — {run.get("workflow_title") or run.get("workflow_name") or ""}')
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<title>{title}</title><style>{AI_WORKFLOW_TRACE_PDF_CSS}</style>'
            f'</head><body>{body}</body></html>')


def ai_workflow_trace_pdf_filename(run: dict) -> str:
    """Имя файла выгрузки: `trace-201406-dating_mail_write.pdf`.

    ⚠ В имени остаются только латиница, цифры, дефис и подчёркивание: имя
    уезжает в заголовок `Content-Disposition`, а кириллица и пробелы там живут
    только в экранированном виде — у части клиентов до сих пор криво.
    """
    name = str(run.get('workflow_name') or 'workflow')
    safe = ''.join(c if c.isascii() and (c.isalnum() or c in '-_') else '-' for c in name)
    return f'trace-{run.get("id")}-{safe.strip("-") or "workflow"}.pdf'


# ── разделы документа ──────────────────────────────────────────────────────

def _cover(run: dict, plan: list, offset) -> str:
    """Обложка: чем прогон был, чем кончился и из чего состоит."""
    steps_qty = sum(1 for e in plan if e['kind'] == 'step')
    child_qty = sum(1 for e in plan if e['kind'] == 'run')
    llm, tokens_in, tokens_out = _llm_stats(run)
    speed = (f'{tokens_out / (run["duration_ms"] / 1000):.1f}'
             if tokens_out and (run.get('duration_ms') or 0) > 0 else '—')

    # ⚠ «шагов всего», а не «шагов»: здесь дерево целиком, вместе с подпотоками,
    # — как и счёт моделей с токенами рядом. На карточке ленты число другое
    # (только свои шаги прогона), и без слова «всего» два числа об одном
    # прогоне выглядели бы расхождением.
    tiles = [('шагов всего', steps_qty), ('подпотоков', child_qty),
             ('LLM-вызовов', sum(llm.values())),
             ('токенов ↑', f'{tokens_in:,}'.replace(',', ' ')),
             ('токенов ↓', f'{tokens_out:,}'.replace(',', ' ')),
             ('tok/s', speed)]
    tiles_html = ''.join(
        f'<div class="tile"><div class="tile-value">{ai_workflow_trace_pdf_text_escape(value)}</div>'
        f'<div class="tile-label">{label}</div></div>' for label, value in tiles)

    facts = [
        ('Запуск', f'#{run.get("id")} · {run.get("run_uuid") or "—"}'),
        ('Workflow', _pair(run.get('workflow_title'), run.get('workflow_name'))),
        ('Агент', _pair(run.get('agent_title'), run.get('agent_name'))),
        ('Начат', ai_workflow_trace_pdf_text_moment(run.get('started_at'), offset)),
        ('Завершён', ai_workflow_trace_pdf_text_moment(run.get('finished_at'), offset)),
        ('Длительность', ai_workflow_trace_pdf_text_duration(run.get('duration_ms')) or '—'),
        ('Сессия', run.get('session_uuid') or '—'),
        ('Запрос (request_uuid)', run.get('request_uuid') or '—'),
        ('Обмен (message_id)', run.get('message_id') if run.get('message_id') is not None else '—'),
        ('Модели', ', '.join(f'{name} × {qty}' for name, qty in llm.items()) or '—'),
    ]
    facts_html = ''.join(
        f'<tr><th>{label}</th><td>{ai_workflow_trace_pdf_text_escape(value)}</td></tr>'
        for label, value in facts)

    return (f'<div class="cover">'
            f'<div class="cover-kicker">RhapsodyAi · журнал выполнения</div>'
            f'<div class="cover-title">'
            f'{ai_workflow_trace_pdf_text_escape(run.get("workflow_title") or run.get("workflow_name") or "Workflow")}'
            f'</div>'
            f'<div class="cover-sub">запуск #{run.get("id")} '
            f'{ai_workflow_trace_pdf_text_badge(run.get("status"))}</div>'
            f'<div class="cover-rule"></div>'
            f'<div class="tiles">{tiles_html}</div>'
            f'<table class="facts">{facts_html}</table></div>')


def _contents(run: dict, plan: list, icons: dict) -> str:
    """Содержание: разделы и каждый шаг ссылкой на своё место в документе."""
    rows = [_toc_row('', 'Сводка прогона', '#summary', ''),
            _toc_row('', 'Переменные прогона', '#variables', ''),
            _toc_row('', 'Шаги выполнения', '#steps', '')]
    for entry in plan:
        if entry['kind'] == 'run':
            child = entry['run']
            name = child.get('workflow_title') or child.get('workflow_name') or 'sub-workflow'
            rows.append(_toc_row('↳', f'подпоток · {name}', f'#{entry["anchor"]}',
                                 ai_workflow_trace_pdf_text_duration(child.get('duration_ms')),
                                 depth=entry['depth'], sub=True))
            continue
        step = entry['step']
        icon = icons.get(step.get('step_type'), '·')
        meta = ' · '.join(x for x in (step.get('status'),
                                      ai_workflow_trace_pdf_text_duration(step.get('duration_ms'))) if x)
        rows.append(_toc_row(f'#{step.get("exec_index")}',
                             f'{icon} {step.get("step_title") or step.get("step_type") or ""}',
                             f'#{entry["anchor"]}', meta, depth=entry['depth']))
    return f'{_heading(run, "toc", "§", "Содержание")}{"".join(rows)}</div>'


def _summary(run: dict) -> str:
    """Сводка: запрос и ответ движка слева, контракт HTTP-вызова справа."""
    failed = run.get('status') in ('error', 'stopped')
    answer_label = {'error': 'Ошибка', 'stopped': 'Остановлен'}.get(run.get('status'), 'Ответ')
    answer = run.get('error') if failed else run.get('result')
    return (f'{_heading(run, "summary", "1", "Сводка прогона")}'
            f'<div class="pair">'
            f'<div><div class="label">Запрос</div>'
            f'{ai_workflow_trace_pdf_text_block(run.get("prompt_user"))}</div>'
            f'<div><div class="label">{answer_label}</div>'
            f'{ai_workflow_trace_pdf_text_block(answer)}</div></div>'
            f'<div class="pair">'
            f'<div><div class="label">Request contract</div>{_contract(run.get("request_json"))}</div>'
            f'<div><div class="label">Response contract</div>{_contract(run.get("response_json"))}</div>'
            f'</div></div>')


def _variables(run: dict) -> str:
    """Переменные прогона: последнее значение каждой и то, откуда оно взялось."""
    snapshot = run.get('variables_start') or ''
    if '...[truncated]' in str(snapshot):
        note = ('<div class="note">Снапшот старта обрезан при записи '
                '(<code>TRACE_VALUE_MAX_LEN</code>) и как JSON не разбирается.</div>')
        return _variables_section(run, note)
    try:
        values = json.loads(snapshot) if snapshot else {}
    except (ValueError, TypeError):
        return _variables_section(run, '<div class="note">Снапшот старта не разбирается как JSON.</div>')
    if not isinstance(values, dict):
        return _variables_section(run, '<div class="note">Снапшот старта не является объектом.</div>')

    source = {name: 'старт' for name in values}
    for step in run.get('steps') or []:
        try:
            changed = json.loads(step.get('variables_changed') or '{}')
        except (ValueError, TypeError):
            continue
        if not isinstance(changed, dict):
            continue
        for name, value in changed.items():
            values[name] = value
            source[name] = f'шаг #{step.get("exec_index")}'

    rows = ''.join(
        f'<tr><td class="v-name">%{ai_workflow_trace_pdf_text_escape(name)}%</td>'
        f'<td class="v-from">{ai_workflow_trace_pdf_text_escape(source.get(name, ""))}</td>'
        f'<td class="v-value">{ai_workflow_trace_pdf_text_inline(values[name])}</td></tr>'
        for name in sorted(values))
    table = (f'<table class="vars"><tr><th>Переменная</th><th>Источник</th><th>Значение</th></tr>'
             f'{rows}</table>' if rows else '<div class="note">Переменных нет.</div>')
    return _variables_section(run, table, len(values))


def _steps(run: dict, plan: list, icons: dict) -> str:
    """Тело документа: шаги и подпотоки ровно в том порядке, что в содержании."""
    blocks = [ai_workflow_trace_pdf_step_child_html(entry) if entry['kind'] == 'run'
              else ai_workflow_trace_pdf_step_html(entry, icons)
              for entry in plan]
    body = ''.join(blocks) or '<div class="note">Шагов в прогоне нет.</div>'
    return f'{_heading(run, "steps", "3", "Шаги выполнения")}{body}</div>'


# ── мелочи разметки ────────────────────────────────────────────────────────

def _heading(run: dict, anchor: str, number: str, title: str) -> str:
    """Начало раздела: новая страница, заголовок и подпись «чей это прогон».

    ⚠ Возвращает **незакрытый** `<div class="section">` — тело раздела
    дописывает вызывающий и закрывает сам. Иначе пришлось бы либо склеивать
    тело строкой заранее (а оно у разделов собирается по-разному), либо
    заводить вторую функцию «конец раздела», которую легко забыть.
    """
    name = run.get('workflow_title') or run.get('workflow_name') or 'workflow'
    return (f'<div class="section" id="{anchor}">'
            f'<h2><span class="h2-num">{number}</span>'
            f'{ai_workflow_trace_pdf_text_escape(title)}</h2>'
            f'<div class="sheet-mark">'
            f'<span>{ai_workflow_trace_pdf_text_escape(name)} · запуск #{run.get("id")}</span>'
            f'<span>{ai_workflow_trace_pdf_text_escape(run.get("run_uuid") or "")}</span></div>')


def _variables_section(run: dict, inner: str, qty: int | None = None) -> str:
    """Обёртка раздела переменных: заголовок со счётчиком и тело."""
    counter = f' ({qty})' if qty is not None else ''
    return f'{_heading(run, "variables", "2", f"Переменные прогона{counter}")}{inner}</div>'


def _toc_row(number: str, name: str, href: str, meta: str, depth: int = 0, sub: bool = False) -> str:
    """Строка содержания: номер, название ссылкой, состояние и длительность справа."""
    shift = f' style="padding-left:{depth * 12}px"' if depth else ''
    return (f'<div class="toc-item{" toc-sub" if sub else ""}"{shift}>'
            f'<span class="toc-no">{ai_workflow_trace_pdf_text_escape(number)}</span>'
            f'<span class="toc-name"><a href="{href}">'
            f'{ai_workflow_trace_pdf_text_escape(name)}</a></span>'
            f'<span class="toc-meta">{ai_workflow_trace_pdf_text_escape(meta)}</span></div>')


def _pair(title, name) -> str:
    """«Название · имя» без пустых половин: удалённый workflow даёт обе пустыми.

    ⚠ Прочерк ставится один на всю строку, а не на каждую половину: «— · —»
    читается как два разных отсутствующих поля, хотя пусто одно — связь.
    """
    parts = [str(x) for x in (title, name) if x]
    return ' · '.join(parts) if parts else '—'


def _contract(raw) -> str:
    """Половина контракта вызова; пусто — объяснение почему, а не прочерк.

    ⚠ Прочерк читался бы как «зовущий прислал пустоту», то есть как поломка
    там, где её нет: у прогонов не из `/chat/ask` и у начатых до миграции
    `20261013114318` контракта нет и не появится.
    """
    if not raw:
        return ('<div class="note">не записан — прогон начат не через <code>/chat/ask</code> '
                'либо снят до появления записи</div>')
    return ai_workflow_trace_pdf_text_block(ai_workflow_trace_pdf_text_json(raw))


def _llm_stats(run: dict) -> tuple:
    """Модели с числом вызовов и сумма токенов по всему дереву прогона."""
    counts, tokens_in, tokens_out = {}, 0, 0

    def walk(node):
        nonlocal tokens_in, tokens_out
        for step in node.get('steps') or []:
            if step.get('llm_name'):
                counts[step['llm_name']] = counts.get(step['llm_name'], 0) + 1
            tokens_in += step.get('tokens_input') or 0
            tokens_out += step.get('tokens_output') or 0
        for child in node.get('children') or []:
            walk(child)

    walk(run)
    return counts, tokens_in, tokens_out

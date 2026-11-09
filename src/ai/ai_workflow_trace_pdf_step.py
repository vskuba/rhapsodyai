"""Шаги и подпотоки печатного журнала: план обхода и разметка одного шага.

Середина сборки документа. Снизу — `..._pdf_text` (как показать значение),
сверху — `..._pdf` (обложка, содержание, печать).

⚠⚠ **План обхода один на содержание и на тело документа** (`..._step_plan`).
Содержание, собранное отдельным проходом, расходится с телом на первом же
особом случае — шаг без `step_id`, подпоток под удалённым шагом, — и ссылка
ведёт не туда. Поэтому обе половины ходят по одному и тому же плоскому списку:
разойтись им негде по построению.
"""
import json

from src.ai.ai_workflow_trace_pdf_text import (
    ai_workflow_trace_pdf_text_badge,
    ai_workflow_trace_pdf_text_block,
    ai_workflow_trace_pdf_text_duration,
    ai_workflow_trace_pdf_text_escape,
    ai_workflow_trace_pdf_text_json,
)

# Сколько самых долгих шагов прогона красить красным. Три — столько же, сколько
# на экранной странице: выгрузка и страница обязаны обвинять одни и те же шаги.
AI_WORKFLOW_TRACE_PDF_STEP_SLOW_QTY = 3

# От какого объёма значений шагу разрешается разрываться между страницами.
#
# ⚠⚠ Запрет разрыва (`page-break-inside: avoid`) на блоке ВЫШЕ листа Chrome
# молча не исполняет, и платится за это пустыми страницами: блок уезжает на
# следующий лист целиком, не влезает и там, и перед каждым длинным шагом
# остаётся белое поле. Поэтому длинным шагам разрыв разрешается явно.
AI_WORKFLOW_TRACE_PDF_STEP_LONG_CHARS = 1200


def ai_workflow_trace_pdf_step_plan(run: dict) -> list:
    """
    Плоский список того, что попадёт в документ: шаги и подпотоки по порядку.

    Один проход дерева отвечает сразу на все вопросы разметки, которые иначе
    пришлось бы считать дважды: якорь записи, её глубина, куда ведёт переход
    шага, какие подпотоки под ним висят и входит ли шаг в тройку самых долгих.

    Returns:
        list: записи `{'kind': 'step'|'run', 'depth', 'anchor', ...}`.
            У шага — `step`, `run`, `slow`, `transition`, `children`;
            у подпотока — `run`, `parent_step`, `parent_anchor`.
    """
    plan = []
    _plan_run(run, 0, plan)
    return plan


def ai_workflow_trace_pdf_step_html(entry: dict, icons: dict) -> str:
    """Один шаг блоком: шапка со статусом и тело с входом, выходом и переходом."""
    step = entry['step']
    head = [
        f'<span class="step-no">#{ai_workflow_trace_pdf_text_escape(step.get("exec_index"))}</span>',
        f'<span class="step-icon">{ai_workflow_trace_pdf_text_escape(icons.get(step.get("step_type"), "·"))}</span>',
        f'<span class="step-name">{ai_workflow_trace_pdf_text_escape(step.get("step_title") or step.get("step_type"))}</span>',
    ]
    if step.get('llm_name'):
        head.append(f'<span class="badge badge-llm">{ai_workflow_trace_pdf_text_escape(step["llm_name"])}</span>')
    tokens = _tokens(step)
    if tokens:
        head.append(f'<span class="badge badge-tokens">{tokens}</span>')
    head.append(ai_workflow_trace_pdf_text_badge(step.get('status')))
    slow = ' step-time-slow' if entry.get('slow') else ''
    head.append(f'<span class="step-time{slow}">'
                f'{ai_workflow_trace_pdf_text_duration(step.get("duration_ms"))}</span>')
    head.append('<a class="step-up" href="#toc">↑ содержание</a>')

    body = []
    if entry.get('transition'):
        body.append('<div class="label">Переход</div>')
        body.append(_transition_html(entry['transition']))
    for anchor, title in entry.get('children') or []:
        body.append(f'<div class="label">Подпоток</div><div><a href="#{anchor}">↓ '
                    f'{ai_workflow_trace_pdf_text_escape(title)}</a></div>')
    body.append('<div class="label">Вход — metadata после рендера</div>')
    body.append(ai_workflow_trace_pdf_text_block(ai_workflow_trace_pdf_text_json(step.get('metadata_rendered'))))
    body.append('<div class="label">Выход — изменённые переменные</div>')
    body.append(ai_workflow_trace_pdf_text_block(ai_workflow_trace_pdf_text_json(step.get('variables_changed'))))
    if step.get('output'):
        body.append('<div class="label">Raw output</div>')
        body.append(ai_workflow_trace_pdf_text_block(step.get('output')))
    if step.get('error'):
        body.append('<div class="label">Ошибка</div>')
        body.append(f'<div class="err">{ai_workflow_trace_pdf_text_block(step.get("error"))}</div>')

    long_class = ' step-long' if _weight(step) > AI_WORKFLOW_TRACE_PDF_STEP_LONG_CHARS else ''
    indent = f' style="margin-left:{entry["depth"] * 10}px"' if entry['depth'] else ''
    return (f'<div class="step{long_class}" id="{entry["anchor"]}"{indent}>'
            f'<div class="step-head">{"".join(head)}</div>'
            f'<div class="step-body">{"".join(body)}</div></div>')


def ai_workflow_trace_pdf_step_child_html(entry: dict) -> str:
    """Шапка подпотока: имя ветки, состояние, длительность и возврат к шагу-родителю."""
    child = entry['run']
    name = child.get('workflow_title') or child.get('workflow_name') or 'sub-workflow'
    parent = entry.get('parent_step') or {}
    back = ''
    if entry.get('parent_anchor'):
        back = (f'<a class="step-up" href="#{entry["parent_anchor"]}">↑ из шага '
                f'#{ai_workflow_trace_pdf_text_escape(parent.get("exec_index"))}</a>')
    indent = f' style="margin-left:{entry["depth"] * 10}px"' if entry['depth'] else ''
    return (f'<div class="child" id="{entry["anchor"]}"{indent}>'
            f'<div class="child-head">'
            f'<span class="child-kicker">Подпоток</span>'
            f'<span class="child-name">{ai_workflow_trace_pdf_text_escape(name)}</span>'
            f'{ai_workflow_trace_pdf_text_badge(child.get("status"))}'
            f'<span class="step-time">{ai_workflow_trace_pdf_text_duration(child.get("duration_ms"))}</span>'
            f'{back}</div>'
            f'<div class="note">шагов: {len(child.get("steps") or [])}'
            f' · запуск #{ai_workflow_trace_pdf_text_escape(child.get("id"))}</div></div>')


# ── детали сборки ──────────────────────────────────────────────────────────

def _plan_run(run: dict, depth: int, plan: list) -> None:
    """Один прогон в плане: его шаги по порядку, под каждым — его подпотоки."""
    steps = run.get('steps') or []
    children_by_step = {}
    for child in run.get('children') or []:
        children_by_step.setdefault(str(child.get('parent_step_id')), []).append(child)

    slow = {s['id'] for s in sorted((s for s in steps if (s.get('duration_ms') or 0) > 0),
                                    key=lambda s: s['duration_ms'], reverse=True
                                    )[:AI_WORKFLOW_TRACE_PDF_STEP_SLOW_QTY]}

    for step in steps:
        anchor = f'step-{step["id"]}'
        kids = [(f'run-{c["id"]}',
                 c.get('workflow_title') or c.get('workflow_name') or 'sub-workflow')
                for c in children_by_step.get(str(step.get('step_id')), [])]
        plan.append({
            'kind': 'step', 'depth': depth, 'anchor': anchor, 'run': run, 'step': step,
            'slow': step['id'] in slow, 'children': kids,
            'transition': _transition_parts(step, steps),
        })
        for child in children_by_step.get(str(step.get('step_id')), []):
            plan.append({'kind': 'run', 'depth': depth + 1, 'anchor': f'run-{child["id"]}',
                         'run': child, 'parent_step': step, 'parent_anchor': anchor})
            _plan_run(child, depth + 1, plan)


def _transition_parts(step: dict, steps: list) -> dict | None:
    """Сработавший переход, разобранный до карточек «откуда → куда» с якорями."""
    raw = step.get('transition')
    if not raw:
        return None
    data = raw if isinstance(raw, dict) else None
    if data is None:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    return {
        'phase': data.get('phase') or '',
        'condition': data.get('condition') or '',
        'from': _step_card(data.get('from_step_id'), step, steps, forward=False),
        'to': _step_card(data.get('to_step_id'), step, steps, forward=True),
    }


def _step_card(step_id, current: dict, steps: list, forward: bool) -> dict:
    """Карточка шага перехода: номер, название и якорь — если шаг в прогоне исполнялся.

    ⚠⚠ Сторона перехода выбирает занятие по-разному, и это не придирка: шаг в
    петле исполняется много раз, а `transition` хранит только `step_id`.
    «Куда» (`forward`) — ближайшее исполнение ПОСЛЕ текущего: туда и перешли.
    «Откуда» — ближайшее НЕ ПОЗЖЕ текущего, то есть обычно сам текущий шаг;
    без этого карточка «откуда» у второго прохода петли показывала бы пятый
    заход вместо второго (поймано кадром выгрузки).
    """
    if not step_id:
        return {'label': '—', 'anchor': ''}
    same = [s for s in steps if s.get('step_id') == step_id]
    if not same:
        return {'label': f'ID {step_id} · шага нет в прогоне', 'anchor': ''}
    here = current.get('exec_index') or 0
    if forward:
        fit = [s for s in same if (s.get('exec_index') or 0) > here]
        target = fit[0] if fit else same[-1]
    else:
        fit = [s for s in same if (s.get('exec_index') or 0) <= here]
        target = fit[-1] if fit else same[0]
    title = target.get('step_title') or target.get('step_type') or ''
    return {'label': f'#{target.get("exec_index")} · {title} (ID {step_id})',
            'anchor': f'step-{target["id"]}'}


def _transition_html(parts: dict) -> str:
    """Переход схемой: две карточки шагов и стрелка с фазой и условием между ними."""
    mid = []
    if parts['phase']:
        mid.append(f'<div>{ai_workflow_trace_pdf_text_escape(parts["phase"])}</div>')
    mid.append('<div class="transition-arrow">⟶</div>')
    if parts['condition']:
        mid.append(f'<div class="transition-cond">'
                   f'{ai_workflow_trace_pdf_text_escape(parts["condition"])}</div>')
    return (f'<div class="transition">{_transition_card(parts["from"])}'
            f'<div class="transition-mid">{"".join(mid)}</div>'
            f'{_transition_card(parts["to"])}</div>')


def _transition_card(card: dict) -> str:
    """Карточка перехода: ссылкой, если шаг в документе есть, иначе просто текстом."""
    text = ai_workflow_trace_pdf_text_escape(card['label'])
    if card['anchor']:
        return f'<a class="transition-card" href="#{card["anchor"]}">{text}</a>'
    return f'<div class="transition-card">{text}</div>'


def _tokens(step: dict) -> str:
    """Токены шага строкой `↑N ↓N`; не LLM-шаг — пусто."""
    parts = []
    if step.get('tokens_input') is not None:
        parts.append(f'↑{step["tokens_input"]}')
    if step.get('tokens_output') is not None:
        parts.append(f'↓{step["tokens_output"]}')
    return ' '.join(parts)


def _weight(step: dict) -> int:
    """Сколько знаков значений несёт шаг — по этому решается разрыв между страницами."""
    return sum(len(str(step.get(key) or ''))
               for key in ('metadata_rendered', 'variables_changed', 'output', 'error'))

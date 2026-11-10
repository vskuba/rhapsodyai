"""Жребий прогона: какие варианты были и какой выпал.

Трасса пишет **выпавшее**. Чтобы понять, почему письмо вышло таким, нужно
соседнее — **из чего выбирали**: доли вариантов живут в описании жребия, и без
них «выпало confession» не значит ничего.

⚠⚠ Описание жребия в шаге **не лежит**. У `tool_invoke` в `inputs_map.spec`
стоит ИМЯ переменной (`dice_invite_batch_spec`), а её значение собирается в
заходе — из настройки сайта, из входящей переменной, из шага выше. Поэтому
описание ищется в переменных прогона, а не в определении шага: снимок старта
плюс всё, что дописали шаги до жребия.

⚠ Модуль чистый: ни базы, ни разметки. Определения шагов ему отдаёт
`..._pdf_source`, показывает собранное `..._pdf`.
"""
import json

# Доля-«остаток»: всё, что не разобрали соседи по переменной. Имя то же, что у
# самого инструмента (`src/tool/dice/dice.py`, `DICE_REST`) — разойдись они, в
# документе появилась бы доля «rest» как вариант с именем.
AI_WORKFLOW_TRACE_PDF_DICE_REST = 'rest'

# Сумма долей одной переменной, от которой считается «остаток».
AI_WORKFLOW_TRACE_PDF_DICE_TOTAL = 100


def ai_workflow_trace_pdf_dice(run: dict, defined: dict) -> list:
    """
    Жребии, связанные с прогоном: варианты, доли и то, что выпало.

    Args:
        run: дерево прогона из `GET /workflow_trace/run/{run_uuid}`.
        defined: `{workflow_id: [описание шага жребия]}` из `..._pdf_source` —
            шаги **по определению** workflow, включая не сработавшие.

    Returns:
        list: по записи на шаг жребия —
        `{'title', 'tool_name', 'spec_ref', 'workflow', 'fired', 'exec_index',
        'anchor', 'groups': [{'name', 'options': [{'label','share','rolled'}]}]}`.
        `fired=False` — до шага прогон не дошёл; `groups` тогда пуст, если
        описание не нашлось в переменных.

    ⚠ Порядок — по веткам дерева, как они идут в документе: сперва жребии
    корня, затем подпотоков. Жребий, не сработавший в этот раз, остаётся в
    списке — он описывает, каким прогон мог быть.
    """
    out: list = []
    _collect(run, defined, out)
    return out


# ── детали сборки ──────────────────────────────────────────────────────────

def _collect(node: dict, defined: dict, out: list) -> None:
    """Жребии одной ветки, затем её подпотоков — тем же порядком, что в теле."""
    variables = _snapshot(node)
    fired = _fired(node)

    for item in defined.get(node.get('workflow_id')) or []:
        step = fired.get(item['step_id'])
        spec = _spec(variables, item.get('spec_ref'))
        out.append({
            'title': item.get('title') or 'Жребий',
            'tool_name': item.get('tool_name'),
            'spec_ref': item.get('spec_ref'),
            'workflow': node.get('workflow_title') or node.get('workflow_name') or '',
            'run_id': node.get('id'),
            'fired': step is not None,
            'exec_index': step.get('exec_index') if step else None,
            'anchor': f'step-{step["id"]}' if step else '',
            'groups': _groups(spec, _rolled(step, item)),
        })

    for child in node.get('children') or []:
        _collect(child, defined, out)


def _snapshot(node: dict) -> dict:
    """Переменные ветки: снимок старта плюс всё, что дописали её шаги.

    ⚠ Накапливаем по всем шагам, а не до жребия: описание жребия задаётся
    до него по построению, а частичный снимок терял бы его у шага, чей
    `spec` собирается соседним шагом того же захода.
    """
    try:
        values = json.loads(node.get('variables_start') or '{}')
    except (ValueError, TypeError):
        values = {}
    if not isinstance(values, dict):
        values = {}

    for step in node.get('steps') or []:
        try:
            changed = json.loads(step.get('variables_changed') or '{}')
        except (ValueError, TypeError):
            continue
        if isinstance(changed, dict):
            values.update(changed)
    return values


def _fired(node: dict) -> dict:
    """Сработавшие шаги ветки по `step_id` — последний заход, если их было много."""
    out = {}
    for step in node.get('steps') or []:
        if step.get('step_id'):
            out[step['step_id']] = step
    return out


def _spec(variables: dict, spec_ref) -> dict:
    """Описание жребия по имени переменной; не нашлось — пустой словарь."""
    if not spec_ref:
        return {}
    value = variables.get(spec_ref)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _rolled(step, item: dict) -> dict:
    """Что выпало: `{имя переменной жребия: [значения]}`.

    ⚠⚠ Имён у выпавшего два, и смотреть надо оба. Движок кладёт результат и в
    `dice_<step_id>_result_<ключ>`, и в то имя, которое задано `outputs_map`;
    у `dice_batch` значение — список на всю пачку, то есть выпало сразу
    несколько вариантов.
    """
    if not step:
        return {}
    try:
        changed = json.loads(step.get('variables_changed') or '{}')
    except (ValueError, TypeError):
        return {}
    if not isinstance(changed, dict):
        return {}

    outputs = item.get('outputs_map') or {}
    out: dict = {}
    for key in set(list(outputs) + list(changed)):
        value = changed.get(outputs.get(key, key))
        if value is None:
            value = changed.get(f'{item["tool_name"]}_{item["step_id"]}_result_{key}')
        if value is None:
            continue
        out[key] = _values(value)
    return out


def _values(value) -> list:
    """Выпавшее списком: у `dice_batch` это серия, у `dice` — одно значение."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = value
        value = parsed
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _groups(spec: dict, rolled: dict) -> list:
    """Переменные жребия с их вариантами; выпавшие помечены."""
    groups = []
    for name, options in spec.items():
        if not isinstance(options, dict):
            continue
        hits = rolled.get(name) or []
        known = sum(v for v in options.values() if isinstance(v, (int, float)))
        rest = max(0, AI_WORKFLOW_TRACE_PDF_DICE_TOTAL - known)
        groups.append({
            'name': name,
            'rolled': hits,
            'options': [{'label': str(label),
                         'share': _share(share, rest),
                         'rolled': str(label) in hits}
                        for label, share in options.items()],
        })
    return groups


def _share(share, rest: int) -> str:
    """Доля словами: число процентами, `rest` — остатком, метка — как есть.

    ⚠ Метка (`%имя%`) доезжает сюда только тогда, когда переменной в заходе не
    было: движок подставляет её значение до вызова инструмента. Показываем её
    как есть — это и есть ответ «доля не задана».
    """
    if isinstance(share, bool):
        return str(share)
    if isinstance(share, (int, float)):
        return f'{share:g}%'
    if str(share) == AI_WORKFLOW_TRACE_PDF_DICE_REST:
        return f'остаток ({rest}%)'
    return str(share)

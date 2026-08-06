"""
Формат плана Manager.

План живёт в `task.pipeline_plan` как JSON `{plan_text, subtasks, goals}`: первое
идёт человеку на утверждение, второе после утверждения материализуется в
`project_task_subtask`, третье попадает в `project_task.goals` (колонка «Цели»).

Цели держим и здесь тоже, хотя они уже записаны в задачу: в `task.goals` человек
их правит, а в плане остаётся то, что предложил менеджер, — иначе разбирать
расхождение будет нечем.
"""
import json


def task_plan_serialize(plan_text: str, subtasks: list, goals: list | None = None) -> str:
    return json.dumps(
        {'plan_text': plan_text, 'subtasks': subtasks, 'goals': goals or []},
        ensure_ascii=False,
    )


def task_plan_parse(raw: str) -> tuple[str, list]:
    """Returns: (plan_text, subtasks). Пустой/битый план — ('', [])."""
    data = _task_plan_dict(raw)
    subtasks = data.get('subtasks')
    return str(data.get('plan_text') or ''), subtasks if isinstance(subtasks, list) else []


def task_plan_goals_get(raw: str) -> list[dict]:
    """Цели, предложенные менеджером, из JSON плана. Returns: [{'text', 'done'}]."""
    return task_plan_goals_normalize(_task_plan_dict(raw).get('goals'))


def task_plan_goals_normalize(goals_raw) -> list[dict]:
    """
    Привести цели к формату колонки `project_task.goals` — `[{'text', 'done'}]`.

    На входе что угодно из трёх источников: JSON-строка из БД, список строк от
    менеджера (`task_goals_json`) или уже готовые словари. Пустые и повторные
    формулировки отбрасываем — в UI это были бы пустые чекбоксы.
    """
    if isinstance(goals_raw, str):
        try:
            goals_raw = json.loads(goals_raw or '')
        except (ValueError, TypeError):
            return []
    if isinstance(goals_raw, dict):
        goals_raw = goals_raw.get('goals')
    if not isinstance(goals_raw, list):
        return []

    goals, seen = [], set()
    for item in goals_raw:
        text = str((item.get('text') if isinstance(item, dict) else item) or '').strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        goals.append({'text': text, 'done': bool(item.get('done')) if isinstance(item, dict) else False})
    return goals


def task_plan_goals_merge(goals_current_raw, goals_new: list) -> str:
    """
    JSON для `project_task.goals`: цели человека остаются как есть, цели менеджера
    добавляются в конец.

    Перезаписывать нельзя — у уже отмеченных целей потерялся бы `done`, а список
    человека для менеджера был входными данными, а не черновиком.
    """
    goals = task_plan_goals_normalize(goals_current_raw)
    seen = {g['text'].lower() for g in goals}
    for goal in task_plan_goals_normalize(goals_new):
        if goal['text'].lower() in seen:
            continue
        seen.add(goal['text'].lower())
        goals.append(goal)
    return json.dumps(goals, ensure_ascii=False)


def _task_plan_dict(raw) -> dict:
    try:
        data = json.loads(raw or '')
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}

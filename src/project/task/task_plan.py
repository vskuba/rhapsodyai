"""
Формат плана Manager.

План живёт в `task.pipeline_plan` как JSON `{plan_text, subtasks, goals}`: первое
идёт человеку на утверждение, второе после утверждения материализуется в детей той
же `project_task` (`pipeline_from_plan = 1`), третье попадает в `project_task.goals`
(колонка «Цели»).

Цели держим и здесь тоже, хотя они уже записаны в задачу: в `task.goals` человек
их правит, а в плане остаётся то, что предложил менеджер, — иначе разбирать
расхождение будет нечем.
"""
import json
import re
from difflib import SequenceMatcher

# Насколько похожие формулировки считаем одной целью.
#
# Точного совпадения мало: менеджер разводит одну проверку на две строки, поменяв
# в ней пару слов, — человеку это две галочки об одном и том же, а QA прогоняет
# круг проверки на каждую. Порог подобран по живым планам: 0.85 склеивает такие
# пары и оставляет врозь цели, у которых различие по существу, а не в обёртке.
TASK_PLAN_GOAL_SIMILAR_RATIO = 0.85


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
    менеджера (`task_goals_json`) или уже готовые словари. Пустые формулировки
    отбрасываем — в UI это были бы пустые чекбоксы, — а повторные и близкие к уже
    принятым схлопываем в одну: см. `TASK_PLAN_GOAL_SIMILAR_RATIO`.

    Из пары похожих остаётся первая: порядок целей задаёт человек или менеджер, и
    вторая формулировка — это уже пересказ принятой, а не уточнение к ней.
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

    goals, keys = [], []
    for item in goals_raw:
        text = str((item.get('text') if isinstance(item, dict) else item) or '').strip()
        key = _task_plan_goal_key(text)
        if not key or _task_plan_goal_seen(key, keys):
            continue
        keys.append(key)
        goals.append({'text': text, 'done': bool(item.get('done')) if isinstance(item, dict) else False})
    return goals


def task_plan_goals_merge(goals_current_raw, goals_new: list) -> str:
    """
    JSON для `project_task.goals`: цели человека остаются как есть, цели менеджера
    добавляются в конец.

    Перезаписывать нельзя — у уже отмеченных целей потерялся бы `done`, а список
    человека для менеджера был входными данными, а не черновиком.

    Похожие на уже имеющиеся цели менеджера не добавляем по тому же правилу, что и
    внутри одного списка: человек написал цель своими словами, менеджер повторил её
    своими — проверять это дважды незачем.
    """
    goals = task_plan_goals_normalize(goals_current_raw)
    keys = [_task_plan_goal_key(goal['text']) for goal in goals]
    for goal in task_plan_goals_normalize(goals_new):
        key = _task_plan_goal_key(goal['text'])
        if _task_plan_goal_seen(key, keys):
            continue
        keys.append(key)
        goals.append(goal)
    return json.dumps(goals, ensure_ascii=False)


def _task_plan_goal_key(text: str) -> str:
    """
    Формулировка без регистра, знаков и лишних пробелов — по ней сверяем цели.

    Пунктуация здесь только мешает: «панель раскрывается, и схлопывается» и
    «панель раскрывается и схлопывается» — одна цель.
    """
    return ' '.join(re.sub(r'[^\w\s]+', ' ', str(text or '').lower()).split())


def _task_plan_goal_seen(key: str, keys: list[str]) -> bool:
    """Есть ли среди уже принятых целей та же — точно или с точностью до слов."""
    return any(key == seen or SequenceMatcher(None, key, seen).ratio() >= TASK_PLAN_GOAL_SIMILAR_RATIO
               for seen in keys)


def _task_plan_dict(raw) -> dict:
    try:
        data = json.loads(raw or '')
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}

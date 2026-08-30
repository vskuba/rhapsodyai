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


def task_plan_serialize(plan_text: str, subtasks: list, goals: list | None = None,
                        repo_dir: str = '') -> str:
    """
    План в JSON. `repo_dir` — привести пути к корню репозитория.

    Зачем приведение. План читает исполнитель, а работает он в своей выкладке —
    отдельном каталоге репозитория. Абсолютный путь уводит его оттуда: файл ложится в
    основной чекаут, а коммит идёт следом за файлом. Так подзадача #4799 попала в
    главную ветку, и это не было небрежностью — путь стоял прямо в плане, исполнитель
    сделал написанное.

    Промпт менеджера теперь требует относительных путей (миграция `20260830120000`),
    но требование в промпте держится ровно до первой невнимательности модели. Здесь —
    то же правило делом: через эту функцию проходит каждая запись плана, чья бы она ни
    была, поэтому чинится и то, что напишет человек руками.

    Переписываем молча, а не отвергаем: путь однозначен — `<repo>/src/x.py` при корне
    `<repo>` означает `src/x.py` и ничего другого. Отказ ронял бы круг планирования
    (15–25 минут работы) ради того, что чинится подстановкой.

    Без `repo_dir` ничего не трогаем: у части вызывающих корня под рукой нет, и
    гадать, что здесь абсолютный путь проекта, а что — путь из чужой системы, нельзя.
    """
    if repo_dir:
        plan_text = task_plan_paths_relative(plan_text, repo_dir)
        subtasks = [
            {**item, 'plan': task_plan_paths_relative(str(item.get('plan') or ''), repo_dir)}
            if isinstance(item, dict) and item.get('plan') else item
            for item in (subtasks or [])
        ]

    return json.dumps(
        {'plan_text': plan_text, 'subtasks': subtasks, 'goals': goals or []},
        ensure_ascii=False,
    )


def task_plan_paths_relative(text: str, repo_dir: str) -> str:
    """
    Абсолютные пути проекта — в пути от корня репозитория.

    Два вида приставок, и порядок важен. Сначала каталог выкладки
    (`<repo>/.claude/worktrees/feature_task_<N>/`) — он длиннее и содержит в себе
    корень, так что снятый первым корень оставил бы от него бессмысленный хвост
    `.claude/worktrees/feature_task_5/src/x.py`. Потом сам корень.

    Выкладка попадает в план, когда менеджер ведёт разведку у себя: путь, который он
    там видит, ведёт в его собственный каталог, а исполнитель работает в другом —
    и такой путь не лучше, чем путь в основной чекаут.

    Чужие абсолютные пути не трогаем: `/etc/hosts` и `/var/log/…` — это не про наш
    репозиторий, и обрезать их значило бы испортить осмысленный текст.
    """
    text = str(text or '')
    root = str(repo_dir or '').rstrip('/')
    if not text or not root:
        return text

    text = re.sub(re.escape(root) + r'/\.claude/worktrees/feature_task_\d+/', '', text)

    return text.replace(root + '/', '')


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


def task_plan_goals_text(goals_raw) -> str:
    """
    Цели нумерованным списком — в таком виде их видит агент в промпте.

    Номера считаем с единицы и по сырому списку, не схлопывая похожие: те же
    номера выдаёт QA инструмент `task_goal_pick`, и вердикт «цель 3 закрыта»
    должен относиться к той же строке, что человек видит в колонке «Цели».

    Отметку `done` показываем: на повторном круге закрытые цели перепроверять
    незачем, а без пометки агент проходит их заново.

    Пустая строка на выходе ложна для `%if task_goals%` — блок целей в промпте
    тогда не раскроется, и агент увидит «не заданы» вместо пустого заголовка.
    """
    try:
        goals = json.loads(str(goals_raw or '') or '[]') if isinstance(goals_raw, str) else goals_raw
    except (ValueError, TypeError):
        return ''
    if not isinstance(goals, list):
        return ''

    lines = []
    for i, goal in enumerate(goals, 1):
        text = str((goal.get('text') if isinstance(goal, dict) else goal) or '').strip()
        if not text:
            continue
        mark = ' [закрыта]' if isinstance(goal, dict) and goal.get('done') else ''
        lines.append(f'{i}.{mark} {text}')
    return '\n'.join(lines)


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

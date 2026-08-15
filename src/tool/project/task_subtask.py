"""
Разбиение неделимой работы — без хода агента.

Менеджеру нечего решать, когда разведка уже назвала работу точечной (`task_size
= small`): у такой задачи одна подзадача на всю задачу, и она повторяет её план
и цели. По трейсам этот ход стоил 2-12 минут и заканчивался ответом «работа
неделимая» — время платили за то, что и так известно.

Собирает JSON инструмент, а не шаблон `variable_conversion`: заголовок и
описание пишет человек, и первая же кавычка или перевод строки в них порвали бы
склеенную строками разметку. Здесь всё уходит через `json.dumps`.
"""
import json

from mysql_.mysql_ import mysql_get_db_async

# Описание подзадачи читает исполнитель перед работой: несколько предложений
# помогают, страница текста — нет, у него для этого есть план.
TASK_SUBTASK_DESCRIPTION_MAX_CHARS = 1000


async def task_subtask_single(task_id: int, plan_json: str = '', goals_json: str = '') -> dict:
    """
    Собирает разбиение из одной подзадачи, повторяющей саму задачу.

    Для точечной работы, которую делить не на что: подзадача берёт заголовок и
    описание задачи, а план и цели — те, что менеджер только что выдал.
     - task_id: ID задачи (project_task.id), которую разбиваем
     - plan_json: план от менеджера, объект с ключом plan_text либо готовый текст
     - goals_json: цели от менеджера, массив строк
    Returns:
        dict: Разбиение, содержащее:
            subtasks_json (str): массив из одной подзадачи с полями title,
                description, plan, goals — тот же вид, что даёт ход менеджера.
            subtasks_count (int): сколько подзадач получилось; всегда 1.
    """
    task = await _task_load(int(task_id or 0))

    subtask = {
        'title': task['title'],
        'description': task['description'][:TASK_SUBTASK_DESCRIPTION_MAX_CHARS],
        'plan': _plan_text(plan_json),
        'goals': _goals_list(goals_json),
    }

    return {'subtasks_json': json.dumps([subtask], ensure_ascii=False), 'subtasks_count': 1}


async def _task_load(task_id: int) -> dict:
    """Заголовок и описание задачи. Пустая строка вместо NULL — их увидит агент."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT title, description FROM project_task WHERE id = %s', (task_id,))
        row = await db.fetchone()

    if not row:
        raise ValueError(f'задача {task_id} не найдена')

    return {'title': str(row.get('title') or '').strip(),
            'description': str(row.get('description') or '').strip()}


def _plan_text(raw) -> str:
    """План текстом: менеджер отдаёт объект `{"plan_text": …}`, но переспрос — строку."""
    value = _json_load(raw)
    if isinstance(value, dict):
        return str(value.get('plan_text') or '').strip()

    return str(raw or '').strip()


def _goals_list(raw) -> list:
    """Цели списком строк. Не массив — значит целей нет, и выдумывать их нечем."""
    value = _json_load(raw)
    if not isinstance(value, list):
        return []

    return [str(item).strip() for item in value if str(item).strip()]


def _json_load(raw):
    """Разбор без падения: JSON пишет агент, и битую строку роняет не инструмент."""
    if isinstance(raw, (dict, list)):
        return raw

    try:
        return json.loads(str(raw or '').strip() or 'null')
    except Exception:
        return None

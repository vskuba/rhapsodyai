"""
Смена охвата вставшей подзадачи: раздробить цели или сократить их.

Зачем. Подзадача #1029 — «разобрать три больших файла» — за три круга ни разу не
уложилась: два прогона оборвались по таймауту, три дошли до отчёта со словами
«работа начата, но не доведена». Дело не в агенте и не во времени круга: в один
круг не влезает объём. Четвёртый заход с тем же охватом кончится тем же, и
единственное, что здесь помогает, — уменьшить охват.

Решение это человека, а не конвейера, поэтому спрашивается вопросом
(`task_question_auto`), а здесь только исполнение ответа.

Два действия, и разница между ними существенная.

**Раздробить** — отмеченные цели уезжают в новую соседнюю подзадачу. Работа не
теряется: её сделает отдельный круг, просто не этот. Это ответ на «слишком много
за раз».

**Сократить** — цели исчезают вовсе. Это ответ на «эта работа не нужна», а не на
«она не влезает»: выбрасывать невлезающее значит закрыть подзадачу, не сделав
того, ради чего её заводили.

Обе правки пишутся и в решения подзадачи (`metadata.decisions`), чтобы роль на
следующем круге видела не только новый список целей, но и то, что список меняли и
почему. Без этого агент, помнящий прежний охват по журналу, принялся бы доделывать
убранное.
"""
import json

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_plan import task_plan_goals_normalize
from src.project.task.task_state import task_state_kanban_status

# Хвост к названию новой подзадачи при дроблении. Нужен: без него в списке две
# строки с одинаковым названием, и понять, где какая половина работы, нельзя.
TASK_GOAL_SCOPE_SPLIT_SUFFIX = ' (продолжение)'

# Потолок на длину названия — колонка `title` не резиновая, а к исходному имени
# добавляется хвост.
TASK_GOAL_SCOPE_TITLE_MAX = 200


async def task_goal_scope_split(subtask: dict, indexes: list) -> dict:
    """
    Вынести отмеченные цели в новую соседнюю подзадачу.

    Args:
        subtask: строка подзадачи целиком — из неё берутся цели, родитель и проект.
        indexes: номера целей с нуля, в порядке колонки `goals`.

    Новая строка заводится с `pipeline_from_plan = 1` — тем же происхождением, что
    и подзадачи менеджера. Иначе сброс плана обошёл бы её стороной и оставил
    сироту от снесённого плана.

    Позиция — сразу за исходной строкой: дробление даёт продолжение работы, и
    место ему рядом, а не в конце списка.

    Returns: `{ok, moved, kept, subtask_id}`; `subtask_id` — заведённая строка.
        Отмечены все цели или ни одной — `{ok: False}`: в первом случае получилась
        бы пустая исходная подзадача, во втором пустая новая.
    """
    goals = task_plan_goals_normalize(subtask.get('goals'))
    moved, kept = _goals_partition(goals, indexes)
    if not moved or not kept:
        return {'ok': False, 'error': 'Отметьте часть целей: пустая подзадача ни к чему',
                'moved': len(moved), 'kept': len(kept)}

    title = (str(subtask.get('title') or '').strip() + TASK_GOAL_SCOPE_SPLIT_SUFFIX)[:TASK_GOAL_SCOPE_TITLE_MAX]
    description = _split_description(subtask, moved)

    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_task "
            "       (project_id, parent_id, title, description, goals, position, status, "
            "        task_type_id, pipeline_state, pipeline_from_plan) "
            "SELECT t.project_id, t.parent_id, %s, %s, %s, t.position + 1, %s, "
            "       (SELECT id FROM project_task_type WHERE name = 'dev'), 'planned', 1 "
            "  FROM project_task t WHERE t.id = %s",
            (title, description, json.dumps(moved, ensure_ascii=False),
             task_state_kanban_status('planned'), subtask['id']),
        )
        created = db.lastrowid
        await db.execute("UPDATE project_task SET goals = %s WHERE id = %s",
                         (json.dumps(kept, ensure_ascii=False), subtask['id']))
        await db.connection.commit()

    logger_info(f"[task] subtask#{subtask['id']}: {len(moved)} целей вынесено в #{created}")

    return {'ok': True, 'moved': len(moved), 'kept': len(kept), 'subtask_id': created,
            'moved_text': [g['text'] for g in moved]}


async def task_goal_scope_drop(subtask: dict, indexes: list) -> dict:
    """
    Убрать отмеченные цели из подзадачи совсем.

    Все цели разом убрать не даём: подзадача без единой цели неотличима от
    сделанной — QA нечего проверять, и она пройдёт проверку, не будучи выполненной.

    Returns: `{ok, dropped, kept}`.
    """
    goals = task_plan_goals_normalize(subtask.get('goals'))
    dropped, kept = _goals_partition(goals, indexes)
    if not dropped:
        return {'ok': False, 'error': 'Не отмечено ни одной цели', 'dropped': 0, 'kept': len(kept)}
    if not kept:
        return {'ok': False, 'error': 'Нельзя убрать все цели: подзадачу станет нечем принимать',
                'dropped': len(dropped), 'kept': 0}

    async with mysql_get_db_async() as db:
        await db.execute("UPDATE project_task SET goals = %s WHERE id = %s",
                         (json.dumps(kept, ensure_ascii=False), subtask['id']))
        await db.connection.commit()

    logger_info(f"[task] subtask#{subtask['id']}: убрано целей {len(dropped)}")

    return {'ok': True, 'dropped': len(dropped), 'kept': len(kept),
            'dropped_text': [g['text'] for g in dropped]}


def _goals_partition(goals: list, indexes: list) -> tuple[list, list]:
    """
    Разделить цели на отмеченные и оставшиеся, сохранив порядок.

    Номера приходят от страницы и могли устареть: пока попап был открыт, цели мог
    поменять сам агент. Выход за границы списка пропускаем молча — лучше сделать
    меньше, чем задеть не ту цель.
    """
    picked = {int(i) for i in (indexes or []) if str(i).lstrip('-').isdigit()}

    return ([g for n, g in enumerate(goals) if n in picked],
            [g for n, g in enumerate(goals) if n not in picked])


def _split_description(subtask: dict, moved: list) -> str:
    """
    Описание новой строки: откуда она взялась и что именно в неё уехало.

    Копировать описание исходной подзадачи целиком нельзя — оно описывает весь
    прежний охват, и агент новой строки принялся бы делать всё то же самое.
    """
    origin = f"Выделено из подзадачи #{subtask['id']} «{str(subtask.get('title') or '').strip()}»: "
    origin += 'охват не укладывался в круг, часть целей вынесена сюда.'
    goals = '\n'.join(f"- {g['text']}" for g in moved)

    return f'{origin}\n\nЦели, которые сюда переехали:\n{goals}'

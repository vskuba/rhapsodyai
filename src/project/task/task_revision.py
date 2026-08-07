"""
История версий плана задачи.

План живёт в `project_task.pipeline_plan` и перезаписывается на месте — и менеджером,
и человеком. Каждая такая запись оставляет здесь строку, поэтому самая свежая ревизия
всегда совпадает с текущим планом; предыдущие остаются, чтобы было видно, как план
менялся и кто его менял.

Отдельный модуль, а не часть `task_state.py`: там пишет только конвейер, а ревизии
добавляет ещё и HTTP-роутер от имени человека.
"""
import json

from pymysql.err import IntegrityError

from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_plan import task_plan_goals_normalize

TASK_REVISION_LIMIT = 20  # сколько последних ревизий отдавать в UI вместе с содержимым


async def task_revision_add(task_id: int, plan_text: str, goals: list, subtasks: list,
                            author_kind: str, author_id: int | None = None,
                            author_name: str = '') -> int | None:
    """
    Добавить ревизию плана. Returns: номер ревизии либо None, если писать нечего.

    Не пишем в двух случаях. Первый — пустой план без подзадач: версионировать
    отсутствие плана не нужно. Второй — содержимое совпадает с последней ревизией:
    страница отправляет `plan_text` при каждом «Сохранить», в том числе когда правили
    название, и без этой проверки история заросла бы одинаковыми чипсами.
    """
    plan_text = str(plan_text or '').strip()
    goals     = task_plan_goals_normalize(goals)
    subtasks  = subtasks if isinstance(subtasks, list) else []
    if not plan_text and not subtasks:
        return None

    goals_json    = json.dumps(goals, ensure_ascii=False)
    subtasks_json = json.dumps(subtasks, ensure_ascii=False)

    last = await _task_revision_last(task_id)
    if last and last['plan_text'] == plan_text and last['goals'] == goals_json:
        return None

    # Номер считается тем же запросом, что и вставка: отдельный SELECT + INSERT
    # разъехались бы под двумя воркерами. Уникальный ключ ловит остаток гонки —
    # проигравший повторяет попытку и получает следующий номер.
    sql = (
        "INSERT INTO project_task_plan_revision "
        "       (task_id, revision_no, plan_text, goals, subtasks, author_kind, author_id, author_name) "
        "SELECT %s, COALESCE(MAX(revision_no), 0) + 1, %s, %s, %s, %s, %s, %s "
        "  FROM project_task_plan_revision WHERE task_id = %s"
    )
    params = (task_id, plan_text, goals_json, subtasks_json,
              author_kind, author_id, str(author_name or '')[:64], task_id)

    async with mysql_get_db_async() as db:
        try:
            await db.execute(sql, params)
        except IntegrityError:
            # Номер увели из-под нас — второй заход посчитает следующий. Дальше
            # ошибку не глотаем: молча пропавшая ревизия хуже упавшего шага.
            await db.execute(sql, params)
        await db.connection.commit()

        await db.execute(
            "SELECT MAX(revision_no) AS n FROM project_task_plan_revision WHERE task_id = %s",
            (task_id,),
        )
        row = await db.fetchone()

    return int(row['n']) if row and row['n'] is not None else None


async def task_revision_list(task_id: int, limit: int = TASK_REVISION_LIMIT) -> tuple[list[dict], int]:
    """
    Ревизии задачи от свежих к старым, вместе с содержимым.

    Returns: (ревизии, сколько их всего).

    Содержимое отдаём сразу, а не отдельным запросом на каждый чипс: переключение
    между версиями должно быть мгновенным, в этом весь смысл ряда чипсов. Отсюда и
    `limit` — без него страница тянула бы всю историю целиком.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, revision_no, plan_text, goals, subtasks, author_kind, author_id, author_name, created_at "
            "  FROM project_task_plan_revision WHERE task_id = %s "
            " ORDER BY revision_no DESC LIMIT %s",
            (task_id, int(limit)),
        )
        rows = await db.fetchall()

        await db.execute(
            "SELECT COUNT(*) AS cnt FROM project_task_plan_revision WHERE task_id = %s",
            (task_id,),
        )
        total = await db.fetchone()

    return [_task_revision_row(r) for r in (rows or [])], int(total['cnt'] if total else 0)


async def task_revision_get(task_id: int, revision_no: int) -> dict | None:
    """
    Одна ревизия задачи по её номеру.

    Ищем по паре (задача, номер), а не по `id`: номер — это то, что показано человеку
    в чипсе, и ссылка на ревизию чужой задачи не должна подменить план не той задачи.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, revision_no, plan_text, goals, subtasks, author_kind, author_id, author_name, created_at "
            "  FROM project_task_plan_revision WHERE task_id = %s AND revision_no = %s",
            (task_id, int(revision_no)),
        )
        row = await db.fetchone()

    return _task_revision_row(row) if row else None


async def task_revision_delete(task_id: int, revision_no: int) -> bool:
    """
    Удалить одну ревизию.

    После удаления номера не пересчитываются — это упрощает каскад и сохраняет
    ссылки. Просто удаляем строку, остальные номера не трогаем.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "DELETE FROM project_task_plan_revision WHERE task_id = %s AND revision_no = %s",
            (task_id, int(revision_no)),
        )
        await db.connection.commit()
    return True


def _task_revision_row(row) -> dict:
    """Строка ревизии для API: JSON-колонки разворачиваем, цели приводим к [{text, done}]."""
    return {
        'id':          int(row['id']),
        'n':           int(row['revision_no']),
        'plan_text':   str(row['plan_text'] or ''),
        'goals':       task_plan_goals_normalize(row['goals']),
        'subtasks':    _task_revision_json_list(row['subtasks']),
        'author_kind': str(row['author_kind'] or 'manager'),
        'author_id':   row['author_id'],
        'author_name': str(row['author_name'] or ''),
        'created_at':  row['created_at'],
    }


def _task_revision_json_list(raw) -> list:
    try:
        data = json.loads(raw or '')
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


async def _task_revision_last(task_id: int) -> dict | None:
    """Самая свежая ревизия — с ней сравнивается новая, чтобы не плодить дубли."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT plan_text, goals FROM project_task_plan_revision "
            " WHERE task_id = %s ORDER BY revision_no DESC LIMIT 1",
            (task_id,),
        )
        row = await db.fetchone()
    return {'plan_text': str(row['plan_text'] or ''), 'goals': str(row['goals'] or '')} if row else None

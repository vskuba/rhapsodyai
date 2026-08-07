"""
Захват работы конвейера и возврат протухших блокировок.

Запуски крона могут накладываться, поэтому захват — условный `UPDATE` с проверкой
`rowcount`, а не `SELECT ... FOR UPDATE`: два воркера не должны взять одну строку.
Если воркер умрёт посреди перехода, строка залипнет в переходном состоянии —
`task_claim_locks_reclaim()` возвращает такие строки в работу по таймауту.
"""
import os
import socket

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_state import task_state_subtask_set

LOCK_TIMEOUT_SEC = 900

# Переходные состояния и то, куда их возвращать при протухшей блокировке.
# Для qa_pending и review состояние то же — снимается только сама блокировка.
#
# `review` нельзя возвращать в `new`, как `planning`: план у такой задачи есть, и
# `task_claim_task_unplanned` её не подберёт — задача залипла бы навсегда. Оставляем
# ждать пересмотра, за ней придёт следующий тик.
_TASK_STATE_RECLAIM = {'planning': 'new', 'review': 'review'}
_SUBTASK_STATE_RECLAIM = {'developing': 'planned', 'qa_pending': 'qa_pending'}


def task_claim_worker_id() -> str:
    return f'{socket.gethostname()}:{os.getpid()}'[:64]


async def task_claim_task(state_from: str, state_to: str, worker: str) -> dict | None:
    """
    Перевести одну задачу state_from -> state_to и вернуть её.
    None, если подходящих нет или строку увёл параллельный воркер.
    """
    return await _task_claim(
        "pipeline_state = %s", [state_from], state_to, worker)


async def task_claim_task_unplanned(worker: str) -> dict | None:
    """
    Захватить задачу без плана и увести её в `planning`.

    Человеческий `status` при отборе не смотрим: критерий — плана нет ИЛИ
    целей нет. Задача может и не быть заведена в конвейер явно (`pipeline_state IS
    NULL`) — план менеджер пишет всё равно.

    «Плана нет» — это ноль подзадач в `pipeline_plan`. Битый JSON приравниваем
    к пустому плану (через `JSON_VALID`). «Целей нет» — пустой массив в колонке
    `goals`. Если план есть, а целей нет — задача тоже попадает к менеджеру,
    чтобы дописать цели.

    `failed` сюда не попадает намеренно: у сорвавшегося менеджера план так и
    остался пустым, и без этого фильтра тик подбирал бы такую задачу вечно.

    Задачи с подзадачами тоже не берём: родитель — контейнер, его планом уже
    является список детей. Иначе эпик с пятью подзадачами дал бы шесть походов в
    LLM, а план родителя пересказывал бы то, что и так разложено по детям.
    Подзапрос обёрнут в производную таблицу — MySQL не даёт читать в UPDATE ту же
    таблицу, которую пишет (ошибка 1093).
    """
    # Родительские задачи (их не берёт ни один шаг).
    # Обёртка в derived table — MySQL 1093 запрещает читать из UPDATE ту же таблицу.
    subparents = (
        "(SELECT pid FROM ("
        "    SELECT DISTINCT parent_id AS pid FROM project_task "
        "    WHERE parent_id IS NOT NULL"
        ") AS _t)"
    )
    return await _task_claim(
        # (Нет подзадач в pipeline_plan ИЛИ goals пустой/битый)
        # pipeline_state новый или NULL, не родитель
        f"(COALESCE(JSON_LENGTH(JSON_EXTRACT("
        "    IF(JSON_VALID(pipeline_plan), pipeline_plan, '{}'), '$.subtasks')), 0) = 0 "
        " OR JSON_LENGTH(COALESCE("
        "    IF(JSON_VALID(goals), goals, '[]'), '$')) = 0) "
        " AND (pipeline_state IS NULL OR pipeline_state = 'new') "
        f" AND id NOT IN ({subparents} )",
        [], 'planning', worker)


async def task_claim_task_review(worker: str) -> dict | None:
    """
    Захватить задачу, отправленную человеком на пересмотр плана.

    Состояние не меняется — `review` остаётся `review`, ставится только блокировка
    (так же устроен захват `qa_pending`). Из-за этого условие на свободную блокировку
    обязано быть в самом `where`: в `_task_claim` от второго воркера защищает переход
    состояния, а здесь перехода нет, и без проверки задачу взяли бы двое.
    """
    return await _task_claim(
        "pipeline_state = 'review' AND (pipeline_locked_at IS NULL OR pipeline_locked_by = '')",
        [], 'review', worker)


async def task_claim_subtask(state_from: str, state_to: str, worker: str) -> dict | None:
    """То же для подзадачи. state_to может совпадать с state_from — тогда это только блокировка."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id FROM project_task_subtask "
            " WHERE state = %s AND (locked_at IS NULL OR locked_by = '') "
            " ORDER BY task_id, position, id LIMIT 1",
            (state_from,),
        )
        row = await db.fetchone()
        if not row:
            return None

        await db.execute(
            "UPDATE project_task_subtask SET state = %s, locked_at = NOW(), locked_by = %s "
            " WHERE id = %s AND state = %s AND (locked_at IS NULL OR locked_by = '')",
            (state_to, worker, row['id'], state_from),
        )
        claimed = db.rowcount
        await db.connection.commit()
        if not claimed:
            return None

        await db.execute("SELECT * FROM project_task_subtask WHERE id = %s", (row['id'],))
        subtask = await db.fetchone()

    return dict(subtask) if subtask else None


async def task_claim_subtask_developable(worker: str, max_attempts: int) -> dict | None:
    """
    Свежая подзадача либо возврат от QA, у которого ещё остались попытки.
    Исчерпавшие лимит лежат в `blocked` и сюда не попадают.
    """
    for state_from in ('planned', 'failed_qa'):
        subtask = await task_claim_subtask(state_from, 'developing', worker)
        if not subtask:
            continue
        if int(subtask['attempt_count']) < max_attempts:
            return subtask
        # Лимит исчерпан уже после захвата — вернуть в blocked, дальше не крутить.
        await task_state_subtask_set(subtask['id'], 'blocked')
    return None


async def task_claim_locks_reclaim() -> int:
    """Вернуть в работу строки, чей воркер умер, не доведя переход до конца."""
    total = 0
    async with mysql_get_db_async() as db:
        for state_from, state_to in _TASK_STATE_RECLAIM.items():
            await db.execute(
                "UPDATE project_task SET pipeline_state = %s, pipeline_locked_at = NULL, pipeline_locked_by = '' "
                " WHERE pipeline_state = %s AND pipeline_locked_at IS NOT NULL "
                "   AND pipeline_locked_at < NOW() - INTERVAL %s SECOND",
                (state_to, state_from, LOCK_TIMEOUT_SEC),
            )
            total += db.rowcount

        for state_from, state_to in _SUBTASK_STATE_RECLAIM.items():
            await db.execute(
                "UPDATE project_task_subtask SET state = %s, locked_at = NULL, locked_by = '' "
                " WHERE state = %s AND locked_at IS NOT NULL "
                "   AND locked_at < NOW() - INTERVAL %s SECOND",
                (state_to, state_from, LOCK_TIMEOUT_SEC),
            )
            total += db.rowcount

        await db.connection.commit()

    if total:
        logger_info(f'[task] сброшено протухших блокировок: {total}')
    return total


async def _task_claim(where: str, params: list, state_to: str, worker: str) -> dict | None:
    """
    Общий захват задачи: выбрать первую подходящую под `where` и перевести её
    в `state_to`. Условие повторяется в UPDATE, поэтому строку не увести дважды.
    """
    async with mysql_get_db_async() as db:
        await db.execute(f"SELECT id FROM project_task WHERE {where} ORDER BY id LIMIT 1", params)
        row = await db.fetchone()
        if not row:
            return None

        await db.execute(
            f"UPDATE project_task SET pipeline_state = %s, pipeline_locked_at = NOW(), pipeline_locked_by = %s "
            f" WHERE id = %s AND {where}",
            [state_to, worker, row['id']] + params,
        )
        claimed = db.rowcount
        await db.connection.commit()
        if not claimed:
            return None  # успели раньше нас

        await db.execute("SELECT * FROM project_task WHERE id = %s", (row['id'],))
        task = await db.fetchone()

    return dict(task) if task else None

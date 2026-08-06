"""
Эндпоинты конвейера агентов: чтение состояния и переходы, требующие человека.

Сам конвейер крутится в `src/project/task/`; здесь только точки, где в него
вмешивается пользователь. CRUD задач — в `project_task.py`.
"""
from fastapi import APIRouter, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.project.task.task_plan import task_plan_goals_get, task_plan_parse

router = APIRouter()


@router.get('/task/{task_id}/pipeline')
async def project_task_pipeline_get(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, pipeline_state, pipeline_plan, pipeline_error FROM project_task WHERE id = %s",
            (task_id,)
        )
        task = await db.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail='task not found')

        await db.execute(
            "SELECT id, position, title, description, state, attempt_count, last_error "
            "  FROM project_task_subtask WHERE task_id = %s ORDER BY position, id",
            (task_id,)
        )
        subtasks = await db.fetchall()

        await db.execute(
            "SELECT a.id, a.subtask_id, a.attempt_no, a.role, a.status, a.output, a.error, a.created_at "
            "  FROM project_task_attempt a JOIN project_task_subtask s ON s.id = a.subtask_id "
            " WHERE s.task_id = %s ORDER BY a.id",
            (task_id,)
        )
        attempts = await db.fetchall()

    plan_text, _ = task_plan_parse(task['pipeline_plan'] or '')
    return {
        'pipeline_state': task['pipeline_state'],
        'plan_text':      plan_text,
        # Цели отдаём из плана, а не из `task.goals`: в задаче они уже смешаны с
        # целями человека, а панель показывает именно предложенное менеджером.
        'goals':          task_plan_goals_get(task['pipeline_plan'] or ''),
        'error':          task['pipeline_error'],
        'subtasks':       [dict(r) for r in (subtasks or [])],
        'attempts':       [dict(r) for r in (attempts or [])],
    }


@router.post('/task/{task_id}/pipeline/start')
async def project_task_pipeline_start(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Отправить задачу в конвейер. Вход только явный — обычные задачи агенты не трогают."""
    return await _pipeline_state_set(task_id, expected=None, new_state='new')


@router.post('/task/{task_id}/pipeline/approve')
async def project_task_pipeline_approve(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Человек утвердил план — оркестратор разложит его на подзадачи."""
    return await _pipeline_state_set(task_id, expected='pending_approval', new_state='approved')


@router.post('/task/{task_id}/pipeline/reject')
async def project_task_pipeline_reject(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Отклонить план и вывести задачу из конвейера. План сохраняется для разбора."""
    return await _pipeline_state_set(task_id, expected='pending_approval', new_state=None)


async def _pipeline_state_set(task_id: int, expected: str | None, new_state: str | None) -> dict:
    """
    Условный перевод состояния. Сверка с `expected` идёт прямо в UPDATE, иначе
    двойной клик в UI проскочит гонку и утвердит план дважды.
    """
    where_state = "pipeline_state IS NULL" if expected is None else "pipeline_state = %s"
    params: list = [new_state]
    if expected is not None:
        params.append(expected)
    params.append(task_id)

    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE project_task SET pipeline_state = %s, pipeline_error = '', "
            f"pipeline_locked_at = NULL, pipeline_locked_by = '' "
            f"WHERE {where_state} AND id = %s",
            params
        )
        updated = db.rowcount
        await db.connection.commit()

        row = None
        if not updated:
            await db.execute("SELECT pipeline_state FROM project_task WHERE id = %s", (task_id,))
            row = await db.fetchone()

    if not updated:
        if not row:
            raise HTTPException(status_code=404, detail='task not found')
        raise HTTPException(
            status_code=409,
            detail=f'Задача не в состоянии {expected or "вне конвейера"} (сейчас: {row["pipeline_state"] or "—"})'
        )

    return {'ok': True, 'pipeline_state': new_state}

from fastapi import APIRouter, Request, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/workflow_trace/run/list")
async def trace_run_list(
        request: Request,
        workflow_id: int | None = None,
        agent_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 30,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TRACE_VIEW]))
):
    """Список запусков workflow (только верхний уровень, depth=0) с пагинацией."""
    where = ["r.depth = 0"]
    params: list = []

    if workflow_id:
        where.append("r.workflow_id = %s")
        params.append(workflow_id)
    if agent_id:
        where.append("r.agent_id = %s")
        params.append(agent_id)
    if status in ('running', 'success', 'error'):
        where.append("r.status = %s")
        params.append(status)

    where_sql = " AND ".join(where)
    limit = max(1, min(int(limit), 100))
    page = max(1, int(page))
    offset = (page - 1) * limit

    async with mysql_get_db_async() as db:
        await db.execute(f"SELECT COUNT(*) as qty FROM agent_workflow_run r WHERE {where_sql}", params)
        total = (await db.fetchone())['qty']

        await db.execute(
            f"""
            SELECT r.id, r.run_uuid, r.workflow_id, r.agent_id, r.user_id, r.status,
                   r.prompt_user, r.result, r.error, r.started_at, r.duration_ms,
                   w.title AS workflow_title,
                   a.title AS agent_title,
                   (SELECT COUNT(*) FROM agent_workflow_run_step s WHERE s.run_id = r.id) AS steps_qty,
                   (SELECT COUNT(*) FROM agent_workflow_run c WHERE c.parent_run_id = r.id) AS children_qty
            FROM agent_workflow_run r
            LEFT JOIN agent_workflow w ON w.id = r.workflow_id
            LEFT JOIN agent a ON a.id = r.agent_id
            WHERE {where_sql}
            ORDER BY r.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset]
        )
        rows = await db.fetchall()

    return {
        "result": rows,
        "pagination": {
            "current_page": page,
            "total_pages": max(1, (total + limit - 1) // limit),
            "total_records": total,
        },
    }


@router.get("/workflow_trace/run/{run_uuid}")
async def trace_run_detail(
        request: Request,
        run_uuid: str,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TRACE_VIEW]))
):
    """Запуск с шагами и деревом дочерних запусков (sub-workflow)."""
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT r.*, w.title AS workflow_title, w.name AS workflow_name, a.title AS agent_title
            FROM agent_workflow_run r
            LEFT JOIN agent_workflow w ON w.id = r.workflow_id
            LEFT JOIN agent a ON a.id = r.agent_id
            WHERE r.run_uuid = %s
            """,
            (run_uuid,)
        )
        root = await db.fetchone()
        if not root:
            raise HTTPException(status_code=404, detail="Запуск не найден")

        # Собираем всех потомков по уровням (BFS по parent_run_id)
        runs = {root['id']: root}
        layer = [root['id']]
        while layer:
            placeholders = ', '.join(['%s'] * len(layer))
            await db.execute(
                f"""
                SELECT r.*, w.title AS workflow_title, w.name AS workflow_name, a.title AS agent_title
                FROM agent_workflow_run r
                LEFT JOIN agent_workflow w ON w.id = r.workflow_id
                LEFT JOIN agent a ON a.id = r.agent_id
                WHERE r.parent_run_id IN ({placeholders})
                """,
                layer
            )
            children = await db.fetchall()
            layer = [c['id'] for c in children]
            for c in children:
                runs[c['id']] = c

        # Все шаги всех запусков одним запросом
        run_ids = list(runs.keys())
        placeholders = ', '.join(['%s'] * len(run_ids))
        await db.execute(
            f"""
            SELECT * FROM agent_workflow_run_step
            WHERE run_id IN ({placeholders})
            ORDER BY run_id, exec_index, id
            """,
            run_ids
        )
        all_steps = await db.fetchall()

    # Сборка дерева: у каждого запуска — шаги и дочерние запуски
    for run in runs.values():
        run['steps'] = []
        run['children'] = []
    for step in all_steps:
        runs[step['run_id']]['steps'].append(step)
    for run in runs.values():
        parent_id = run.get('parent_run_id')
        if parent_id and parent_id in runs:
            runs[parent_id]['children'].append(run)

    return {"result": root}


@router.delete("/workflow_trace/run/{run_uuid}")
async def trace_run_delete(
        request: Request,
        run_uuid: str,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TRACE_DELETE]))
):
    """Удаляет запуск: шаги и дочерние запуски удаляются каскадно (FK)."""
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM agent_workflow_run WHERE run_uuid = %s", (run_uuid,))
    return {"result": "success"}

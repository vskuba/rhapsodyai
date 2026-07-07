from fastapi import APIRouter, Request, Depends
from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.agent_workflow_variable_repository import AgentWorkflowVariableRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

@router.get("/agent_workflow_variable/list")
async def variable_list(request: Request, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    sql = """
        SELECT v.*, GROUP_CONCAT(r.name) as role_names, GROUP_CONCAT(r.id) as role_ids
        FROM agent_workflow_variable v
        LEFT JOIN agent_workflow_variable_role vr ON v.id = vr.variable_id
        LEFT JOIN role r ON vr.role_id = r.id
        WHERE v.node_id IS NOT NULL
        GROUP BY v.id
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql)
        results = await db.fetchall()
        # Преобразуем role_ids в список чисел
        for row in results:
            if row['role_ids']:
                row['role_ids'] = [int(r) for r in row['role_ids'].split(',')]
            else:
                row['role_ids'] = []
        return {"result": results}

@router.post("/agent_workflow_variable")
async def variable_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.WORKFLOW_CREATE]))):
    async with mysql_get_db_async() as db:
        sql = """
            INSERT INTO agent_workflow_variable (name, description, `default`, workflow_id, node_id, pattern)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        await db.execute(sql, (data.get('name'), data.get('description'), data.get('default'), 
                               data.get('workflow_id'), data.get('node_id'), data.get('pattern')))
        variable_id = db.lastrowid

        # Сохранение ролей
        role_ids = data.get('role_ids', [])
        for role_id in role_ids:
            await db.execute("INSERT INTO agent_workflow_variable_role (variable_id, role_id) VALUES (%s, %s)", (variable_id, role_id))

        return {"result": {"id": variable_id}}

@router.put("/agent_workflow_variable/{variable_id}")
async def variable_update(request: Request, variable_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))):
    async with mysql_get_db_async() as db:
        sql = """
            UPDATE agent_workflow_variable 
            SET name=%s, description=%s, `default`=%s, workflow_id=%s, node_id=%s, pattern=%s
            WHERE id=%s
        """
        await db.execute(sql, (data.get('name'), data.get('description'), data.get('default'), 
                               data.get('workflow_id'), data.get('node_id'), data.get('pattern'), variable_id))

        # Обновление ролей
        await db.execute("DELETE FROM agent_workflow_variable_role WHERE variable_id=%s", (variable_id,))
        role_ids = data.get('role_ids', [])
        for role_id in role_ids:
            await db.execute("INSERT INTO agent_workflow_variable_role (variable_id, role_id) VALUES (%s, %s)", (variable_id, role_id))

        return {"result": "success"}

@router.delete("/agent_workflow_variable/{variable_id}")
async def variable_delete(request: Request, variable_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))):
    repo = AgentWorkflowVariableRepository()
    await repo.delete(variable_id)
    return {"result": "success"}

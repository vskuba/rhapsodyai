from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.agent_workflow_variable_repository import AgentWorkflowVariableRepository
from src.auth.auth import AuthChecker
from src.auth.auth_field_policy import ALL_FIELDS, auth_fields_filter_for_update, auth_fields_allowed
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/node/workflow_variable/list")
async def variable_list(
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_VIEW]))
):
    sql = """
        SELECT v.*, 
               GROUP_CONCAT(DISTINCT r.name) as role_names, 
               GROUP_CONCAT(DISTINCT r.id) as role_ids,
               GROUP_CONCAT(DISTINCT vw.workflow_id) as workflow_ids
        FROM agent_workflow_variable v
        LEFT JOIN agent_workflow_variable_role vr ON v.id = vr.variable_id
        LEFT JOIN role r ON vr.role_id = r.id
        LEFT JOIN agent_workflow_variable_workflow vw ON v.id = vw.variable_id
        WHERE v.node_id IS NOT NULL
    """
    params = []

    if user.role != "admin":
        # Только переменные в нодах текущего пользователя
        sql += " AND v.node_id IN (SELECT node_id FROM user_node WHERE user_id = %s)"
        params.append(user.user_id)
        # Переменные без ролей — всем; с ролями — только при совпадении роли пользователя
        sql += """
            AND (
                NOT EXISTS (SELECT 1 FROM agent_workflow_variable_role vr2 WHERE vr2.variable_id = v.id)
                OR EXISTS (
                    SELECT 1 FROM agent_workflow_variable_role vr3
                    JOIN role r3 ON r3.id = vr3.role_id
                    WHERE vr3.variable_id = v.id AND r3.name = %s
                )
            )
        """
        params.append(user.role)

    sql += " GROUP BY v.id ORDER BY v.name ASC"

    async with mysql_get_db_async() as db:
        await db.execute(sql, params or None)
        results = await db.fetchall()
        # Преобразуем role_ids и workflow_ids в списки чисел
        for row in results:
            if row['role_ids']:
                row['role_ids'] = [int(r) for r in row['role_ids'].split(',')]
            else:
                row['role_ids'] = []
            if row.get('workflow_ids'):
                row['workflow_ids'] = [int(w) for w in row['workflow_ids'].split(',')]
            else:
                row['workflow_ids'] = []

        # Отдаём только поля, разрешённые роли пользователя на чтение
        allowed = auth_fields_allowed('agent_workflow_variable', 'read', user.role)
        if allowed != ALL_FIELDS:
            results = [{k: v for k, v in row.items() if k in allowed} for row in results]

        return {"result": results}


@router.get("/node/workflow_variable/{variable_id}/hints")
async def variable_hints(
        request: Request,
        variable_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_VIEW]))
):
    async with mysql_get_db_async() as db:
        await db.execute("SELECT node_id, position FROM agent_workflow_variable WHERE id=%s", (variable_id,))
        variable = await db.fetchone()

        if not variable:
            return {"result": []}

        # Переменные той же ноды, помеченные use_as_hint, стоящие выше текущей
        await db.execute(
            """
            SELECT name, description
            FROM agent_workflow_variable
            WHERE node_id <=> %s AND use_as_hint = 1 AND position < %s
            ORDER BY position ASC
            """,
            (variable['node_id'], variable['position'])
        )
        results = await db.fetchall()

        return {"result": results}



@router.post("/node/workflow_variable")
async def variable_create(
        request: Request,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_CREATE]))
):
    async with mysql_get_db_async() as db:
        # Позиция по умолчанию — в конец списка своей ноды
        position = data.get('position')
        if position is None:
            await db.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS position FROM agent_workflow_variable WHERE node_id <=> %s",
                (data.get('node_id'),))
            position = (await db.fetchone())['position']

        sql = """
            INSERT INTO agent_workflow_variable (name, description, `default`, node_id, position, use_as_hint)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        await db.execute(sql, (data.get('name'), data.get('description'), data.get('default'),
                               data.get('node_id'), position,
                               int(bool(data.get('use_as_hint')))))
        variable_id = db.lastrowid

        # Сохранение ролей
        role_ids = data.get('role_ids', [])
        for role_id in role_ids:
            await db.execute("INSERT INTO agent_workflow_variable_role (variable_id, role_id) VALUES (%s, %s)",
                             (variable_id, role_id))

        # Сохранение workflow_ids
        workflow_ids = data.get('workflow_ids', [])
        if not isinstance(workflow_ids, list):
            workflow_ids = [workflow_ids] if workflow_ids is not None else []
        
        single_workflow_id = data.get('workflow_id')
        if single_workflow_id and single_workflow_id not in workflow_ids:
            workflow_ids.append(single_workflow_id)

        for w_id in workflow_ids:
            if w_id:
                await db.execute("INSERT INTO agent_workflow_variable_workflow (variable_id, workflow_id) VALUES (%s, %s)",
                                 (variable_id, w_id))

        return {"result": {"id": variable_id}}


@router.put("/node/workflow_variable/{variable_id}")
async def variable_update(
        request: Request,
        variable_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_UPDATE]))
):
    # Оставляем только поля, разрешённые роли пользователя (admin — все)
    fields, data = auth_fields_filter_for_update('agent_workflow_variable', 'write', user.role, data)

    async with mysql_get_db_async() as db:
        if fields:
            # Исключаем реляционные и нетабличные поля из UPDATE-запроса к agent_workflow_variable
            db_fields = [f for f in fields if f not in ('workflow_id', 'workflow_ids', 'role_ids')]
            if db_fields:
                set_clause = ', '.join(f"`{f}`=%s" for f in db_fields)
                values = [data[f] for f in db_fields] + [variable_id]
                await db.execute(f"UPDATE agent_workflow_variable SET {set_clause} WHERE id=%s", values)

        # Обновление ролей — только если поле role_ids разрешено политикой
        if 'role_ids' in data:
            await db.execute("DELETE FROM agent_workflow_variable_role WHERE variable_id=%s", (variable_id,))
            for role_id in data.get('role_ids') or []:
                await db.execute("INSERT INTO agent_workflow_variable_role (variable_id, role_id) VALUES (%s, %s)",
                                 (variable_id, role_id))

        # Обновление workflow_ids — если передано в data (или если workflow_id передан)
        if 'workflow_ids' in data or 'workflow_id' in data:
            await db.execute("DELETE FROM agent_workflow_variable_workflow WHERE variable_id=%s", (variable_id,))
            
            workflow_ids = data.get('workflow_ids', [])
            if not isinstance(workflow_ids, list):
                workflow_ids = [workflow_ids] if workflow_ids is not None else []
            
            single_workflow_id = data.get('workflow_id')
            if single_workflow_id and single_workflow_id not in workflow_ids:
                workflow_ids.append(single_workflow_id)
                
            for w_id in workflow_ids:
                if w_id:
                    await db.execute("INSERT INTO agent_workflow_variable_workflow (variable_id, workflow_id) VALUES (%s, %s)",
                                     (variable_id, w_id))

        return {"result": "success"}


@router.delete("/node/workflow_variable/{variable_id}")
async def variable_delete(
        request: Request,
        variable_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_DELETE]))
):
    repo = AgentWorkflowVariableRepository()
    await repo.delete(variable_id)
    return {"result": "success"}

import re

from fastapi import APIRouter, Request, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.agent_workflow_repository import AgentWorkflowRepository
from src.mysql_.repository.agent_workflow_step_repository import AgentWorkflowStepRepository
from src.mysql_.repository.agent_workflow_step_type_repository import AgentWorkflowStepTypeRepository
from src.mysql_.repository.agent_workflow_variable_repository import AgentWorkflowVariableRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/workflow/list")
async def workflow_list(request: Request, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.find_by({}, 'title ASC')}


@router.post("/workflow")
async def workflow_create(
        request: Request,
        data: dict,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_CREATE]))
):
    async with db:
        sql = """
            INSERT INTO agent_workflow (name, title, node_id, description, position, group_name, subflow)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            data.get('name'),
            data.get('title'),
            data.get('node_id') or None,
            data.get('description', ''),
            int(data.get('position', 0)),
            data.get('group_name') or None,
            int(data.get('subflow', 0))
        )
        await db.execute(sql, values)
        await db.connection.commit()

        # Получаем ID только что созданной строки в MySQL
        new_id = db.lastrowid

        return {"status": "success", "result": {"id": new_id}}


@router.post("/workflow/{workflow_id}/duplicate")
async def workflow_duplicate(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_CREATE]))
):
    """Полный дубликат workflow: строка agent_workflow (title + ' copy', уникальный name),
    все шаги и связи переменных. Внутри metadata шагов ремапятся id: переходы
    (step_id) и переменные результатов (tool_{id}_result_*) указывают на новые шаги."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM agent_workflow WHERE id = %s", (workflow_id,))
        source = await db.fetchone()
        if not source:
            raise HTTPException(status_code=404, detail="Workflow не найден")

        # Уникальное имя (u_w_workflow_name, CHAR(50)): name_copy, name_copy2, ...
        new_name = None
        for i in range(1, 100):
            suffix = '_copy' if i == 1 else f'_copy{i}'
            candidate = source['name'][:50 - len(suffix)] + suffix
            await db.execute("SELECT id FROM agent_workflow WHERE name = %s", (candidate,))
            if not await db.fetchone():
                new_name = candidate
                break
        if not new_name:
            raise HTTPException(status_code=400, detail="Не удалось подобрать уникальное имя дубликата")

        new_title = (source['title'] + ' copy')[:50]

        await db.execute(
            """
            INSERT INTO agent_workflow (node_id, name, title, description, position, subflow)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (source['node_id'], new_name, new_title, source['description'],
             source['position'], source['subflow'])
        )
        new_workflow_id = db.lastrowid

        # Шаги: первый проход — вставка копий, собираем соответствие old id -> new id
        await db.execute(
            "SELECT * FROM agent_workflow_step WHERE workflow_id = %s ORDER BY position ASC",
            (workflow_id,)
        )
        steps = await db.fetchall()

        id_map = {}
        metadata_by_new_id = {}
        for step in steps:
            await db.execute(
                """
                INSERT INTO agent_workflow_step (workflow_id, type_id, title, position, metadata)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (new_workflow_id, step['type_id'], step['title'], step['position'], step['metadata'])
            )
            id_map[step['id']] = db.lastrowid
            metadata_by_new_id[db.lastrowid] = step['metadata'] or ''

        # Второй проход — ремап id шагов в metadata. Новые id (AUTO_INCREMENT) всегда
        # больше всех старых, поэтому последовательные замены не пересекаются
        for new_step_id, metadata in metadata_by_new_id.items():
            updated = metadata
            for old_id, new_id in id_map.items():
                # Переходы: "step_id": "66" (строкой) и "step_id": 66 (числом)
                updated = re.sub(rf'("step_id"\s*:\s*"){old_id}(")', rf'\g<1>{new_id}\g<2>', updated)
                updated = re.sub(rf'("step_id"\s*:\s*){old_id}(\s*[,}}\]])', rf'\g<1>{new_id}\g<2>', updated)
                # Переменные результатов шагов: tool_66_result_* -> tool_<new>_result_*
                updated = updated.replace(f'_{old_id}_result', f'_{new_id}_result')
            if updated != metadata:
                await db.execute(
                    "UPDATE agent_workflow_step SET metadata = %s WHERE id = %s",
                    (updated, new_step_id)
                )

        # Связи переменных: обычные и публичные (сами переменные общие, копируем только связи)
        await db.execute(
            """
            INSERT INTO agent_workflow_variable_workflow (variable_id, workflow_id)
            SELECT variable_id, %s FROM agent_workflow_variable_workflow WHERE workflow_id = %s
            """,
            (new_workflow_id, workflow_id)
        )
        await db.execute(
            """
            INSERT INTO node_variable_workflow (node_variable_id, workflow_id)
            SELECT node_variable_id, %s FROM node_variable_workflow WHERE workflow_id = %s
            """,
            (new_workflow_id, workflow_id)
        )

        await db.connection.commit()

        return {"status": "success", "result": {"id": new_workflow_id, "title": new_title, "name": new_name}}


@router.get("/workflow/{node_id}/list")
async def workflow_list(request: Request, node_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.find_by({"node_id": node_id}, 'title ASC')}


@router.get("/workflow/{workflow_id}")
async def workflow(request: Request, workflow_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.find(workflow_id)}


@router.put("/workflow/{workflow_id}")
async def workflow(
        request: Request,
        workflow_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    repo = AgentWorkflowRepository()
    return {"result": await repo.update(workflow_id, data)}


@router.delete("/workflow/{workflow_id}")
async def workflow_delete(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))
):
    """Удаляет workflow вместе с его шагами. Связи переменных чистит FK CASCADE;
    у агентов и журнала запусков workflow_id обнуляется (FK SET NULL).
    Шаги удаляем явно: их FK — ON DELETE SET NULL, иначе остались бы сироты."""
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM agent_workflow_step WHERE workflow_id = %s", (workflow_id,))
        await db.execute("DELETE FROM agent_workflow WHERE id = %s", (workflow_id,))
        deleted = db.rowcount
        await db.connection.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow не найден")

    return {"status": "success", "result": deleted}


@router.get("/workflow/{workflow_id}/steps")
async def workflow_steps(request: Request, workflow_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    """
    Получает все шаги задачи вместе с их иконками и описаниями типов.
    """
    sql = f"""
            SELECT
                ts.*,
                tst.icon,
                tst.description as description
            FROM `agent_workflow_step` ts
            LEFT JOIN `agent_workflow_step_type` tst ON ts.type_id = tst.id
            WHERE ts.workflow_id = %s
            ORDER BY ts.position ASC
        """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        return {"result": await db.fetchall()}


@router.get("/workflow/{workflow_id}/variables")
async def workflow_variables(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))
):
    # Получает все переменные, связанные с конкретным workflow (включая глобальные и публичные переменные ноды)
    sql = """
        (SELECT v.id, v.name, v.`type`, v.`default`, v.description, NULL as node_id
         FROM `agent_workflow_variable` v
         JOIN `agent_workflow_variable_workflow` vw ON v.id = vw.variable_id
         WHERE vw.workflow_id = %s)
        UNION
        (SELECT v.id, v.name, v.`type`, v.`default`, v.description, NULL as node_id
         FROM `agent_workflow_variable` v
         WHERE v.type = 'global')
        UNION
        (SELECT v.id, v.name, 'node' as `type`, v.`default`, v.description, v.node_id
         FROM `node_variable` v
         JOIN `node_variable_workflow` vw ON v.id = vw.node_variable_id
         WHERE vw.workflow_id = %s)
        ORDER BY name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,workflow_id,))
        rows = await db.fetchall()
        return {"result": rows}


@router.post("/workflow/{workflow_id}/step")
async def workflow_step_add(
        request: Request,
        workflow_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    repo_workflow_step = AgentWorkflowStepRepository()
    repo_workflow_step_type = AgentWorkflowStepTypeRepository()

    # 1. Получаем текущие шаги, чтобы вычислить следующую позицию
    current_steps = await repo_workflow_step.find_by({"workflow_id": workflow_id})
    next_position = len(current_steps)

    type_id = data.get("type_id", 0)
    workflow_step_type = await repo_workflow_step_type.find(type_id)

    # 2. Подготавливаем данные для вставки
    # Извлекаем title из данных или ставим дефолт, если в схеме NOT NULL
    new_step_data = {
        "workflow_id": workflow_id,
        "type_id": type_id,
        "title": workflow_step_type.get('description', f"Шаг {next_position}"),
        "position": next_position,
        "metadata": data.get("metadata", "{}")  # Инициализируем пустым JSON
    }

    new_id = await repo_workflow_step.add(new_step_data)

    return {"result": new_id}


@router.post("/workflow/{workflow_id}/variable")
async def workflow_variable_add(
        request: Request,
        workflow_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    async with mysql_get_db_async() as db:
        # Check if relation already exists
        sql_check = """
            SELECT v.id 
            FROM agent_workflow_variable v
            JOIN agent_workflow_variable_workflow vw ON v.id = vw.variable_id
            WHERE vw.workflow_id = %s AND v.name = %s
        """
        await db.execute(sql_check, (workflow_id, data.get("name")))
        variable = await db.fetchone()
        if variable:
            return {"result": variable.get("id")}

        variable_type = data.get("type", "workflow")

        # Check if variable with same name and type already exists
        await db.execute(
            "SELECT id FROM agent_workflow_variable WHERE name = %s AND `type` = %s",
            (data.get("name"), variable_type)
        )
        existing_var = await db.fetchone()

        if existing_var:
            variable_id = existing_var.get("id")
        else:
            # Create new variable
            sql_insert_var = """
                INSERT INTO agent_workflow_variable (name, `default`, `type`)
                VALUES (%s, %s, %s)
            """
            await db.execute(sql_insert_var, (data.get("name"), data.get("default"), variable_type))
            variable_id = db.lastrowid

        # Insert relationship
        sql_insert_link = """
            INSERT INTO agent_workflow_variable_workflow (variable_id, workflow_id)
            VALUES (%s, %s)
        """
        await db.execute(sql_insert_link, (variable_id, workflow_id))

        return {"result": variable_id}


@router.put("/workflow/{workflow_id}/steps/reorder")
async def workflow_steps_reorder(
        request: Request,
        workflow_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    repo = AgentWorkflowStepRepository()
    positions = data.get("positions", [])

    for item in positions:
        step_id = item.get("id")
        new_position = item.get("position")

        if step_id is not None:
            await repo.update(int(step_id), {"position": int(new_position)})

    return {"result": "success"}


@router.put("/workflow/{workflow_id}/step/{workflow_step_id}")
async def workflow_step_update(
        request: Request,
        workflow_step_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    repo = AgentWorkflowStepRepository()
    return {"result": await repo.update(workflow_step_id, data)}


@router.delete("/workflow/{workflow_id}/step/{workflow_step_id}")
async def workflow_step_delete(
        request: Request,
        workflow_step_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))
):
    repo = AgentWorkflowStepRepository()
    return {"result": await repo.delete(workflow_step_id)}


@router.get("/workflow/{workflow_id}/parents")
async def workflow_parents(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))
):
    """Workflows that call this subflow via workflow_invoke step."""
    wid = str(workflow_id)
    # Cover both compact and spaced JSON: "workflow_id":36, / "workflow_id": 36,
    id_patterns = [
        f'%"workflow_id":{wid},%',
        f'%"workflow_id":{wid}}}%',
        f'%"workflow_id": {wid},%',
        f'%"workflow_id": {wid}}}%',
    ]
    async with mysql_get_db_async() as db:
        placeholders = " OR ".join(
            ["(s.metadata LIKE %s AND s.metadata LIKE '%%workflow_invoke%%')"] * len(id_patterns)
        )
        await db.execute(
            f"SELECT DISTINCT w.id, w.name, w.title "
            f"FROM agent_workflow_step s "
            f"JOIN agent_workflow w ON w.id = s.workflow_id "
            f"WHERE {placeholders}",
            id_patterns
        )
        rows = await db.fetchall()
    return {"result": [dict(r) for r in rows]}


@router.get("/workflow/{workflow_id}/agents")
async def workflow_agents(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))
):
    """Agents that use this workflow."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, title FROM agent WHERE workflow_id = %s ORDER BY title",
            (workflow_id,)
        )
        rows = await db.fetchall()
    return {"result": [dict(r) for r in rows]}


@router.delete("/workflow/{workflow_id}/variable/{workflow_variable_id}")
async def workflow_variable_delete(
        request: Request,
        workflow_variable_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))
):
    repo = AgentWorkflowVariableRepository()
    return {"result": await repo.delete(workflow_variable_id)}

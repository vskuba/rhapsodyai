from mysql_.mysql_ import mysql_get_db_async


async def ai_workflow_variables_global_get() -> list[str]:
    sql = """
        SELECT v.name
        FROM agent_workflow_variable v
        WHERE v.type = 'global'
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql)
        rows = await db.fetchall()
        return [x.get("name") for x in rows]


async def ai_workflow_variables_node_get(node_id: int) -> list[str]:
    sql = """
        SELECT v.name
        FROM agent_workflow_variable v
        WHERE v.type = 'node' AND v.node_id == %s
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        rows = await db.fetchall()
        return [x.get("name") for x in rows]


async def ai_workflow_variables_input_get(workflow_id: int) -> list[str]:
    sql = """
        SELECT v.name
        FROM agent_workflow_variable v
        LEFT JOIN agent_workflow_variable_workflow vw ON v.id = vw.variable_id
        WHERE v.type = 'input' AND vw.workflow_id == %s
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        rows = await db.fetchall()
        return [x.get("name") for x in rows]

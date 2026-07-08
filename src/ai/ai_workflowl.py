from mysql_.mysql_ import mysql_get_db_async


async def ai_workflow_variables_default_get() -> list[str]:
    sql = """
        SELECT v.*
        FROM agent_workflow_variable v
        WHERE v.node_id IS NULL AND NOT EXISTS (
            SELECT 1 FROM agent_workflow_variable_workflow vw WHERE vw.variable_id = v.id
        )
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql)
        rows = await db.fetchall()
        return [x.get("name") for x in rows]

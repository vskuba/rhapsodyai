from mysql_.mysql_ import mysql_get_db_async


async def ai_workflow_variables_default_get() -> list[str]:
    sql = """
        SELECT *
        FROM agent_workflow_variable
        WHERE node_id IS NULL AND workflow_id IS NULL
        ORDER BY name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql)
        rows = await db.fetchall()
        return [x.get("name") for x in rows]

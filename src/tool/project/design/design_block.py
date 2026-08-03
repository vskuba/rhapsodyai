import json

from mysql_.mysql_ import mysql_get_db_async


async def design_block_save(project_id: int, blocks_json: list) -> dict:
    """
    Сохраняет блоки UI проекта. Удаляет существующие и записывает новые.
     - project_id: ID проекта
     - blocks_json: список блоков, каждый содержит name, description, stateless
    Returns:
        dict: blocks_count (int)
    """
    project_id = int(project_id)
    if isinstance(blocks_json, str):
        try:
            blocks_json = json.loads(blocks_json)
        except Exception:
            blocks_json = []
    if not isinstance(blocks_json, list):
        blocks_json = []

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_design_ui_block WHERE project_id = %s", (project_id,))
        count = 0
        for i, block in enumerate(blocks_json):
            if not isinstance(block, dict):
                continue
            name = str(block.get('name') or '')[:255]
            if not name:
                continue
            description = block.get('description') or None
            stateless = 1 if block.get('stateless') else 0
            await db.execute(
                "INSERT INTO project_design_ui_block "
                "(project_id, name, description, stateless, created_by, order_index) "
                "VALUES (%s, %s, %s, %s, 'ai', %s)",
                (project_id, name, description, stateless, i)
            )
            count += 1

    return {'blocks_count': count}


async def design_block_list(project_id: int) -> dict:
    """
    Возвращает все блоки проекта.
     - project_id: ID проекта
    Returns:
        dict: blocks (list) — каждый блок содержит id, name, description, states (list)
    """
    project_id = int(project_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, description, created_by, order_index "
            "FROM project_design_ui_block WHERE project_id = %s ORDER BY order_index",
            (project_id,)
        )
        block_rows = await db.fetchall()

    blocks = [
        {'id': b['id'], 'name': b['name'], 'description': b['description'],
         'created_by': b['created_by'], 'states': []}
        for b in block_rows
    ]
    return {'blocks': blocks}

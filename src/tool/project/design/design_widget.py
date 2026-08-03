import json

from mysql_.mysql_ import mysql_get_db_async


async def design_widget_save(block_id: int, widgets_json: list) -> dict:
    """
    Сохраняет виджеты (стилизованные варианты) блока.
    Удаляет существующие виджеты блока и записывает новые.
     - block_id: ID блока из project_design_ui_block
     - widgets_json: список виджетов, каждый содержит name, description, css, html
    Returns:
        dict: widgets_count (int)
    """
    block_id = int(block_id)
    if isinstance(widgets_json, str):
        try:
            widgets_json = json.loads(widgets_json)
        except Exception:
            widgets_json = []
    if not isinstance(widgets_json, list):
        widgets_json = []

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_design_prototype_widget WHERE block_id = %s", (block_id,))
        count = 0
        for i, widget in enumerate(widgets_json):
            if not isinstance(widget, dict):
                continue
            name = str(widget.get('name') or '')[:255]
            if not name:
                continue
            description = widget.get('description') or None
            css = widget.get('css') or None
            html = widget.get('html') or None
            await db.execute(
                "INSERT INTO project_design_prototype_widget "
                "(block_id, name, description, css, html, created_by, order_index) "
                "VALUES (%s, %s, %s, %s, %s, 'ai', %s)",
                (block_id, name, description, css, html, i)
            )
            count += 1
        await db.connection.commit()

    return {'widgets_count': count}


async def design_widget_list(block_id: int) -> dict:
    """
    Возвращает виджеты блока.
     - block_id: ID блока
    Returns:
        dict: widgets (list) — каждый виджет содержит id, name, description, css, html
    """
    block_id = int(block_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, description, css, html, created_by, order_index "
            "FROM project_design_prototype_widget WHERE block_id = %s ORDER BY order_index",
            (block_id,)
        )
        rows = await db.fetchall()
    return {'widgets': [dict(r) for r in (rows or [])]}

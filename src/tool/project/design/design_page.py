import json

from mysql_.mysql_ import mysql_get_db_async


async def design_page_save(project_id: int, pages_json: list) -> dict:
    """
    Сохраняет дерево страниц проекта в таблицу project_design_prototype_page.
    Удаляет существующие страницы проекта и записывает новые (дерево).
     - project_id: ID проекта
     - pages_json: список страниц (list), каждая может иметь children для вложенных страниц
    Returns:
        dict: Результат операции, содержащий:
            pages_count (int): Общее количество сохранённых страниц.
    """
    project_id = int(project_id)
    if isinstance(pages_json, str):
        try:
            pages_json = json.loads(pages_json)
        except Exception:
            pages_json = []
    if not isinstance(pages_json, list):
        pages_json = []

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_design_prototype_page WHERE project_id = %s", (project_id,))
        count = await _insert_pages(db, project_id, pages_json, parent_id=None, order_start=0)
        summary = f"{count} страниц сгенерировано"
        await db.execute(
            """
            INSERT INTO project_planning_phase (project_id, phase, status, summary, started_at, completed_at)
            VALUES (%s, 'design_pages', 'complete', %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE status='complete', summary=%s, completed_at=NOW()
            """,
            (project_id, summary, summary)
        )
        await db.connection.commit()

    return {'pages_count': count}


async def design_page_list(project_id: int) -> dict:
    """
    Возвращает список страниц проекта из БД в виде плоского списка.
     - project_id: ID проекта
    Returns:
        dict: Результат, содержащий:
            pages (list): Список страниц с полями id, parent_id, name, description, page_type, roles, order_index.
    """
    project_id = int(project_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, parent_id, name, description, page_type, roles, order_index "
            "FROM project_design_prototype_page WHERE project_id = %s ORDER BY order_index",
            (project_id,)
        )
        rows = await db.fetchall()
    return {'pages': [dict(r) for r in rows]}


async def _insert_pages(db, project_id: int, pages: list, parent_id, order_start: int) -> int:
    count = 0
    for i, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        name = str(page.get('name') or '')[:255]
        if not name:
            continue
        description = page.get('description') or None
        page_type = str(page.get('page_type') or 'feature')[:50]
        roles_val = page.get('roles', [])
        roles_str = ','.join(str(r) for r in roles_val) if isinstance(roles_val, list) else str(roles_val)
        tags_val = page.get('tags', [])
        tags_str = ','.join(str(t).strip().lower() for t in tags_val if t) if isinstance(tags_val, list) else str(tags_val or '')

        await db.execute(
            "INSERT INTO project_design_prototype_page "
            "(project_id, parent_id, name, description, page_type, tags, roles, order_index) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (project_id, parent_id, name, description, page_type, tags_str[:500], roles_str[:500], order_start + i)
        )
        new_id = db.lastrowid
        count += 1

        children = page.get('children') or []
        if isinstance(children, list) and children:
            count += await _insert_pages(db, project_id, children, parent_id=new_id, order_start=0)

    return count

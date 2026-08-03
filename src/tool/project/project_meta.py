from mysql_.mysql_ import mysql_get_db_async


async def project_meta_save(project_id: int, cloud_tags: str, entities: str, roles: str) -> dict:
    """
    Сохраняет облако тегов, сущности и роли пользователей в project.
     - project_id: ID проекта
     - cloud_tags: JSON-массив тегов (строка)
     - entities: JSON-массив сущностей проекта (строка)
     - roles: JSON-массив ролей пользователей (строка)
    Returns:
        dict: saved (bool): True если сохранено успешно.
    """
    project_id = int(project_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project SET cloud_tags = %s, entities = %s, roles = %s WHERE id = %s",
            (str(cloud_tags), str(entities), str(roles), project_id)
        )
    return {'saved': True}

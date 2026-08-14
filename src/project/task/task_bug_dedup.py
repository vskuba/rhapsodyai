"""
Проверка дубликатов баг-задач по trace_meta JSON-полю.

Публичные функции:
    task_bug_dedup_check — проверяет, существует ли уже задача с данным error_hash
"""


async def task_bug_dedup_check(domain: str, error_hash: str) -> bool:
    """
    Проверяет, существует ли уже задача с таким error_hash в trace_meta.

    Args:
        domain: Имя домена (например, 'workflow_trace').
        error_hash: SHA-256 хеш ошибки для дедупа.

    Returns:
        True если задача с таким hash уже существует (пропустить),
        False если hash не найден (можно создавать).
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT 1 FROM project_task
            WHERE trace_meta IS NOT NULL
              AND JSON_CONTAINS(
                  trace_meta,
                  JSON_OBJECT("domain", %s, "error_hash", %s),
                  "$"
              )
            LIMIT 1
            """,
            (domain, error_hash),
        )
        row = await db.fetchone()
        return row is not None

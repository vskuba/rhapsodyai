import traceback

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from qdrant_.qdrant_ import qdrant_save


async def fact_qdrant_sync() -> str:
    """
    Фоновый воркер для синхронизации несинхронизированных фактов с Qdrant.
    Берет пачку из 50 записей, динамически извлекает разрешенные поля из базы и отправляет в Qdrant.
    """
    async with mysql_get_db_async() as db:
        sql_unsynced = """
            SELECT f.*, fc.name as collection_name, fc.field as collection_fields
            FROM `fact` f
            JOIN `fact_collection` fc ON f.`collection_id` = fc.`id`
            WHERE f.`qdrant_synced` = 0
            LIMIT 50
        """
        await db.execute(sql_unsynced)
        rows = await db.fetchall()

    if not rows:
        return "Все данные во всех коллекциях синхронизированы."

    rows_by_collection = {}
    for row in rows:
        c_name = row['collection_name']
        if c_name not in rows_by_collection:
            rows_by_collection[c_name] = []
        rows_by_collection[c_name].append(row)

    total_synced = 0
    processed_collections_count = 0
    errors = []

    for c_name, collection_rows in rows_by_collection.items():
        if not collection_rows:
            continue

        fact_ids = [r['id'] for r in collection_rows]

        async with mysql_get_db_async() as db:
            try:
                raw_fields_string = collection_rows[0].get('collection_fields') or ""
                allowed_fields = {f.strip() for f in raw_fields_string.split(',') if f.strip()}

                # 'id' и 'document' гарантированно должны присутствовать
                allowed_fields.add('id')
                allowed_fields.add('document')

                prepared_data = []
                for r in collection_rows:
                    clean_row = {field: r.get(field) for field in allowed_fields}
                    prepared_data.append(clean_row)

                mock_metadata = {field: {"table_name": "fact"} for field in allowed_fields}

                synced_count = await qdrant_save(c_name, mock_metadata, prepared_data)
                total_synced += synced_count
                processed_collections_count += 1

                placeholders = ", ".join(["%s"] * len(fact_ids))
                sql_update = f"UPDATE `fact` SET `qdrant_synced` = 1 WHERE `id` IN ({placeholders})"

                await db.execute(sql_update, list(fact_ids))

                if hasattr(db, 'conn') and db.conn:
                    await db.conn.commit()
                elif hasattr(db, 'connection') and db.connection:
                    await db.connection.commit()

            except Exception as e:
                try:
                    if hasattr(db, 'conn') and db.conn:
                        await db.conn.rollback()
                    elif hasattr(db, 'connection') and db.connection:
                        await db.connection.rollback()
                except Exception as rollback_err:
                    logger_info(f"⚠️ Ошибка отката транзакции: {rollback_err}")

                backtrace = traceback.format_exc()
                logger_info(
                    f"❌ Сбой при синхронизации фактов для коллекции '{c_name}': {e}.\n"
                    f"Полный стек вызовов:\n{backtrace}"
                )
                errors.append((c_name, str(e)))

    if errors:
        error_msg = "; ".join([f"'{c}': {err}" for c, err in errors])
        return (
            f"Синхронизация завершена с ошибками. Успешно синхронизировано {total_synced} фактов "
            f"в {processed_collections_count} коллекциях. Ошибки в коллекциях: {error_msg}"
        )

    return f"Успешно синхронизировано {total_synced} фактов в {processed_collections_count} коллекциях."


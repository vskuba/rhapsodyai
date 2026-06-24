from qdrant_client import AsyncQdrantClient

from mysql_.mysql_ import mysql_get_db_async
from qdrant_.qdrant_ import _qdrant_db_get_client, qdrant_save
from src.ai.ai_fact_collection import ai_collection_metadata_get

qdrant_client: AsyncQdrantClient = _qdrant_db_get_client()


async def fact_qdrant_sync() -> str:
    async with mysql_get_db_async() as db:
        sql_unsynced = """
            SELECT f.*, fc.name as collection_name
            FROM fact f
            JOIN fact_collection fc ON f.collection_id = fc.id
            WHERE f.qdrant_synced = 0
            LIMIT 50
        """
        await db.execute(sql_unsynced)
        rows = await db.fetchall()

        if not rows:
            return "Все данные во всех коллекциях синхронизированы."

        # 1. Группируем ID фактов по именам коллекций для дальнейшей обработки
        rows_by_collection = {}
        for row in rows:
            c_name = row['collection_name']
            if c_name not in rows_by_collection:
                rows_by_collection[c_name] = []
            rows_by_collection[c_name].append(row)

        total_synced = 0
        processed_collections_count = 0

        # 2. Обрабатываем каждую коллекцию отдельно
        for c_name, collection_rows in rows_by_collection.items():
            fact_ids = [r['id'] for r in collection_rows]
            dynamic_table = f"fact_collection_{c_name}"

            try:
                # Получаем актуальную карту метаданных именно для этой коллекции
                collection_metadata = await ai_collection_metadata_get(c_name)

                # Определяем поля, которые нужно добрать из динамической таблицы
                dyn_fields = [f for f, info in collection_metadata.items() if info['table_name'] == dynamic_table]

                # Подтягиваем доп. поля из динамической таблицы для текущей пачки ID
                extra_data = {}
                if dyn_fields:
                    f_str = ", ".join([f"`{f}`" for f in dyn_fields])
                    ids_str = ", ".join(["%s"] * len(fact_ids))
                    sql_extra = f"SELECT fact_id, {f_str} FROM `{dynamic_table}` WHERE fact_id IN ({ids_str})"
                    # ВАЖНО: Аргументы для IN (...) передаем строго как кортеж
                    await db.execute(sql_extra, tuple(fact_ids))
                    extra_rows = await db.fetchall()
                    extra_data = {r['fact_id']: r for r in extra_rows}

                # 3. ПОДГОТОВКА ДАННЫХ: Объединяем базовые и динамические поля в единые объекты
                prepared_data = []
                for r in collection_rows:
                    f_id = r['id']

                    # Создаем копию базовой строки из таблицы fact (содержит content, girl_id, tags и т.д.)
                    merged_row = dict(r)

                    # Если для этого факта есть динамические поля, подмешиваем их в этот же словарь
                    if f_id in extra_data:
                        for field in dyn_fields:
                            merged_row[field] = extra_data[f_id].get(field)
                    else:
                        # Если записи в динамической таблице нет, проставляем None для полей,
                        # чтобы qdrant_save не упал по KeyError, если эти поля ожидаются
                        for field in dyn_fields:
                            merged_row[field] = None

                    prepared_data.append(merged_row)

                # 4. СОХРАНЕНИЕ: Передаем полностью собранный массив данных
                synced_count = await qdrant_save(c_name, collection_metadata, prepared_data)
                total_synced += synced_count
                processed_collections_count += 1

                # 5. Обновляем статус пачкой для ЭТОЙ конкретной коллекции
                placeholders = ", ".join(["%s"] * len(fact_ids))
                # ВАЖНО: Приводим fact_ids к tuple, чтобы aiomysql корректно подставил параметры в IN()
                await db.execute(f"UPDATE fact SET qdrant_synced = 1 WHERE id IN ({placeholders})", tuple(fact_ids))

                # Фиксируем изменения для текущей успешной коллекции
                await db.commit()

            except Exception as collection_error:
                # Если одна коллекция упала (например, по KeyError из-за несовпадения схем),
                # мы логируем это, но не прерываем цикл, чтобы остальные коллекции могли синхронизироваться
                print(f"❌ Ошибка при синхронизации коллекции '{c_name}': {collection_error}")
                continue

        return f"Успешно синхронизировано {total_synced} фактов в {processed_collections_count} коллекциях."


async def main():
    try:
        result = await fact_qdrant_sync()
        print(result)
    except Exception as e:
        print(f"Критическая ошибка в процессе синхронизации: {e}")
    finally:
        if qdrant_client:
            await qdrant_client.close()
            print("Соединение с Qdrant закрыто.")


if __name__ == '__main__':
    import asyncio

    asyncio.run(main())
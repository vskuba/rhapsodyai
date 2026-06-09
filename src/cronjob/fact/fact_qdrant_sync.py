import json
import sys
import uuid

from qdrant_client import AsyncQdrantClient

from ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from mysql_.mysql_ import mysql_get_db_async
from qdrant_.qdrant_ import _qdrant_db_get_client

qdrant_client: AsyncQdrantClient = _qdrant_db_get_client()

EMBEDDING_MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
SPARSE_MODEL = 'Qdrant/bm25'


async def fact_qdrant_sync(metadata: dict) -> str:
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

        # Группируем ID фактов по именам коллекций для дальнейшей обработки
        rows_by_collection = {}
        for row in rows:
            c_name = row['collection_name']
            if c_name not in rows_by_collection:
                rows_by_collection[c_name] = []
            rows_by_collection[c_name].append(row)

        manager = AiFrameworkAgentManager()
        qdrant_client.set_model(EMBEDDING_MODEL)
        qdrant_client.set_sparse_model(SPARSE_MODEL)

        total_synced = 0

        # 2. Обрабатываем каждую коллекцию отдельно
        for c_name, collection_rows in rows_by_collection.items():
            fact_ids = [r['id'] for r in collection_rows]
            dynamic_table = f"fact_collection_{c_name}"

            # Получаем метаданные именно для этой коллекции
            collection_metadata = await manager.collection_metadata_get(c_name)

            # Определяем поля, которые нужно добрать из динамической таблицы
            dyn_fields = [f for f, info in collection_metadata.items() if info['table_name'] == dynamic_table]

            # Подтягиваем доп. поля из динамической таблицы для текущей пачки ID
            extra_data = {}
            if dyn_fields:
                f_str = ", ".join([f"`{f}`" for f in dyn_fields])
                ids_str = ", ".join(["%s"] * len(fact_ids))
                sql_extra = f"SELECT fact_id, {f_str} FROM `{dynamic_table}` WHERE fact_id IN ({ids_str})"
                await db.execute(sql_extra, fact_ids)
                extra_rows = await db.fetchall()
                extra_data = {r['fact_id']: r for r in extra_rows}

            docs, payloads = [], []

            for r in collection_rows:
                f_id = r['id']
                # Формируем базовый payload
                payload = {
                    "category": r.get('category'),
                    "language": r.get('language'),
                    "tags": r.get('tags').split(',') if r.get('tags') else []
                }

                # Добавляем динамические поля, если они есть для этого ID
                if f_id in extra_data:
                    for field in dyn_fields:
                        payload[field] = extra_data[f_id].get(field)

                docs.append(r['content'])
                payloads.append(payload)

            # 3. Загружаем в Qdrant
            await qdrant_client.add(
                collection_name=c_name,
                documents=docs,
                metadata=payloads,
                ids=[str(uuid.uuid4()) for _ in docs]
            )

            # 4. Обновляем статус пачкой для этой коллекции
            placeholders = ", ".join(["%s"] * len(fact_ids))
            await db.execute(f"UPDATE fact SET qdrant_synced = 1 WHERE id IN ({placeholders})", fact_ids)
            total_synced += len(collection_rows)

        await db.commit()
        return f"Успешно синхронизировано {total_synced} фактов в {len(rows_by_collection)} коллекциях."


async def main(metadata: dict):
    try:
        result = await fact_qdrant_sync(metadata)
        print(result)
    except Exception as e:
        print(f"Ошибка в процессе синхронизации: {e}")
    finally:
        if qdrant_client:
            await qdrant_client.close()
            print("Соединение с Qdrant закрыто.")


if __name__ == '__main__':
    import asyncio

    metadata = json.loads(sys.argv[1])

    asyncio.run(main(metadata))

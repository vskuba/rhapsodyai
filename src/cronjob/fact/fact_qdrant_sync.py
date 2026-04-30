import uuid
from contextlib import asynccontextmanager
from qdrant_client import AsyncQdrantClient

from mysql_.mysql_ import mysql_get_db_async
from qdrant_.qdrant_ import _qdrant_db_get_client

qdrant_client: AsyncQdrantClient = _qdrant_db_get_client()

EMBEDDING_MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
SPARSE_MODEL = 'Qdrant/bm25'


async def fact_qdrant_sync() -> str:
    async with asynccontextmanager(mysql_get_db_async)() as db:
        async with db.cursor() as cursor:
            # 1. Получаем данные (уже с чистым контентом)
            sql = """
                SELECT f.id, f.content, f.document, f.category, f.language, f.source_file, f.group_id,
                       fc.name as collection_name, 
                       GROUP_CONCAT(ft.name) as tags_list
                FROM fact f
                JOIN fact_collection fc ON f.collection_id = fc.id
                LEFT JOIN fact_tags ft ON ft.fact_id = f.id
                WHERE f.qdrant_synced = 0
                GROUP BY f.id
                LIMIT 50
            """
            await cursor.execute(sql)
            rows = await cursor.fetchall()

            if not rows:
                return "Все данные синхронизированы."

            # Настройка моделей
            qdrant_client.set_model(EMBEDDING_MODEL)
            qdrant_client.set_sparse_model(SPARSE_MODEL)

            collections_map = {}
            for row in rows:
                c_name = row['collection_name']
                if c_name not in collections_map:
                    collections_map[c_name] = {"docs": [], "payloads": [], "ids": []}

                # Используем контент напрямую, так как он уже в нужном формате
                doc_text = row['content']

                payload = {
                    "document": row['document'],
                    "category": row['category'],
                    "language": row['language'],
                    "source_file": row['source_file'],
                    "group_id": row['group_id'],
                    "tags": row['tags_list'].split(',') if row['tags_list'] else [],
                    "content": doc_text
                }

                collections_map[c_name]["docs"].append(doc_text)
                collections_map[c_name]["payloads"].append(payload)
                collections_map[c_name]["ids"].append(row['id'])

            # 2. Загрузка в Qdrant
            for c_name, data in collections_map.items():
                await qdrant_client.add(
                    collection_name=c_name,
                    documents=data["docs"],
                    metadata=data["payloads"],
                    ids=[str(uuid.uuid4()) for _ in data["docs"]]
                )

                # 3. Массовое обновление статуса
                ids_str = ",".join(map(str, data["ids"]))
                await cursor.execute(f"UPDATE fact SET qdrant_synced = 1 WHERE id IN ({ids_str})")

            await db.commit()
            return f"Успешно синхронизировано {len(rows)} фактов."


async def main():
    try:
        result = await fact_qdrant_sync()
        print(result)
    except Exception as e:
        print(f"Ошибка в процессе синхронизации: {e}")
    finally:
        if qdrant_client:
            await qdrant_client.close()
            print("Соединение с Qdrant закрыто.")


if __name__ == '__main__':
    import asyncio

    asyncio.run(main())

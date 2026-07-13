from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from qdrant_.qdrant_ import qdrant_search, qdrant_remove_by
from src.ai.ai_fact import fact_qdrant_sync
from src.ai.ai_fact_collection import ai_fact_collection_metadata_get


async def qdrant_fact_sync() -> dict:
    """
    Немедленно синхронизирует несинхронизированные факты (qdrant_synced = 0)
    из базы данных в Qdrant, не дожидаясь фоновой синхронизации по расписанию.
    Обрабатывает пачками по 50 до полной синхронизации (максимум 20 пачек за
    вызов); останавливается, если пачка не дает прогресса (ошибки синка).
    Returns:
        A dictionary with the sync report.
        synced_qty (int): Количество синхронизированных фактов за вызов.
        report_str (str): Отчет последней пачки синхронизации.
    """
    report = 'Все факты уже синхронизированы'
    synced_before = None
    unsynced_start = 0

    for batch in range(20):
        async with mysql_get_db_async() as db:
            await db.execute("SELECT COUNT(*) AS qty FROM `fact` WHERE `qdrant_synced` = 0")
            unsynced = (await db.fetchone())['qty']

        if batch == 0:
            unsynced_start = unsynced
        if not unsynced:
            break
        if synced_before is not None and unsynced >= synced_before:
            # Пачка не уменьшила остаток — синхронизация падает, не крутимся впустую
            break

        synced_before = unsynced
        report = await fact_qdrant_sync()

    async with mysql_get_db_async() as db:
        await db.execute("SELECT COUNT(*) AS qty FROM `fact` WHERE `qdrant_synced` = 0")
        unsynced_end = (await db.fetchone())['qty']

    return {
        "synced_qty": max(0, unsynced_start - unsynced_end),
        "report_str": report,
    }


async def qdrant_fact_search(
        query_text: str,
        collection_name: str,
        metadata_filter: str,
        limit: int = 5
) -> str:
    """
    Высокоуровневая обёртка для поиска.
    Автоматически подтягивает метаданные и возвращает только список текстовых фактов.
    """
    metadata_filter_json = json_from_string(metadata_filter)
    field_document = 'document'

    if 'tags' in metadata_filter_json:
        metadata_filter_json['tags'] = [tag.strip() for tag in metadata_filter_json['tags'].split(',')]

    search_results = await qdrant_search(
        query_text=query_text,
        collection_name=collection_name,
        metadata=await ai_fact_collection_metadata_get(collection_name),
        metadata_filter=metadata_filter_json,
        limit=limit
    )

    facts_text_list = []
    for point in search_results:
        if point.payload and field_document in point.payload:
            facts_text_list.append(str(point.payload[field_document]))

    return " ".join(facts_text_list)


async def qdrant_fact_remove(collection_name: str, metadata_filter: str) -> int:
    """
    Удаляет факты из коллекции Qdrant на основе фильтра метаданных.
    """
    metadata_filter_json = json_from_string(metadata_filter)

    return await qdrant_remove_by(collection_name, await ai_fact_collection_metadata_get(collection_name), metadata_filter_json)

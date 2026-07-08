from json_.json_ import json_from_string
from qdrant_.qdrant_ import qdrant_search, qdrant_remove_by
from src.ai.ai_fact_collection import ai_fact_collection_metadata_get


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

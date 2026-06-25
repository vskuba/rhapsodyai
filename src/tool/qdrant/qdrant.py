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

    # 1. Добавлен оператор await перед вызовом асинхронного поиска
    search_results = await qdrant_search(
        query_text=query_text,
        collection_name=collection_name,
        metadata=await ai_fact_collection_metadata_get(collection_name),
        metadata_filter=metadata_filter_json,
        limit=limit
    )

    # 2. Извлекаем текстовое содержимое (поле 'content') из payload каждой найденной точки
    # По вашему коду синхронизации текст факта пишется в payload['content'] через docs.append(r['content'])
    facts_text_list = []
    for point in search_results:
        if point.payload and 'content' in point.payload:
            facts_text_list.append(str(point.payload['content']))

    return " ".join(facts_text_list)


async def qdrant_fact_remove(collection_name: str, metadata_filter: str) -> int:
    """
    Удаляет факты из коллекции Qdrant на основе фильтра метаданных.
    """
    metadata_filter_json = json_from_string(metadata_filter)

    return await qdrant_remove_by(collection_name, await ai_fact_collection_metadata_get(collection_name), metadata_filter_json)

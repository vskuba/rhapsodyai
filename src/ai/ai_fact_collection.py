from mysql_.mysql_table import mysql_table_metadata_get
from src.mysql_.repository.fact_collection_repository import FactCollectionRepository

collection_metadata_cache = {}


async def ai_fact_collection_metadata_get(collection_name) -> dict:
    if collection_name in collection_metadata_cache:
        return collection_metadata_cache[collection_name]

    repo = FactCollectionRepository()
    entity_collection = await repo.find_one_by({"name": collection_name})
    if not entity_collection:
        raise Exception(f"Fact collection {collection_name} not found")

    collection_metadata = {}

    fields = entity_collection.get('field', '')
    fields_allowed: list[str] = fields.split(',')

    for table_name in ['fact']:
        table_metadata = await mysql_table_metadata_get(table_name)

        for field, m in table_metadata.items():
            comment_metadata = m.get('comment_metadata')
            if (
                    comment_metadata and comment_metadata.get('tag') == 'extract'
                    and field in fields_allowed
            ):
                collection_metadata[field] = {
                    'table_name': table_name,
                    'description': m['comment_metadata']['desc'],
                }

    collection_metadata_cache[collection_name] = collection_metadata

    return collection_metadata
from mysql_.mysql_table import mysql_table_metadata_get


async def ai_collection_metadata_get(collection_name) -> dict:
    collection_metadata = {}

    for table_name in ['fact', f'fact_collection_{collection_name}']:
        table_metadata = await mysql_table_metadata_get(table_name)

        for field, m in table_metadata.items():
            comment_metadata = m.get('comment_metadata')
            if comment_metadata and comment_metadata.get('tag') == 'extract':
                collection_metadata[field] = {
                    'table_name': table_name,
                    'description': m['comment_metadata']['desc'],
                }

    return collection_metadata
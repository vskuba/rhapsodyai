import json
import traceback

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_fact_collection import ai_fact_collection_metadata_get
from src.mysql_.repository.fact_collection_repository import FactCollectionRepository


async def fact_collection_output_format(collection_name: str) -> str:
    """
    Возвращает JSON в виде текстовой строки.
    Внутри JSON описаны поля таблицы fact, которые имеют комментарий с тегом "extract".
    """
    collection_metadata = await ai_fact_collection_metadata_get(collection_name)

    example_fact_extract = ''
    if collection_metadata:
        example_fact_extract = "[{\n"
        lines = [f'  "{f}": "' + v['description'] + '"' for f, v in collection_metadata.items()]
        example_fact_extract += ",\n".join(lines)
        example_fact_extract += "\n},{\n"
        example_fact_extract += ",\n".join(lines)
        example_fact_extract += "\n}]"

    return example_fact_extract


async def fact_collection_add(collection_name: str, data: list[dict]) -> dict:
    """
    Добавляет данные напрямую в базовую таблицу фактов 'fact'.
     - collection_name: имя коллекции для поиска ее ID и разрешенных полей в базе
     - data: список словарей с данными или валидная JSON-строка-массив
    Возвращает текстовую строку со всеми добавленными фактами.

    Example:
        collection_name: dating_talk
        data: [{"document_id": "alla_user1", "language": "ru", "document": "Мы обсуждали его привычки в тренировках.", "tags": "тренажерный зал, физическая активность"}]

    Returns:
        facts_qty (int): количество добавленных фактов
        facts_str (str): текстовая строка со всеми добавленными фактами
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
            logger_info(f"🔹 Входные данные 'data' для '{collection_name}' успешно десериализованы из JSON.")
        except (json.JSONDecodeError, TypeError) as json_err:
            raise ValueError(f"Не удалось распарсить строку 'data' как валидный JSON-массив: {json_err}")

    if isinstance(data, dict):
        data = [data]

    if not data or not isinstance(data, list):
        raise ValueError("Fact data collection must be a non-empty list")

    repo = FactCollectionRepository()
    entity_collection = await repo.find_one_by({"name": collection_name})
    if not entity_collection:
        raise ValueError(f"Collection with name '{collection_name}' not found")

    collection_id = entity_collection.get('id')

    raw_fields_string = entity_collection.get('field') or ""
    allowed_fact_fields = {f.strip() for f in raw_fields_string.split(',') if f.strip()}

    if not allowed_fact_fields:
        raise ValueError(f"Конфигурация полей для коллекции '{collection_name}' пуста или отсутствует в БД.")

    field_document = 'document'
    field_document_id = 'document_id'
    documents: list[str] = []

    async with mysql_get_db_async() as db:
        try:
            for index, entry in enumerate(data):
                if not isinstance(entry, dict):
                    raise ValueError(f"Запись под индексом {index} должна быть словарем (dict)")

                # Отбираем только те поля, которые реально переданы и разрешены для этой коллекции в базе
                present_fields = [f for f in allowed_fact_fields if f in entry]

                fact_fields = ['collection_id'] + present_fields
                fact_values = [collection_id] + [entry.get(f) for f in present_fields]

                document_value = entry.get(field_document, '')
                document_id_value = entry.get(field_document_id, '')

                documents.append(document_value)

                sql = """
                    SELECT `id` FROM `fact`
                    WHERE `collection_id` = %s AND `document` = %s AND `document_id` = %s
                """
                await db.execute(sql, (collection_id, document_value, document_id_value))
                row = await db.fetchone()
                if  row:
                    logger_info(
                        f"⚠️ Факт с collection_id={collection_id}, document='{document_value}', document_id='{document_id_value}' "
                        f"уже существует в таблице 'fact'. Пропускаем добавление.")
                    continue

                f_str = ", ".join([f"`{f}`" for f in fact_fields])
                f_placeholders = ", ".join(["%s"] * len(fact_fields))

                sql_fact = f"INSERT INTO `fact` ({f_str}) VALUES ({f_placeholders})"
                await db.execute(sql_fact, fact_values)

            if hasattr(db, 'connection') and db.connection:
                await db.connection.commit()

        except Exception as e:
            if hasattr(db, 'connection') and db.connection:
                await db.connection.rollback()

            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Сбой при добавленнии фактов в БД: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise ValueError(f"Database error: {str(e)}")

    return {
        "facts_qty": len(data),
        "facts_str": ' '.join(documents)
    }


async def fact_collection_remove_by(collection_name: str, criteria: dict) -> int:
    """
    Удаляет факты из таблицы 'fact' по переданным критериям.
    Все переданные критерии объединяются через логическое 'И' (AND).

    :param collection_name: Имя коллекции фактов
    :param criteria: Словарь с фильтрами для удаления (например, {"document_id": "dasha"})
    :return: Количество удаленных записей
    :raises ValueError: Если коллекция не найдена или критерии пусты
    """
    repo = FactCollectionRepository()
    entity_collection = await repo.find_one_by({"name": collection_name})
    if not entity_collection:
        raise ValueError(f"Collection with name '{collection_name}' not found")

    collection_id = entity_collection.get('id')

    if not criteria:
        raise ValueError("Критерии для очистки коллекции не могут быть пустыми во избежание потери данных.")

    raw_fields_string = entity_collection.get('field') or ""
    allowed_fact_fields = {f.strip() for f in raw_fields_string.split(',') if f.strip()}

    allowed_fact_fields.update({"id", "qdrant_synced"})

    conditions = ["`collection_id` = %s"]
    params = [collection_id]

    for field, value in criteria.items():
        if value is None or field not in allowed_fact_fields:
            continue
        conditions.append(f"`{field}` = %s")
        params.append(value)

    async with mysql_get_db_async() as db:
        try:
            sql_count = f"SELECT COUNT(`id`) as total FROM `fact` WHERE {' AND '.join(conditions)}"
            await db.execute(sql_count, params)
            count_res = await db.fetchone()
            affected_rows = count_res.get('total', 0) if count_res else 0

            if affected_rows == 0:
                return 0

            sql_delete = f"DELETE FROM `fact` WHERE {' AND '.join(conditions)}"
            await db.execute(sql_delete, params)

            if hasattr(db, 'connection') and db.connection:
                await db.connection.commit()

            return affected_rows

        except Exception as e:
            if hasattr(db, 'connection') and db.connection:
                await db.connection.rollback()

            backtrace = traceback.format_exc()
            logger_info(
                f"❌ Сбой при удалении фактов из БД: {e}."
                f"Полный стек вызовов:\n{backtrace}"
            )
            raise ValueError(f"Ошибка при удалении фактов из коллекции '{collection_name}': {str(e)}")

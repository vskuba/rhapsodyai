from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_fact_collection import ai_collection_metadata_get
from src.mysql_.repository.fact_collection_repository import FactCollectionRepository


async def fact_collection_output_format(collection_name: str) -> str:
    """
    Возвращает JSON в виде текстовой строки.
    Внутри JSON описаны поля таблицы fact_collection_{collection_name}, которые имеют комментарий с тегом "extract".
    """
    collection_metadata = await ai_collection_metadata_get(collection_name)

    example_fact_extract = ''
    if collection_metadata:
        example_fact_extract = "[{\n"
        lines = [f'  "{f}": "' + v['description'] for f, v in collection_metadata.items()]
        example_fact_extract += ",\n".join(lines)
        example_fact_extract += "\n},{\n"
        example_fact_extract += ",\n".join(lines)
        example_fact_extract += "\n}]"

    return example_fact_extract


async def fact_collection_add(collection_name: str, data: list[dict]) -> int:
    """
    Добавляет данные в коллекцию фактов. Данные должны быть в виде списка словарей, где ключи - это имена полей, а значения - это значения для этих полей.
     - collection_name: имя коллекции фактов (без префикса "fact_collection_")
     - data: список словарей с данными для сохранения
     Возвращает строку статуса операции.
     1. Валидация входных данных: проверяем, что data - это непустой список словарей.
     2. Получаем метаданные коллекции по имени, чтобы понять структуру таблиц и необходимые поля.
     3. Для каждой записи в data:
        a. Вставляем базовые поля в таблицу 'fact' и получаем новый ID факта.
        b. Вставляем дополнительные поля в динамическую таблицу 'fact_collection_{collection_name}', используя полученный ID факта для связи 1-to-1.
     4. Коммитим транзакцию и возвращаем результат.
     5. В случае ошибки откатываем транзакцию и возвращаем сообщение об ошибке.
    """
    if not data or not isinstance(data, list):
        raise ValueError("Fact data collection must be a non-empty list")

    repo = FactCollectionRepository()
    entity_collection = await repo.find_by({"name": collection_name})
    if not entity_collection:
        raise ValueError(f"Collection with name '{collection_name}' not found")

    collection_id = entity_collection.get('id')
    collection_name = entity_collection.get('name')

    dynamic_table = f"fact_collection_{collection_name}"

    collection_metadata = await ai_collection_metadata_get(collection_name)

    # 1. Группируем метаданные по таблицам
    fields_map = {"fact": [], dynamic_table: []}
    for field, info in collection_metadata.items():
        t_name = info['table_name']
        if t_name in fields_map:
            fields_map[t_name].append(field)

    # Валидация входных данных
    required_fields = set(collection_metadata.keys())
    for index, entry in enumerate(data):
        if not required_fields.issubset(entry.keys()):
            missing = required_fields - set(entry.keys())
            raise ValueError(f"Entry {index} missing: {', '.join(missing)}")

    async with mysql_get_db_async() as db:
        try:
            for entry in data:
                # --- ШАГ 1: Вставка в таблицу 'fact' ---
                fact_fields = ['collection_id'] + fields_map['fact']
                fact_values = [collection_id] + [entry.get(f) for f in fields_map['fact']]

                f_str = ", ".join([f"`{f}`" for f in fact_fields])
                f_placeholders = ", ".join(["%s"] * len(fact_fields))

                sql_fact = f"INSERT INTO `fact` ({f_str}) VALUES ({f_placeholders})"
                await db.execute(sql_fact, fact_values)

                # Получаем ID только что созданной записи в 'fact'
                new_fact_id = db.lastrowid

                # --- ШАГ 2: Вставка в динамическую таблицу ---
                # Даже если доп. полей нет, мы должны создать запись для связи 1-to-1
                coll_fields = ['fact_id'] + fields_map[dynamic_table]
                coll_values = [new_fact_id] + [entry.get(f) for f in fields_map[dynamic_table]]

                c_str = ", ".join([f"`{f}`" for f in coll_fields])
                c_placeholders = ", ".join(["%s"] * len(coll_fields))

                sql_coll = f"INSERT INTO `{dynamic_table}` ({c_str}) VALUES ({c_placeholders})"
                await db.execute(sql_coll, coll_values)

            await db.commit()
        except Exception as e:
            await db.rollback()
            raise ValueError(f"Database error: {str(e)}")

    return len(data)

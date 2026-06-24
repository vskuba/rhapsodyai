import json

from logging_.logging_ import logger_info
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
        lines = [f'  "{f}": "' + v['description'] + '"' for f, v in collection_metadata.items()]
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
    if isinstance(data, str):
        try:
            data = json.loads(data)
            logger_info(f"🔹 Входные данные 'data' для '{collection_name}' успешно десериализованы из JSON-строки.")
        except (json.JSONDecodeError, TypeError) as json_err:
            raise ValueError(f"Не удалось распарсить строку 'data' как валидный JSON-массив: {json_err}")

        # Оборачиваем в список, если пришел один объект вместо массива
    if isinstance(data, dict):
        data = [data]

    if not data or not isinstance(data, list):
        raise ValueError("Fact data collection must be a non-empty list")

    repo = FactCollectionRepository()
    entity_collection = await repo.find_one_by({"name": collection_name})
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

            await db.connection.commit()
        except Exception as e:
            await db.connection.rollback()
            raise ValueError(f"Database error: {str(e)}")

    return len(data)


async def fact_collection_remove_by(collection_name: str, criteria: dict) -> int:
    """
    Удаляет факты из базовой и динамической таблиц по переданным критериям.
    Все переданные критерии объединяются через логическое 'И' (AND).

    :param collection_name: Имя коллекции фактов (без префикса)
    :param criteria: Словарь с фильтрами для удаления (например, {"girl_id": 1})
    :return: Количество удаленных записей
    :raises ValueError: Если коллекция не найдена или критерии пусты
    """
    repo = FactCollectionRepository()
    entity_collection = await repo.find_one_by({"name": collection_name})
    if not entity_collection:
        raise ValueError(f"Collection with name '{collection_name}' not found")

    collection_id = entity_collection.get('id')
    dynamic_table = f"fact_collection_{collection_name}"
    collection_metadata = await ai_collection_metadata_get(collection_name)

    # Защита от случайной полной очистки базы данных
    if not criteria:
        raise ValueError("Критерии для очистки коллекции не могут быть пустыми во избежание полной потери данных.")

    # Разделяем критерии по таблицам происхождения
    fact_conditions = ["f.collection_id = %s"]
    fact_params = [collection_id]

    dyn_conditions = []
    dyn_params = []

    for field, value in criteria.items():
        if value is None or field not in collection_metadata:
            continue

        table_origin = collection_metadata[field]['table_name']
        if table_origin == "fact":
            fact_conditions.append(f"f.`{field}` = %s")
            fact_params.append(value)
        elif table_origin == dynamic_table:
            dyn_conditions.append(f"d.`{field}` = %s")
            dyn_params.append(value)

    async with mysql_get_db_async() as db:
        try:
            # Шаг 1: Находим все ID фактов, подлежащих удалению
            if dyn_conditions:
                # Если есть фильтры по динамической таблице, делаем JOIN
                all_conditions = fact_conditions + dyn_conditions
                all_params = fact_params + dyn_params
                sql_select = f"""
                    SELECT f.id FROM `fact` f
                    JOIN `{dynamic_table}` d ON f.id = d.fact_id
                    WHERE {" AND ".join(all_conditions)}
                """
            else:
                # Если фильтры только по базовой таблице, ищем напрямую
                all_params = fact_params
                sql_select = f"""
                    SELECT f.id FROM `fact` f
                    WHERE {" AND ".join(fact_conditions)}
                """

            await db.execute(sql_select, all_params)
            rows = await db.fetchall()

            if not rows:
                return 0

            target_fact_ids = [r['id'] for r in rows]
            placeholders = ", ".join(["%s"] * len(target_fact_ids))
            params_tuple = tuple(target_fact_ids)

            # Шаг 2: Удаляем связанные записи из динамической таблицы
            sql_delete_dyn = f"DELETE FROM `{dynamic_table}` WHERE fact_id IN ({placeholders})"
            await db.execute(sql_delete_dyn, params_tuple)

            # Шаг 3: Удаляем записи из базовой таблицы 'fact'
            sql_delete_fact = f"DELETE FROM `fact` WHERE id IN ({placeholders})"
            await db.execute(sql_delete_fact, params_tuple)

            # Фиксируем транзакцию
            await db.connection.commit()
            return len(target_fact_ids)

        except Exception as e:
            await db.connection.rollback()
            raise ValueError(f"Ошибка при очистке MySQL коллекции '{collection_name}': {str(e)}")
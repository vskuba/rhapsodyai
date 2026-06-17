from fastapi import APIRouter, Request, Depends, HTTPException

from ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.fact_collection_repository import FactCollectionRepository
from src.parser.md_to_fact.data_parser import ParserMdToFact

router = APIRouter()


@router.get("/fact/collection/list")
async def fact_collection_list(request: Request, db=Depends(mysql_get_db_async)):
    async with db:
        await db.execute("SELECT * FROM fact_collection")
        return {"result": await db.fetchall()}


@router.get("/fact/collection/{collection_name}")
async def fact_list(
        request: Request,
        collection_name: str,
        page: int = 1,
        limit: int = 20,
        query: str = None,  # Добавляем фильтр
        db=Depends(mysql_get_db_async)
):
    offset = (page - 1) * limit
    params = [collection_name]
    search_condition = ""

    # Если есть поисковый запрос, добавляем условие LIKE
    if query:
        search_condition = " AND f.content LIKE %s"
        params.append(f"%{query}%")

    async with db:
        # 1. Считаем общее количество с учетом фильтра
        count_sql = f"""
            SELECT COUNT(*) as total FROM fact f
            JOIN fact_collection fc ON f.collection_id = fc.id
            WHERE fc.name = %s {search_condition}
        """
        # Важно: передаем params как кортеж или список
        await db.execute(count_sql, params)
        total_res = await db.fetchone()
        total_count = total_res['total'] if total_res else 0

        # 2. Получаем данные страницы
        # Добавляем limit и offset в список параметров
        data_params = params + [limit, offset]
        sql = f"""
                    SELECT f.*, fc.name as collection_name
                    FROM fact_collection_{collection_name} c
                    JOIN fact f ON c.fact_id = f.id
                    JOIN fact_collection fc ON f.collection_id = fc.id
                    WHERE fc.name = %s {search_condition}
                    GROUP BY f.id
                    ORDER BY f.id DESC
                    LIMIT %s OFFSET %s
                """
        await db.execute(sql, data_params)
        facts = await db.fetchall()

        return {
            "result": facts,
            "pagination": {
                "current_page": page,
                "limit": limit,
                "total_records": total_count,
                "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1
            }
        }


@router.put("/fact/collection/{collection_id}")
async def fact_collection_save(request: Request, collection_id: int, data: list[dict], db=Depends(mysql_get_db_async)):
    if not data or not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Fact data collection must be a non-empty list")

    repo = FactCollectionRepository()
    collection_entity = await repo.find(collection_id)
    collection_name = collection_entity.get('name')
    dynamic_table = f"fact_collection_{collection_name}"

    manager = AiFrameworkAgentManager()
    collection_metadata = await manager.collection_metadata_get(collection_name)

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
            raise HTTPException(status_code=400, detail=f"Entry {index} missing: {', '.join(missing)}")

    async with db:
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
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"status": "success", "added": len(data)}


@router.delete("/fact/{fact_id}")
async def delete_fact(fact_id: int, db=Depends(mysql_get_db_async)):
    async with db:
        # Проверяем существование
        await db.execute("DELETE FROM fact WHERE id = %s", fact_id)
        return {"status": "success", "message": f"Fact {fact_id} deleted"}

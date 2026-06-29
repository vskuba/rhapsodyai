from fastapi import APIRouter, Request, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.fact_collection_repository import FactCollectionRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/fact/collection/list")
async def fact_collection_list(request: Request, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.FACT_COLLECTION_VIEW]))):
    async with db:
        await db.execute("SELECT * FROM fact_collection")
        return {"result": await db.fetchall()}


@router.get("/fact/collection/{collection_name}")
async def fact_list(
        request: Request,
        collection_name: str,
        page: int = 1,
        limit: int = 20,
        query: str = '',
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.FACT_VIEW]))
):
    page = max(1, page)
    limit = max(1, min(100, limit))
    offset = (page - 1) * limit

    params = [collection_name]
    search_condition = ""

    if query:
        search_condition = " AND f.`content` LIKE %s"
        params.append(f"%{query.strip()}%")

    async with db:

        count_sql = f"""
            SELECT COUNT(f.`id`) as total 
            FROM `fact` f
            JOIN `fact_collection` fc ON f.`collection_id` = fc.`id`
            WHERE fc.`name` = %s {' ' + search_condition if search_condition else ''}
        """
        await db.execute(count_sql, params)
        total_res = await db.fetchone()
        total_count = total_res['total'] if total_res else 0

        if total_count == 0:
            return {
                "result": [],
                "pagination": {
                    "current_page": page,
                    "limit": limit,
                    "total_records": 0,
                    "total_pages": 1
                }
            }

        sql = f"""
            SELECT f.*, fc.`name` as collection_name
            FROM `fact` f
            JOIN `fact_collection` fc ON f.`collection_id` = fc.`id`
            WHERE fc.`name` = %s {' ' + search_condition if search_condition else ''}
            ORDER BY f.`id` DESC
            LIMIT {int(limit)} OFFSET {int(offset)}
        """
        await db.execute(sql, params)
        facts = await db.fetchall()

        return {
            "result": facts,
            "pagination": {
                "current_page": page,
                "limit": limit,
                "total_records": total_count,
                "total_pages": (total_count + limit - 1) // limit
            }
        }


@router.put("/fact/collection/{collection_id}")
async def fact_collection_save(
        request: Request,
        collection_id: int,
        data: list[dict],
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.FACT_CREATE]))
):
    if not data or not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Fact data collection must be a non-empty list")

    repo = FactCollectionRepository()
    collection_entity = await repo.find(collection_id)
    if not collection_entity:
        raise HTTPException(status_code=404, detail=f"Collection with ID {collection_id} not found")

    raw_fields_string = collection_entity.get('field') or ""
    allowed_fact_fields = {f.strip() for f in raw_fields_string.split(',') if f.strip()}

    if not allowed_fact_fields:
        raise HTTPException(
            status_code=500,
            detail=f"Конфигурация полей для коллекции ID {collection_id} пуста или не настроена в БД."
        )

    async with db:
        for index, entry in enumerate(data):
            if not isinstance(entry, dict):
                raise HTTPException(status_code=400, detail=f"Entry {index} must be a dictionary")

            present_fields = [f for f in allowed_fact_fields if f in entry]

            fact_fields = ['collection_id'] + present_fields
            fact_values = [collection_id] + [entry.get(f) for f in present_fields]

            f_str = ", ".join([f"`{f}`" for f in fact_fields])
            f_placeholders = ", ".join(["%s"] * len(fact_fields))

            sql_fact = f"INSERT INTO `fact` ({f_str}) VALUES ({f_placeholders})"
            await db.execute(sql_fact, fact_values)

        await db.connection.commit()

        return {"status": "success", "added": len(data)}


@router.delete("/fact/{fact_id}")
async def delete_fact(fact_id: int, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.FACT_DELETE]))):
    async with db:
        # Проверяем существование
        await db.execute("DELETE FROM fact WHERE id = %s", fact_id)
        return {"status": "success", "message": f"Fact {fact_id} deleted"}
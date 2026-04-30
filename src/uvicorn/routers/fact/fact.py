from fastapi import APIRouter, Request, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.parser.md_to_fact.data_parser import ParserMdToFact

router = APIRouter()


@router.get("/fact/collection/list")
async def fact_collection_list(request: Request, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        await cursor.execute("SELECT * FROM fact_collection")
        return {"result": await cursor.fetchall()}


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

    async with db.cursor() as cursor:
        # 1. Считаем общее количество с учетом фильтра
        count_sql = f"""
            SELECT COUNT(*) as total FROM fact f
            JOIN fact_collection fc ON f.collection_id = fc.id
            WHERE fc.name = %s {search_condition}
        """
        # Важно: передаем params как кортеж или список
        await cursor.execute(count_sql, params)
        total_res = await cursor.fetchone()
        total_count = total_res['total'] if total_res else 0

        # 2. Получаем данные страницы
        # Добавляем limit и offset в список параметров
        data_params = params + [limit, offset]
        sql = f"""
                    SELECT f.*, fc.name as collection_name, GROUP_CONCAT(ft.name) as tags_list
                    FROM fact f
                    JOIN fact_collection fc ON f.collection_id = fc.id
                    LEFT JOIN fact_tags ft ON ft.fact_id = f.id
                    WHERE fc.name = %s {search_condition}
                    GROUP BY f.id
                    ORDER BY f.id DESC
                    LIMIT %s OFFSET %s
                """
        await cursor.execute(sql, data_params)
        facts = await cursor.fetchall()

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
async def fact_collection_save(request: Request, collection_id: int, data: dict, db=Depends(mysql_get_db_async)):
    content = data.get("content", '')
    if not content:
        raise HTTPException(status_code=400, detail="Content is empty")

    parser = ParserMdToFact()
    entries = await parser._parse_content(content)

    if not entries:
        return {"status": "error", "message": "No entries parsed"}

    async with db.cursor() as cursor:
        sql = """
            INSERT INTO fact (
                collection_id, document, group_id, category, 
                language, source_file, content, qdrant_synced
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
        """

        values = [
            (
                collection_id,
                entry.title,
                entry.group_id,
                entry.category,
                entry.language,
                entry.filename,  # {name}.md
                entry.content,
            ) for entry in entries
        ]

        await cursor.executemany(sql, values)
        await db.commit()

    return {"status": "success", "added": len(entries)}


@router.delete("/fact/{fact_id}")
async def delete_fact(fact_id: int, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        # Проверяем существование
        await cursor.execute("DELETE FROM fact WHERE id = %s", (fact_id,))
        return {"status": "success", "message": f"Fact {fact_id} deleted"}

from fastapi import APIRouter, Request, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.parser.md_to_fact.data_parser import ParserMdToFact

router = APIRouter()


@router.get("/fact/collection/list")
async def user_list(request: Request, db=Depends(mysql_get_db_async)):
    async with db.cursor() as cursor:
        await cursor.execute("SELECT * FROM fact_collection")
        return {"result": await cursor.fetchall()}


@router.put("/fact/collection/{name}")
async def save_fact_collection(request: Request, name: str, data: dict, db=Depends(mysql_get_db_async)):
    content = data.get("content", '')
    if not content:
        raise HTTPException(status_code=400, detail="Content is empty")

    parser = ParserMdToFact()
    entries = await parser._parse_content(content)

    if not entries:
        return {"status": "error", "message": "No entries parsed"}

    async with db.cursor() as cursor:
        # SQL запрос согласно вашей структуре в phpMyAdmin
        sql = """
            INSERT INTO fact (
                collection_id, document, group_id, category, 
                language, source_file, content, qdrant_synced
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
        """

        # Формируем данные для массовой вставки
        values = [
            (
                data.get("collection_id"),
                entry.title,
                entry.group_id,
                entry.category,
                entry.language,
                entry.filename,  # {name}.md
                entry.content,
            ) for entry in entries
        ]

        # Используем executemany для быстрой вставки всех фактов сразу
        await cursor.executemany(sql, values)
        await db.commit()

    return {"status": "success", "added": len(entries)}

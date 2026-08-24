from fastapi import APIRouter, Request, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from qdrant_.qdrant_ import qdrant_remove_by
from src.ai.ai_fact import ai_fact_qdrant_sync
from src.ai.ai_fact_collection import ai_fact_collection_metadata_get
from src.mysql_.repository.fact_collection_repository import FactCollectionRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import auth_role_is_full

router = APIRouter()

# Видимость фактов для не-админов: только собственные факты — созданные
# workflow-запусками этого пользователя (fact.user_id)
FACT_OWNER_CONDITION = "f.`user_id` = %s"


@router.post("/fact/collection/{collection_name}/resync")
async def fact_collection_resync(
        request: Request,
        collection_name: str,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.FACT_UPDATE]))
):
    """Пересинхронизация фактов в Qdrant: удаляет из Qdrant все записи выбранного
    document_title (или всей коллекции при 'all'), помечает факты в БД
    несинхронизированными и заново заливает их в Qdrant."""
    document_title = (data or {}).get('document_title') or 'all'

    repo = FactCollectionRepository()
    collection = await repo.find_one_by({"name": collection_name})
    if not collection:
        raise HTTPException(status_code=404, detail=f"Коллекция '{collection_name}' не найдена")

    condition = "collection_id = %s"
    params = [collection['id']]
    if document_title != 'all':
        condition += " AND document_title = %s"
        params.append(document_title)

    async with mysql_get_db_async() as db:
        # Qdrant хранит document_id (не title) — собираем их для удаления
        await db.execute(
            f"SELECT DISTINCT document_id FROM fact "
            f"WHERE {condition} AND document_id IS NOT NULL AND document_id != ''",
            params
        )
        document_ids = [r['document_id'] for r in await db.fetchall()]

        if not document_ids:
            raise HTTPException(status_code=404, detail="По выбранному фильтру нет фактов с document_id")

        # Помечаем факты несинхронизированными — заново зальет цикл ниже (или крон)
        await db.execute(f"UPDATE fact SET qdrant_synced = 0 WHERE {condition}", params)

    # Удаляем из Qdrant все записи выбранных document_id
    collection_metadata = await ai_fact_collection_metadata_get(collection_name)
    for document_id in document_ids:
        await qdrant_remove_by(collection_name, collection_metadata, {"document_id": document_id})

    # Заново записываем из БД: пачки по 50, стоп при отсутствии прогресса
    report = 'нет несинхронизированных фактов'
    unsynced_before = None
    for _ in range(20):
        async with mysql_get_db_async() as db:
            await db.execute("SELECT COUNT(*) AS qty FROM `fact` WHERE `qdrant_synced` = 0")
            unsynced = (await db.fetchone())['qty']
        if not unsynced:
            break
        if unsynced_before is not None and unsynced >= unsynced_before:
            break
        unsynced_before = unsynced
        report = await ai_fact_qdrant_sync()

    return {"result": {"documents_qty": len(document_ids), "report_str": report}}


@router.get("/fact/collection/list")
async def fact_collection_list(request: Request, db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.FACT_COLLECTION_VIEW]))):
    join_condition = "fc.id = f.collection_id"
    params = []
    if not auth_role_is_full(user.role):
        join_condition += f" AND {FACT_OWNER_CONDITION}"
        params.append(user.user_id)

    async with db:
        await db.execute(f"""
            SELECT fc.*, COUNT(f.id) as fact_count
            FROM fact_collection fc
            LEFT JOIN fact f ON {join_condition}
            GROUP BY fc.id
        """, params)
        return {"result": await db.fetchall()}


@router.get("/fact/collection/{collection_name}/documents")
async def fact_collection_documents(
        request: Request,
        collection_name: str,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.FACT_VIEW]))
):
    role_condition = ""
    params = [collection_name]
    if not auth_role_is_full(user.role):
        role_condition = f" AND {FACT_OWNER_CONDITION}"
        params.append(user.user_id)

    async with db:
        sql = f"""
            SELECT DISTINCT f.document_title
            FROM fact f
            JOIN fact_collection fc ON f.collection_id = fc.id
            WHERE fc.name = %s AND f.document_title IS NOT NULL AND f.document_title != ''{role_condition}
            ORDER BY f.document_title ASC
        """
        await db.execute(sql, params)
        rows = await db.fetchall()
        return {"result": [r["document_title"] for r in rows]}


@router.get("/fact/collection/{collection_name}")
async def fact_list(
        request: Request,
        collection_name: str,
        page: int = 1,
        limit: int = 20,
        query: str = '',
        document_id: str = '',
        document_title: str = '',
        status: str = 'all',
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.FACT_VIEW]))
):
    page = max(1, page)
    limit = max(1, min(100, limit))
    offset = (page - 1) * limit

    params = [collection_name]
    search_condition = ""

    if query:
        search_condition += " AND f.`document` LIKE %s"
        params.append(f"%{query.strip()}%")

    if document_id and document_id != "all":
        search_condition += " AND f.`document_id` = %s"
        params.append(document_id)

    if document_title and document_title != "all":
        search_condition += " AND f.`document_title` = %s"
        params.append(document_title)

    if status == '1':
        search_condition += " AND f.`qdrant_synced` = 1"
    elif status == '0':
        search_condition += " AND f.`qdrant_synced` = 0"

    if not auth_role_is_full(user.role):
        search_condition += f" AND {FACT_OWNER_CONDITION}"
        params.append(user.user_id)

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


@router.put("/fact/{fact_id}")
async def fact_update_endpoint(
    request: Request,
    fact_id: int,
    json_request: dict,
    db=Depends(mysql_get_db_async),
    user=Depends(AuthChecker([AuthPermission.FACT_UPDATE]))
):
    async with db:
        # Check if fact exists
        await db.execute("SELECT id FROM fact WHERE id = %s", (fact_id,))
        fact_exists = await db.fetchone()
        if not fact_exists:
            raise HTTPException(status_code=404, detail="Fact not found")

        # Update the columns that are passed
        update_clauses = []
        params = []
        if "document" in json_request:
            update_clauses.append("`document` = %s")
            params.append(json_request["document"])
        if "category" in json_request:
            update_clauses.append("`category` = %s")
            params.append(json_request["category"])
        if "tags" in json_request:
            update_clauses.append("`tags` = %s")
            params.append(json_request["tags"])

        if update_clauses:
            update_clauses.append("`qdrant_synced` = 0")
            sql = f"UPDATE fact SET {', '.join(update_clauses)} WHERE id = %s"
            params.append(fact_id)
            await db.execute(sql, tuple(params))

        return {"result": {"updated": True, "id": fact_id}}


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
    from logging_.logging_ import logger_info
    from qdrant_.qdrant_ import qdrant_remove_by

    async with db:
        # Сначала получаем информацию о факте для удаления из Qdrant
        sql_fact = """
            SELECT f.*, fc.name as collection_name, fc.field as collection_fields
            FROM `fact` f
            JOIN `fact_collection` fc ON f.`collection_id` = fc.`id`
            WHERE f.`id` = %s
        """
        await db.execute(sql_fact, fact_id)
        fact_entity = await db.fetchone()

        if fact_entity:
            c_name = fact_entity["collection_name"]
            raw_fields_string = fact_entity.get("collection_fields") or ""
            allowed_fields = {f.strip() for f in raw_fields_string.split(',') if f.strip()}
            allowed_fields.add('id')
            allowed_fields.add('document')
            mock_metadata = {field: {"table_name": "fact"} for field in allowed_fields}

            # Пытаемся удалить из Qdrant
            try:
                await qdrant_remove_by(
                    collection_name=c_name,
                    metadata=mock_metadata,
                    metadata_filter={"id": fact_id}
                )
                logger_info(f"Fact {fact_id} successfully removed from Qdrant collection '{c_name}'")
            except Exception as qdrant_err:
                logger_info(f"⚠️ Ошибка при удалении факта {fact_id} из Qdrant: {qdrant_err}")

        # Удаляем из MySQL
        await db.execute("DELETE FROM fact WHERE id = %s", fact_id)
        return {"status": "success", "message": f"Fact {fact_id} deleted"}
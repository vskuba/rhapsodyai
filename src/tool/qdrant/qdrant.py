from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from qdrant_.qdrant_ import qdrant_search, qdrant_remove_by
from src.ai.ai_fact import ai_fact_qdrant_sync
from src.ai.ai_fact_collection import ai_fact_collection_metadata_get


async def qdrant_fact_sync() -> dict:
    """
    Немедленно синхронизирует несинхронизированные факты (qdrant_synced = 0)
    из базы данных в Qdrant, не дожидаясь фоновой синхронизации по расписанию.
    Обрабатывает пачками по 50 до полной синхронизации (максимум 20 пачек за
    вызов); останавливается, если пачка не дает прогресса (ошибки синка).
    Returns:
        A dictionary with the sync report.
        synced_qty (int): Количество синхронизированных фактов за вызов.
        report_str (str): Отчет последней пачки синхронизации.
    """
    report = 'Все факты уже синхронизированы'
    synced_before = None
    unsynced_start = 0

    for batch in range(20):
        async with mysql_get_db_async() as db:
            await db.execute("SELECT COUNT(*) AS qty FROM `fact` WHERE `qdrant_synced` = 0")
            unsynced = (await db.fetchone())['qty']

        if batch == 0:
            unsynced_start = unsynced
        if not unsynced:
            break
        if synced_before is not None and unsynced >= synced_before:
            # Пачка не уменьшила остаток — синхронизация падает, не крутимся впустую
            break

        synced_before = unsynced
        report = await ai_fact_qdrant_sync()

    async with mysql_get_db_async() as db:
        await db.execute("SELECT COUNT(*) AS qty FROM `fact` WHERE `qdrant_synced` = 0")
        unsynced_end = (await db.fetchone())['qty']

    return {
        "synced_qty": max(0, unsynced_start - unsynced_end),
        "report_str": report,
    }


async def qdrant_fact_search(
        query_text: str,
        collection_name: str,
        metadata_filter: str,
        limit: int = 5
) -> str:
    """
    Высокоуровневая обёртка для поиска.
    Автоматически подтягивает метаданные и возвращает только список текстовых фактов.
    Пустой запрос (переменная workflow не заполнена) — пустой ответ, не отказ.
    """
    # ⚠⚠ Незаполненная переменная приходит сюда как `None`, и это **по контракту**:
    # движок берёт значение `variables.get(имя, None)`, а кастование по аннотациям
    # `None` намеренно пропускает как есть (`tools.md`, §8). Значит различать
    # «не передано» и «передано пустым» — работа инструмента, и вот она.
    #
    # ⚠ Цена пропуска измерена. Без этой проверки `None` доезжал до токенизатора
    # внутри `qdrant_search`, и тот отвечал `TextEncodeInput must be
    # Union[TextInputSequence, …]` — сообщение, по которому не найти ни шага, ни
    # переменной. На проде так падал подпоток `girl_fact_invent` каждый раз,
    # когда родитель не передавал ему `prompt_user` (99 попаданий в журнале
    # с 26.09), а весь прогон `dating_talk` обрывался с «Внутренняя ошибка
    # сервера».
    #
    # Пустой ответ, а не отказ: искать факты по пустому запросу нечем, и «ничего
    # не нашлось» — честный итог, с которым workflow идёт дальше. Прежде так и
    # было, пока пустая строка доходила вместо `None`: поиск отрабатывал и
    # возвращал пусто.
    if query_text is None or not str(query_text).strip():
        logger_info(f"🔍 qdrant_fact_search: запрос пуст, искать нечего "
                    f"(коллекция '{collection_name}') — возвращаем пусто")
        return ''

    metadata_filter_json = json_from_string(metadata_filter)
    field_document = 'document'

    if 'tags' in metadata_filter_json:
        # Тот же вид, что при записи (см. `_tags_normalize` в fact_collection_): фильтр
        # сравнивается с payload точным совпадением, поэтому «Hobbies» в запросе обязан
        # стать «hobbies», иначе факт не найдётся. Пустые куски отбрасываем: висячая
        # запятая давала пустой тег, и он не совпадал ни с чем.
        raw_tags = metadata_filter_json['tags']
        if not isinstance(raw_tags, (list, tuple)):
            raw_tags = str(raw_tags or '').split(',')
        metadata_filter_json['tags'] = [t for t in (str(tag).strip().lower() for tag in raw_tags) if t]

    search_results = await qdrant_search(
        query_text=query_text,
        collection_name=collection_name,
        metadata=await ai_fact_collection_metadata_get(collection_name),
        metadata_filter=metadata_filter_json,
        limit=limit
    )

    facts_text_list = []
    for point in search_results:
        if point.payload and field_document in point.payload:
            facts_text_list.append(str(point.payload[field_document]))

    return " ".join(facts_text_list)


async def qdrant_fact_remove(collection_name: str, metadata_filter: str) -> int:
    """
    Удаляет факты из коллекции Qdrant на основе фильтра метаданных.
    """
    metadata_filter_json = json_from_string(metadata_filter)

    return await qdrant_remove_by(collection_name, await ai_fact_collection_metadata_get(collection_name), metadata_filter_json)

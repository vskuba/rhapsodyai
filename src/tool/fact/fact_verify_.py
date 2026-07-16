from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async


async def fact_verify_result_save(fact_id: int, verify_status: str, document_corrected: str = '') -> dict:
    """
    Сохраняет результат фактчека: помечает факт проверенным, при исправлении
    обновляет текст факта и сбрасывает qdrant_synced (пересинк подхватит крон).
     - fact_id: ID проверенного факта
     - verify_status: вердикт проверки: ok | corrected | unverifiable
     - document_corrected: исправленный текст факта (только для verify_status=corrected)
    Returns:
        dict: Словарь с результатом сохранения, содержащий:
            saved (int): 1 - сохранено, 0 - факт не найден или неизвестный статус.
    """
    verify_status = str(verify_status or '').strip().lower()
    if verify_status not in ('ok', 'corrected', 'unverifiable'):
        logger_info(f"⚠️ fact_verify_result_save: неизвестный статус '{verify_status}' (fact {fact_id})")
        return {"saved": 0}

    document_corrected = str(document_corrected or '').strip()

    async with mysql_get_db_async() as db:
        if verify_status == 'corrected' and document_corrected:
            # Исправленный текст + сброс синка: вектор в Qdrant пересоберет существующий крон
            await db.execute(
                """
                UPDATE fact
                SET document = %s, qdrant_synced = 0, verify_status = %s, verified_at = NOW()
                WHERE id = %s
                """,
                (document_corrected, verify_status, int(fact_id))
            )
        else:
            await db.execute(
                "UPDATE fact SET verify_status = %s, verified_at = NOW() WHERE id = %s",
                (verify_status, int(fact_id))
            )
        saved = db.rowcount
        await db.connection.commit()

    logger_info(f"✅ Фактчек: fact {fact_id} -> {verify_status}"
                + (f", текст исправлен: '{document_corrected[:80]}'" if verify_status == 'corrected' else ''))
    return {"saved": 1 if saved else 0}

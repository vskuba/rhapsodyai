from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Журнал запросов держим неделю: этого хватает для метрик от 1 минуты до 7 дней
LLM_REQUEST_TTL_DAYS = 7


async def ai_llm_request_log(
        llm_id: int | None,
        user_id: int | None,
        status_code: int = 200, error: str | None = None,
        duration_ms: int | None = None
):
    """Пишет запрос к LLM в журнал llm_request (метрики страницы /admin/llm).

    Заодно оппортунистически удаляет записи старше LLM_REQUEST_TTL_DAYS
    (порциями, чтобы не блокировать таблицу). Сбой журнала не должен
    ломать сам запрос — только warning в лог."""
    if not llm_id:
        return

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO llm_request (llm_id, user_id, status_code, duration_ms, error) "
                "VALUES (%s, %s, %s, %s, %s)",
                (llm_id, user_id or None, status_code, duration_ms,
                 (error or None) and str(error)[:255])
            )
            await db.execute(
                "DELETE FROM llm_request WHERE created_at < NOW() - INTERVAL %s DAY LIMIT 500",
                (LLM_REQUEST_TTL_DAYS,)
            )
    except Exception as e:
        logger_info(f"⚠️ Не удалось записать llm_request (llm_id={llm_id}): {e}")

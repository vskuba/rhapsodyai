from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

LLM_PROVIDERS = ('openrouter', 'claude', 'ollama', 'gemini', 'groq', 'mistral', 'huggingface', 'cerebras', 'openai')

# Журнал запросов держим неделю: этого хватает для метрик от 1 минуты до 7 дней
LLM_REQUEST_TTL_DAYS = 7


def ai_llm_provider(model_name: str) -> str | None:
    for provider in LLM_PROVIDERS:
        if (model_name or '').lower().startswith(provider + '/'):
            return provider
    return None


async def ai_llm_node_get(node_id: int | None) -> list[dict]:
    """Список LLM ноды (с фоллбэком на catchall-ноду для агентов без своей ноды)."""
    effective_node_id = node_id or await ai_llm_node_id_default_get()

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT l.* FROM `llm` l
            JOIN `node_llm` nl ON l.id = nl.llm_id
            WHERE nl.node_id = %s
            ORDER BY nl.rate_limit_at ASC, nl.position ASC
            """,
            (effective_node_id,)
        )
        return await db.fetchall()


async def ai_llm_node_id_default_get() -> int:
    """Нода-фоллбэк (node.is_catchall=1) для агентов без своей ноды (node_id IS NULL)."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT id FROM `node` WHERE is_catchall = 1 LIMIT 1")
        row = await db.fetchone()
        return row['id'] if row else None


async def ai_llm_request_log(
        llm_id: int | None,
        user_id: int | None,
        node_id: int | None = None,
        status_code: int = 200, error: str | None = None,
        duration_ms: int | None = None
):
    """Пишет запрос к LLM в журнал llm_request (метрики страницы /admin/llm).

    node_id — нода, под которой реально шел запрос: node_llm может делить одну
    модель между несколькими нодами, поэтому фильтр статистики по ноде нужно
    строить по факту запроса, а не по текущему списку моделей ноды.

    Заодно оппортунистически удаляет записи старше LLM_REQUEST_TTL_DAYS
    (порциями, чтобы не блокировать таблицу). Сбой журнала не должен
    ломать сам запрос — только warning в лог."""
    if not llm_id:
        return

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO llm_request (llm_id, user_id, node_id, status_code, duration_ms, error) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (llm_id, user_id or None, node_id or None, status_code, duration_ms,
                 (error or None) and str(error)[:255])
            )
            await db.execute(
                "DELETE FROM llm_request WHERE created_at < NOW() - INTERVAL %s DAY LIMIT 500",
                (LLM_REQUEST_TTL_DAYS,)
            )
    except Exception as e:
        logger_info(f"⚠️ Не удалось записать llm_request (llm_id={llm_id}): {e}")

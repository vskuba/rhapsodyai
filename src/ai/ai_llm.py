import json
from datetime import datetime

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


CHUNK_SIZE_REFRESH_MINUTES = 15
CHUNK_SIZE_TARGET_SECONDS = 10


async def ai_llm_speed_get(llm_id: int | None, target_seconds: int = CHUNK_SIZE_TARGET_SECONDS) -> dict:
    """Returns LLM speed metrics with cached chunk_size.

    chunk_size кешируется в llm.chunk_size (JSON) на CHUNK_SIZE_REFRESH_MINUTES минут.
    Формат: {"10": 15000, "avg_ms": 32000, "chars_per_ms": 1.5, "n": 117}
    Ключ = target_seconds (строка). При истечении кеша или chunk_size_refresh_at=NULL — пересчёт.

    Returns: {'chars_per_ms', 'avg_ms', 'chunk_size', 'n'}
    """
    _default = _ai_llm_speed_default(target_seconds)

    if not llm_id:
        return _default

    # Читаем кеш из llm
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT chunk_size, chunk_size_refresh_at FROM llm WHERE id = %s",
            (llm_id,)
        )
        llm_row = await db.fetchone()

    if llm_row:
        refresh_at = llm_row.get('chunk_size_refresh_at')
        raw = llm_row.get('chunk_size')
        if refresh_at and raw:
            now = datetime.utcnow()
            if isinstance(refresh_at, str):
                try:
                    refresh_at = datetime.fromisoformat(refresh_at)
                except Exception:
                    refresh_at = None
            if refresh_at and now < refresh_at:
                try:
                    cached = json.loads(raw) if isinstance(raw, str) else raw
                    key = str(target_seconds)
                    if key in cached:
                        return {
                            'chars_per_ms': float(cached.get('chars_per_ms') or 1.5),
                            'avg_ms': float(cached.get('avg_ms') or 10000),
                            'chunk_size': int(cached[key]),
                            'n': int(cached.get('n') or 0),
                        }
                except Exception:
                    pass

    # Кеш устарел или отсутствует — пересчитываем
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT
                SUM(CASE WHEN prompt_length > 0 THEN prompt_length ELSE NULL END) /
                    NULLIF(SUM(CASE WHEN prompt_length > 0 THEN duration_ms ELSE NULL END), 0) AS chars_per_ms,
                AVG(duration_ms) AS avg_ms,
                COUNT(*) AS n
            FROM llm_request
            WHERE llm_id = %s AND status_code = 200 AND duration_ms > 0
              AND created_at >= NOW() - INTERVAL 7 DAY
            """,
            (llm_id,)
        )
        row = await db.fetchone()

    avg_ms = float((row or {}).get('avg_ms') or 10000)
    n = int((row or {}).get('n') or 0)
    chars_per_ms_raw = (row or {}).get('chars_per_ms')
    chars_per_ms = float(chars_per_ms_raw) if chars_per_ms_raw else 15000.0 / max(avg_ms, 1)

    chunk_size = max(5000, int(chars_per_ms * target_seconds * 1000 * 0.7))

    # Сохраняем в кеш: мерджим с существующими ключами других target_seconds
    try:
        existing: dict = {}
        if llm_row and llm_row.get('chunk_size'):
            try:
                existing = json.loads(llm_row['chunk_size']) if isinstance(llm_row['chunk_size'], str) else dict(llm_row['chunk_size'])
            except Exception:
                pass
        existing.update({
            str(target_seconds): chunk_size,
            'avg_ms': avg_ms,
            'chars_per_ms': chars_per_ms,
            'n': n,
        })
        async with mysql_get_db_async() as db:
            await db.execute(
                "UPDATE llm SET chunk_size = %s, chunk_size_refresh_at = DATE_ADD(NOW(), INTERVAL %s MINUTE) WHERE id = %s",
                (json.dumps(existing), CHUNK_SIZE_REFRESH_MINUTES, llm_id)
            )
            await db.connection.commit()
    except Exception as e:
        logger_info(f"⚠️ Не удалось обновить chunk_size кеш для llm_id={llm_id}: {e}")

    logger_info(f'📐 chunk_size пересчитан: llm_id={llm_id}, target={target_seconds}s → {chunk_size} симв. (chars/ms={chars_per_ms:.3f}, avg_ms={avg_ms:.0f})')
    return {'chars_per_ms': chars_per_ms, 'avg_ms': avg_ms, 'chunk_size': chunk_size, 'n': n}


def _ai_llm_speed_default(target_seconds: int = CHUNK_SIZE_TARGET_SECONDS) -> dict:
    chunk_size = max(5000, int(1.5 * target_seconds * 1000 * 0.7))
    return {'chars_per_ms': 1.5, 'avg_ms': 10000.0, 'chunk_size': chunk_size, 'n': 0}


async def ai_llm_request_log(
        llm_id: int | None,
        user_id: int | None,
        node_id: int | None = None,
        status_code: int = 200, error: str | None = None,
        duration_ms: int | None = None,
        prompt_length: int | None = None,
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
                "INSERT INTO llm_request (llm_id, user_id, node_id, status_code, duration_ms, prompt_length, error) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (llm_id, user_id or None, node_id or None, status_code, duration_ms,
                 prompt_length or None, (error or None) and str(error)[:255])
            )
            await db.execute(
                "DELETE FROM llm_request WHERE created_at < NOW() - INTERVAL %s DAY LIMIT 500",
                (LLM_REQUEST_TTL_DAYS,)
            )
    except Exception as e:
        logger_info(f"⚠️ Не удалось записать llm_request (llm_id={llm_id}): {e}")

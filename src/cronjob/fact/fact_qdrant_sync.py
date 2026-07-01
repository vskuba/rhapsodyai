import asyncio
from logging_.logging_ import logger_info
from ai.ai_fact import fact_qdrant_sync
from qdrant_.qdrant_ import _qdrant_db_get_client


async def main():
    qdrant_client = None
    try:
        result = await fact_qdrant_sync()
        logger_info(result)
    except Exception as e:
        logger_info(f"Критическая ошибка в процессе синхронизации: {e}")
    finally:
        try:
            qdrant_client = _qdrant_db_get_client()
            if qdrant_client:
                await qdrant_client.close()
                logger_info("Соединение с Qdrant закрыто.")
        except Exception as close_err:
            logger_info(f"Ошибка при закрытии соединения с Qdrant: {close_err}")


if __name__ == '__main__':
    asyncio.run(main())


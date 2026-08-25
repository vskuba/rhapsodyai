import asyncio
from logging_.logging_ import logger_info, logging_init
from src.ai.ai_fact import ai_fact_qdrant_sync
from qdrant_.qdrant_ import _qdrant_db_get_client


async def main():
    logging_init()
    try:
        result = await ai_fact_qdrant_sync()
        logger_info(result)
        print(result)
    except Exception as e:
        logger_info(f"Критическая ошибка в процессе синхронизации: {e}")
        print(f"Критическая ошибка в процессе синхронизации: {e}")
    finally:
        try:
            qdrant_client = _qdrant_db_get_client()
            if qdrant_client:
                await qdrant_client.close()
                logger_info("Соединение с Qdrant закрыто.")
                print("Соединение с Qdrant закрыто.")
        except Exception as close_err:
            logger_info(f"Ошибка при закрытии соединения с Qdrant: {close_err}")
            print(f"Ошибка при закрытии соединения с Qdrant: {close_err}")


if __name__ == '__main__':
    asyncio.run(main())


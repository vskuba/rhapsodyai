import asyncio
from logging_.logging_ import logger_info, logging_init
from dashboard.src.page.journal.journal_install import journal_install_here
from dashboard.src.page.journal.journal_mysql import (journal_mysql_watch_start,
                                      journal_mysql_watch_stop)
from src.ai.ai_fact import ai_fact_qdrant_sync
from qdrant_.qdrant_ import _qdrant_db_get_client


async def main():
    logging_init()
    # Ошибки кронджоба — в общий журнал установки (страница «Журнал»,
    # /admin/journal): он живёт минуту в отдельном процессе, и его отказ
    # иначе теряется вместе с этим процессом.
    journal_install_here('cronjob')
    # Счёт запросов к базе — подвкладка «MySQL» той же страницы. Сбрасывает
    # его `journal_mysql_watch_stop` перед выходом: процесс короткий.
    await journal_mysql_watch_start('cronjob')
    try:
        result = await ai_fact_qdrant_sync()
        logger_info(result)
        print(result)
    except Exception as e:
        logger_info(f"Критическая ошибка в процессе синхронизации: {e}")
        print(f"Критическая ошибка в процессе синхронизации: {e}")
    finally:
        # Счёт запросов за этот заход — в подвкладку «MySQL»: процесс короткий,
        # и без сброса его работа пропала бы вместе с ним.
        await journal_mysql_watch_stop()
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


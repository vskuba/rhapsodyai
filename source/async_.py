import asyncio
from source.logging_ import logger_info

async_loop: asyncio.AbstractEventLoop | None = None
waiting_event: asyncio.Event | None = None
async_loop_task = None


def async_loop_init(loop: asyncio.AbstractEventLoop, loop_task):
    global async_loop, waiting_event, async_loop_task
    async_loop = loop
    waiting_event = asyncio.Event()
    async_loop_task = loop_task


async def async_waiting_start():
    if waiting_event:
        logger_info('Асинхронноее ожидание: включаем')
        waiting_event.clear()
        await waiting_event.wait()


def async_waiting_clear():
    if async_loop and waiting_event:
        logger_info('Асинхронноее ожидание: сброс флага')
        async_loop.call_soon_threadsafe(waiting_event.set)


def async_waiting_is_active() -> bool:
    if waiting_event:
        logger_info('Асинхронноее ожидание: активно')
        return not waiting_event.is_set()
    logger_info('Асинхронноее ожидание: не активно')
    return False


def async_loop_task_cancel():
    global async_loop, async_loop_task
    async_loop.call_soon_threadsafe(async_loop_task.cancel)

import asyncio

async_loop: asyncio.AbstractEventLoop | None = None
waiting_event: asyncio.Event | None = None


def async_loop_init(loop: asyncio.AbstractEventLoop):
    global async_loop, waiting_event
    async_loop = loop
    waiting_event = asyncio.Event()


async def async_waiting_start():
    if waiting_event:
        print('Асинхронноее ожидание: включаем')
        waiting_event.clear()
        await waiting_event.wait()


def async_waiting_clear():
    if async_loop and waiting_event:
        print('Асинхронноее ожидание: сброс флага')
        async_loop.call_soon_threadsafe(waiting_event.set)


def async_waiting_is_active() -> bool:
    if waiting_event:
        print('Асинхронноее ожидание: активно')
        return not waiting_event.is_set()
    print('Асинхронноее ожидание: не активно')
    return False

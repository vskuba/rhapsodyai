import threading
import asyncio

from typing import Callable
from state.state import state_get


def thread_with_callback(init_func: Callable, callback_func: Callable):
    def thread_target():
        result = None
        try:
            result = asyncio.run(init_func())
        except Exception as e:
            print(f"❌ Ошибка в потоке парсера: {e}")
            result = e
        finally:
            state_get('window').after(100, lambda: callback_func(result))

    threading.Thread(target=thread_target, daemon=True).start()
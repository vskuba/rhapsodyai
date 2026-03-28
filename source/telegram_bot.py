import asyncio
import queue

from aiogram import Bot, Dispatcher, types

from source.ai.framework.pydanticai.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from source.config import config_get
from source.queue_ import queue_get


async def init_telegram_bot(agent_name: str):
    bot = Bot(token=config_get('telegram_token'))
    dp = Dispatcher()
    queues = queue_get()

    @dp.message()
    async def handle_message(message: types.Message):

        framework_model = AiFrameworkAgentManagerPydantic().load(agent_name)
        framework_model.chat_id = message.chat.id
        framework_model.prompt = message.text

        queues['agent'].put(framework_model)

    async def response_message():
        while True:
            response = {}
            try:
                response = queue_get()['telegram_response'].get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)

            if response:
                text = response.get('text')
                framework_model = response.get('framework_model')
                await bot.send_message(chat_id=framework_model.chat_id, text=text)

    # Запускаем рассыльщик ответов фоном
    asyncio.create_task(response_message())

    # Запускаем бесконечный поллинг
    await dp.start_polling(bot, handle_signals=False)
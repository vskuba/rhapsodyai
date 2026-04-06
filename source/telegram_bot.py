import asyncio
import queue
from functools import partial

from aiogram import Bot, Dispatcher, types

from source.ai.framework.pydanticai.ai_framework_agent_manager_pydantic import AiFrameworkAgentManagerPydantic
from source.ai.framework.pydanticai.ai_framework_agent_model_pydantic import AiFrameworkAgentModelPydantic
from source.config import config_get
from source.faster_whisper_ import faster_whisper_create_model
from source.logging_ import logger_info
from source.queue_ import queue_get

agent_manager = AiFrameworkAgentManagerPydantic()

async def init_telegram_bot(agent_name: str):
    bot = Bot(token=config_get('telegram_token'))
    dp = Dispatcher()
    queues = queue_get()

    @dp.message()
    async def handle_message(message: types.Message):
        user_text = ""

        # 1. Если это текст
        if message.text:
            user_text = message.text

        # 2. Если это голосовое сообщение
        elif message.voice:
            # Скачиваем файл во временный буфер или файл
            file_id = message.voice.file_id
            file = await message.bot.get_file(file_id)

            # Скачиваем файл (нужен путь, куда сохранить, например 'voice.ogg')
            file_path = f"temp_{file_id}.ogg"
            await message.bot.download_file(file.file_path, file_path)

            # Конвертируем голос в текст через faster-whisper
            # (Предполагается, что модель whisper инициализирована заранее)
            segments, info = faster_whisper_create_model(config_get('whisper_model_name')).transcribe(file_path, beam_size=5)
            user_text = " ".join([segment.text for segment in segments])

            logger_info(f"Распознанный текст: {user_text}")

        logger_info(f'Пришло сообщение из телеграм бота "{agent_name}": "{user_text}"')
        framework_model = agent_manager.load(agent_name)
        framework_model.chat_id = message.chat.id
        framework_model.prompt = user_text
        framework_model.is_gui_mode = False

        async def on_complete(response_text: str, framework_model: AiFrameworkAgentModelPydantic):
            queue_get()['telegram_response'].put({"text": response_text, "framework_model": framework_model})

        framework_model.on_complete = partial(on_complete, framework_model=framework_model)

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
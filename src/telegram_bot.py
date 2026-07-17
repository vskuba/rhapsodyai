import asyncio
import queue

from functools import partial
from aiogram import Bot, Dispatcher, types

from config.config import config_get
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.ai.framework.agent.ai_framework_model import AiFrameworkAgentModel
from src.faster_whisper.faster_whisper_model import faster_whisper_create_model
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from queue_.queue_ import queue_get
from src.mysql_.repository.agent_repository import AgentRepository

agent_manager = AiFrameworkAgentManager()

# Пользователь-владелец телеграм-бота: его очередь LLM используется для ответов
TELEGRAM_BOT_USER_ID = 1

async def init_telegram_bot(agent_name: str):
    bot = Bot(token=config_get('TELEGRAM_TOKEN'))
    dp = Dispatcher()

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

            segments, info = faster_whisper_create_model().transcribe(
                file_path,
                beam_size=5,
                best_of=5,
                language=None,
                condition_on_previous_text=False
            )
            user_text = " ".join([segment.text for segment in segments])

            logger_info(f"Распознанный текст: {user_text}")

        logger_info(f'Пришло сообщение из телеграм бота "{agent_name}": "{user_text}"')

        repo = AgentRepository()
        entity = await repo.find_one_by({"name": agent_name})

        # LLM-очередь пользователя-владельца бота: без entities_llm
        # у модели нет активной LLM и запрос падает
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                SELECT l.* FROM `llm` l
                JOIN `user_llm` ul ON l.id = ul.llm_id
                WHERE ul.user_id = %s
                ORDER BY ul.rate_limit_at ASC, ul.position ASC
                """,
                (TELEGRAM_BOT_USER_ID,)
            )
            entities_llm = await db.fetchall()

        framework_model = await agent_manager.framework_model_create({
            "entity_agent": entity,
            "entities_llm": entities_llm,
            "user_id": TELEGRAM_BOT_USER_ID,
        })
        framework_model.chat_id = message.chat.id
        framework_model.prompt_user = user_text
        framework_model.is_gui_mode = False

        async def on_complete(response_text: str, framework_model: AiFrameworkAgentModel):
            queue_get('telegram_response').put({"text": response_text, "framework_model": framework_model})

        framework_model.on_complete = partial(on_complete, framework_model=framework_model)

        # Модели обрабатывает фоновый цикл ai_thread_framework_run (очередь ai_framework_model)
        queue_get('ai_framework_model').put(framework_model)

    async def response_message():
        while True:
            response = {}
            try:
                response = queue_get('telegram_response').get_nowait()
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
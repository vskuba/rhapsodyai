import httpx

from config.config import config_get
from logging_.logging_ import logger_info


async def telegram_notify_send_owner(text: str):
    """
    Отправляет сообщение владельцу бота напрямую через Telegram Bot API (HTTP,
    без aiogram - в процессе uvicorn эта библиотека не установлена, она нужна
    только процессу main_telegram.py). Используется из uvicorn, который не
    запускает main_telegram.py и не может положить ответ в его in-memory очереди.
    """
    owner_chat_id = config_get('TELEGRAM_OWNER_CHAT_ID')
    bot_token = config_get('TELEGRAM_TOKEN_RHAPSODY')
    if not owner_chat_id or not bot_token:
        logger_info('⚠️ TELEGRAM_OWNER_CHAT_ID/TELEGRAM_TOKEN не заданы, уведомление в Telegram пропущено')
        return

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f'https://api.telegram.org/bot{bot_token}/sendMessage',
            json={'chat_id': int(owner_chat_id), 'text': text}
        )

    if response.status_code != 200:
        logger_info(f'❌ Не удалось отправить Telegram-уведомление владельцу: {response.status_code} {response.text}')


async def telegram_notify_bot_setup():
    """
    Настраивает кнопку Mini App в чате владельца для бота уведомлений
    (TELEGRAM_TOKEN_RHAPSODY). Этот бот не поллит сообщения (нет Dispatcher) -
    поэтому настройка через голый HTTP, а не aiogram. Идемпотентно, безопасно
    вызывать при каждом старте uvicorn.
    """
    owner_chat_id = config_get('TELEGRAM_OWNER_CHAT_ID')
    bot_token = config_get('TELEGRAM_TOKEN_RHAPSODY')
    mini_app_url = config_get('TELEGRAM_MINI_APP_URL')
    if not (owner_chat_id and bot_token and mini_app_url):
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f'https://api.telegram.org/bot{bot_token}/setChatMenuButton',
                json={
                    'chat_id': int(owner_chat_id),
                    'menu_button': {'type': 'web_app', 'text': 'Панель', 'web_app': {'url': mini_app_url}}
                }
            )
        if response.status_code != 200:
            logger_info(f'❌ Не удалось настроить кнопку Mini App: {response.status_code} {response.text}')
    except Exception as e:
        logger_info(f'⚠️ telegram_notify_bot_setup: не удалось подключиться к Telegram API: {e}')

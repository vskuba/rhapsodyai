import json

from event_.event_ import Event, event_subscribe
from src.mysql_.repository.event_log_repository import EventLogRepository
from src.telegram_.telegram_notify import telegram_send_owner


def event_handlers_register():
    event_subscribe('user.login', _event_log_persist)
    event_subscribe('user.login', _telegram_notify_login)


async def _event_log_persist(event: Event):
    repo = EventLogRepository()
    await repo.add({
        'type': event.type,
        'payload': json.dumps(event.payload, ensure_ascii=False),
    })


async def _telegram_notify_login(event: Event):
    username = event.payload.get('username', '?')
    role = event.payload.get('role', '?')
    # Логины admin не шлем в Telegram - это сам владелец бота, уведомление о
    # себе самом только шумит; интересны входы остальных пользователей
    if role == 'admin':
        return
    await telegram_send_owner(f"🔐 Пользователь \"{username}\" ({role}) залогинился в систему")

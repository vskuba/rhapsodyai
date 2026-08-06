import json

from event_.event_ import Event, event_subscribe
from src.auth.auth_role import auth_role_is_full
from src.mysql_.repository.event_log_repository import EventLogRepository
from src.telegram_.telegram_notify import telegram_send_owner


def event_handlers_register():
    event_subscribe('user.login', _event_log_persist)
    event_subscribe('user.login', _telegram_notify_login)


async def _event_log_persist(event: Event):
    repo = EventLogRepository()
    payload = dict(event.payload)
    payload['event_type'] = event.type
    await repo.add({
        'type': 'system',
        'payload': json.dumps(payload, ensure_ascii=False),
    })


async def _telegram_notify_login(event: Event):
    username = event.payload.get('username', '?')
    role = event.payload.get('role', '?')
    # Логины полноправных ролей не шлём в Telegram: `admin` — это сам владелец бота,
    # а `qa` логинится на каждом тесте (десятки раз за прогон) — в обоих случаях
    # уведомление только шумит; интересны входы остальных пользователей
    if auth_role_is_full(role):
        return
    await telegram_send_owner(f"🔐 Пользователь \"{username}\" ({role}) залогинился в систему")

import json

from event_.event_ import Event, event_subscribe
from src.auth.auth_role import auth_role_is_full
from src.mysql_.repository.event_log_repository import EventLogRepository
from src.telegram_.telegram_notify import telegram_notify_send_owner


def event_handlers_register():
    event_subscribe('user.login', _event_log_persist)
    # ⚠ Уведомление о входе в Telegram **отключено**: подписки нет, сам
    # обработчик оставлен — см. оговорку у `_telegram_notify_login`.


async def _event_log_persist(event: Event):
    repo = EventLogRepository()
    payload = dict(event.payload)
    payload['event_type'] = event.type
    await repo.add({
        'type': 'system',
        'payload': json.dumps(payload, ensure_ascii=False),
    })


async def _telegram_notify_login(event: Event):
    """Уведомление о входе в Telegram. ⚠⚠ **Сейчас не подписан ни на что.**

    Отключён 23 сентября: уведомления о логине шумели без пользы. Отсев по роли
    внизу оставлял входы обычных пользователей, но и они оказались не нужны —
    вход в панель это не событие, о котором будят владельца бота.

    ⚠ **Функция оставлена, а не удалена.** Включить обратно — одна строка в
    `event_handlers_register`; удали мы её, вернуть пришлось бы вместе с отсевом
    ролей, а он куплен опытом: `qa` логинится на каждом тесте, десятки раз за
    прогон.

    ⚠ Журнал входов при этом **остаётся**: его пишет `_event_log_persist`, и он
    по-прежнему подписан. Отключено уведомление, а не запись события.
    """
    username = event.payload.get('username', '?')
    role = event.payload.get('role', '?')
    # Логины полноправных ролей не шлём в Telegram: `admin` — это сам владелец бота,
    # а `qa` логинится на каждом тесте (десятки раз за прогон) — в обоих случаях
    # уведомление только шумит; интересны входы остальных пользователей
    if auth_role_is_full(role):
        return
    await telegram_notify_send_owner(f"🔐 Пользователь \"{username}\" ({role}) залогинился в систему")

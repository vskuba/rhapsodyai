"""
Переменные `.env`, которые отдаются фронтенду.

Список один, а эндпоинта два: `/setting/config` для админки (право `setting:view`) и
`/telegram-app/config` для Mini App (доступ по `telegram_owner_id` в сессии). Так вышло
потому, что и способов авторизации два, и они несовместимы: Mini App обычной сессии с
ролью не заводит — вход через `/telegram-app/auth` кладёт в сессию только id владельца,
и `AuthChecker` такого посетителя не пропускает.

До появления второго эндпоинта Mini App получал от `/setting/config` отказ
«Not authenticated», а `config.js` в этом случае кэширует пустой словарь — и кэширует
навсегда, до перезагрузки страницы. То есть конфиг в Mini App не работал вообще, ни
разу. Заметно это не было по случайности: обе кнопки, которые его читают, имеют
запасной адрес прямо в коде и молча уходили на него.

Секретам здесь не место: всё, что вернёт функция, видно в DevTools любому, кто открыл
страницу.
"""
import os

# Ключ наружу → имя переменной в `.env`. Имена расходятся у тех, что заведены с
# префиксом `TELEGRAM_`: фронтенду он не нужен, там и так всё про Mini App.
SETTING_CONFIG_PUBLIC_KEYS = {
    'SITE_LOGIN_REMOTE_URL': 'TELEGRAM_SITE_LOGIN_REMOTE_URL',
    'SITE_LOGIN_LOCAL_URL':  'TELEGRAM_SITE_LOGIN_LOCAL_URL',
    'DEEPSEEK_HARNESS_GX10': 'DEEPSEEK_HARNESS_GX10',
}


def setting_config_public() -> dict:
    """Значения `.env` для фронтенда: `{ключ: значение}`, незаданное — пустой строкой."""
    return {key: os.getenv(env_name, '') for key, env_name in SETTING_CONFIG_PUBLIC_KEYS.items()}

# Settings — конфигурация системы

> Настройки хранятся в таблице `setting` со скоупами (общая / нодовая / пользовательская).
> Отдельно есть endpoint `/setting/config` — публикует часть переменных `.env` для фронтенда.

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `py_modules/setting_/setting_.py` | `setting_get()` / `setting_set()` / `setting_delete()` — доступ к таблице |
| `src/uvicorn/routers/setting/setting.py` | REST API настроек + `/setting/config` |
| `src/uvicorn/routers/dashboard.py` | Роут страницы `/admin/setting` |
| `data/uvicorn/template/admin/setting.html` | Страница настроек |
| `data/uvicorn/public/js/setting.js` | JS страницы настроек |
| `data/uvicorn/public/js/telegram_app/config.js` | Клиент `/setting/config` для Mini App |

## Таблица `setting`

```sql
CREATE TABLE `setting` (
    `id`      INT AUTO_INCREMENT PRIMARY KEY,
    `key`     CHAR(50) NOT NULL,
    `user_id` INT DEFAULT NULL,       -- скоуп: пользователь
    `node_id` INT DEFAULT NULL,       -- скоуп: нода
    `value`   LONGTEXT NOT NULL,
    `dynamic` TINYINT NOT NULL DEFAULT 0
);
ALTER TABLE setting ADD UNIQUE INDEX idx_key_user (`key`, user_id, node_id);
```

Скоупы:

| `user_id` | `node_id` | Значение |
|-----------|-----------|----------|
| NULL | NULL | общая настройка |
| NULL | задан | переопределение для ноды |
| задан | NULL | настройка пользователя |

`dynamic = 1` — значение записано кодом в рантайме (счётчики, служебное состояние);
такие строки не показываются на странице настроек.

Уникальный индекс не ловит дубли при `NULL` в скоуп-колонках, поэтому `setting_set()`
делает свой upsert (`UPDATE`, затем `INSERT` при `rowcount = 0`).

## Python API

```python
from py_modules.setting_.setting_ import setting_get, setting_set, setting_delete

tz = await setting_get('timezone', '+0')                    # общая настройка + default
limit = await setting_get('llm_parallel_per_agent_max', 3, node_id=9)
await setting_set('timezone', '+3')
await setting_set('runner_state', 'busy', dynamic=1)        # служебное значение
await setting_delete('timezone', node_id=9)                 # вернуть ноду к общему значению
```

## REST API

Роутер подключён без префикса (`main_uvicorn.py`), пути — как ниже.

| Метод | Путь | Права | Назначение |
|-------|------|-------|-----------|
| GET | `/setting/list` | `setting:view` | Общие и нодовые настройки (без `dynamic = 1`) |
| POST | `/setting` | `setting:update` | Upsert; пустой `value` удаляет запись |
| DELETE | `/setting/key/{key}` | `setting:update` | Удалить настройку целиком (общее + все нодовые) |
| GET | `/setting/{key}/user/{user_id}` | `setting:view` | Значение настройки пользователя |
| POST | `/setting/{key}/user/{user_id}` | `setting:update` | Записать настройку пользователя |
| GET | `/setting/config` | `setting:view` | Конфиг для фронтенда (значения из `.env`) |

Тело `POST /setting`:

```json
{ "key": "timezone", "value": "+3", "node_id": null }
```

Пустой `value` в этом запросе означает удаление: нодовая ячейка возвращается
к общему значению.

Страница `/admin/setting` требует только авторизации (`require_auth`), права
проверяются на уровне API.

## `/setting/config` — переменные для фронтенда

```python
@router.get("/setting/config")
async def setting_config_route(request: Request, user=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    return {
        "result": {
            "SITE_LOGIN_REMOTE_URL": os.getenv("TELEGRAM_SITE_LOGIN_REMOTE_URL", ""),
            "SITE_LOGIN_LOCAL_URL": os.getenv("TELEGRAM_SITE_LOGIN_LOCAL_URL", ""),
        }
    }
```

Соответствующие переменные `.env`:

```bash
TELEGRAM_SITE_LOGIN_REMOTE_URL=https://your-domain.com   # продакшен
TELEGRAM_SITE_LOGIN_LOCAL_URL=http://localhost:8011      # разработка
```

Это не таблица `setting`, а проброс `.env` в браузер. Секреты сюда не попадают:
всё, что возвращает endpoint, видно в DevTools.

### JS-клиент (`telegram_app/config.js`)

```javascript
import { loadConfig, getConfig, isConfigLoaded, getAllConfig, resetConfig } from './config.js';

await loadConfig();                                  // один fetch, дальше из кэша
const url = getConfig('SITE_LOGIN_REMOTE_URL', '');  // второй аргумент — default
```

`loadConfig()` дедуплицирует параллельные вызовы (общий `_loadPromise`) и при
ошибке сети кладёт в кэш `{}`, не бросая исключение. `resetConfig()` нужен тестам.

## Добавление новой переменной в `/setting/config`

1. Добавить переменную в `.env` (и на проде — через secret `ENV_FILE`, иначе деплой её сотрёт).
2. Добавить ключ в `dict` внутри `setting_config_route()`.
3. Читать во фронтенде через `getConfig('KEY')` — правки в `config.js` не нужны.
4. Перезапустить uvicorn: `docker restart uvicorn`.

## Права

```python
# src/auth/auth_permission.py
SETTING_VIEW = "setting:view"
SETTING_UPDATE = "setting:update"
```

`SETTING_VIEW` входит в `AUTH_PERMISSIONS_DEFAULT` — доступен любой роли.
`SETTING_UPDATE` есть только у полноправных ролей (`admin`, `qa`).
Детали модели прав — `auth.md`.

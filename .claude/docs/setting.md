# Settings — конфигурация системы

> Настройки хранятся в таблице `setting` со скоупами (общая / нодовая / пользовательская).
> Отдельно есть endpoint `/api/setting/config` — публикует часть переменных `.env` для фронтенда.

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `py_modules/setting_/setting_.py` | `setting_get()` / `setting_set()` / `setting_delete()` — доступ к таблице |
| `src/uvicorn/routers/setting/setting.py` | REST API настроек + `/api/setting/config` |
| `src/uvicorn/routers/dashboard.py` | Роут страницы `/admin/setting` |
| `dashboard/template/admin/setting.html` | Страница настроек |
| `data/uvicorn/public/js/setting.js` | JS страницы настроек |
| `data/uvicorn/public/js/telegram_app/config.js` | Клиент `/api/setting/config` для Mini App |

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

### `timezone` — пояс показа, а не хранения

Настройка `timezone` (`'+3'`) отвечает на один вопрос: в каком поясе человек читает
метки времени. Хранится время в UTC — и в базе, и в приложении, контейнеры живут по
UTC.

Отсюда правило: **всё, что уходит человеку, сдвигается перед показом.** Помощники —
в `py_modules/datetime_/datetime_.py`:

```python
offset = await setting_get('timezone', '+0')                 # один раз на список
shown  = datetime_offset_apply(row['created_at'], offset)    # хранимое UTC → пояс показа
one    = await datetime_local(row['created_at'])             # разовый показ, смещение само
now    = await datetime_now()                                # «сейчас» в поясе настройки
```

Полное правило со всеми ловушками — `.claude/docs-common/datetime_rules.md`: там же
про сравнение свежести (обе стороны обязаны быть из одного источника) и про колонки,
которые фронтенд переводит сам и потому пишутся строго в UTC.

## REST API

Роутер подключён без префикса (`main_uvicorn.py`), пути — как ниже.

| Метод | Путь | Права | Назначение |
|-------|------|-------|-----------|
| GET | `/api/setting` | `setting:view` | Общие и нодовые настройки (без `dynamic = 1`) |
| POST | `/setting` | `setting:update` | Upsert; пустой `value` удаляет запись |
| DELETE | `/api/setting/{key}` | `setting:update` | Удалить настройку целиком (общее + все нодовые) |
| GET | `/setting/{key}/user/{user_id}` | `setting:view` | Значение настройки пользователя |
| POST | `/setting/{key}/user/{user_id}` | `setting:update` | Записать настройку пользователя |
| GET | `/api/setting/config` | `setting:view` | Конфиг для фронтенда (значения из `.env`) |

Тело `POST /setting`:

```json
{ "key": "timezone", "value": "+3", "node_id": null }
```

Пустой `value` в этом запросе означает удаление: нодовая ячейка возвращается
к общему значению.

Страница `/admin/setting` требует только авторизации (`dashboard_require_auth`), права
проверяются на уровне API.

## Таймауты конвейера — `task_setting_timeout.py`

Таймауты конвейера задач раньше были константами в модулях (`TASK_WORKER_JOB_TIMEOUT`,
`LOCK_TIMEOUT_SEC`, `CLAUDE_SHELL_TIMEOUT`, `MAX_ATTEMPTS`…). Теперь это строки таблицы
`setting` с реестром в `src/project/task/task_setting_timeout.py` и редактором на карточках
`/admin/team`. Значение читается в момент ожидания, поэтому правка работает без
перезапуска контейнеров.

| Ключ | Умолчание | Что обрывает |
|------|-----------|--------------|
| `timeout_manager_run` | 6400 с | прогон агента Manager |
| `timeout_developer_run` | 14400 с | прогон агента Developer, включая круги доработки |
| `timeout_qa_run` | 7400 с | прогон агента QA |
| `timeout_bugfix_run` | 7400 с | прогон агента Bugfixer |
| `timeout_shell_call` | 300 с | вызов `claude_shell_call` целиком |
| `timeout_shell_ack` | 120 с | подтверждение доставки сообщения оболочке |
| `timeout_shell_busy` | 300 с | ожидание, пока агент освободится |
| `timeout_shell_stale` | 30 с | пинг оболочки, после которого её считают мёртвой |
| `timeout_restart_ack` | 60 с | приём маркера перезапуска watch |
| `timeout_restart_settle` | 10 с | пауза перед опросом готовности после перезапуска |
| `timeout_restart_ready` | 180 с | ожидание поднявшегося агента |
| `timeout_worker_job` | 3900 с | job воркера в rq (дефолт rq — 180 с!) |
| `timeout_task_lock` | 4200 с | когда блокировку строки считают протухшей |
| `timeout_ping_stale` | 30 с | свежесть карточки команды и живой роли |
| `timeout_retry_max` | 3 раза | перезапусков агента на одном прогоне |
| `timeout_attempt_max` | 3 раза | попыток одной задачи в конвейере |

```python
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_WORKER_JOB,
    task_setting_timeout_get)

seconds = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_WORKER_JOB)  # значение или умолчание
items = await task_setting_timeout_all()                    # весь реестр одним запросом
await task_setting_timeout_set('timeout_worker_job', 4000)  # ValueError вне границ
```

Реестр — единственный список правимых ключей: чужой ключ через API не пролезет, иначе
страница команды стала бы редактором произвольных настроек. Значение из ячейки читается
терпимо (`_value_normalize`): пустая строка, буквы или число вне границ дают умолчание,
опечатка человека не роняет ожидание.

Лестница «прогон агента < job воркера < блокировка строки» проверяется
`task_setting_timeout_ladder_problem()` и только показывается предупреждением на карточке.
Запретить нельзя: поднять все три значения разом одним запросом не получится, и
промежуточное нарушение законно.

API — в `project_team.py`: `GET /api/team/timeout` (весь реестр + `problem`),
`POST /api/team/timeout` (`{key, value}`, 422 на неизвестный ключ и выход за границы).

## `/api/setting/config` — переменные для фронтенда

```python
@router.get("/setting/config")
async def setting_config_route(request: Request, user=Depends(AuthChecker([AuthPermission.SETTING_VIEW]))):
    return {
        "result": {
            "SITE_LOGIN_REMOTE_URL": os.getenv("TELEGRAM_SITE_LOGIN_REMOTE_URL", ""),
            "SITE_LOGIN_LOCAL_URL": os.getenv("TELEGRAM_SITE_LOGIN_LOCAL_URL", ""),
            "DEEPSEEK_HARNESS_GX10": os.getenv("DEEPSEEK_HARNESS_GX10", ""),
        }
    }
```

Соответствующие переменные `.env`:

```bash
TELEGRAM_SITE_LOGIN_REMOTE_URL=https://your-domain.com   # продакшен
TELEGRAM_SITE_LOGIN_LOCAL_URL=http://localhost:8011      # разработка
DEEPSEEK_HARNESS_GX10=http://host:port                   # иконка 🐋 в меню Mini App
```

> Имя ключа наружу совпадает с именем переменной, если у той нет префикса
> `TELEGRAM_`: тот префикс отрезается (`TELEGRAM_SITE_LOGIN_LOCAL_URL` →
> `SITE_LOGIN_LOCAL_URL`), а `DEEPSEEK_HARNESS_GX10` уходит как есть — переменная
> заведена под этим именем и читается не только Mini App'ом.

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

## Добавление новой переменной в `/api/setting/config`

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

## `journal_mysql_enabled` — счёт запросов к базе

Выключатель подвкладки «MySQL» на `/admin/journal`: считать ли запросы к базе.
Умолчание `1`; гасят `0`, `false`, `no`, `off` и пустое значение. Строку заводит
миграция `20260929133434_setting_journal_mysql.sql`.

Настройкой, а не переменной окружения, по той же причине, что и таймауты конвейера:
счёт включают ровно тогда, когда что-то тормозит, — на живой установке и без захода в
конфиги. Переменной `MYSQL_WATCH_ENABLED` выключатель побыл один коммит: на проде её
пришлось бы класть через secret `ENV_FILE` (иначе сотрёт деплой), а погасить счёт —
правкой конфига с перезапуском контейнеров.

**Правка действует через полминуты, без перезапуска.** Такт сброса
(`journal_mysql_flush_forever`) перечитывает настройку на каждом обороте: сбрасывает
накопленное, затем сверяет состояние счётчика с настройкой. Короткие процессы —
воркеры и кронджобы — читают её на старте своего захода.

⚠ Скоуп только общий. Ячейка ноды здесь бессмысленна: запросы к базе шлёт процесс, а
не узел LLM.

Механика — `dashboard/src/page/journal/journal_mysql.py`, устройство подвкладки — `journal.md`, §8.

## `gx10_autocompact_limit` — порог автосжатия контекста

Значение флага `--autocompact` в командах запуска ролевых оболочек. Claude Code,
упершись в окно модели, сжимает разговор и продолжает работать по пересказу; эта
настройка говорит, на каком объёме начинать.

Умолчание — `115k`. Окно модели GX10 — 131072 токена, и 115k оставляет запас под
ответ до этой границы. Допустимо число токенов (`115k`, `120000`, `2m`) либо
`auto`; мусор молча откатывается к умолчанию — Claude Code на непонятном значении
не стартует вовсе, и роль просто не поднялась бы.

**Подставляется при показе карточки** на `/admin/team`, а не при её заведении.
Команда лежит в `project_team.command` и переживает правку настройки: подставь мы
значение один раз — смена настройки не дошла бы до уже созданных карточек, и
человек копировал бы кнопкой старое число.

Отсюда следствие: правка видна сразу, но **действует со следующего запуска
оболочки**. Работающая роль свой флаг получила при старте.

Куда смотреть при подборе: вкладка «Статистика» на `/admin/task`. Признак того,
что сжатие случилось посреди работы, — несоразмерно большое число токенов на
коротком шаге (шаг отчёта на 17 тысяч токенов вместо двухсот).

Механика — `src/project/team/team_setting_autocompact.py`.

# Quick Start — запуск и разработка

> Всё крутится в Docker Compose. Приложение не запускается с хоста напрямую:
> в `.env` хостнеймы контейнерные (`MYSQL_HOST=mysql`, `REDIS_URL=redis://redis:6379`).

## Структура

| Путь | Содержимое |
|------|-----------|
| `main_uvicorn.py` | FastAPI/Uvicorn — Web API + HTML-фронтенд |
| `main_telegram.py` | Telegram-бот |
| `py_modules/` | Переиспользуемые библиотеки (не знают про `src/`) |
| `src/` | Код приложения |
| `tests/` | pytest-сьюита (ходит по HTTP в запущенный uvicorn) |

Правила размещения кода — `architecture_rules.md`.

## Запуск

```bash
# Весь стек
docker-compose up -d

# Минимум для работы над веб-частью
docker-compose up -d mysql redis qdrant uvicorn

# Состояние и логи
docker-compose ps
docker-compose logs -f uvicorn
```

Миграции и seed применяются автоматически в `lifespan()` при старте uvicorn
(`mysql_migration_up()` → `mysql_seed_up()`).

**После правки `.py` — перезапуск обязателен:**

```bash
docker restart uvicorn
```

Правки шаблонов (`data/uvicorn/template/`) и статики (`data/uvicorn/public/`)
подхватываются без перезапуска.

## Порты

| Сервис | Хост | Внутри | Примечание |
|--------|------|--------|-----------|
| uvicorn | 8011 | 8000 | основной сервер |
| uvicorn_green | 8012 | 8000 | profile `green`, blue-green деплой |
| mysql | 3302 | 3306 | в `.env` порт 3306 — он контейнерный |
| phpmyadmin | 9634 | 80 | |
| redis | — | 6379 | наружу не публикуется |
| rq-dashboard | 9181 | 9181 | очереди |
| qdrant | 6333 / 6334 | | UI: `:6333/dashboard` |
| opensearch | 9200 / 9600 | | |
| opensearch-dashboards | 5601 | | |
| cronicle | 3012 | | планировщик |
| gatus | 8090 | 8080 | health-мониторинг |
| caddy | 80 / 443 | | profile `on_prod_only` |

Профили: `telegram` и `caddy` — только `on_prod_only`, `uvicorn_green` — `green`.

## Тесты

Сьюита интеграционная: ей нужен поднятый uvicorn на `localhost:8011`
и заполненный seed (тесты опираются на агента id=9 `dating_bot`).

```bash
.venv/bin/python3 -m pytest tests/ -v
.venv/bin/python3 -m pytest tests/test_setting_crud.py -v
.venv/bin/python3 -m pytest tests/ -v -s          # с логами
```

Конфиг — `[tool.pytest.ini_options]` в `pyproject.toml`: `asyncio_mode = "auto"`,
`pythonpath = [".", "py_modules"]`.

Логинятся все тесты одной QA-учёткой (`tests/constants.py`), поэтому нужны:

```bash
QA_USERNAME=vova.tkachenko
QA_PASSWORD=...
```

`tests/constants.py` берёт их из окружения, а если там пусто — из `.env.local`
(`constants_env_get`). Такой fallback нужен потому, что `.env` на проде пересобирается
из секрета `ENV_FILE` и креды автотестов из него исчезают: без них `TEST_AUTH` уходит
с пустым паролем, `/auth/login` отвечает **400**, и вся сьюита валится.
Роль `qa` имеет полный набор прав — см. `auth.md`.

Браузерные тесты (`tests/test_team_task_pages.py`) требуют Playwright с установленным
chromium: `.venv/bin/python3 -m playwright install chromium`.

## Переменные окружения

`.env` — файл, который читают и `load_dotenv()`, и `env_file` в `docker-compose.yml`:
контейнеры видят только его. Шаблон — `.env.dist`. На проде переменные добавляются
через GitHub secret `ENV_FILE`, иначе деплой их сотрёт (`deploy.md`).

`.env.local` — локальная копия того же набора, в контейнеры не попадает. Из него читает
только `tests/constants.py` (fallback для `QA_USERNAME`/`QA_PASSWORD`). Новую переменную
добавляйте в оба файла, иначе после регенерации `.env` она пропадёт без следа.

```bash
APP_ENV=local
LLM='ollama/qwen2.5:14b'

# MySQL — хостнейм и порт контейнерные
MYSQL_HOST=mysql
MYSQL_PORT=3306
MYSQL_USER=developer
MYSQL_PASSWORD=...
MYSQL_DATABASE=project

REDIS_URL=redis://redis:6379

# Telegram: два бота
TELEGRAM_TOKEN_RHAPSODY=...
TELEGRAM_TOKEN_SOKO=...
TELEGRAM_OWNER_CHAT_ID=...
TELEGRAM_MINI_APP_URL=...
TELEGRAM_SITE_LOGIN_REMOTE_URL=https://your-domain.com
TELEGRAM_SITE_LOGIN_LOCAL_URL=http://localhost:8011

SESSION_SECRET_KEY=...
```

Ключи LLM-провайдеров (`OPENAI_API_KEY`, `CLAUDE_API_KEY`, `GEMINI_API_KEY`,
`GROQ_API_KEY`, `OPENROUTER_API_KEY`, …) — полный список в `.env.dist`.

## База данных

Схема живёт только в `migrations/0001.sql`, данные — через Seed UI. Подробности
и порядок сброса — `migration.md`, `database.md`, `seed.md`.

```bash
# Консоль MySQL (без --default-character-set кириллица покажется как "??????")
docker compose exec mysql mysql --default-character-set=utf8mb4 -u developer -p project
# локально контейнер называется rhapsodyai-mysql-1, поэтому docker exec -it mysql ... не сработает
```

Полный бэкап — страница `/admin/backup` (`backup.md`).

## Полезное

```bash
docker exec -it uvicorn bash

# Уведомление в Telegram владельцу
docker exec uvicorn python3 -c "
import asyncio
from src.telegram_.telegram_notify import telegram_send_owner
asyncio.run(telegram_send_owner('your message'))
"
```

# Architecture — модули, сервисы, окружение

> Справочник верхнего уровня: что лежит в `py_modules/` и `src/`, какие зависимости и
> Docker-сервисы поднимаются, какие переменные `.env` и имена очередей используются.
> Правила размещения кода внутри этих папок — `architecture_rules.md`.

## Core Modules (`py_modules/`)

| Module | Purpose |
|--------|---------|
| `ai/` | AI framework core — agents, tasks, MCP, tools, sessions |
| `async_/` | Event-loop helpers: `async_loop_init`, `async_waiting_*`, отмена задач |
| `config/` | Configuration via `.env` |
| `event_/` | Локальная шина событий: `event_subscribe` / `event_emit` |
| `flux_schnell/` | Image generation (SDXL-Turbo/Flux) |
| `i18n_/` | `i18n_text_resolve` / `i18n_languages_parse` — мультиязычные строки |
| `json_/` | `json_from_string` — устойчивый парсинг JSON из ответа LLM |
| `logging_/` | Structured logging |
| `mcp_/` | Model Context Protocol client |
| `microphone/` | Speech recognition |
| `mysql_/` | MySQL connection pooling & repositories |
| `qdrant_/` | Vector database client |
| `queue_/` | In-memory async queue system |
| `redis_/` & `redis_queue/` | Redis connection & RQ queue |
| `setting_/` | Settings persistence |
| `sqllite3/` | SQLite for LLM short-term memory |
| `state/` | Global state management |
| `thread_/` | `thread_with_callback` — запуск блокирующего кода в потоке |
| `translator/` | `translate_text` — перевод текста |

## Application Code (`src/`)

| Path | Purpose |
|------|---------|
| `ai/` | AI workflow, tools, fact collection |
| `auth/` | Authentication (session, role, permission, field policy) |
| `browser/` | Контейнер-браузер: пул сессий, живое окно, движок сценариев (точка входа — `main_browser.py`, см. `browser.md`) |
| `cronjob/` | Scheduled jobs — только точки входа (см. `architecture_rules.md`) |
| `event/` | `event_handlers.py` — подписки на шину `py_modules/event_` (event_log, Telegram-уведомления) |
| `faster_whisper/` | Speech-to-text |
| `mysql_/repository/` | Database repositories for all entities |
| `parser/` | Data parsers (HTML→JSON, MD→Qdrant, MD→Fact) |
| `project/` | Project-модули: `planning/`, `task/`, `team/` (см. `project_*.md`) |
| `telegram_/` | `telegram_notify.py` — отправка сообщений через Bot API |
| `tool/` | Tool implementations — по категориям, auto-discovery (`tools.md`) |
| `translator/` | `translator_md.py` — перевод markdown-документов |
| `uvicorn/routers/` | FastAPI route handlers |
| `telegram_bot.py` | Telegram bot handler (точка входа — `main_telegram.py`) |
| `filesystem.py`, `os_.py`, `voice.py` | Утилиты: открыть файл в редакторе, статус сервисов/env, TTS |

## Key Dependencies

- **AI/LLM**: `pydantic-ai`, `anthropic`, `openai`, `groq`, `google-genai`
- **Vector DB**: `qdrant-client`, `fastembed`
- **Database**: `pymysql`, `aiomysql`, `yoyo-migrations`
- **Web**: `fastapi`, `uvicorn`, `jinja2`
- **Telegram**: `aiogram`
- **Voice**: `faster-whisper`
- **Queue**: `redis`, `redis-queue`
- **Tools**: `crawl4ai`, `PyGithub`

Install: `pip install -r docker/uvicorn/requirements.txt` / `docker/telegram/requirements.txt`

## Docker Services

| Service | Port (host→container) | Profile | Purpose |
|---------|------|---------|---------|
| `uvicorn` | 8011→8000 | — | Main FastAPI application (blue-слот) |
| `uvicorn_green` | 8012→8000 | `green` | Green-слот для Blue-Green деплоя (`deploy.md`) |
| `uvicorn_task` | 8013→8000 | `task` | Сервер над рабочим каталогом подзадачи: на нём QA проверяет ветку, поднимается `./task_server.sh up <id>` (`project_task.md`) |
| `browser` | 127.0.0.1:8014→8000 | — | Контейнер-браузер: один Chromium, изолированные сессии-контексты (`browser.md`) |
| `worker_task` | — | — | `rq worker-pool … -n 3 default` — конвейер задач |
| `worker_planning` | — | — | `rq worker-pool … -n 2 planning` — цепочки фаз планирования |
| `mysql` | 3302→3306 | — | Primary database |
| `redis` | внутренний 6379 | — | Queue & caching (порт наружу не публикуется) |
| `qdrant` | 6333/6334 | — | Vector database (API+UI / gRPC) |
| `opensearch` | 9200, 9600 | — | Log search |
| `opensearch-dashboards` | 5601 | — | Log visualization |
| `logstash` | — | — | Доставка логов в OpenSearch |
| `cronicle` | 3012 | — | Job scheduler |
| `rq-dashboard` | 9181 | — | Redis queue monitoring; свой образ `docker/rq_dashboard/dockerfile` (151 МБ) — общий с приложением тянул Playwright и модели ради веб-страницы |
| `phpmyadmin` | 9634→80 | — | MySQL admin |
| `gatus` | 8090→8080 | — | Health-мониторинг эндпоинтов |
| `telegram` | — | `on_prod_only` | Telegram-бот, образ `ghcr.io/vskuba/marina-ai:latest` |
| `caddy` | 80, 443 | `on_prod_only` | Reverse proxy + TLS; `/play/detective/*` отдаёт статику напрямую |

Сервисы с профилем не поднимаются обычным `docker compose up` — нужен
`--profile green` / `--profile on_prod_only`.

### Хранение логов Cronicle

Cronicle копит две разные кучи, и убираются они по-разному. Держим трое суток
в обеих.

| Что | Где | Кто чистит |
|-----|-----|-----------|
| История прогонов | `data/cronicle/data/jobs` | сам Cronicle в ночное обслуживание (`maintenance: "04:00"`) по `CRONICLE_job_data_expire_days=3` из `docker-compose.yml` |
| Архивы суточной ротации логов | `data/cronicle/logs/archives` | `src/cronjob/cronicle_log_cleanup.py` (логика — `src/cronicle/cronicle_log.py`) |

Второй крон нужен потому, что **свой лог Cronicle ротирует, но архивы не удаляет
никогда**: при умолчаниях на проде накопился гигабайт истории прогонов и 30 МБ
архивов за месяц. Событие в Cronicle заводится вручную, как и остальные, — см.
`project_task.md`, там же про URL `http://caddy:8090/cronjob`.

После уборки крон шлёт владельцу в Telegram строку с размерами обеих куч. Размер
истории прогонов там не для красоты: `CRONICLE_job_data_expire_days` применяется
в память (`applyConfigOverrides` в `pixl-server`), а в `conf/config.json` внутри
образа остаётся прежнее значение — убедиться, что настройка доехала, можно только
по каталогу. Прогон вручную без сообщения — `{"notify": false}` в metadata.

## Environment Variables (`.env`)

- `LLM`, `LLM_ALLOWED` — default model and allowed models list
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `XAI_API_KEY`
- `GITHUB_TOKEN`, `JIRA_URL`, `JIRA_API_TOKEN`, `JIRA_EMAIL`
- `WHISPER_MODEL_NAME`, `WHISPER_LANGUAGE`
- `DATA_DIR`, `HISTORY_DIR`, `REPORT_DIR`, `TASK_DIR`, `LOG_DIR`
- `SESSION_SECRET_KEY` — FastAPI session secret
- `TELEGRAM_TOKEN_RHAPSODY`, `TELEGRAM_OWNER_CHAT_ID` — Telegram Mini App

## Queue Names

Key queues used across the system:
`chat`, `chat_response`, `chat_input_send`, `task`, `task_abort`, `task_complete`, `task_continue`, `tool`, `agent_abort`, `agent_response`, `ai_framework_model`

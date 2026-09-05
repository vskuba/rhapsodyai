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
| uvicorn_task | 8013 | 8000 | profile `task`, сервер над каталогом подзадачи: `./task_server.sh up <id>` (`project_task.md`) |
| browser | 127.0.0.1:8014 | 8000 | контейнер-браузер, порт только для отладки (`browser.md`) |
| mysql | 3302 | 3306 | в `.env` порт 3306 — он контейнерный |
| phpmyadmin | 9634 | 80 | |
| redis | — | 6379 | наружу не публикуется |
| rq-dashboard | 9181 | 9181 | очереди |
| qdrant | 6333 / 6334 | | UI: `:6333/dashboard` |
| opensearch | 9200 / 9600 | | |
| opensearch-dashboards | 5601 | | |
| cronicle | 3012 | | планировщик |
| gatus | 8090 | 8080 | health-мониторинг; **отключён** — profile `disabled`, уведомления в Telegram выключены |
| caddy_local | 44153 / 80 | 44152 | profile `on_local_only`: локальный HTTPS для Mini App |

`caddy_local` поднимается только профилем `on_local_only` и берёт на хосте **44153**, а
внутри слушает 44152: локальный 44152 занят системным Apache, а адрес сайта должен
совпадать с портом в URL — роутер пробрасывает внешний 44152 на 44153. Порт 80 нужен
ему только под ACME-челлендж.
| caddy | 80 / 443 | | profile `on_prod_only` |

Профили: `telegram` и `caddy` — только `on_prod_only`, `uvicorn_green` — `green`.

## Документация API

`/docs` — Swagger UI, `/openapi.json` — сама схема. Локально `http://localhost:8011/docs`,
на рабочей установке — `/docs` того же домена.

В схему попадает не всё приложение, а только то, что предназначено соседним проектам:
внутренние точки монтируются с `include_in_schema=False` — админка, мини-приложение
Telegram, запись и очистка журналов. Поэтому путей там несколько десятков, а не сотни.

**Страница собрана из своей статики.** Встроенный Swagger у FastAPI тянет скрипт и стили
с `cdn.jsdelivr.net`, а favicon — с `fastapi.tiangolo.com`; у нас все три файла лежат в
репозитории, версия зафиксирована (`swagger-ui-dist` 5.32.14):

| Файл | Где лежит |
|------|-----------|
| `swagger-ui-bundle.js` | `data/uvicorn/public/js/vendor/` |
| `swagger-ui.css` | `data/uvicorn/public/css/vendor/` |
| `swagger-favicon.png` | `data/uvicorn/public/assets/` |

Собирает страницу `swagger_ui_docs` в `main_uvicorn.py`; встроенная отключена
(`docs_url=None`) — два роута на один путь не уживаются. Причина местных файлов общая
для проекта (`docs-common/frontend_rules.md`): работа без интернета, отсутствие внешней
точки отказа и утечки факта захода, воспроизводимость версии. Держит это
`tests/test_api_docs.py`: он проверяет и что в разметке нет внешних адресов, и что файлы
по указанным путям отдаются.

Обновлять версию — заменить три файла и поправить номер здесь; ссылки в коде
относительные и правки не потребуют.

`/redoc` остался штатным и **закрыт авторизацией** (401), в отличие от `/docs`.

### Локальные порты против прод-овых

Таблица выше — порты прода. На машине разработчика те же номера занимает SSH-туннель
(`LocalForward` у `Host rhapsody-prod` в `~/.ssh/config`), поэтому локальные контейнеры
уведены на соседние — `docker-compose.override.yml`:

| Сервис | Прод (туннель) | Локально |
|--------|----------------|----------|
| phpmyadmin | 9634 | 9635 |
| cronicle | 3012 | 3013 |
| qdrant | 6333 | 6335 |
| opensearch-dashboards | 5601 | 5602 |
| rq-dashboard | 9181 | 9182 |

Порядок здесь важнее самих номеров: у туннеля стоит `ExitOnForwardFailure yes`, и один
занятый порт роняет весь туннель целиком — не поднимется ни один прод-сервис. Обратная
сторона тоже неприятна: если туннель успел занять порт первым, Docker контейнер не
останавливает, а откатывает сетевой endpoint — контейнер «живой», но без сети и все
задачи в нём падают с `getaddrinfo EAI_AGAIN`. Поэтому маппинги в override идут с
`!override`, а не добавляются к списку из основного файла.

Шапка админки (`base.html`) рисует по одной ссылке на сервис: страница прода ведёт на
прод-сервис, страница локальной установки — на локальный. Разницы в шаблоне для этого не
нужно, потому что ссылка открывается в браузере админа и всегда ведёт на его `localhost`:
до прод-сервисов он ходит через SSH-туннель, до локальных напрямую. Номер приходит
Jinja-глобалом `<NAME>_PORT` из `main_uvicorn.py`; номеров в коде нет вовсе — он знает
лишь список имён сервисов, значения в `.env` (полный набор ключей виден в `.env.dist`),
а локальные отклонения — в `.env.local` машины разработчика.
Адрес Grafana — целиком в `GRAFANA_URL`: она стоит вне docker-compose, на отдельной
машине, и одним портом не описывается.

## Тесты

Сьюита интеграционная: ей нужен поднятый uvicorn на `localhost:8011`
и заполненный seed (тесты опираются на агента id=9 `dating_bot`).

```bash
.venv/bin/python3 -m pytest tests/ -v
.venv/bin/python3 -m pytest tests/test_setting_crud.py -v
.venv/bin/python3 -m pytest tests/ -v -s          # с логами
```

Адрес сервера — в переменной `BASE_URL`, по умолчанию `http://localhost:8011`:

```bash
BASE_URL=http://localhost:8013 .venv/bin/python3 -m pytest tests/ -q
```

Переменная нужна конвейеру задач: QA проверяет не общий `:8011`, а сервер ветки
подзадачи (`uvicorn_task`, свой порт). На `:8011` работает код основного чекаута,
и сьюита там зелёная независимо от того, что сделал разработчик. Читают переменную
`tests/conftest.py` и каждый тестовый модуль — одна команда переключает всю сьюиту.

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

**Сюита убирает за собой по префиксам, до и после прогона.** Сессионные фикстуры
`conftest.py` сносят пользователей `test_`, агентов `test_agent_`, роли из
`TEST_ROLE_NAMES` и задачи `__pytest*` (`cleanup_test_tasks`). Уборка именно
сессионная, а не только в фикстуре теста: прерванный прогон — Ctrl-C, таймаут,
перезапуск сервера — оставляет строки в **рабочей** БД, и брошенная задача не просто
мусорит списком. Задачу без плана конвейер отдаёт живому Менеджеру независимо от
статуса (`task_claim_task_unplanned`), то есть агентское время уходит на пустышку
в общей очереди с настоящими задачами. Отсюда правило: **новая сущность в тестах —
узнаваемый префикс в имени и строка в сессионной уборке.**

## Переменные окружения

`.env` — файл инсталляции: его читают и `load_dotenv()`, и `env_file` в
`docker-compose.yml`. Шаблон — `.env.dist`. На проде переменные добавляются через GitHub
secret `ENV_FILE`, иначе деплой их сотрёт (`deploy.md`).

`.env.local` — то, чем конкретная машина отличается от инсталляции: порты
админ-инструментов, тестовые учётки. `py_modules/config/config.py` грузит его **поверх**
`.env` с `override=True`; ключа в нём нет — значение остаётся из `.env`, нет самого файла
— работает один `.env`. Отдельный `env_file` в compose не нужен: каталог проекта и так
смонтирован в контейнер (`./:/app`), а override обязателен именно потому, что `.env`
приезжает в контейнер уже настоящими переменными окружения — без него `.env.local` молча
ни на что не влиял бы.

Новую переменную заводите в `.env` и `.env.dist`; в `.env.local` — только если её
значение расходится на конкретной машине.

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

# Хостовый путь репозитория. Без него `docker compose` не поднимется вовсе:
# монтирование `${PROJECT_HOST_DIR}:${PROJECT_HOST_DIR}` есть у uvicorn,
# worker_task и uvicorn_task — рабочие каталоги задач (`project_task.md`).
# Каталоги других проектов машины монтируются отдельно, в
# `docker-compose.override.yml` — см. «Много проектов» в `project_task.md`.
PROJECT_HOST_DIR=/home/user/PycharmProjects/RhapsodyAi
# Адрес сервера задачи для проекта самой установки (сервис `uvicorn_task`).
# У других проектов свой порт — их адрес хранится в карточке проекта
# (`project.task_server_url`), а это значение остаётся запасным.
PROJECT_TASK_QA_SERVER_URL=http://localhost:8013
```

Ключи LLM-провайдеров (`OPENAI_API_KEY`, `CLAUDE_API_KEY`, `GEMINI_API_KEY`,
`GROQ_API_KEY`, `OPENROUTER_API_KEY`, …) — полный список в `.env.dist`.

## База данных

Схема живёт только в `migrations/20260101000000_initial_schema.sql`, данные — через Seed UI. Подробности
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
from src.telegram_.telegram_notify import telegram_notify_send_owner
asyncio.run(telegram_notify_send_owner('your message'))
"
```

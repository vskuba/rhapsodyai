# Telegram Mini App

Встроенное веб-приложение (SPA), открывающееся внутри Telegram через кнопку Menu Button бота. Доступно только владельцу бота (`TELEGRAM_OWNER_CHAT_ID`).

## Файлы

| Файл | Назначение |
|------|------------|
| `data/uvicorn/template/telegram_app.html` | Единственный шаблон Mini App (SPA без base.html) |
| `src/uvicorn/routers/telegram_app/telegram_app.py` | Роутер: аутентификация, события, агенты, чат |
| `src/uvicorn/routers/telegram_app/telegram_app_plan.py` | Роутер: CRUD планов + AI-редактирование |
| `src/mysql_/repository/event_log_repository.py` | Репозиторий таблицы `event_log` |
| `src/mysql_/repository/plan_repository.py` | Репозиторий таблицы `plan` |

Оба роутера зарегистрированы в `main_uvicorn.py` с `include_in_schema=False`.

## Аутентификация

Mini App использует **Telegram WebApp initData** — не сессию admin-панели.

1. JS вызывает `tg.ready()` + `tg.expand()` и постит `initData` на `POST /telegram-app/auth`
2. Бэкенд проверяет HMAC-SHA256 подпись (ключ = `HMAC(b"WebAppData", bot_token)`), срок действия (`auth_date` ≤ 24 ч) и `user.id == TELEGRAM_OWNER_CHAT_ID`
3. При успехе пишет `telegram_owner_id` в сессию
4. Все эндпоинты вызывают `_require_telegram_owner(request)` — проверяет наличие `telegram_owner_id` в сессии

**Env-переменные:**
- `TELEGRAM_NOTIFY_TOKEN` — токен бота (используется для проверки подписи)
- `TELEGRAM_OWNER_CHAT_ID` — Telegram user_id владельца

## Вкладки и интерфейс

SPA с иконочным сайдбаром (60px) и контент-панелью. Три вкладки:

| Вкладка | Иконка | Назначение |
|---------|--------|------------|
| Events | 🔔 | Лента событий + список агентов |
| Chat | 💬 | Чат с AI-ассистентом |
| Plans | 📋 | Список планов, создание и редактирование |

**Сайдбар переключается в режим плана** при открытии конкретного плана: вместо трёх вкладок показываются «← Назад» и «🗑 Удалить». Реализовано переключением `.active-group` между двумя `<div class="icon-sidebar-group">`.

**Input-бары** вынесены за пределы `.content-panel` (полная ширина экрана). Видимость управляется `updateInputBarsVisibility()`:
- `#chatInputBar` / `#chatProgress` — только на вкладке Chat
- `#planInputBar` / `#planProgress` — только когда открыт конкретный план
- `#planCreateBar` / `#planCreateProgress` — только на списке планов

## Вкладка Events

Загружает параллельно `GET /telegram-app/events` и `GET /telegram-app/agents`.

- **События**: последние 50 записей из `event_log` (тип + время), `ORDER BY created_at DESC`
- **Агенты**: все с `dynamic = 0`, `ORDER BY title`

## Вкладка Chat

Чат с агентом `telegram_assistant`. Каждое сообщение — новый HTTP-запрос (не WebSocket). Сессия сохраняется в `chatSessionUuid` (первый ответ возвращает UUID, последующие переиспользуют).

**Константы в `telegram_app.py`:**
- `TELEGRAM_CHAT_USER_ID = 1`
- `TELEGRAM_CHAT_AGENT_NAME = 'telegram_assistant'`
- `TELEGRAM_CHAT_COMPANION_ID = 3` / `TELEGRAM_CHAT_COMPANION_NAME = 'user_admin'`

Запрос через `AiFrameworkAgentManager` синхронно (Future + `asyncio.wait_for`, timeout 60 сек).

## Вкладка Plans

Markdown-планы с AI-созданием и редактированием.

| Агент | Workflow | Назначение |
|-------|----------|------------|
| `plan_creator` | id=17 | Создаёт новый план по инструкции |
| `plan_editor` | id=16 | Правит план: получает `plan_current_content` + инструкцию |

**Создание**: голос → транскрипция → `POST /telegram-app/plans` → `plan_creator` → сохранение → открытие detail-view.

**Редактирование**: textarea в detail-view (Enter = отправить, Shift+Enter = перенос). `POST /telegram-app/plans/{id}/edit` прогоняет инструкцию через `plan_editor`, который возвращает полный обновлённый документ.

**Рендеринг Markdown**: `renderPlanContent()` — собственный построчный рендерер (не CommonMark). Поддерживает:
- `- [ ]` / `- [x]` → disabled-чекбоксы
- `### заголовки` → `.plan-heading`
- `- списки` → bullet-точка
- `**жирный**` → `<b>`
- пустые строки → вертикальный отступ

## Голосовой ввод

Фабрика `createVoiceRecorder({micBtn, cancelBtn, progressEl, onError, onTranscript})` — изолированный экземпляр для каждого микрофона.

1. Первый тап — запрашивает микрофон (стрим переиспользуется), начинает запись, кнопка пульсирует
2. Крестик `micCancel` — отмена без отправки
3. Второй тап по микрофону — останавливает запись
4. `MediaRecorder.onstop` → `Blob(audio/wav)` → `POST /telegram-app/chat/voice` → faster-whisper → `onTranscript(text)`
5. Запись < 1000 мс или отменённая — игнорируется

## База данных

**Таблица `plan`:**

| Колонка | Тип | Назначение |
|---------|-----|------------|
| `id` | INT PK | |
| `node_id` | INT NULL FK | Нода (обычно NULL) |
| `user_id` | INT NULL FK | Владелец |
| `title` | CHAR(150) | Парсится из первого `# заголовка` в content |
| `content` | LONGTEXT | Markdown-текст плана |
| `status` | ENUM | `active` / `archived` |
| `position` | INT | Порядок сортировки |
| `dynamic` | TINYINT | `1` = рантайм, не входит в seed-экспорт |

Список: `ORDER BY FIELD(status, 'active', 'archived'), updated_at DESC` — активные первыми.

**Таблица `event_log`:**

| Колонка | Тип | Назначение |
|---------|-----|------------|
| `id` | INT PK | |
| `type` | VARCHAR(100) | Тип события |
| `payload` | JSON NULL | Данные события |
| `created_at` | DATETIME | Время записи |

## API эндпоинты

| Метод | URL | Назначение |
|-------|-----|------------|
| `GET` | `/telegram-app` | Страница Mini App (HTML) |
| `POST` | `/telegram-app/auth` | Аутентификация через Telegram initData |
| `GET` | `/telegram-app/events` | Последние 50 событий |
| `GET` | `/telegram-app/agents` | Все non-dynamic агенты |
| `POST` | `/telegram-app/chat/ask` | Сообщение ассистенту |
| `POST` | `/telegram-app/chat/voice` | Транскрипция аудио (Whisper) |
| `GET` | `/telegram-app/plans` | Список планов |
| `GET` | `/telegram-app/plans/{id}` | Получить план |
| `POST` | `/telegram-app/plans` | Создать план |
| `DELETE` | `/telegram-app/plans/{id}` | Удалить план |
| `POST` | `/telegram-app/plans/{id}/edit` | Редактировать план |

## Добавление нового функционала

- **Новая вкладка**: добавить кнопку в `#sidebarDefaultIcons`, `<div class="tab-view">` в `.content-panel`, обработчик в `initTabs()`, логику видимости в `updateInputBarsVisibility()`
- **Новый AI-агент**: создать запись в миграции, добавить константу имени в роутере, вызывать через `_plan_workflow_run(agent_name, instruction, extra_variables)`
- **Расширение доступа**: заменить проверку `telegram_user_id != int(owner_chat_id)` на белый список в `_telegram_init_data_verify()`

# Telegram Mini App — SPA внутри Telegram

> Встроенное веб-приложение (SPA), открывающееся внутри Telegram через Menu Button бота.
> Доступно только владельцу бота (`TELEGRAM_OWNER_CHAT_ID`). Вкладки: Events, Claude
> (вопросы Claude Code — кнопками); есть голосовой ввод.

## Файловая структура

### Шаблон и статика

| Файл | Назначение |
|------|------------|
| `data/uvicorn/template/telegram_app.html` | markup-шаблон вкладки (без inline `<style>` и `<script>`) |
| `data/uvicorn/public/css/telegram_app.css` | Все стили Mini App (~300 строк) |
| `data/uvicorn/public/js/telegram_app/app.js` | Точка входа: инициализация, ping-loop |
| `data/uvicorn/public/js/telegram_app/state.js` | Единый shared-объект `state` |
| `data/uvicorn/public/js/telegram_app/sidebar.js` | Навигация, переключение групп иконок |
| `data/uvicorn/public/js/telegram_app/input_bar.js` | Фабрики `createInputBar()` / `createMicOnlyBar()` |
| `data/uvicorn/public/js/telegram_app/events.js` | Вкладка Events: загрузка, рендер, форматтеры |
| `data/uvicorn/public/js/telegram_app/claude.js` | Вкладка Claude: сессии, polling, управление |
| `data/uvicorn/public/js/telegram_app/claude_dialog.js` | Вопрос Claude Code кнопками: разбор текста оболочки, радио/галочки, строка ответа |
| `data/uvicorn/public/js/telegram_app/plans.js` | Вкладка Plans: CRUD, рендер Markdown. **Экрана больше нет**; модуль на странице не импортируется |
| `data/uvicorn/public/js/telegram_app/utils.js` | `escapeHtml`, `linkify`, `confirmDialog`, `appendBubble` |
| `data/uvicorn/public/js/telegram_app/voice.js` | Фабрика `createVoiceRecorder()` |

### Backend-роутеры

| Файл | Назначение |
|------|------------|
| `src/uvicorn/routers/telegram_app/telegram_app.py` | Аутентификация, ping, агенты |
| `src/uvicorn/routers/telegram_app/telegram_app_chat.py` | Только voice — распознавание для микрофона вкладки Claude (вкладку «Чат» сняли, имя файла осталось) |
| `src/uvicorn/routers/telegram_app/telegram_app_claude.py` | Claude: ask, messages, sessions/active, respond |
| `src/uvicorn/routers/telegram_app/telegram_app_claude_session.py` | Session registry: register, heartbeat, inbox, finalize, delete |
| `src/uvicorn/routers/telegram_app/telegram_app_plan.py` | Plans: CRUD + AI-редактирование |
| `src/uvicorn/routers/telegram_app/telegram_app_common.py` | Shared: `_require_telegram_owner`, `_require_claude_secret`, constants |
| `src/uvicorn/routers/event/event.py` | Events: GET /events, DELETE /events, POST /event-log |

Все роутеры зарегистрированы в `main_uvicorn.py` с `include_in_schema=False`.

## Аутентификация

Mini App использует **два способа** установки сессии:

### 1. Telegram WebApp initData (production)
1. JS вызывает `tg.ready()` + `tg.expand()` и постит `initData` на `POST /telegram-app/auth`
2. Backend проверяет HMAC-SHA256 подпись, срок действия (`auth_date` ≤ 24 ч) и `user.id == TELEGRAM_OWNER_CHAT_ID`
3. При успехе пишет `telegram_owner_id` в сессию

### 2. Access Token (dev / тесты)
```json
POST /telegram-app/auth
{ "init_data": "", "access_token": "<uuid>" }
```
Токен ищется в `user_access_token WHERE user_id = 1`. Seeded test-токен: `a0000000-1111-4444-bbbb-000000000001`.

Все защищённые эндпоинты вызывают `_require_telegram_owner(request)` — проверяет `telegram_owner_id` в сессии.

**Mini App внутри админки.** Страница `/admin/miniapp` (вкладка «📱 MiniApp» в шапке)
открывает тот же `/telegram-app` в iframe шириной 390 px. Токен страница берёт сама:
`/auth/me` → `/user/{id}/token` → `?access_token=…`. Отсюда следствие: под учёткой, чей
`user_id ≠ 1`, в рамке будет «Доступ запрещён» — токен ищется только у владельца
(см. способ 2 выше). На iframe стоит `allow="microphone"`, иначе голосовой ввод молча
не запустится.

**Env-переменные:**
- `TELEGRAM_TOKEN_RHAPSODY` — токен бота (подпись initData + X-Claude-Secret)
- `TELEGRAM_OWNER_CHAT_ID` — Telegram user_id владельца

## JS-архитектура

Все модули — ES modules (`type="module"`). Используют `import`/`export`.

```
app.js  ──┬── state.js          (shared state object)
          ├── sidebar.js        (navigation, visibility)
          ├── input_bar.js      (DOM factories)
          ├── events.js
          └── claude.js  ─┬── sidebar.js (setSidebarPageMode)
                          └── claude_dialog.js (вопрос Claude Code кнопками)
               └── voice.js (createVoiceRecorder)
               └── utils.js (shared helpers)
```

**Shared state** (`state.js`):
```js
export const state = {
    currentTab: 'events', currentPlanId: null,
    eventsTimezone: '+0', pingFailCount: 0,
    claude: { sessionUuid, sessionLabel, sessionUnreachable,
              pollTimer, statusPollTimer, renderedUserIds,
              renderedResponses, pendingUserCount, typingBubble },
};
```

**Input bars** создаются программно в `app.js` через фабрику `createInputBar({ id, progressId, placeholder, hasQuickCmd })` и аппендятся в `.app-wrapper` — только для Claude.

**Sidebar callbacks**: чтобы избежать циклических зависимостей (`sidebar.js` ↔ `claude.js`), коллбэки `onTabChange` и `onGoHome` передаются в `initSidebar()` из `app.js`.

## Интерфейс и вкладки

SPA с иконочным сайдбаром (60px) и контент-панелью. Две вкладки:

| Вкладка | Иконка | Назначение |
|---------|--------|------------|
| Events  | 🔔     | Лента системных событий |
| Claude  | ☁️     | Чат с терминальными сессиями Claude Code |

Вкладки Планов, Чата (💬, агент `telegram_assistant`) и Задач (📝) сняты 21.11.2026 —
ими не пользовались. Задачи ведутся на `/admin/task`.

**Группы иконок в сайдбаре** — переключаются через `.active-group`:

| ID | Показывается когда |
|----|-------------------|
| `sidebarDefaultIcons` | Главный экран: 2 вкладки + внешние ссылки (🌐 прод, 💻 локальная установка, 🐋 DeepSeek) |
| `sidebarPageIcons` | Открыта Claude-сессия (`← Назад`) |
| `sidebarClaudeIcons` | Режим сессии Claude (`← к списку`, `⟳ статус`, `🧹 очистить`, `🗑 удалить`) |

**Видимость input-баров** управляется `updateInputBarsVisibility()` в `sidebar.js`:
- `#claudeInputBar` — только вкладка Claude, сессия открыта

**Home-кнопка** (`#homeIconBtn`) пульсирует красным при ≥2 пропущенных ping'ах подряд.

## Вкладка Events

Загружает `GET /events` каждые 5 секунд; после нажатия ≈ очистка приостанавливается
на 30 секунд, чтобы список не оживал мгновенно из-за новых записей `event_log`.

- **Последние 50** записей из `event_log`, `ORDER BY created_at DESC`
- Время отображается как **чип** (rounded pill, `.event-time`) с учётом `timezone` из настроек
- Кнопка 🗑 очищает все события (`DELETE /events`); при сбое выводит текст ошибки
- Форматтеры по типу (`EVENT_FORMATTERS` в `events.js`):

| Тип | Формат |
|-----|--------|
| `github` | 🚀/✅/❌ deploy.started/finished · branch · commit |
| `system` | 👤 event_type · username (role) |
| `claude_session` | 🖥 event_type · project_label · role |
| `agent` | 🤖 event_type · agent_name |
| `llm` | 💬 event_type · model · ↑in ↓out |

## Вкладка Claude

Два уровня: список активных терминальных сессий → чат конкретной сессии.

**Список сессий** (`GET /telegram-app/claude/sessions/active`):
- Показывает сессии с `last_seen_at` не старше **60 секунд** (heartbeat от `session_client.py watch`)
- Карточка: роль, project_label, превью последнего сообщения

**Чат сессии**:
- Polling `GET /telegram-app/claude/messages?session_uuid=...` каждые 4 секунды
- Пользовательское сообщение отправляется с **7-секундной задержкой** (кнопка ✕ для отмены)
- Typing-индикатор пока ждём ответа
- Status-polling `refreshClaudeSessionStatus()` каждые 5 секунд — детектирует закрытие терминала

**Quick commands** (кнопка `⋯` рядом с textarea):
```
🏓 Ping
📦 Закомить и запусти деплой
🔀 Закомить и пришли MR
🧪 Запусти pytest и верни отчёт
```

**Иконки управления сессией** (`sidebarClaudeIcons`):
- `← к списку` — закрыть сессию, вернуться к списку
- `⟳ статус` — `POST /telegram-app/claude/session/restart-processes`, ждёт 5с и проверяет heartbeat
- `🧹 очистить` — `POST /telegram-app/claude/session/clear-messages`
- `🗑 удалить` — `POST /telegram-app/claude/session/delete-request`

**Вопрос Claude Code кнопками** (`claude_dialog.js`). Когда Claude в терминале задаёт
вопрос (`AskUserQuestion` или диалог разрешения), оболочка `claude-shell` присылает его
**текстом** (`shell.py`, `_permission_notify`): заголовок `🔐 Claude ждёт ответа:`, варианты
`1. …`. Структуры рядом нет — пузырь с таким текстом разбирается и рисуется кнопками:

| Вид текста | Признак | Кнопки | Что уходит |
|---|---|---|---|
| простой (один вопрос или разрешение) | хвост «Ответь номером» | радио | голая цифра `2` |
| сложный (несколько вопросов / мультивыбор) | блоки `Вопрос N.`, хвост «Ответь номерами вариантов» | радио, а у «(можно несколько)» — галочки | `1: 2,3; 2: 1` |

Нажатие только отмечает вариант; «Отправить» загорается, когда отмечено хоть что-то.
У каждого вопроса есть ещё пункт **«✎ Свой вариант»** (радио или галочка, как у
вопроса) с полем под ним: текст уходит отдельной строкой `N:= текст`, и оболочка
вписывает его в пункт Claude Code «Type something» — Claude получает его ответом на
вопрос. У диалога разрешения такого пункта в Claude Code нет: там оболочка жмёт Esc и
отдаёт текст Claude просьбой. Метка `:=` выбрана потому, что `=` в номерном формате уже
значит «номер вопроса» (`2=1`), и текст «42» прочитался бы вариантом.
«Отменить» шлёт `нет` — оболочка жмёт Esc. Ответ идёт **обычным сообщением**
(`/claude/ask`, с тем же 7-секундным отсчётом и ✕), оболочка разбирает его
`_ask_answer_parse` и сама жмёт галочки, «→» и Submit. Поэтому формат строки — договор с
оболочкой: ⚠ простой вид нельзя слать как `1: 2` — у диалога разрешения нет списка
вопросов, и оболочка приняла бы это за отказ (Esc).

Открыт только вопрос, **после которого в сессии ничего нет** (`_dialogRefreshState`):
ответ человека, экран Submit следующим вопросом или «✅ На вопрос ответили в терминале»
(его шлёт оболочка, заметив, что диалог закрыли у терминала) — любая новая строка
закрывает кнопки, иначе повторное нажатие ушло бы в Claude Code новым промптом.
Закрытый вопрос остаётся на экране с отметками: вопросы `claude_message_cloud` не
стирает, хотя прочие спонтанные сообщения сменяют друг друга.
Текст не разобрался — пузырь остаётся текстом, и цифрой можно ответить руками.

## Вкладка Plans

Markdown-планы с AI-созданием и редактированием. **Экрана больше нет**: `app.js` не
импортирует `plans.js`. Точки
`/telegram-app/plans*` и сам модуль живы — их судьба за пределами этой правки.

| Агент | Назначение |
|-------|------------|
| `plan_creator` | Создаёт новый план по голосовой инструкции |
| `plan_editor` | Правит план: получает `plan_current_content` + инструкцию |

**Создание**: голос → транскрипция → `POST /telegram-app/plans` → `plan_creator` → сохранение → открытие detail-view.

**Редактирование**: textarea в detail-view (Enter = отправить, Shift+Enter = перенос). `POST /telegram-app/plans/{id}/edit`.

**Рендеринг Markdown** (`renderPlanContent()` в `plans.js`):
- `- [ ]` / `- [x]` → disabled-чекбоксы
- `### заголовки` → `.plan-heading`
- `- списки` → bullet-точка
- `**жирный**` → `<b>`
- пустые строки → вертикальный отступ

## Голосовой ввод

Фабрика `createVoiceRecorder({ micBtn, cancelBtn, progressEl, onError, onTranscript })` — изолированный экземпляр для каждого микрофона (Claude, Chat, Plan-edit, Plan-create).

1. Тап → запрашивает микрофон, начинает запись, кнопка пульсирует
2. ✕ `micCancel` — отмена без отправки
3. Повторный тап → останавливает запись
4. `MediaRecorder.onstop` → `Blob(audio/wav)` → `POST /telegram-app/chat/voice` → faster-whisper → `onTranscript(text)`
5. Запись < 1000 мс или отменённая — игнорируется

## База данных

**Таблица `plan`:**

| Колонка | Тип | Назначение |
|---------|-----|------------|
| `id` | INT PK | |
| `user_id` | INT NULL FK | Владелец (= `TELEGRAM_CHAT_USER_ID = 1`) |
| `title` | CHAR(150) | Парсится из первого `# заголовка` в content |
| `content` | LONGTEXT | Markdown-текст плана |
| `status` | ENUM | `active` / `archived` |
| `position` | INT | Порядок сортировки |

Список: `ORDER BY FIELD(status, 'active', 'archived'), updated_at DESC`.

**Таблица `event_log`:**

| Колонка | Тип | Назначение |
|---------|-----|------------|
| `id` | INT PK | |
| `type` | VARCHAR(100) | `system`, `github`, `claude_session`, `agent`, `llm` |
| `payload` | JSON NULL | Данные события |
| `created_at` | DATETIME | Время записи |

**Таблица `ai_claude_session`** — очередь сообщений:

| Колонка | Назначение |
|---------|------------|
| `session_uuid` | UUID сессии |
| `content` | Сообщение пользователя |
| `response` | Ответ Claude |
| `handled` | 0 = непрочитано терминалом |

**Таблица `ai_claude_session_registry`** — реестр активных терминалов:

| Колонка | Назначение |
|---------|------------|
| `session_uuid` | UUID (ключует `ai_claude_session`) |
| `role` | `developer`, `qa`, и т.д. |
| `project_label` | basename cwd |
| `last_seen_at` | Heartbeat от `session_client.py watch` |

## API эндпоинты

### Публичные / страница
| Метод | URL | Назначение |
|-------|-----|------------|
| `GET` | `/telegram-app` | Страница Mini App (HTML) |
| `GET` | `/telegram-app/ping` | Health check (без auth) |
| `POST` | `/telegram-app/auth` | Аутентификация (initData или access_token) |

### Events (owner session)
| Метод | URL | Назначение |
|-------|-----|------------|
| `GET` | `/events` | Последние 50 событий + timezone |
| `DELETE` | `/events` | Очистить все события |
| `GET` | `/telegram-app/agents` | Все non-dynamic агенты |

### Events write (X-Claude-Secret)
| Метод | URL | Назначение |
|-------|-----|------------|
| `POST` | `/event-log` | Добавить событие (типы: system/github/claude_session/agent/llm) |

### Голос (owner session)
| Метод | URL | Назначение |
|-------|-----|------------|
| `POST` | `/telegram-app/chat/voice` | Транскрипция аудио (Whisper) |

### Claude (owner session)
| Метод | URL | Назначение |
|-------|-----|------------|
| `GET` | `/telegram-app/claude/sessions/active` | Список сессий (last_seen ≤ 60с) |
| `POST` | `/telegram-app/claude/ask` | Отправить сообщение в сессию |
| `GET` | `/telegram-app/claude/messages` | История чата по session_uuid |
| `POST` | `/telegram-app/claude/session/delete-request` | Удалить сессию + маркер очистки |
| `POST` | `/telegram-app/claude/session/clear-messages` | Очистить историю сессии |
| `POST` | `/telegram-app/claude/session/restart-processes` | Команда перезапуска клиента |
| `GET` | `/telegram-app/claude/session/process-status` | Статус процессов по session_uuid |

### Claude session (X-Claude-Secret — терминал)
| Метод | URL | Назначение |
|-------|-----|------------|
| `GET` | `/telegram-app/claude/sessions` | Список registry-записей для project_label |
| `POST` | `/telegram-app/claude/session/register` | Регистрация новой сессии |
| `POST` | `/telegram-app/claude/session/resume` | Возобновление сессии |
| `POST` | `/telegram-app/claude/session/heartbeat` | Обновить last_seen_at |
| `GET` | `/telegram-app/claude/session/inbox` | Непрочитанные сообщения (handled=0) |
| `POST` | `/telegram-app/claude/respond` | Ответ терминала в чат Mini App |
| `POST` | `/telegram-app/claude/session/finalize` | Записать summary, закрыть |
| `POST` | `/telegram-app/claude/session/cleanup-confirm` | Удалить строки после маркера |

### Plans (owner session)
| Метод | URL | Назначение |
|-------|-----|------------|
| `GET` | `/telegram-app/plans` | Список планов |
| `GET` | `/telegram-app/plans/{id}` | Получить план |
| `POST` | `/telegram-app/plans` | Создать план (AI) |
| `DELETE` | `/telegram-app/plans/{id}` | Удалить план |
| `POST` | `/telegram-app/plans/{id}/edit` | Редактировать план (AI) |

## Добавление нового функционала

### Новая вкладка
1. Добавить кнопку `<button class="icon-btn" data-tab="..." id="tabBtn...">` в `#sidebarDefaultIcons` (HTML)
2. Добавить `<div class="tab-view" id="tab-...">` в `.tab-views` (HTML)
3. Создать ES-модуль `data/uvicorn/public/js/telegram_app/<name>.js`
4. Добавить `import` и вызов `init<Name>()` в `app.js`
5. При необходимости input bar: добавить через `createInputBar()`/`createMicOnlyBar()` в `app.js`, дополнить `updateInputBarsVisibility()` в `sidebar.js`

### Новый event-тип
1. Добавить Pydantic-модель payload и discriminated union в `event.py`
2. Добавить форматтер в `EVENT_FORMATTERS` в `events.js`

### Новая quick command
Добавить `<div class="quick-cmd-item" data-text="...">🎯 Текст команды</div>` в `#claudeQuickCmdPopup` в `telegram_app.html`.

### Новый AI-агент для Plans
Создать запись в миграции, добавить имя-константу в `telegram_app_plan.py`, вызывать через `_plan_workflow_run(agent_name, instruction, extra_variables)`.

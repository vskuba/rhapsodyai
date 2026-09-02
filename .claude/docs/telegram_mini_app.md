# Telegram Mini App — SPA внутри Telegram

> Встроенное веб-приложение (SPA), открывающееся внутри Telegram через Menu Button бота.
> Доступно только владельцу бота (`TELEGRAM_OWNER_CHAT_ID`). Вкладки: Events, Claude,
> Chat, Plans; есть голосовой ввод.

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
| `data/uvicorn/public/js/telegram_app/chat.js` | Вкладка Chat |
| `data/uvicorn/public/js/telegram_app/claude.js` | Вкладка Claude: сессии, polling, управление |
| `data/uvicorn/public/js/telegram_app/plans.js` | Вкладка Plans: CRUD, рендер Markdown |
| `data/uvicorn/public/js/telegram_app/tasks.js` | Вкладка Tasks: список задач, вкладки фаз, чипсы статуса |
| `data/uvicorn/public/js/telegram_app/questions.js` | Панель вопросов задачи: свой DOM-слой, ответ на вопрос |
| `data/uvicorn/public/js/telegram_app/flags.js` | Флаги фаз корневой задачи: `to_planning` / `to_development` / `to_testing` |
| `data/uvicorn/public/css/telegram_app/task.css` | Стили вкладок фаз, карточек, чипсов, флагов и панели вопросов |
| `data/uvicorn/public/js/telegram_app/utils.js` | `escapeHtml`, `linkify`, `confirmDialog`, `appendBubble` |
| `data/uvicorn/public/js/telegram_app/voice.js` | Фабрика `createVoiceRecorder()` |

### Backend-роутеры

| Файл | Назначение |
|------|------------|
| `src/uvicorn/routers/telegram_app/telegram_app.py` | Аутентификация, ping, агенты |
| `src/uvicorn/routers/telegram_app/telegram_app_chat.py` | Chat: ask + voice |
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
          ├── chat.js
          ├── claude.js  ──── sidebar.js (setSidebarPageMode)
          └── plans.js   ──── sidebar.js (setSidebarPlanMode)
               │
               └── voice.js (createVoiceRecorder)
               └── utils.js (shared helpers)
```

**Shared state** (`state.js`):
```js
export const state = {
    currentTab: 'events', currentPlanId: null, chatSessionUuid: null,
    eventsTimezone: '+0', pingFailCount: 0,
    claude: { sessionUuid, sessionLabel, sessionUnreachable,
              pollTimer, statusPollTimer, renderedUserIds,
              renderedResponses, pendingUserCount, typingBubble },
};
```

**Input bars** создаются программно в `app.js` через фабрики и аппендятся в `.app-wrapper`:
- `createInputBar({ id, progressId, placeholder, hasQuickCmd })` — для Claude, Chat, Plan
- `createMicOnlyBar({ id, progressId })` — для создания нового плана голосом

**Sidebar callbacks**: чтобы избежать циклических зависимостей (`sidebar.js` ↔ `claude.js`/`plans.js`), коллбэки `onTabChange` и `onGoHome` передаются в `initSidebar()` из `app.js`.

## Интерфейс и вкладки

SPA с иконочным сайдбаром (60px) и контент-панелью. Четыре вкладки:

| Вкладка | Иконка | Назначение |
|---------|--------|------------|
| Events  | 🔔     | Лента системных событий |
| Claude  | ☁️     | Чат с терминальными сессиями Claude Code |
| Chat    | 💬     | Чат с AI-ассистентом (`telegram_assistant`) |
| Plans   | 📋     | Список планов, создание и редактирование |

**Группы иконок в сайдбаре** — переключаются через `.active-group`:

| ID | Показывается когда |
|----|-------------------|
| `sidebarDefaultIcons` | Главный экран: 4 вкладки + внешние ссылки (🌐 прод, 💻 локальная установка, 🐋 DeepSeek) |
| `sidebarPageIcons` | Открыта Claude-сессия (`← Назад`) |
| `sidebarPlanIcons` | Открыт план (`← Назад` + `🗑`) |
| `sidebarClaudeIcons` | Режим сессии Claude (`← к списку`, `⟳ статус`, `🧹 очистить`, `🗑 удалить`) |

**Видимость input-баров** управляется `updateInputBarsVisibility()` в `sidebar.js`:
- `#claudeInputBar` — только вкладка Claude, сессия открыта
- `#chatInputBar` — только вкладка Chat
- `#planInputBar` — только вкладка Plans, план открыт
- `#planCreateBar` — только вкладка Plans, список (создание голосом)

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

## Вкладка Chat

Чат с агентом `telegram_assistant`. Каждое сообщение — новый HTTP-запрос. Сессия сохраняется в `state.chatSessionUuid`.

**Константы** (в `telegram_app_common.py`):
```python
TELEGRAM_CHAT_USER_ID = 1
TELEGRAM_CHAT_AGENT_NAME = 'telegram_assistant'
TELEGRAM_CHAT_COMPANION_ID = 3
```

Запрос через `AiFrameworkAgentManager` (`asyncio.wait_for`, timeout 60 сек).

## Вкладка Plans

Markdown-планы с AI-созданием и редактированием.

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

## Вкладка задач

Список задач проекта с вкладками фаз, флажками фаз и панелью вопросов. Файлы —
`tasks.js` (список), `questions.js` (панель), `flags.js` (флажки), `task.css`
(подключается отдельной строкой в шаблоне: `telegram_app.css` описывает оболочки
вкладок, а не содержимое задачи).

**Панели готовы, каркас — за соседней подзадачей.** Вкладка как экран собрана не здесь:
модули ещё не подключены (`app.js` не импортирует `tasks.js`), в шаблоне нет ни
контейнера `tasksListView`, ни кнопки в сайдбаре, ни прокси-точек
`/telegram-app/tasks` и `/telegram-app/task/*` — это пункты плана других подзадач.
Пока их нет, вкладки на экране не видно; панелям это не помеха: `questions.js` заводит
свой DOM-слой сам, а карточка переживает отсутствующую точку сохранения — отказ видно на
чипе, а не в логе. Поэтому панели проверяются без сервера и без живой вкладки: тест
подкладывает каркас и ответы (`page.route`). Из перечисленного здесь лежит только
`task.css` — он подключён шаблоном отдельной строкой.

**Вкладки фаз** — `planning` / `development` / `testing` / `bugs`. Отбор по `task_type_id`
(1 разработка, 2 баг, 3 тест, 4 исследование, 5 план): `metadata` строки списка
`task_type_name` не несёт, поэтому фильтр держит номера типов, как и админка.
 Подписи вкладок — ролями, теми же словами, что на админской странице
(`PHASE_TAB_TITLES`, `task.html:2003`): человек переключается между двумя интерфейсами
и должен видеть одни и те же имена — «Багфиксер», а не «Баги».

Готовая работа (`status === 'done'` или `pipeline_state === 'done'` — достаточно одной
оси, как в `taskIsDone`) уходит с вкладки своего типа на `testing`: там её принимают и
вливают, кнопок приёмки у разработки нет, и оставленная на «Разработчике» строка висела
бы непринятой. У бага инстанция своя — закрытый остаётся на `bugs`, там его завели и там
же смотрят принятую ветку. Правило перенесено из `taskMatchesPhase` (`task.html:2348`).

**Флажки фаз** — три чекбокса у корневой задачи, у подзадачи их нет (едет с родителем).
Ключи `metadata` и их умолчания: `to_planning` (включён отсутствием, снятый — явное
`false`), `to_development` (одноразовый триггер: включён явным `true`, снятый — `null`,
ключ стирается), `to_testing` (включён отсутствием, снятый — явное `false`). Сохранение —
`POST /telegram-app/task/{id}/metadata` с `patch` ровно из одного ключа, затем список
перезагружается.

**Подпись чипа обещает ровно этот шаг.** Админский переключатель фазы
(`_taskPhaseSwitch`, `task.html:3823`) пишет ключ и вдогонку шлёт
`POST /task/{id}/pipeline/stop|resume` — гасит или возобновляет прогон. Здесь этого
второго запроса нет: точка закрыта правом `planning.update`, а прокси под неё — не моя
подзадача. Поэтому чип пишет одну запись в `metadata` и больше ничего, и его `title`
говорит то же: снятый `to_planning` убирает задачу из очереди за планом
(`task_metadata_plan_free_sql` читают отбор менеджера и захват), а идущий прогон не
останавливает. Формулировка «планирование прекратится» была бы враньем там, где запись
меняет только следующий отбор.

Рядом с флажками у открытой карточки встаёт кнопка «Утвердить план» — ровно на состоянии
`plan_approval` (`POST /telegram-app/task/{id}/pipeline/approve`, точку рисует соседняя
подзадача), и снимается, когда открыли другую задачу. Без неё флажки работают впустую:
план, который нечем утвердить, до `to_development` не доводит.

Сбои флажок держит на себе, а не в безмолвии: запрос мог не дойти, и оставленный
отмеченным чекбокс показывает состояние, которого в базе нет. Поэтому при ошибке
чекбокс возвращается обратно, чип краснеет (`.task-flag-failed`), а причина пишется в
`title` — её видно по наведению, отдельного тоста странице не нужно. Отметка живёт в
модуле словарём `{'задача:чип': причина}` и попадает в разметку при каждой перерисовке:
список перезаписывает карточку строкой, и висящей на старом узле подсветки не бывает.
Своя запись её и снимает — прошла запись, ключ удалён. Перезагрузка списка следует за
запросом при любом его исходе: `await _reloadTasks()` стоит вне ветки успеха. Разморозка
не отдана на откуп этой перезагрузке: `_writeFlag` возвращает `disabled` сама, если узел
всё ещё в документе. Список мог не вернуться, его коллбек мог молча не дойти — и чекбокс
остался бы выключенным до первой перерисовки, которой может и не случиться, а второй
клик человеку нужен сразу. Три чипа
собраны над одной `_writeFlag` — разъехаться было нечему, кроме имени ключа, а его
понимает админка.

**Панель вопросов** открывается на карточке и рисуется из строки списка: вопрос лежит в
`metadata.question`/`metadata.questions`, там же `decisions`. GET
`/telegram-app/task/{id}/question` дорисовывает принятые решения и — главное — цели.
Ответ — `POST /telegram-app/task/{id}/question/answer` с `answers`, `note`, а действия над
целями (`goals_split`, `goals_drop`) несут ещё `goal_indexes`. Форму обеих отправок
собирает один `askFormRead`; два разбора одной формы разъезжаются молча, и цель, отмеченную
на экране, теряет тот путь, который забыли поправить.

Ответ на вопрос **пачки** уходит без `goal_indexes` (`_batchBody`) — и это не забывчивость.
Тело с `index` сервер ведёт в `task_question_batch_answer`, а он берёт только `answers` и
`note`: пачку задаёт менеджер про замысел, охват подзадачи ею не меняют, и `_scope_apply`
на этом пути не зовётся. Номера целей в таком теле были бы полем, которое сервер молча
выбросит, а по журналу выходило бы, что дробление заказано и исполнено.

Открывается панель не только тапом по карточке: у строки с неотвеченным вопросом есть
свой «❓ Вопрос» (`.task-btn-ask`, привязка через `data-ask` — вложенная кнопка
останавливает всплытие, иначе клик по ней считается открытием деталей). Кнопка рисуется
только там, где спрашивают (`taskHasQuestion` читает `metadata` строки): на молчаливой
карточке она звала бы в «вопросов нет», а искать вопросы по одной карточке человек не
должен.

Панель вставляется в `.content-panel`, а не в `.app-shell`: последняя — горизонтальный
flex, её ребёнком панель легла бы колонкой рядом со списком вместо полосы под вкладками.
Вопросы не импортируют `loadTasks` — цикл `tasks → questions → flags → tasks` оставался
бы невнятным на этапе инициализации, — и перегружают список через общий
`window._tg_reload_tasks`. Ответ на последний вопрос закрыл бы панель и перезагрузил
список даже с мёртвым импортом; теперь так же и без него. Пакетный ответ (несколько
вопросов в одном) при 404 на GET не захлёбывается alert — метка отвеченного
дорисовывается локально (`_markAnswered`), а `_askIndex` пересчитывается на ближайший
неотвеченный, так что оставшиеся вопросы не теряются.

**Отвеченный вопрос открывается со своим ответом.** Поле уточнения (`#askNote`)
подставляется из `_noteSeed`: сервер пакует ответ в `answer.text` как
`метки выбранных вариантов; вольный текст` (`task_question_batch_answer`), и назад
в поле надо вернуть ровно вольный текст. Поэтому ведущие части, совпадающие с подписями
выбранных вариантов, отрезаются **по равенству** (не по вхождению — иначе «Да» съело бы
«Да, но позже») и **не дальше, чем меток в префиксе**: их столько, сколько подписей
насчитал `_labelsFor`, а не сколько ключей в `answer.keys` — ключ, под который не
нашлось варианта (вопрос под панелью сменился), подписи не имеет и в префикс не попал,
так что граница по числу ключей резала бы фразу дальше безопасного. Ориентир — сохранить
слова человека: недорезанный хвост показывает лишнюю подпись, дорезанный — съедает начало
его же фразы («Да» + «Да; но не в этой версии»). Хвост остаётся
целиком, даже внутри него есть `; `. Подписи выбранных вариантов за обоими разборами —
один `_labelsFor` (им же пользуется локальная доводка `_markAnswered`): два воплощения
серверной нормы в одном файле обязательно разъезжаются. Без этого
открыть отвеченный вопрос значило показать пустое поле: человек не видит, что уже
отвечал, и правит вслепую. Локальная доводка состояния (`_markAnswered`) складывает
`answer` в той же форме, что пишет сервер, — иначе переоткрытый из локального состояния
вопрос показал бы метки вместо текста и потерял бы галочки.

**Нумерация целей — серверная.** Сервер перед применением `goal_indexes` прогоняет колонку
`goals` через `task_plan_goals_normalize` (`task_plan.py:101`, схлопывание похожих по
порогу 0.85), поэтому номер цели равен её месту в **схлопнутом** серверном списке, а не в
том, что приехал строкой списка. Панель отмечает цели из ответа GET; колонка `goals`
строки — показ до ответа и подстраховка, когда GET целей не принёс (панель обязана
работать и без него). Повторять серверноё схлопывание на клиенте не стал намеренно:
второй источник истины разъехался бы при первом же изменении Python-нормы. Без отметки
ответ не уходит, если отмечать есть чем (закрытая цель нарисована снятой и недоступной).

Проверяется в `tests/test_telegram_app_task_ui.py` на chromium с подменой ответов
(`page.route`); сервер и БД не нужны — точки роутера рисует соседняя подзадача. GET вопроса
подменяется двояко: 404 («точки ещё нет», панель работает со строки списка) и живым
списком целей (проверка серверной нумерации). Точка сохранения подменяется кодом ответа
(`metadata_status=500` рисует отказ флажка), а ответ на POST — своим телом: `done: true`
(панель закрывается) или `done: false` (пачка листается сама). Вызовы `alert()`
регистрируются в `window.__alerts`: алерт на уже принятом сервером ответе — то же
вранье, что и молчаливый отказ.

Вторая проверка — `tests/test_telegram_app_task_contract.py`, и она про другое: браузерная
доказывает, какое тело уходит, а эта — что после такого тела в задаче меняется `metadata` и
появляются `decisions`. Заглушек в ней нет: те же байты отправляются живым обработчикам
`POST /task/{id}/metadata` и `POST /task/{id}/question/answer` — тем самым, контракт которых
прокси-точки `/telegram-app/task/*` должны повторить, когда их напишет своя подзадача.
Результат читается из БД; обе строки, и подзадачу, и корневую, заводит и убирает сам тест
(`_drop`), а сессионный сметатель сюиты (`conftest.py:151`) остаётся страховкой на
прерванный прогон: корневая заводится в `planned`, и живой Менеджер забирает такую строку
всерьёз. Тела не переписаны по памяти — `test_frontend_sends_exactly_this_shape`
сверяет их с `flags.js` и `questions.js`, поэтому рассинхрон фронтенда красит проверку.

Отдельно проверяются те три вещи, которые не прошла проверка: чипы остаются кликабельными
и после отказа, и после перезагрузки, список которой не дорисовал карточку
(`flags.js` сама снимает `disabled`); `title` чипа плана не обещает остановки прогона;
отвеченный пакетный вопрос переоткрывается со своим вольным текстом и сохранёнными
отметками вариантов — в том числе когда GET точки нет и состояние сложилось локально.

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

### Chat (owner session)
| Метод | URL | Назначение |
|-------|-----|------------|
| `POST` | `/telegram-app/chat/ask` | Сообщение ассистенту |
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

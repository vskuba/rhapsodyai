# Claude Shell (claude_shell)

> Обёртка вокруг Claude Code CLI — PTY-сессия для интерактивного использования + HTTP-сервер для headless-вызова из Docker-контейнера.

## 1. Структура

```
claude_shell/
  claude_shell.py          # Основная оболочка: PTY-обёртка + workflow-tool HTTP-сервер
  session_client.py        # CLI управления сессиями (register/resume/heartbeat/inbox/respond/finalize/status)
  session_tool.py          # Общие утилиты + CLI для API-вызовов, event-log, quota
  litellm/
    litellm_manager.py     # LiteLLM proxy-менеджер (gx10) — запуск/статус/порт 4000
    litellm_config.yaml    # Конфиг прокси LiteLLM
    litellm.pid            # PID-файл прокси
    litellm.log            # Лог прокси
  wrapper.pid              # PID-файл PTY-обёртки (создаётся при запуске)
  session_uuid             # Сохранённый UUID текущей сессии
  inbox_pending.json       # Очередь отложенной инъекции (session_uuid + inbox_id)
  logs/
    claude_shell_*.log     # Логи PTY-сессий
    workflow.log           # Лог workflow-tool HTTP-сервера
```

**PROJECT_ROOT** = `claude_shell/` + `..` (родительская директория, обычно RhapsodyAi).
**SHELL_DIR** = абсолютный путь до `claude_shell/`.

## 2. Режимы запуска

### 2.1 PTY-режим (по умолчанию, для интерактивного использования)

Запускает `claude` как дочерний процесс в PTY. Фоновый поток опрашивает inbox Mini App и вставляет сообщения напрямую в PTY. Умеет перезапускать дочерний процесс при получении маркера `RESTART_WATCH_MARKER`.

```bash
# Обычный запуск — подхватывает сохранённую сессию или создаёт новую
python3 claude_shell/claude_shell.py

# С флагом gx10 — использовать LiteLLM proxy как LLM-бэкенд
python3 claude_shell/claude_shell.py --gx10

# Форс-новая сессия
python3 claude_shell/claude_shell.py --register

# Продолжить конкретную сессию
python3 claude_shell/claude_shell.py --session-uuid <uuid>
```

**Доступные флаги:**

| Флаг | Описание |
|------|----------|
| `--session-uuid UUID` | Продолжить существующую сессию |
| `--register` | Создать новую сессию (игнорирует сохранённый UUID) |
| `--project-label LABEL` | Метка проекта для реестра (по умолчанию basename cwd) |
| `--gx10` | Запустить LiteLLM proxy (порт 4000) и использовать как бэкенд Claude |
| `--verbose` | Передать `--verbose` в Claude Code |
| `--workflow-tool` | Запустить HTTP-сервер вместо PTY (§2.2) |
| `claude_args ...` | Дополнительные аргументы передаются в `claude` |

### 2.2 Workflow-tool режим (`--workflow-tool`)

**Назначение:** HTTP-сервер, принимающий запросы из Docker-контейнера (uvicorn), запускающий Claude Code в headless режиме (`-p`) и возвращающий результат. Используется DB-инструментами для запроса контекста проекта (страницы, блоки, wireframes, токены) от Manager-агента.

```bash
# Запуск
python3 claude_shell/claude_shell.py --workflow-tool

# Работает в фоне:
nohup python3 claude_shell/claude_shell.py --workflow-tool >> claude_shell/logs/workflow.log 2>&1 &
```

**Эндпоинты:**

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/health` | Health-check: `{"status":"ok","pid":<pid>}` |
| `POST` | `/run` | Headless вызов Claude: промпт → `claude -p` → результат |

**POST /run** — тело:

```json
{
  "prompt": "Опиши структуру страниц проекта #{id}",
  "use_gx10": true
}
```

Заголовки:
- `X-Claude-Secret: claude-shell-workflow`
- `Content-Type: application/json`

**Ответ:**

```json
{
  "status": "ok",
  "message": "<ответ Claude, очищенный от ANSI>",
  "raw": "<полный ответ Claude с ANSI-кодами>"
}
```

При ошибке — `"status": "error"`, `"message": "<описание>"`.

**Параметры:**
- Порт: **8999**
- Привязка: **0.0.0.0:8999** (доступен из Docker-контейнеров)
- Таймаут: 720 секунд (12 минут, как у Manager)
- Секрет: `claude-shell-workflow` (header `X-Claude-Secret`)
- Рабочая директория: `PROJECT_ROOT`
- LiteLLM proxy: поднимается автоматически при `use_gx10: true` (port 4000)

## 3. Управление сессиями (PTY-режим)

### 3.1 Регистр сессий

Сессии хранятся в `ai_claude_session_registry` (MySQL). Каждая запись: `session_uuid`, `role` (по default `developer`), `project_label`, `status` (active/closing/inactive), `summary`.

### 3.2 CLI: session_client.py

```bash
# Регистрация новой сессии
python3 claude_shell/session_client.py register --role developer --project-label RhapsodyAi

# Возобновление сессии (из текущего контекста или по UUID)
python3 claude_shell/session_client.py resume --session-uuid <uuid>

# Heartbeat (каждые 5с, для staleness detection)
python3 claude_shell/session_client.py heartbeat --session-uuid <uuid>

# Проверка inbox (непрочитанные сообщения)
python3 claude_shell/session_client.py inbox --session-uuid <uuid>

# Ответ на сообщение из inbox
python3 claude_shell/session_client.py respond --session-uuid <uuid> --response "текст ответа"

# Завершение сессии (записать summary)
python3 claude_shell/session_client.py finalize --session-uuid <uuid> --summary "краткое содержание"

# Статус сессии (проверить: watch жив, сервер отвечает, файл session_uuid на месте)
python3 claude_shell/session_client.py status --session-uuid <uuid>
```

**Механизм:**
- `session_uuid` сохраняется в `claude_shell/session_uuid` — при следующем запуске подхватывается автоматически.
- Фоновый `watch`-процесс гонит heartbeat каждые 5 секунд.
- Сессия считается видимой, если `last_seen_at` не старше **60 секунд** (12× интервал).
- `start_new_session=True` — `watch` полностью отвязан от процесса Claude Code (переживает перезапуск/краш).

### 3.3 Хуки SessionStart / SessionEnd

Регистрируются в `.claude/settings.json`:
- **SessionStart** — хук `.claude/hooks/session_start.py`: проверяет сохранённый UUID → `resume` (автоматически) или `register` (через `AskUserQuestion`).
- **SessionEnd** — хук `.claude/hooks/session_end.py`: останавливает `watch` при осознанном выходе (`exit`/`/exit`).

## 4. Inbox-механизм

Сообщения от Mini App (через `POST /claude_message_user` или из чата Mini App) попадают в таблицу `ai_claude_session`. PTY-обёртка поллит inbox каждые 5 секунд и вставляет сообщения в PTY Claude.

**Полный цикл:**
1. Пользователь отправляет сообщение → `ai_claude_session` (`content`, `handled=0`).
2. `watch` (или PTY `ClaudeShell._inbox_loop`) забирает через `GET /telegram-app/claude/session/inbox?session_uuid=...`.
3. Новые строки (`id > _last_id`) обрабатываются `_process_rows()`:
   - Маркеры (`CLEANUP_MARKER`, `RESTART_WATCH_MARKER`, `QUOTA_CHECK_MARKER`) обрабатываются отдельно.
   - Обычные сообщения: `POST /respond` (подтверждение "Принял") → текст + `\r` в PTY.
4. Claude обрабатывает сообщение → PTY выводит ответ → ответ дублируется в Mini App через `POST /telegram-app/claude/respond` (с `notify: false` для промежуточных шагов, `notify: true` для финального ответа).

**Маркеры:**

| Маркер | Обработка |
|--------|-----------|
| `__SESSION_CLEANUP__` | Очистка `ai_claude_session` для сессии, удаление `session_uuid`, остановка |
| `__RESTART_WATCH__` | Перезапуск дочернего `claude` процесса |
| `__QUOTA_CHECK__` | Запуск `session_tool.py quota`, ответ возвращается через `/respond` |

## 5. LiteLLM Proxy (gx10)

Мост между Claude Code CLI и локальным LLM-прокси LiteLLM.

**Файлы:**
- Конфиг: `claude_shell/litellm/litellm_config.yaml`
- PID: `claude_shell/litellm/litellm.pid`
- Лог: `claude_shell/litellm/litellm.log`
- Порт: **4000**

**API:**
- `litellm_is_running()` → `bool` (проверяет порт 4000 + PID-файл)
- `litellm_start()` → запускает `litellm --config ... --port 4000` в фоне
- `litellm_ensure_running()` → поднимает если не запущен, возвращает порт

**Настройка окружения Claude:**
```python
os.environ["ANTHROPIC_BASE_URL"] = f"http://localhost:4000"
os.environ["ANTHROPIC_API_KEY"] = "litellm-proxy"
```

## 6. container → laptop архитектура (workflow-tool)

```
┌──────────────────────┐     HTTP POST     ┌──────────────────────────┐
│  Docker-контейнер     │ ───────────────▶  │  Ноутбук (host.docker.   │
│                       │  POST /run        │   internal:8999/run)     │
│  src/tool/claude_shell/│  {prompt, use_   │                          │
│  claude_shell.py      │  gx10:true}       │  claude_shell.py         │
│                       │                   │  --workflow-tool         │
│  claude_shell_call()  │                   │                          │
│                       │                   │  subprocess.run([        │
│  HTTP → host.docker.  │                   │    claude, -p, prompt])  │
│   internal:8999       │                   │  + gx10 env vars         │
└──────────────────────┘                   └──────────────────────────┘
```

**Инструмент в контейнере** (`src/tool/claude_shell/claude_shell.py`):
- `claude_shell_call(prompt, use_gx10=True)` — POST на ноутбук, запускает `claude -p`, возвращает ответ.
- `claude_shell_is_available()` — проверка health-эндпоинта.
- Автоматически обнаруживается через `rglob` в `src/ai/ai_tool.py`.

**Сетевая настройка:**
- Docker Compose: `extra_hosts: ["host.docker.internal:host-gateway"]` (уже настроено для uvicorn).
- HTTP-сервер на ноутбуке привязан к `0.0.0.0:8999` — доступен из контейнера.

## 7. Использование Manager-агентом

Manager (`task_plan_manager`, workflow #55) получает только `task_title`, `task_description`, `task_goals` — без знания структуры проекта. Для составления детальных планов Manager должен вызывать `claude_shell_call`:

```python
# Пример использования Manager-агентом:
result = claude_shell_call(
    prompt=(
        f"Проект #{project_id}. "
        f"Опиши все страницы (project_design_prototype_page) с wireframe, "
        f"блоки (project_design_prototype_page_block) и виджеты "
        f"(project_design_prototype_widget). "
        f"Составь детальную структуру для плана."
    ),
    use_gx10=True,
)
```

**Результат** — структурированный текст от Claude в headless режиме, который Manager использует как контекст для планирования.

## 8. Константы

```python
WRAPPER_PID_FILE       # claude_shell/wrapper.pid
SESSION_UUID_PATH      # claude_shell/session_uuid
CLEANUP_MARKER         # "__SESSION_CLEANUP__"
RESTART_WATCH_MARKER   # "__RESTART_WATCH__"
QUOTA_CHECK_MARKER     # "__QUOTA_CHECK__"

_WORKFLOW_PORT         # 8999
_WORKFLOW_SECRET       # "claude-shell-workflow"
_CLAUDE_SHELL_URL      # "http://host.docker.internal:8999/run"
_CLAUDE_SHELL_TIMEOUT  # 720
```

## 9. Сравнение с Claude Session Registry

| Аспект | Claude Session Registry | claude_shell (workflow-tool) |
|--------|------------------------|------------------------------|
| **Назначение** | Интерактивная сессия Claude Code через Mini App | Headless вызов из Docker-контейнера |
| **Управление** | Хуки + PTY + inbox | HTTP-сервер + subprocess |
| **Вызов** | Через Mini App UI / Claude Code CLI | Из DB-инструмента в контейнере |
| **Видимость** | Сессии в Cloud-вкладке Mini App | Не виден в реестре |
| **Лайфтайм** | Пока открыт терминал | Пока запущен процесс |
| **LLM-бэкенд** | anthropic или gx10 (--gx10) | gx10 по умолчанию |

Два режима (`claude_shell.py --session-uuid ...` и `claude_shell.py --workflow-tool`) работают независимо и могут быть запущены одновременно.

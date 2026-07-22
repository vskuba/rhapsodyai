# Автономные агенты Developer/QA — архитектура и workflow-план

> Итог обсуждения архитектуры двух автономных ролей: агент-Разработчик (разбирает очередь задач,
> пишет код, открывает PR) и агент-QA (постоянно мониторит прод, заводит задачи при находках).
> Построено на существующей инфраструктуре проекта (Cronicle, Claude Code CLI под Team-подпиской,
> MySQL, Qdrant/fact_collection), без Managed Agents API (см. §2).

## 1. Цель

Пользователь ставит задачи текстом/голосом в Telegram → задача редактируется → уходит в общую
очередь → агент-Разработчик реализует и открывает PR → агент-QA непрерывно проверяет прод и сам
заводит задачи в ту же очередь при обнаружении проблем. Коммит/пуш — только в PR, слияние в `main`
— вручную пользователем (см. память `no-auto-commit.md`, `dev-qa-loop-architecture.md`).

## 2. Почему не Managed Agents API

Рассматривался вариант на официальном Anthropic Managed Agents (`/v1/agents`, `/v1/sessions`,
`/v1/environments`, Outcome-грейдер, Scheduled Deployments, webhooks). Отклонён по деньгам: это
отдельный биллинг через `ANTHROPIC_API_KEY` (по токенам), не покрываемый текущей **Claude Team**
подпиской (`/status` → Login method: Claude Team account, org Protonix), под которой уже идёт
интерактивная работа с Claude Code. Решили строить на том же Team-аккаунте через headless-запуски
`claude` CLI — без дополнительной статьи расходов.

## 3. Общая схема

```
Telegram (текст/голос) ──▶ MySQL task (status=draft) ──▶ редактирование ──▶ status=ready
                                                                                  │
                                                                                  ▼
Cronicle (локальная установка, ноутбук)                              Cronicle (прод-установка)
   │  каждые ~2ч: claude -p "developer-loop"                            │  каждые ~10-15 мин: claude -p "qa-sweep"
   ▼                                                                     ▼
Агент-Разработчик                                                   Агент-QA
  - Workflow: pipeline по задачам ready                               - Workflow: parallel-проверки здоровья
  - Qdrant fact-поиск за контекстом                                   - дедуп находок против fact_collection
  - реализация + тесты                                                - заведение task (source=qa) в ту же очередь
  - commit → feature-ветка → PR (без мержа)                           - НИКАКИХ фиксов/рестартов самостоятельно
  - запись факта о работе в Qdrant
  - update task.status, Telegram-уведомление
```

## 4. Роли, хосты, биллинг

| | Developer | QA |
|---|---|---|
| Хост | Ноутбук пользователя | Прод-сервер |
| Доступность | Только когда ноутбук включён (некритично — задача просто ждёт) | Должен быть всегда (задача мониторинга) |
| Cronicle-инсталляция | Локальная (своя, отдельная от прод — см. `rhapsody-prod-tunnel.md`) | Прод |
| Может писать/менять код | Да | **Нет** |
| Может коммитить/пушить | Да, только в feature-ветку + PR | Нет |
| Биллинг | Claude Team seat (та же подписка, что и эта сессия) | Claude Team seat |
| Жизненный цикл сессии | Пересоздаётся Cronicle каждые ~2ч (headless `claude -p`, не бесконечный `/loop`) | Пересоздаётся каждый Cronicle-тик |

## 5. Очередь задач — схема MySQL (предложение, требует миграции)

```sql
CREATE TABLE task (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  source ENUM('user','qa') NOT NULL DEFAULT 'user',
  status ENUM('draft','ready','in_progress','done','blocked') NOT NULL DEFAULT 'draft',
  title VARCHAR(255) NOT NULL,
  description TEXT NOT NULL,
  assigned_agent VARCHAR(50) NULL,       -- 'developer' на время in_progress
  pr_url VARCHAR(255) NULL,
  result_summary TEXT NULL,
  fact_ref VARCHAR(64) NULL,             -- ссылка на связанный факт в Qdrant (если задача из QA)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Единая таблица для задач от пользователя и от QA — Developer-агент не различает источник, разбирает
`status='ready'` по порядку.

## 6. Память — переиспользование существующей инфраструктуры

Проверено (`src/ai/ai_fact.py`, `src/tool/fact/fact_collection_.py`, `py_modules/qdrant_/qdrant_.py`):
уже есть полностью параметризованный пайплайн факт-памяти, ничего писать с нуля не нужно.

- **`fact_collection_add()`** (`src/tool/fact/fact_collection_.py`) — пишет факт в MySQL `fact`
  (валидирует поля по allowlist из `fact_collection.field`, дедуп по `(collection_id, document, document_id)`).
- **`fact_qdrant_sync()`** (`src/ai/ai_fact.py`) — фоновая синхронизация несинхронизированных
  фактов в Qdrant батчами по 50 (через `qdrant_save()`).
- **`qdrant_fact_search()`** — семантический поиск + фильтры по тегам/полям, возвращает текст факта.

**Что нужно добавить:** одна новая `fact_collection` (например `dev_qa_memory`) с полями
`task_id (filter)`, `category (filter: bugfix/feature/incident)`, `summary (extract)`. Тонкий
CLI-скрипт-обёртка (`scripts/dev_qa_memory.py`) с двумя командами (`save-fact`, `search-facts`),
чтобы агент вызывал его через Bash одной командой, а не писал инлайн-Python каждый раз.

**Использование:**
- Developer перед реализацией — `search-facts "<текст задачи>"` за релевантным контекстом из
  прошлых решений, вместо полного повторного исследования репозитория.
- Developer после завершения — `save-fact` с кратким summary того, что сделано (накопление знаний).
- QA перед заведением задачи — `search-facts` на предмет "уже заводили такую же проблему?" (дедуп).

SQLite short-term memory (`py_modules/sqllite3/`) для этого не подходит как есть — она заточена под
`user_id + agent` (диалоговая история для Telegram), под dev/qa-петли не нужна: состояние сессии и
так живёт в MySQL `task`, а не в истории разговора.

## 7. Cronicle — триггеры

Cronicle заменяет кастомный supervisor-скрипт для "перезагрузки сессии каждые 2 часа" — просто
джоба, которая по расписанию запускает headless `claude -p`:

```
# Developer job (локальный Cronicle, порт 3012 на машине разработчика)
Schedule: */2 hours
Command:  claude -p "$(cat prompts/developer_loop.md)" --dangerously-skip-permissions
          (или без --dangerously-skip-permissions + настроенные permissions, см. §8)
CWD:      /home/vasyl/PycharmProjects/RhapsodyAi

# QA job (прод Cronicle)
Schedule: */15 minutes
Command:  claude -p "$(cat prompts/qa_sweep.md)"
CWD:      /path/to/prod/RhapsodyAi
```

Каждый запуск — новый процесс с чистым контекстом; персистентное состояние — в MySQL/Qdrant, не в
истории разговора.

## 8. Права доступа для безнадзорного запуска

Раз никто не подтверждает permission-промпты, нужна точечная настройка вместо `--dangerously-skip-permissions`
(см. `update-config`/`fewer-permission-prompts` скиллы) — в `.claude/settings.json` на каждой машине:

- Разрешить: `Bash(python3 -m pytest*)`, `Bash(git commit*)`, `Bash(git push origin feature/*)`,
  `Bash(gh pr create*)`, чтение/запись в MySQL `task`/`fact` через уже существующие репозитории.
- Запретить явно: `Bash(git push origin main)`, `Bash(git merge*)`, любые деструктивные команды
  (`rm -rf`, `docker system prune` и т.п.) — это техническое ограждение политики "PR-only", а не
  только текстовая инструкция в промпте.
- Для QA — разрешить только read-only команды (curl, docker ps, grep логов, mysql SELECT) и
  INSERT в `task`; никакого доступа на запись к коду или сервисам.

## 9. Developer — детальный флоу + Workflow-скрипт

```js
export const meta = {
  name: 'developer-loop',
  description: 'Обработать очередь готовых задач: контекст, реализация, PR',
  phases: [
    { title: 'Context', detail: 'семантический поиск фактов + точечное чтение репозитория' },
    { title: 'Implement', detail: 'реализация + прогон тестов' },
    { title: 'Ship', detail: 'commit в feature-ветку + PR (без мержа)' },
  ],
}

// args.tasks — задачи со статусом ready, полученные заранее через Bash/MySQL-запрос
const results = await pipeline(
  args.tasks,
  task => agent(
    `Найди в памяти (scripts/dev_qa_memory.py search-facts) контекст, релевантный задаче ` +
    `"${task.title}": ${task.description}. Прочитай только нужные файлы репозитория (glob/grep), ` +
    `не исследуй весь репозиторий с нуля. Верни краткий контекст для реализации.`,
    { phase: 'Context', label: `ctx:${task.id}` }
  ),
  (context, task) => agent(
    `Задача: ${task.description}\nКонтекст: ${context}\n` +
    `Реализуй по CLAUDE.md конвенциям, напиши/прогони тесты (python3 -m pytest). Не коммить.`,
    { phase: 'Implement', label: `impl:${task.id}`, isolation: 'worktree' }
    // worktree — задачи могут идти параллельно по стадиям, изоляция обязательна,
    // иначе конкурентные правки в одном рабочем каталоге друг друга затрут
  ),
  (implResult, task) => agent(
    `Закоммить в ветку feature/task-${task.id}, запушь, открой PR с описанием сделанного. ` +
    `НЕ мержи в main. После — сохрани факт о работе (scripts/dev_qa_memory.py save-fact) и ` +
    `отправь итог в Telegram (telegram_send_owner).`,
    { phase: 'Ship', label: `ship:${task.id}` }
  )
)

return results
```

Почему `pipeline`, а не последовательный цикл: задачи независимы друг от друга — пока одна ждёт
тестов, другая уже может собирать контекст. Барьер (`parallel`) тут не нужен, кросс-задачного
контекста между ними нет.

## 10. QA — детальный флоу + Workflow-скрипт

```js
export const meta = {
  name: 'qa-sweep',
  description: 'Проверка здоровья прод-окружения, заведение задач при находках',
  phases: [
    { title: 'Checks', detail: 'параллельные проверки здоровья' },
    { title: 'Report', detail: 'дедуп против памяти, заведение задач' },
  ],
}

const CHECKS = [
  { key: 'uvicorn_health', prompt: 'Проверь curl http://localhost:8011/health, распарси ответ.' },
  { key: 'docker_status', prompt: 'docker ps -a — все ожидаемые контейнеры должны быть Up.' },
  { key: 'error_logs', prompt: 'Проверь логи uvicorn/telegram за последний час на ERROR/CRITICAL.' },
  { key: 'db_connectivity', prompt: 'Проверь коннект к mysql/redis/qdrant (простой ping-запрос).' },
]

const findings = (await parallel(CHECKS.map(c => () =>
  agent(c.prompt, { phase: 'Checks', label: c.key, schema: FINDING_SCHEMA })
))).filter(Boolean)

const problems = findings.filter(f => f.status !== 'ok')
if (problems.length === 0) { log('всё штатно'); return { filed: [] } }

const filed = await pipeline(
  problems,
  p => agent(
    `Через scripts/dev_qa_memory.py search-facts проверь, заводили ли уже такую же проблему: ` +
    `${p.description}. Ответь, дубликат это или нет.`,
    { phase: 'Report', label: `dedup:${p.key}` }
  ),
  (dedup, p) => dedup.is_duplicate ? null : agent(
    `Заведи задачу в таблице task: source='qa', title=краткое, description="${p.description}". ` +
    `Не пытайся чинить сама, только зафиксируй.`,
    { phase: 'Report', label: `file:${p.key}` }
  )
)

return { filed: filed.filter(Boolean) }
```

QA не имеет тулов на запись кода/рестарт сервисов вообще — только bash для read-only диагностики
и INSERT в `task` (см. §8).

## 11. Telegram — приём и отчётность

- Приём: существующий бот (aiogram) + faster-whisper для голоса → черновик в `task` (`status=draft`).
- Редактирование: через бота или отдельную страницу в админке (TODO — решить конкретный UX).
- Отчётность: `telegram_send_owner()` (`src/telegram_/telegram_notify.py`) — уже готов, вызывается
  Developer-агентом на стадии Ship и (опционально) QA при найденных проблемах.

## 12. Открытые вопросы / TODO

- [ ] Миграция для таблицы `task` (см. §5) — согласовать финальную схему, добавить в `migrations/`.
- [ ] Новая `fact_collection` `dev_qa_memory` + `scripts/dev_qa_memory.py` (save-fact/search-facts).
- [ ] Точный UX редактирования черновиков задач в Telegram/админке.
- [ ] Cronicle job-конфиги (`prompts/developer_loop.md`, `prompts/qa_sweep.md`) — итоговые тексты промптов.
- [ ] `.claude/settings.json` на обеих машинах — точечные permissions (§8), проверить, что PR-политика
      технически enforced, а не только словами в промпте.
- [ ] Подтвердить на практике: не мешают ли параллельные Cronicle-сессии интерактивной работе в этой
      же Claude Team-организации (лимитов не найдено, но не проверено на реальной нагрузке).

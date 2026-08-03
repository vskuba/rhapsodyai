# Агентный плейбук: Почасовой список работ (ручной — после blueprint)

## Концепция

Список работ строится **на реальных данных**: аналогичные open-source проекты, публичные roadmap-ы конкурентов, данные о скорости команд из GitHub и Jira-отчётов. Агент не придумывает оценки — он находит прецеденты и масштабирует под конкретный стек и команду.

**Предусловие:** выполнены `planning_product.md` (есть MVP scope и бэклог фич) и `planning_tech.md` (есть архитектура и стек).

---

## Уровень 0 — Сбор прецедентов оценок (Estimation Benchmarks)

**Цель:** найти реальные данные о трудозатратах на аналогичные фичи и продукты.

**Действия агента:**

### Шаг 0.1 — Найти похожие open-source проекты с историей коммитов
WebSearch:
```
"{ниша OR ключевая фича}" open source GitHub
"{технология}" boilerplate starter template GitHub stars
"{тип продукта}" SaaS starter kit
site:github.com "{ниша}" "{стек технологий}"
```

WebFetch: страница репозитория на GitHub → вкладка Insights → Contributors → смотреть общий объём коммитов и временной span.

### Шаг 0.2 — Найти публичные данные о скорости разработки
WebSearch:
```
"{тип фичи}" how long to build developer hours
"{стек}" development time estimate
"built in X weeks" OR "took X months" "{тип продукта}"
site:indiehackers.com built {тип продукта} how long
site:reddit.com/r/SaaS built how long
```

### Шаг 0.3 — Найти отраслевые бенчмарки velocity
WebSearch:
```
software development velocity benchmark {стек}
"{тип задачи}" story points hours average
agile velocity benchmark "{размер команды}"
"{фреймворк}" development speed benchmark
"lines of code per day" "{стек технологий}"
```

WebFetch:
```
mckinsey.com/capabilities/mckinsey-digital/our-insights developer-velocity
linearb.io/blog/engineering-benchmarks
jellyfish.co/blog/engineering-benchmarks
```

### Шаг 0.4 — Найти примеры разбивки по ролям в аналогичных проектах
WebSearch:
```
"{тип продукта}" development team breakdown roles hours
"{стек}" project estimate breakdown frontend backend
"{тип продукта}" MVP time to build breakdown
site:upwork.com "{тип проекта}" hours estimate
```

**Выходной артефакт — Benchmark Foundation:**
```
Прецеденты похожих продуктов:
| Проект | Стек | Команда | Время до MVP | Источник |
|-------|------|---------|-------------|---------|
| {название} | {стек} | {N} чел | {X} мес / {Y} ч | {URL} |

Velocity бенчмарки ({стек}):
- Senior developer: {X}–{Y} ч/задача (источник: {URL})
- Backend задача среднего размера: {X} ч (бенчмарк: {URL})
- Frontend компонент: {X} ч (бенчмарк: {URL})
- Интеграция с внешним API: {X} ч (бенчмарк: {URL})
- Тест покрытие (unit + integration): {X}% от dev-времени (бенчмарк: {URL})
```

---

## Уровень 1 — Декомпозиция фич (Feature Breakdown)

**Цель:** разбить каждую фичу из MVP scope на атомарные задачи с ролью-исполнителем.

**Действия агента:**

### Шаг 1.1 — Взять MVP scope из planning_product.md
Из таблицы фич с MoSCoW взять все Must Have. Для каждой фичи:
- Описание поведения (что делает пользователь, что происходит в системе)
- Граничные условия (edge cases из отзывов конкурентов)

### Шаг 1.2 — Найти аналогичные задачи в публичных трекерах
WebSearch:
```
site:github.com/issues "{название фичи}" "{стек}"
"{фича}" implementation checklist developer
"{фича}" technical breakdown tasks
"{фича}" "{технология}" tutorial steps
```

WebFetch: issues на GitHub аналогичных проектов — смотреть labels, linked PRs, комментарии с оценками времени.

### Шаг 1.3 — Найти готовые чеклисты реализации
WebSearch:
```
"{фича}" implementation checklist
"{технология}" "{фича}" step by step developer guide
"{фича}" backend requirements list
"{фича}" frontend requirements list
```

**Выходной артефакт — Feature Decomposition:**
```
Фича: {название}

Backend задачи:
| # | Задача | Роль | Сложность | Зависит от |
|---|-------|------|----------|-----------|
| B1 | Создать модель данных | Backend | S | — |
| B2 | CRUD endpoints + валидация | Backend | M | B1 |
| B3 | Бизнес-логика | Backend | L | B1, B2 |
| B4 | Unit tests | Backend | S | B2, B3 |

Frontend задачи:
| # | Задача | Роль | Сложность | Зависит от |
|---|-------|------|----------|-----------|
| F1 | UI компоненты | Frontend | M | — |
| F2 | Интеграция с API | Frontend | S | B2, F1 |
| F3 | Состояние и кэш | Frontend | M | F2 |

DevOps/Infra:
| # | Задача | Роль | Сложность | Зависит от |
|---|-------|------|----------|-----------|
| D1 | Миграция БД | DevOps | S | B1 |
```

Сложность: S = до 4 ч, M = 4–8 ч, L = 8–16 ч, XL = 16–32 ч.

---

## Уровень 2 — Оценка в часах (Hour Estimation)

**Цель:** каждой задаче назначить конкретные часы с обоснованием из прецедентов.

**Действия агента:**

### Шаг 2.1 — Найти оценки по типу задачи
Для каждого типа задачи из уровня 1 WebSearch:
```
"{тип задачи}" "{стек}" developer hours estimate
how long to build "{компонент}" {технология}
"{задача}" time estimate backend developer
"{задача}" implementation time senior developer
```

### Шаг 2.2 — Найти оценки через аналогичные PR/commits
WebSearch:
```
site:github.com "{фича}" pull request merged "{стек}"
"{фича}" commit history time span
```

WebFetch: найденные PR — смотреть diff size, время от открытия до merge (= реальное время).

### Шаг 2.3 — Найти множители на code review и QA
WebSearch:
```
code review time percentage development
QA testing hours ratio development time
bug fixing overhead percentage development
technical debt overhead software project
```

**Выходной артефакт — Hour Estimates:**
```
Оценка часов по задачам (база — senior developer):

| ID | Задача | Роль | Оценка (ч) | Источник прецедента | Множитель QA |
|----|-------|------|-----------|--------------------|----|
| B1 | Модель данных | Backend | 3 | github.com/... PR #123 | +1 ч |
| B2 | CRUD endpoints | Backend | 6 | "{технология} CRUD estimate" benchmark | +2 ч |
| F1 | UI компоненты | Frontend | 8 | similar component time: {URL} | +2 ч |

Множители (применяются к base estimate):
- Code review: +{X}% (бенчмарк: {URL})
- QA & testing: +{X}% (бенчмарк: {URL})
- Документация: +{X}% (бенчмарк: {URL})
- Буфер на неожиданные сложности: +{X}% (бенчмарк: {URL})

Итоговая формула: estimate × (1 + code_review% + qa% + docs% + buffer%)
```

---

## Уровень 3 — Ролевая разбивка (Role Breakdown)

**Цель:** агрегировать часы по ролям, найти реальные данные о производительности каждой роли.

**Действия агента:**

### Шаг 3.1 — Найти benchmarks по ролям
Для каждой роли в команде WebSearch:
```
"{роль}" productivity benchmark developer
"{роль}" output per week software
senior vs junior "{роль}" productivity ratio
"{стек}" "{роль}" velocity benchmark
```

### Шаг 3.2 — Найти overhead по ролям (meetings, context switching)
WebSearch:
```
developer meeting overhead percentage
"{роль}" context switching cost time
startup developer overhead non-coding time
remote team communication overhead hours
```

WebFetch:
```
paulgraham.com/makersschedule.html
rework.fm developer meeting overhead
```

### Шаг 3.3 — Найти данные об эффективных часах в день
WebSearch:
```
developer effective hours per day productivity
"deep work" hours developer per day
software engineer actual coding hours day
knowledge worker productive hours research
```

**Выходной артефакт — Role Breakdown:**
```
Ролевая сводка:

| Роль | Всего задач | Сырые часы | Overhead ({X}%) | Эффект. часов/день | Рабочих дней | Рабочих недель |
|------|------------|-----------|----------------|-------------------|-------------|----------------|
| Backend | {N} | {X} ч | +{Y} ч = {Z} ч | {E} ч/день (источник: {URL}) | {D} | {W} |
| Frontend | {N} | {X} ч | +{Y} ч = {Z} ч | {E} ч/день | {D} | {W} |
| DevOps | {N} | {X} ч | +{Y} ч = {Z} ч | {E} ч/день | {D} | {W} |
| QA | {N} | {X} ч | +{Y} ч = {Z} ч | {E} ч/день | {D} | {W} |

Overhead sources:
- Meetings: {X}% (источник: {URL})
- Code review: {X}%
- Context switching: {X}%
- Коммуникация: {X}%

Итого overhead: {X}% от coding time
```

---

## Уровень 4 — Спринтовый план (Sprint Planning)

**Цель:** разложить задачи по спринтам с учётом зависимостей и параллельности.

**Действия агента:**

### Шаг 4.1 — Найти оптимальный размер спринта для стека
WebSearch:
```
"{стек}" sprint length recommendation
agile sprint "{тип продукта}" best practice
sprint velocity "{размер команды}" benchmark
"{стек}" release cycle best practice
```

### Шаг 4.2 — Найти примеры sprint planning для похожих продуктов
WebSearch:
```
"{тип продукта}" sprint plan example
SaaS MVP sprint breakdown example
"{стек}" agile roadmap example
startup sprint planning template
```

### Шаг 4.3 — Найти критический путь примеры
WebSearch:
```
software project critical path example
MVP critical path analysis
"{тип продукта}" dependency map development
```

**Выходной артефакт — Sprint Plan:**
```
Параметры спринтов:
- Длительность: {N} недель (бенчмарк для {стек}: {URL})
- Команда: {список ролей}
- Capacity: {X} ч/спринт суммарно

Sprint 1 (Неделя {A}–{B}): Фундамент
| ID | Задача | Роль | Ч | Зависит от | Параллельно с |
|----|-------|------|---|-----------|--------------|
| B1 | ... | Backend | 3 | — | F1 |
| F1 | ... | Frontend | 4 | — | B1 |
Итого: {X} ч | Занятость: Backend {X}%, Frontend {X}%

Sprint 2 (Неделя {C}–{D}): Ядро фич
...

Sprint N (Неделя {X}–{Y}): MVP Release
...

Критический путь:
B1 → B2 → B3 → [интеграционные тесты] → Release
Длина: {N} ч / {M} рабочих дней
```

---

## Уровень 5 — Финансовая оценка работ (Cost Estimation)

**Цель:** перевести часы в деньги с реальными ставками из рынка.

**Действия агента:**

### Шаг 5.1 — Найти рыночные ставки по ролям и регионам
Для каждой роли WebSearch:
```
"{роль}" hourly rate freelance {регион} {год}
"{роль}" contractor rate {стек} {год}
site:upwork.com "{роль}" "{стек}" hourly rate
site:toptal.com "{роль}" rate
site:glassdoor.com "{роль}" salary hourly equivalent {страна}
```

### Шаг 5.2 — Найти сравнение in-house vs freelance vs агентство
WebSearch:
```
freelance vs agency software development cost
in-house developer vs contractor cost comparison
"{стек}" development cost per hour comparison
offshore vs nearshore vs onshore developer rates
```

### Шаг 5.3 — Найти скрытые затраты
WebSearch:
```
hidden costs hiring developer startup
contractor overhead vs employee cost
software project hidden costs estimate
"{тип проекта}" budget overrun statistics
```

**Выходной артефакт — Cost Estimate:**
```
Стоимость по ролям:

| Роль | Часы | Ставка ($/ч) | Источник | Итого |
|------|------|-------------|---------|-------|
| Backend | {X} ч | ${Y}/ч | Upwork: {URL} | ${Z} |
| Frontend | {X} ч | ${Y}/ч | Glassdoor: {URL} | ${Z} |
| DevOps | {X} ч | ${Y}/ч | {URL} | ${Z} |
| QA | {X} ч | ${Y}/ч | {URL} | ${Z} |

Base estimate: ${X}
Буфер {Y}%: +${Z}
Итоговый бюджет: ${TOTAL}

Сценарии найма:
| Модель | Стоимость | Время | Риски |
|-------|----------|-------|-------|
| In-house | ${X} | {T} | высокий overhead, найм {N} нед |
| Freelance (Upwork) | ${X} | {T} | управление, качество |
| Агентство | ${X} | {T} | дороже, меньше контроля |
| Nearshore команда | ${X} | {T} | tz overlap {N} ч |

Рекомендация: {модель} потому что {обоснование из данных}
```

---

## Уровень 6 — Риски и буферы (Risk & Buffers)

**Цель:** найти реальные данные о перерасходе бюджета в аналогичных проектах.

**Действия агента:**

### Шаг 6.1 — Найти статистику overrun в software-проектах
WebSearch:
```
software project budget overrun statistics
MVP development time estimate accuracy
"{тип продукта}" development cost overrun
startup development estimate vs actual
software estimation accuracy research
```

WebFetch:
```
mckinsey.com/business-functions/mckinsey-digital/our-insights large-scale-it-projects
standishgroup.com/chaos-report
```

### Шаг 6.2 — Найти конкретные причины задержек
WebSearch:
```
software project delay reasons statistics
scope creep startup development
third-party API integration delays
"took longer than expected" developer reasons
```

### Шаг 6.3 — Найти best practice для buffer sizing
WebSearch:
```
software estimation buffer best practice
"PERT estimation" software project
agile buffer sprint capacity
"cone of uncertainty" software estimation
```

**Выходной артефакт — Risk Register:**
```
Статистика перерасхода (источник: {URL}):
- Средний overrun для {тип проекта}: {X}% бюджета / {Y}% сроков
- Топ причины: интеграции ({X}%), scope creep ({X}%), технические сложности ({X}%)

Риски проекта:
| Риск | Вероятность | Влияние (ч) | Митигация |
|------|------------|------------|----------|
| Интеграция с {внешний API} сложнее ожидаемого | средняя | +{X} ч | spike задача 4 ч |
| Смена требований по {фиче} | высокая | +{X} ч | freeze scope на Sprint 1–2 |
| {технология} unexpected behaviour | низкая | +{X} ч | PoC до старта |

Рекомендуемые буферы:
- Discovery buffer: {X} ч (spike на неизвестные зависимости)
- Integration buffer: {X} ч (бенчмарк: {X}% от integration tasks, источник: {URL})
- QA buffer: {X} ч
- Release buffer: {X} ч
- Общий буфер: {X}% (бенчмарк cone of uncertainty: {URL})
```

---

## Уровень 7 — Итоговый план работ (Master Work Plan)

**Цель:** сводная таблица всех задач с часами, ролями, сроками и стоимостью.

**Выходной артефакт — Master Work Plan:**

```
ИТОГОВЫЙ ПЛАН РАБОТ: {название продукта} MVP

────────────────────────────────────────────────────────────
СВОДКА
────────────────────────────────────────────────────────────
Всего задач: {N}
Суммарные часы (base): {X} ч
С overhead ({Y}%): {Z} ч
С буфером ({B}%): {TOTAL} ч
Команда: {роли}
Срок: {N} недель
Бюджет: ${X}–${Y}

────────────────────────────────────────────────────────────
ФАЗА 1: ФУНДАМЕНТ (Спринт 1–2, недели 1–{N})
────────────────────────────────────────────────────────────

| # | Фича | Задача | Роль | Ч | Статус |
|---|------|-------|------|---|-------|
| 1.1 | Auth | Модель User + JWT | Backend | 4 | — |
| 1.2 | Auth | Login/Register endpoints | Backend | 6 | — |
| 1.3 | Auth | Форма входа/регистрации | Frontend | 5 | — |
| 1.4 | Infra | Docker + CI/CD | DevOps | 8 | — |
| ... | | | | | |

Итого фаза 1: {X} ч | Backend: {X} ч | Frontend: {X} ч | DevOps: {X} ч

────────────────────────────────────────────────────────────
ФАЗА 2: ЯДРО ПРОДУКТА (Спринт 3–5, недели {A}–{B})
────────────────────────────────────────────────────────────

| # | Фича | Задача | Роль | Ч | Статус |
|---|------|-------|------|---|-------|
...

Итого фаза 2: {X} ч

────────────────────────────────────────────────────────────
ФАЗА 3: РЕЛИЗ (Спринт 6–7, недели {A}–{B})
────────────────────────────────────────────────────────────

| # | Фича | Задача | Роль | Ч | Статус |
|---|------|-------|------|---|-------|
| 3.1 | QA | End-to-end тесты | QA | 16 | — |
| 3.2 | Launch | Production deploy | DevOps | 8 | — |
| 3.3 | Launch | Мониторинг и алерты | DevOps | 6 | — |
...

────────────────────────────────────────────────────────────
ФИНАНСОВАЯ СВОДКА
────────────────────────────────────────────────────────────

| Роль | Часы | Ставка | Сумма |
|------|------|--------|-------|
| Backend | {X} | ${Y}/ч | ${Z} |
| Frontend | {X} | ${Y}/ч | ${Z} |
| DevOps | {X} | ${Y}/ч | ${Z} |
| QA | {X} | ${Y}/ч | ${Z} |
| ИТОГО | {X} | — | ${TOTAL} |
| + Буфер {B}% | +{Y} ч | — | +${BUF} |
| БЮДЖЕТ | {Z} ч | — | ${FINAL} |

────────────────────────────────────────────────────────────
MILESTONES
────────────────────────────────────────────────────────────

| Milestone | Неделя | Критерий готовности |
|----------|--------|---------------------|
| Foundation ready | {N} | Auth работает, CI/CD зелёный |
| Feature complete | {N} | Все Must Have задачи закрыты |
| QA passed | {N} | 0 критических багов |
| MVP Live | {N} | Production deploy |
```

---

## Карта уровней

```
[0] Estimation Benchmarks — реальные прецеденты времени разработки
    ↓
[1] Feature Breakdown — атомарные задачи с ролями и зависимостями
    ↓
[2] Hour Estimation — часы с обоснованием из прецедентов + множители
    ↓
[3] Role Breakdown — агрегация по ролям + overhead
    ↓
[4] Sprint Planning — распределение по спринтам с учётом критического пути
    ↓
[5] Cost Estimation — часы в деньги по рыночным ставкам
    ↓
[6] Risk & Buffers — буферы из статистики overrun реальных проектов
    ↓
[7] Master Work Plan — итоговая таблица всего
```

---

## Правила качества

1. **Каждая оценка — с прецедентом или источником.** «Примерно 8 часов» без обоснования — не оценка.

2. **Зависимости обязательны.** Без dependency map критический путь не виден и сроки будут неверные.

3. **Overhead не игнорировать.** Реальное dev-время ≠ coding time. Meetings + review + context switch = типично 30–40% потерь.

4. **Три уровня детализации:** сначала фичи → потом задачи → потом подзадачи. Не детализировать глубже чем до 4 часов.

5. **Буфер — не опционален.** Данные McKinsey: 45% software-проектов превышают бюджет. Буфер 20–30% = норма, не жадность.

6. **Статус отслеживать в том же документе.** Колонка Status меняется по ходу работы — план живёт вместе с проектом.

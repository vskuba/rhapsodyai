# Индекс агентных плейбуков

Система взаимосвязанных плейбуков для AI-агента — от исследования рынка до масштабирования. Каждый плейбук содержит **конкретные WebSearch/WebFetch действия**, а не абстрактные вопросы.

**Принцип:** агент не отвечает из своих знаний — он ищет реальные примеры, собирает реальные метрики, строит вывод на найденных данных.

---

## Автоматизированные плейбуки

Используются в Cronicle-кронджобах. `research_goal` и `initial_query` генерируются LLM под конкретный продукт; плейбуки — эталон методологии.

| # | Файл | Фаза системы | Назначение | Ключевые источники данных |
|---|------|-------------|-----------|--------------------------|
| 1 | [planning_research.md](planning_research.md) | `market` | Анализ конкурентов, TAM/SAM/SOM, тренды, незанятые ниши | SimilarWeb, G2, Crunchbase, Google Trends |
| 2 | [planning_product.md](planning_product.md) | `product` | Боли пользователей, MVP scope, бэклог фич с ICE | G2/Capterra отзывы, Reddit, Product Hunt |
| 3 | [planning_tech.md](planning_tech.md) | `tech` | Стек, компоненты, ADR, оценка сложности | GitHub, StackOverflow, официальная документация |
| 4 | [planning_gtm.md](planning_gtm.md) | `gtm` | ICP, каналы по трафику конкурентов, CAC бенчмарки | SimilarWeb, Facebook Ads Library, baremetrics |
| 5 | [planning_financial.md](planning_financial.md) | `financial` | Unit-экономика, бенчмарки SaaS, зарплаты, P&L | Glassdoor, Baremetrics, Crunchbase, AWS calculator |
| 6 | [planning_launch.md](planning_launch.md) | `supplement_launch` | Founding users, Product Hunt, пресса, PMF сигналы | Product Hunt, useronboard.com, baremetrics |

---

## Ручные плейбуки (не автоматизированы)

Запускаются вручную после утверждения Blueprint. Фазы `design` и `workload` есть в UI как плейсхолдеры.

| Файл | Когда | Назначение | Ключевые источники |
|------|-------|-----------|-------------------|
| [planning_workload.md](planning_workload.md) | После blueprint | Декомпозиция фич, оценка часов по ролям, спринты, бюджет | GitHub PRs, Upwork rates, McKinsey/Standish benchmarks |
| [planning_design.md](planning_design.md) | После workload | Дизайн-система, карта страниц, спеки экранов, landing, dashboard | Dribbble, Mobbin, GoodUI, useronboard.com |
| [planning_experiments.md](planning_experiments.md) | После запуска (реальные пользователи) | A/B тесты с реальными калькуляторами и прецедентами | goodui.org, CXL, evanmiller.org calculator |

---

## Автоматизированный маршрут системы

```
analyze → market → product → tech → gtm → financial → blueprint → score
                                                                      ↓
                                           supplements (параллельно): market · product · tech · gtm · financial · launch
```

**Что делает каждая автоматизированная фаза:**
1. `analyze` — анализирует саму идею: суть, аудитория, риски, рекомендации (без интернета)
2. `market` → `planning_research.md` — находит конкурентов с трафиком, TAM/SAM/SOM, тренды
3. `product` → `planning_product.md` — извлекает боли из G2/Reddit, формирует MVP scope
4. `tech` → `planning_tech.md` — выбирает стек с обоснованием, open-source аналоги на GitHub
5. `gtm` → `planning_gtm.md` — ICP в LinkedIn, каналы по SimilarWeb конкурентов
6. `financial` → `planning_financial.md` — бенчмарки из baremetrics, зарплаты из Glassdoor
7. `blueprint` — сводный документ из всех фаз (без интернета)
8. `score` — оценка рынка/реализуемости/финансов 1-10 + вердикт go/maybe/no
9. `supplement_*` — детализация каждого направления через свежий интернет-поиск

## Маршрут для ручных фаз

### Новая фича в существующем продукте
```
experiments (наблюдение) → product (уровень 6–8) → tech → launch (фазы 3–5)
```

### Анализ конкурента
```
planning_research.md (фаза 1–3) → planning_gtm.md (фаза 2) → planning_financial.md (уровень 0)
```

---

## Связи между плейбуками

```
[research] ──→ [product]    (Pain Registry питает MVP scope)
     │    ──→  [gtm]        (ICP и конкуренты питают channels)
     └────→    [financial]  (цены конкурентов питают ARPU)

[product] ──→ [tech]        (требования питают архитектуру)
          ──→ [launch]      (MVP определяет что запускаем)

[gtm] ──→ [launch]          (каналы и messaging используются при запуске)
      ──→ [financial]       (CAC по каналам питают unit-экономику)

[blueprint] ──→ [workload]  (фичи из blueprint питают оценку трудозатрат)
[workload]  ──→ [design]    (scope определяет какие экраны проектировать)

[experiments] ←──→ все     (замыкает петлю обучения — питается из всех)
```

---

## Выходные артефакты

| Плейбук | Выходной артефакт системы |
|---------|--------------------------|
| research (market) | market-фаза: конкуренты + трафик + TAM/SAM/SOM |
| product | product-фаза: Feature Backlog с ICE + MVP scope |
| tech | tech-фаза: ADR + Tech Stack с обоснованием |
| gtm | gtm-фаза: Channel Strategy + ICP + Messaging |
| financial | financial-фаза: Unit Economics + P&L 3 сценария |
| blueprint (auto) | Blueprint-документ: сводный MD ~3000 слов |
| score (auto) | Оценки 1-10 + вердикт + summary в project |
| supplement_launch | Supplement-документ: Launch Day Plan + PMF Dashboard |
| workload (ручной) | Master Work Plan: задачи + часы + спринты + бюджет |
| design (ручной) | Design Brief: дизайн-система + спеки экранов |
| experiments (ручной) | Pattern Library + Experiment Log с результатами |

---

## Правила работы агента

1. **Каждый факт = URL источника.** Без источника — не включать в выходной документ.

2. **Реальный пример ценнее теории.** Один работающий сайт с 50K посетителей > аналитический отчёт.

3. **Бенчмарки обязательны.** Каждая цифра сравнивается с рыночным бенчмарком.

4. **Google Trends всегда.** Без него нельзя понять направление рынка.

5. **Данные устаревают.** Фиксировать дату источника. Данные старше 18 месяцев — перепроверять.

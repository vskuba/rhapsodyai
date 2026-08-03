# Агентный плейбук финансового планирования (фаза: financial)

## Концепция

Плейбук для фазы **financial** AI-планировщика. Финансовый план строится **на реальных данных рынка**: цены конкурентов, публичные бенчмарки SaaS-метрик, реальные зарплаты, стоимость инфраструктуры. Агент не придумывает цифры — он находит их из открытых источников и строит модель на их основе.

**Предусловие:** фазы `market`, `gtm` выполнены — есть цены конкурентов и бенчмарки CAC.

---

## Уровень 0 — Сбор финансовых данных рынка (Market Data Collection)

**Цель:** собрать реальные цифры из открытых источников — до начала моделирования.

**Действия агента:**

### Шаг 0.1 — Найти данные о ценах конкурентов
Из `planning_research.md` (фаза 7) взять таблицу тарифов.

Для конкурентов без публичных цен WebSearch:
```
"{конкурент}" pricing
"{конкурент}" how much does it cost
"{конкурент}" price per month
"{конкурент}" "starts at $"
site:reddit.com "{конкурент}" price
```

### Шаг 0.2 — Найти SaaS-бенчмарки для категории
WebFetch ключевых ресурсов с открытыми данными:

```
baremetrics.com/resources/saas-benchmarks
openviewpartners.com/saas-benchmarks
profitwell.com/recur/churn-rate-benchmarks
chartmogul.com/saas-benchmarks-report
saastr.com/category/benchmarks
```

WebSearch:
```
"{ниша}" SaaS benchmarks {год}
"{ниша}" average ARPU
"{ниша}" churn rate average
"{ниша}" LTV CAC ratio benchmark
SaaS gross margin benchmark "{ниша}"
```

### Шаг 0.3 — Найти данные о выручке конкурентов
WebSearch:
```
"{конкурент}" ARR revenue
"{конкурент}" annual recurring revenue million
"{конкурент}" how much revenue
site:latka.com "{конкурент}"
site:crunchbase.com "{конкурент}" revenue
```

WebFetch: `getlatka.com/companies/{slug}` — если доступно.

### Шаг 0.4 — Найти стоимость инфраструктуры
WebFetch страниц pricing облачных провайдеров:
- `aws.amazon.com/pricing/` — EC2, RDS, S3
- `cloud.google.com/pricing` — Compute, Cloud SQL
- `azure.microsoft.com/pricing` — Virtual Machines, SQL

WebSearch:
```
AWS cost calculator "{тип продукта}"
"{стек технологий}" hosting cost monthly
"{тип продукта}" infrastructure cost per user
```

### Шаг 0.5 — Найти стоимость LLM/AI API (для AI-продуктов)
WebFetch актуальных страниц pricing:
```
anthropic.com/pricing
openai.com/pricing
```

WebSearch:
```
"{модель}" tokens per request average
"{usecase}" average token consumption
"{модель}" cost per 1000 requests
AI API cost calculator
```

**Выходной артефакт — Data Foundation:**
```
Данные конкурентов:
| Конкурент | Мин. цена | Макс. цена | ARR (если известно) | Источник |
|----------|----------|----------|--------------------|----|

SaaS-бенчмарки ({ниша}):
- Avg ARPU: ${X}/мес (источник: {URL})
- Avg churn: {X}%/мес (источник: {URL})
- Avg CAC: ${X} (источник: {URL})
- Avg Gross Margin: {X}% (источник: {URL})
- Avg LTV/CAC: {X}x (источник: {URL})

Инфраструктура (оценка при N клиентах):
- Hosting: ${X}/мес (источник: AWS calculator)
- AI API: ${X}/мес при X запросах (источник: {URL})
```

---

## Уровень 1 — Unit-экономика (Unit Economics)

**Цель:** рассчитать экономику одного клиента на основе реальных данных.

**Действия агента:**

### Шаг 1.1 — Определить ARPU
Из данных конкурентов (уровень 0) и позиционирования:
- Если наша цена выше — обоснование: {какой gap закрываем}
- Если ниже — обоснование: {какой сегмент берём}

### Шаг 1.2 — Рассчитать CAC по каналам
Из `planning_gtm.md` (фаза 3) взять бенчмарки CAC.

Дополнительно WebSearch:
```
"{канал}" CAC benchmark B2B SaaS
"{ниша}" cost per lead {канал}
"{ниша}" paid search CPC
"content marketing" CAC benchmark SaaS
```

### Шаг 1.3 — Найти gross margin бенчмарки
WebSearch:
```
SaaS gross margin benchmark by category
"{ниша}" gross margin average
software company gross margin {год}
AI SaaS gross margin
site:meritech.com SaaS gross margin
```

### Шаг 1.4 — Рассчитать COGS на клиента
Из данных уровня 0:
- Hosting cost per customer = Total hosting / Expected customers
- AI API cost per customer = Avg requests × cost per request
- Support cost per customer = Support team cost / Customer count

**Выходной артефакт:**
```
Unit Economics:

ARPU: ${X}/мес
Обоснование: конкуренты берут ${Y}–${Z} (источник: {URL}), мы позиционируемся {выше/ниже} потому что {gap}

COGS per customer:
- Hosting: ${X}/мес
- AI API: ${X}/мес (при {N} запросах, источник: {URL})
- Support: ${X}/мес (оценка)
- Total COGS: ${X}/мес

Gross Margin: {(ARPU - COGS) / ARPU × 100}%
Бенчмарк рынка: {X}% (источник: {URL})

CAC по каналам:
- SEO/Organic: ${X} (бенчмарк: {URL})
- Paid: ${X} (бенчмарк: {URL})
- Blended CAC: ${X}

LTV = ARPU × Gross Margin% / Churn Rate = ${X}
LTV/CAC = {X}x (цель: >3x, бенчмарк: {URL})
Payback Period = CAC / (ARPU × GM%) = {X} мес
```

---

## Уровень 2 — Модель выручки (Revenue Model)

**Цель:** построить MRR waterfall на 24 месяца с обоснованными темпами роста.

**Действия агента:**

### Шаг 2.1 — Найти бенчмарки роста в нише
WebSearch:
```
"{ниша}" SaaS growth rate benchmark
early stage SaaS MoM growth average
"{ниша}" customer acquisition rate typical
seed stage SaaS growth benchmark
site:openviewpartners.com growth benchmarks
```

### Шаг 2.2 — Найти публичные данные о росте конкурентов
WebSearch:
```
"{конкурент}" growth rate customers
"{конкурент}" "from X to Y customers"
"{конкурент}" growth story timeline
"{конкурент}" milestone ARR timeline
```

### Шаг 2.3 — Найти данные о churn
Из `planning_gtm.md` (фаза 7) взять бенчмарки churn.

Уточнить для конкретной категории:
```
"{ниша}" monthly churn rate
"{тип клиента}" SaaS churn benchmark
SMB vs enterprise churn rate comparison
```

**Выходной артефакт:**
```
Revenue Model Assumptions:

Начальные клиенты (M1): {N} (источник: founding users план)
MoM growth rate: {X}% (бенчмарк для early-stage {ниша}: {Y}%, источник: {URL})
Monthly churn: {X}% (бенчмарк: {Y}%, источник: {URL})
Expansion MRR: {X}% (upsell rate бенчмарк: {URL})

MRR Waterfall (ключевые milestone):
- M6: ${X} MRR ({N} клиентов)
- M12: ${X} MRR ({N} клиентов)
- M24: ${X} MRR = ${Y} ARR

Milestones:
- $1K MRR: Месяц {N}
- $10K MRR: Месяц {N}
- $100K MRR: Месяц {N}
- $1M ARR: Месяц {N}
```

---

## Уровень 3 — Структура затрат (Cost Structure)

**Цель:** найти реальные данные о зарплатах и стоимости инструментов.

**Действия агента:**

### Шаг 3.1 — Найти зарплатные данные
Для каждой роли в команде WebSearch:
```
"{роль}" salary {город/страна} {год}
"{роль}" remote salary
site:glassdoor.com "{роль}" "{ниша OR город}"
site:levels.fyi "{роль}"
site:linkedin.com/salary "{роль}"
"{роль}" compensation benchmark startup
```

### Шаг 3.2 — Найти стоимость SaaS-инструментов
WebFetch pricing страниц для каждого инструмента в стеке:
- CRM: HubSpot / Pipedrive / Salesforce
- Analytics: Mixpanel / Amplitude / PostHog
- Support: Intercom / Zendesk / Linear
- Hosting: из уровня 0

### Шаг 3.3 — Найти AI cost модели
WebSearch:
```
"{модель LLM}" cost calculator
"{продукт}" AI costs per user
LLM cost optimization {ниша}
"{провайдер}" pricing calculator
```

WebFetch: официальные калькуляторы цен LLM-провайдеров.

### Шаг 3.4 — Найти бенчмарки распределения расходов
WebSearch:
```
SaaS operating expenses breakdown benchmark
R&D vs S&M vs G&A ratio SaaS
"rule of 40" SaaS cost structure
startup burn rate benchmark by stage
```

**Выходной артефакт:**
```
Cost Structure:

Команда (план найма):
| Роль | Месяц найма | Зарплата | Источник данных |
|------|------------|---------|----------------|
| CTO | M1 | ${X}/мес | Glassdoor: {URL} |
| Developer | M3 | ${X}/мес | Levels.fyi: {URL} |

SaaS-инструменты:
| Инструмент | Цена | При N клиентах |
|-----------|------|---------------|

COGS (переменные затраты):
- Hosting: ${X}/мес при {N} клиентах
- AI API: ${X}/мес (${Y} per client)
- Support tools: ${X}/мес

Целевое распределение OpEx:
- R&D: {X}% (бенчмарк SaaS: 25–40%, источник: {URL})
- S&M: {X}% (бенчмарк: 20–35%, источник: {URL})
- G&A: {X}% (бенчмарк: 10–20%, источник: {URL})
```

---

## Уровень 4 — P&L (Profit & Loss)

**Цель:** построить P&L с тремя сценариями, используя реальные бенчмарки.

**Действия агента:**

### Шаг 4.1 — Найти реальные примеры P&L стартапов в нише
WebSearch:
```
"{ниша}" startup financials public
"{конкурент}" revenue costs breakdown
SaaS P&L example {год}
"{ниша}" unit economics case study
site:saastr.com "{ниша}" financials
```

### Шаг 4.2 — Найти бенчмарки Gross Margin для категории
WebSearch:
```
SaaS gross margin benchmark {год}
"{ниша}" gross margin average
AI product gross margin
infrastructure-heavy SaaS gross margin
site:meritech.com saas gross margins
```

### Шаг 4.3 — Найти "Rule of 40" данные для категории
WebSearch:
```
"{ниша}" rule of 40
SaaS rule of 40 benchmark
"{конкурент}" revenue growth EBITDA
```

**Выходной артефакт:**
```
P&L Summary (M12):

Base Scenario:
Revenue: ${X}
COGS: ${X} (Gross Margin: {X}% vs бенчмарк {Y}%, источник: {URL})
OpEx: ${X}
EBITDA: ${X} ({X}%)
Burn: ${X}/мес

Optimistic (+30% growth, -20% churn):
Revenue: ${X}
EBITDA: ${X}

Pessimistic (-30% growth, +50% churn):
Revenue: ${X}
EBITDA: ${X}
Runway impact: -{N} мес

Ключевые предположения:
- ARPU: ${X} (обосн: цены конкурентов {URL})
- Churn: {X}% (обосн: бенчмарк {URL})
- CAC: ${X} (обосн: {URL})
```

---

## Уровень 5 — Cash Flow и Runway

**Цель:** понять реальный runway и точку безубыточности.

**Действия агента:**

### Шаг 5.1 — Найти стартовый капитал (если bootstrap)
Из планов команды и инфраструктуры рассчитать минимальный burn.

### Шаг 5.2 — Найти бенчмарки runway
WebSearch:
```
startup runway benchmark months
pre-seed seed runway typical
"{ниша}" startup how much runway needed
"how long to profitable" SaaS {ниша}
```

### Шаг 5.3 — Найти benchmark break-even timing
WebSearch:
```
SaaS break-even timeline bootstrap
"{ниша}" profitability timeline
bootstrap SaaS "profitable in" months
"{ниша}" when profitable startup
```

**Выходной артефакт:**
```
Cash Flow & Runway:

Стартовый капитал: ${X}
Начальный burn: ${X}/мес
Текущий runway: {X} мес

Break-even при базовом сценарии: Месяц {N} (при {M} клиентах)
Break-even бенчмарк для {ниша}: {X} мес (источник: {URL})

Funding Trigger: начинать fundraise в Месяц {N}
(за 6–9 мес до исчерпания = при {X} мес runway остатке)
```

---

## Уровень 6 — Стратегия финансирования (Fundraising)

**Цель:** найти реальные данные о раундах в нише и оценках.

**Действия агента:**

### Шаг 6.1 — Найти раунды финансирования в нише
WebSearch:
```
"{ниша}" seed funding {год}
"{ниша}" pre-seed round size
"{ниша}" startup raised million {год}
site:crunchbase.com "{ниша}" seed round
site:techcrunch.com "{ниша}" raises
```

WebFetch: результаты поиска на Crunchbase для компаний в нише — фильтр по стадии и году.

### Шаг 6.2 — Найти типичные оценки (valuation)
WebSearch:
```
"{ниша}" pre-seed valuation multiple
"seed round" "{ниша}" valuation {год}
SaaS ARR multiple valuation {год}
"{ниша}" startup valuation benchmark
site:meritech.com SaaS multiples
site:bessemervp.com SaaS multiples
```

### Шаг 6.3 — Найти инвесторов, которые инвестируют в нишу
WebSearch:
```
"{ниша}" VC investors
"{конкурент}" investors crunchbase
"{ниша}" accelerator program
"invested in" "{ниша}" site:crunchbase.com
```

WebFetch: `crunchbase.com/hub/investors-in-{категория}` — если доступно.

**Выходной артефакт:**
```
Fundraising Strategy:

Раунды в нише (последние 12 мес):
| Компания | Стадия | Размер | Оценка | Инвесторы | Источник |
|---------|--------|-------|--------|----------|---------|

Типичный размер раунда для {ниша}:
- Pre-seed: ${X}–${Y} (источник: {URL})
- Seed: ${X}–${Y} (источник: {URL})

ARR multiple для {ниша}: {X}x (источник: {URL})
Оценка при $100K ARR: ${X}M (при {X}x multiple)

Целевые инвесторы (инвестируют в нишу):
| Фонд | Портфельные компании в нише | Тезис | Контакт |
|-----|---------------------------|-------|--------|
```

---

## Уровень 7 — Финансовый контроль (Financial Controls)

**Цель:** настроить мониторинг метрик с первого дня.

**Действия агента:**

### Шаг 7.1 — Найти инструменты финансового мониторинга
WebSearch:
```
SaaS financial dashboard tools
MRR tracking software {ниша}
ChartMogul vs Baremetrics vs ProfitWell comparison
stripe revenue analytics
```

WebFetch pricing страниц инструментов мониторинга.

### Шаг 7.2 — Найти шаблоны финансовой отчётности
WebSearch:
```
SaaS financial dashboard template
MRR waterfall spreadsheet template free
startup financial report template
```

**Выходной артефакт:**
```
Financial Control Stack:
- MRR tracking: {инструмент + цена} | Источник сравнения: {URL}
- Accounting: {инструмент}
- Payroll: {инструмент}

Weekly KPI Dashboard:
| Метрика | Цель | Красная линия | Источник бенчмарка |
|---------|------|--------------|-------------------|
| MRR | +{X}% | -{X}% | {URL} |
| Churn | <{X}% | >{X}% | {URL} |
| Runway | >{N} мес | <{N} мес | |
```

---

## Уровень 8 — Сценарный анализ (Scenario Planning)

**Цель:** подготовить план Б на основе реальных рисков в нише.

**Действия агента:**

### Шаг 8.1 — Найти реальные "black swan" события в нише
WebSearch:
```
"{ниша}" startup failed why
"{ниша}" company shutdown reason
"{конкурент}" crisis OR problem {год}
"{ниша}" market downturn impact
LLM API price increase impact SaaS
```

### Шаг 8.2 — Найти план Б примеры
WebSearch:
```
SaaS pivot successful example
startup reduced burn rate how
"{ниша}" bootstrap after failed fundraise
startup runway extension strategy
```

**Выходной артефакт:**
```
Scenario Analysis:

Black Swan риски (из реальных случаев в нише):
| Риск | Пример | Вероятность | Plan Б |
|------|--------|------------|--------|
| LLM API цена ×3 | {прецедент, URL} | средняя | кэшировать, альт. модель |
| Конкурент копирует | {прецедент, URL} | высокая | ускорить дифференциатор |

Decision Rules:
- Если churn > {X}% за 2 месяца → {действие}
- Если runway < {N} мес → начать fundraise / cut burn
- Если CAC > LTV → остановить paid, фокус на organic
```

---

## Уровень 9 — Стратегия выхода (Exit Strategy)

**Цель:** найти реальные прецеденты M&A и IPO в нише.

**Действия агента:**

### Шаг 9.1 — Найти M&A прецеденты
WebSearch:
```
"{ниша}" acquisition {год}
"{конкурент}" acquired by
"{ниша}" M&A deal {год}
"{ниша}" strategic acquirer
site:crunchbase.com "{ниша}" acquisitions
```

### Шаг 9.2 — Найти ARR multiples для выхода
WebSearch:
```
SaaS acquisition multiple {год}
"{ниша}" acquisition price ARR multiple
"{конкурент}" acquired for million ARR
strategic acquisition premium {ниша}
site:meritech.com EV/Revenue multiples
```

### Шаг 9.3 — Найти потенциальных покупателей
WebSearch:
```
"{большая компания}" acqui-hire OR acquisition {ниша}
who would buy {ниша} company
"{платформа}" partners acquisitions strategy
"{смежная компания}" M&A history
```

**Выходной артефакт:**
```
Exit Strategy:

M&A прецеденты в нише:
| Компания | Покупатель | Сумма | ARR multiple | Дата | Источник |
|---------|-----------|-------|-------------|------|---------|

Текущие ARR multiples: {X}x (источник: {URL}, дата: {дата})
Оценка при $1M ARR: ${X}M

Потенциальные покупатели:
| Компания | Почему купит | Прецеденты | Синергия |
|---------|------------|-----------|---------|

Условия для привлекательного exit:
- NRR > {X}% (источник: {URL})
- Gross Margin > {X}% (источник: {URL})
- Уникальные данные / IP
```

---

## Карта уровней

```
[0] Market Data Collection — реальные цены, бенчмарки, стоимость инфры
    ↓
[1] Unit Economics — LTV/CAC из реальных данных
    ↓
[2] Revenue Model — темпы роста из бенчмарков
    ↓
[3] Cost Structure — зарплаты из Glassdoor, инструменты из pricing pages
    ↓
[4] P&L — три сценария с реальными бенчмарками GM
    ↓
[5] Cash Flow & Runway — break-even из реальных примеров
    ↓
[6] Fundraising — размеры раундов и оценки из Crunchbase
    ↓
[7] Financial Controls — инструменты мониторинга
    ↓
[8] Scenario Analysis — риски из реальных случаев в нише
    ↓
[9] Exit Strategy — M&A прецеденты и multiples
```

---

## Правила качества

1. **Каждая цифра — с источником.** ARPU "выбранный" без обоснования — это не финмодель.

2. **Три сценария обязательны.** Один сценарий = wishful thinking.

3. **AI costs считать отдельно.** При росте запросов стоимость LLM может вырасти нелинейно.

4. **Зарплаты — из Glassdoor/Levels.fyi.** Не "примерно", а реальные рыночные данные.

5. **M&A multiples устаревают.** Проверять на актуальность — рынок меняется ежеквартально.

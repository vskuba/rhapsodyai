# Агентный плейбук Go-to-Market (фаза: gtm)

## Концепция

Этот документ — пошаговый плейбук для фазы **gtm** AI-планировщика. GTM строится **на реальных данных**: где ICP находится онлайн, как говорят конкуренты, что работает в каналах. Агент не придумывает стратегию — он находит доказательства того, что уже работает на рынке.

**Предусловие:** фазы `market`, `product` выполнены — есть карточки конкурентов, трафик, Pain Registry.

---

## Фаза 0 — Проверка готовности (GTM Readiness)

**Цель:** убедиться, что продукт и данные готовы к GTM.

**Действия агента:**

### Шаг 0.1 — Проверить наличие входных данных из исследования
Из `planning_research.md` должны быть готовы:
- Таблица конкурентов с трафиком (фаза 1–2)
- Pain Registry (фаза 3–5)
- Профиль клиента (фаза 6)
- Данные о ценообразовании (фаза 7)

### Шаг 0.2 — Найти чек-лист GTM readiness реальных компаний
WebSearch:
```
GTM readiness checklist SaaS
"go to market" checklist B2B startup
pre-launch checklist {ниша} startup
```

**Выходной артефакт:**
```
GTM Readiness Check:
[ ] Данные о ≥5 конкурентах с трафиком: {да/нет}
[ ] ≥15 задокументированных болей с источниками: {да/нет}
[ ] ICP профиль с реальными примерами: {да/нет}
[ ] MVP работает end-to-end: {да/нет}
[ ] Способ принять оплату: {да/нет}
```

---

## Фаза 1 — Идеальный клиент (ICP Definition)

**Цель:** найти реальных людей, которые являются ICP, — не придумать персонаж.

**Действия агента:**

### Шаг 1.1 — Найти реальных покупателей в LinkedIn
WebSearch (адаптировать `{роль}` и `{ниша}` из исследования):
```
site:linkedin.com/in "{роль}" "{ниша}"
site:linkedin.com "{должность}" "{индустрия}"
"{роль}" "{ниша}" profile linkedin
```

WebFetch: `linkedin.com/search/results/people/?keywords={роль}+{ниша}` — посмотреть, кто есть.

Зафиксировать:
- Типичные должности
- Размер компаний
- Индустрии
- Локации

### Шаг 1.2 — Найти ICP в сообществах
WebSearch:
```
"{ниша}" community slack OR discord OR reddit
"{целевая аудитория}" online community forum
"{роль}" subreddit site:reddit.com
"{индустрия}" professional community
```

WebFetch: найденные сообщества — посмотреть, кто участвует, что обсуждают.

### Шаг 1.3 — Найти ICP через вакансии (кто нанимает таких людей)
WebSearch:
```
site:linkedin.com/jobs "{роль}" "{ниша}"
"{роль}" "{ниша}" job description requirements
```

Из описаний вакансий — кто такой ICP в деталях (стек, обязанности, контекст работы).

### Шаг 1.4 — Проверить, кто отзывается на конкурентов
WebFetch: G2/Capterra страницы топ-конкурентов — раздел "Reviewer Details":
- Роль рецензентов
- Размер компании
- Индустрия

**Выходной артефакт:**
```
ICP Definition (основан на реальных данных):

Роль: {должность} | Источник: LinkedIn ({N} профилей)
Индустрия: {список} | Источник: G2 отзывы (URL)
Размер компании: {X–Y сотрудников} | Источник: Capterra (URL)
Локация: {регион} | Источник: SimilarWeb трафик конкурентов

Где находятся онлайн:
- Reddit: r/{subreddit} ({N} участников)
- Slack/Discord: {название}, {URL}
- LinkedIn группа: {название}

Trigger events (из форумов):
- {событие} → начинают искать решение | Источник: {URL}

Anti-ICP (кому НЕ продаём):
- {критерий} — потому что {данные}
```

---

## Фаза 2 — Позиционирование и сообщения (Positioning & Messaging)

**Цель:** сформулировать сообщения на языке клиента — используя его собственные слова из отзывов и форумов.

**Действия агента:**

### Шаг 2.1 — Собрать язык клиентов из публичных источников
Из Pain Registry и форумных обсуждений извлечь:
- Конкретные фразы, которые клиенты используют для описания проблемы
- Слова, которые клиенты используют для описания идеального решения

WebSearch дополнительно:
```
"{ниша}" "I need" site:reddit.com
"{ниша}" "looking for" site:reddit.com
"{ниша}" "the best" site:ycombinator.com
```

### Шаг 2.2 — Проанализировать messaging конкурентов
Для каждого из топ-5 конкурентов WebFetch главной страницы.

Извлечь:
- Точный H1 (главный заголовок)
- Subheadline (подзаголовок)
- Главные bullet points
- CTA текст

Построить таблицу messaging конкурентов.

### Шаг 2.3 — Найти positioning holes
Из таблицы messaging — что никто не говорит? Какой angle не занят?

WebSearch:
```
"{ниша}" "no one talks about"
"{ниша}" underrated
"{ниша}" "what they don't tell you"
```

### Шаг 2.4 — Проверить messaging через отзывы
WebSearch:
```
"{конкурент}" "love it because" site:g2.com
"{конкурент}" "best thing about" site:capterra.com
"{конкурент}" what makes it great
```

Это — язык, который резонирует с реальными клиентами.

**Выходной артефакт:**
```
Messaging (на языке клиента):

Positioning Statement:
Для [ICP роль], кто [боль в словах клиента из форума],
[Название] — это [категория],
который [ключевое отличие].
В отличие от [конкурент], мы [наш gap].

Headline варианты (из языка клиентов):
1. "{фраза из отзывов/форумов}" → адаптированная версия
2. ...

Messaging конкурентов (чего избегаем, чтобы не звучать одинаково):
| Конкурент | H1 | Наш угол |
|----------|----|----|
```

---

## Фаза 3 — Каналы (Channel Strategy)

**Цель:** выбрать каналы на основе того, где ICP уже есть и где работает у конкурентов.

**Действия агента:**

### Шаг 3.1 — Проанализировать трафик конкурентов по источникам
Для топ-3 конкурентов WebFetch или WebSearch:
```
similarweb.com/website/{domain}/#traffic-sources
"{domain}" traffic sources similarweb
"{domain}" organic vs paid traffic
```

Извлечь: % из organic search, direct, social, referral, paid.

Вывод: откуда берут трафик конкуренты → это рабочие каналы.

### Шаг 3.2 — Найти, где рекламируются конкуренты
WebSearch:
```
"{конкурент}" ads facebook OR google OR linkedin
"{конкурент}" sponsored site:reddit.com
site:facebook.com/ads/library "{конкурент}"
```

WebFetch: `facebook.com/ads/library/?q={конкурент}` — найти активные рекламные объявления.

### Шаг 3.3 — Найти SEO-возможности
WebSearch для проверки органического потенциала:
```
site:semrush.com keyword "{ключевое слово ниши}"
"{ключевое слово}" keyword difficulty
"{ниша}" low competition keywords
```

### Шаг 3.4 — Найти активные сообщества ICP
Из фазы 1 — список сообществ. Для каждого проверить:
- Размер (кол-во участников)
- Активность (последние посты)
- Правила о промоушене

WebFetch: топ-3 суbreddit/discord — посмотреть, есть ли там конкуренты.

### Шаг 3.5 — Найти бенчмарки CAC по каналам
WebSearch:
```
"{ниша}" CAC by channel
SaaS customer acquisition cost organic vs paid
"{индустрия}" average CAC {год}
"{ниша}" cost per lead linkedin vs google
```

**Выходной артефакт:**
```
Channel Analysis:

| Канал | Конкуренты используют | Трафик % | Оценка CAC | Наш приоритет |
|-------|----------------------|---------|-----------|--------------|
| SEO/Organic | {кто} | {%} | ${X} | #1 / #2 / нет |
| Paid Search | {кто} | {%} | ${X} | ... |
| Reddit | {кто} | {%} | ${X} | ... |
| LinkedIn | {кто} | {%} | ${X} | ... |

Топ-2 канала для старта: {канал 1}, {канал 2}
Обоснование: {конкуренты X и Y получают Y% трафика из {канала}} (источник: SimilarWeb)
```

---

## Фаза 4 — Воронка продаж (Sales Funnel)

**Цель:** построить воронку на основе реальных бенчмарков конверсии.

**Действия агента:**

### Шаг 4.1 — Найти бенчмарки конверсии для категории
WebSearch:
```
"{ниша}" trial to paid conversion rate
SaaS trial conversion benchmark {год}
"{тип продукта}" signup to paid funnel
freemium conversion rate {ниша}
site:openviewpartners.com conversion benchmarks
site:profitwell.com conversion rate
```

### Шаг 4.2 — Проанализировать онбординг конкурентов
WebSearch:
```
"{конкурент}" onboarding flow
"{конкурент}" signup process
site:useronboard.com "{конкурент}"
"{конкурент}" trial experience
```

WebFetch: если `useronboard.com/{конкурент}` существует — подробный анализ онбординга.

### Шаг 4.3 — Найти типичные возражения на рынке
WebSearch:
```
"{ниша}" "why not buying" site:reddit.com
"{конкурент}" "decided not to" site:reddit.com
"{ниша}" "hesitate to buy" OR "not sure"
"{конкурент}" negative review "but"
```

**Выходной артефакт:**
```
Sales Funnel (с бенчмарками):

Этапы → Конверсия:
Awareness → Visit: органический трафик из SEO (бенчмарк: {X} кликов/мес для позиции #1)
Visit → Signup: {X}% (бенчмарк рынка: {Y}%, источник: {URL})
Signup → Activation: {X}% (бенчмарк: {Y}%, источник: {URL})
Activation → Paid: {X}% (бенчмарк: {Y}%, источник: {URL})
Paid → Month 3: {X}% retention (бенчмарк: {Y}%, источник: {URL})

Топ-3 возражения (из форумов/отзывов):
1. "{цитата}" — ответ: {как отвечаем}
2. ...
```

---

## Фаза 5 — Генерация спроса (Demand Generation)

**Цель:** конкретный контент-план и outreach, основанный на реальных данных о поиске.

**Действия агента:**

### Шаг 5.1 — Найти SEO-кластеры
WebSearch для каждого основного ключевого слова:
```
"{ключевое слово}" related keywords
"{ключевое слово}" long tail
"{ниша}" questions people ask
site:answerthepublic.com "{ниша}"
```

WebFetch: `answerthepublic.com` — какие вопросы задают по теме.

Из найденного построить контент-кластеры.

### Шаг 5.2 — Найти темы контента через конкурентов
WebSearch:
```
site:{конкурент_блог} most shared
"{конкурент}" blog top posts
"{ниша}" content marketing examples
"{ниша}" blog posts that rank
```

WebFetch: блог конкурента (если есть) — топ-10 статей по трафику.

### Шаг 5.3 — Найти outreach-аудиторию на LinkedIn
WebSearch:
```
site:linkedin.com/in "{роль ICP}" "{триггер события}"
"{ICP роль}" "{компания с проблемой}" linkedin
```

### Шаг 5.4 — Найти объём потенциального outreach
WebSearch:
```
"{ниша}" how many companies {регион}
"{тип компании}" count {регион} statistics
"{роль ICP}" linkedin count
```

**Выходной артефакт:**
```
Demand Gen Plan (Q1):

SEO-кластеры (топ-5 по объёму/конкуренции):
| Ключевое слово | Объём/мес | Конкуренция | Тип контента |
|---------------|----------|------------|-------------|

Контент-календарь (первые 30 дней):
| Неделя | Тема | Ключевые слова | Источник идеи |
|--------|------|---------------|--------------|

Outreach:
- Размер TAL (целевой список): {N} компаний (источник: {как нашли})
- LinkedIn: {N} потенциальных лидов
- Сообщества для участия: {список с размером}
```

---

## Фаза 6 — Процесс продаж (Sales Process)

**Цель:** построить sales playbook на основе того, как продают конкуренты.

**Действия агента:**

### Шаг 6.1 — Изучить процесс продаж конкурентов
WebFetch сайтов конкурентов:
- Есть ли pricing page? (да = self-serve / нет = enterprise)
- Есть ли "Book a demo"? (да = sales-led)
- Есть ли free trial? Сколько дней?

WebSearch:
```
"{конкурент}" sales process
"{конкурент}" "book a demo" OR "free trial"
"{конкурент}" sales cycle length
"{ниша}" PLG vs sales-led
```

### Шаг 6.2 — Найти скрипты продаж в нише
WebSearch:
```
"{ниша}" sales script template
"{ниша}" discovery call questions
"{ниша}" demo script
"{ниша}" "cold email" template that works
```

### Шаг 6.3 — Найти типичный цикл сделки
WebSearch:
```
"{ниша}" average sales cycle length
"{тип клиента}" purchasing decision timeline
"{ниша}" B2B sales cycle
```

**Выходной артефакт:**
```
Sales Process:

Тип движения: {self-serve / sales-led / PLG} — потому что конкуренты {X,Y,Z} используют {тип}

Trial длина: {N} дней (бенчмарк рынка: {M} дней, источник: {URL})

Discovery call структура (адаптировано из найденных скриптов):
1. {вопрос} — цель: {что выясняем}
2. ...

Средний цикл сделки: {N} дней (источник: {URL})
```

---

## Фаза 7 — Удержание и рост (Retention & Expansion)

**Цель:** найти реальные данные о retention в нише и построить программу удержания.

**Действия агента:**

### Шаг 7.1 — Найти бенчмарки churn для категории
WebSearch:
```
"{ниша}" churn rate benchmark
SaaS churn rate by category
"{тип клиента}" monthly churn average
"{ниша}" NRR net revenue retention benchmark
site:baremetrics.com churn benchmarks
site:profitwell.com churn rate
```

### Шаг 7.2 — Найти причины churn в нише
WebSearch:
```
"{конкурент}" "cancelled" OR "churned" site:reddit.com
"{конкурент}" "why I left" OR "stopped using"
"{ниша}" churn reasons
"{конкурент}" "not renewing" OR "downgrade"
```

### Шаг 7.3 — Найти примеры retention программ
WebSearch:
```
"{ниша}" customer success program
"{ниша}" onboarding best practices retention
"{конкурент}" customer success
SaaS onboarding that improves retention case study
```

**Выходной артефакт:**
```
Retention Strategy:

Бенчмарк churn для {ниша}: {X}%/мес (источник: {URL})
Топ-5 причин churn в нише (из отзывов):
1. "{цитата}" (источник: {URL})

Time-to-value цель: {N} дней (лучший конкурент: {M} дней — источник: {URL})

Onboarding milestones (основаны на "aha-moment" конкурентов):
- День 1: {действие}
- День 7: {действие}
- День 30: {действие}

NRR цель: {X}% (бенчмарк: {Y}%, источник: {URL})
```

---

## Фаза 8 — Партнёрства (Partnerships)

**Цель:** найти реальных потенциальных партнёров в нише.

**Действия агента:**

### Шаг 8.1 — Найти технологических партнёров
WebSearch:
```
"{конкурент}" integrations
"{ниша}" integrates with
"{ниша}" ecosystem partners
"{ниша}" API partners
"{инструмент ICP}" integrations marketplace
```

WebFetch: страницы интеграций конкурентов — кто топ-партнёры?

### Шаг 8.2 — Найти agency/reseller партнёров
WebSearch:
```
"{ниша}" certified partner agency
"{ниша}" reseller program
"{ниша}" affiliate program
"{конкурент}" partner program apply
```

### Шаг 8.3 — Найти co-marketing возможности
WebSearch:
```
"{ниша}" joint webinar
"{ниша}" co-marketing partnership
"{смежная ниша}" + "{наша ниша}" partnership
"{инструмент ICP}" + "{наша ниша}" case study
```

**Выходной артефакт:**
```
Partnership Pipeline:

Технологические интеграции (топ-5 по частоте у конкурентов):
| Инструмент | Конкуренты интегрированы | Аудитория инструмента | Приоритет |
|-----------|-----------------------|----------------------|----------|

Потенциальные agency-партнёры: {список с URL}
Co-marketing: {список смежных инструментов с аудиторией ICP}
```

---

## Фаза 9 — Масштабирование GTM (Scaling)

**Цель:** найти данные о том, когда и как масштабировать GTM.

**Действия агента:**

### Шаг 9.1 — Найти бенчмарки для GTM-найма
WebSearch:
```
SaaS "first sales hire" when ARR
"hire AE" ARR milestone
SaaS SDR hire when
"{ниша}" GTM team structure
site:openviewpartners.com hiring plan SaaS
```

### Шаг 9.2 — Найти зарплатные данные
WebSearch:
```
"{GTM роль}" salary {регион} {год}
AE SDR CSM salary benchmark
site:levels.fyi sales {роль}
site:glassdoor.com "{роль}" "{ниша}"
```

**Выходной артефакт:**
```
GTM Scaling Plan:

Найм GTM (на основе бенчмарков):
| Роль | При каком ARR нанимаем | Зарплата | Источник |
|------|----------------------|---------|---------|

Автоматизация (приоритет):
- {что автоматизируем} — экономия: {N ч/мес}

Новые сегменты/рынки — следующие:
- {сегмент} — потому что: {данные из research}
```

---

## Карта фаз

```
[0] GTM Readiness — входные данные из research
    ↓ LinkedIn, G2, форумы — кто наш ICP в реальности
[1] ICP Definition — реальные профили, не персонажи
    ↓ SimilarWeb конкурентов + их homepage copy
[2] Positioning — язык клиентов из отзывов
    ↓ SimilarWeb traffic sources + Facebook Ads Library
[3] Channel Strategy — где уже есть трафик
    ↓ Бенчмарки конверсии + useronboard.com
[4] Sales Funnel — реальные конверсии
    ↓ answerthepublic + SEMrush + блоги конкурентов
[5] Demand Generation — контент-план из данных поиска
    ↓ Анализ процесса продаж конкурентов
[6] Sales Process — playbook из реальных примеров
    ↓ baremetrics + отзывы об оттоке
[7] Retention — бенчмарки churn и причины ухода
    ↓ Страницы интеграций конкурентов
[8] Partnerships — реальный список потенциальных партнёров
    ↓ Бенчмарки найма + зарплаты
[9] GTM Scaling — когда и кого нанимать
```

---

## Правила качества

1. **ICP = реальные люди.** Не "marketing manager" абстрактно, а конкретные LinkedIn-профили с реальными должностями.

2. **Messaging = слова клиентов.** Заголовки пишутся из цитат форумов и отзывов, не из маркетинговых формулировок.

3. **Каналы выбираются по трафику конкурентов.** Если у топ-3 конкурентов 60% трафика из органики — органика важна.

4. **Каждый бенчмарк со ссылкой.** "Бенчмарк churn 3–5%" без источника — не бенчмарк.

5. **Partnerships = существующие инструменты ICP.** Партнёрства с тем, чем ICP уже пользуется.

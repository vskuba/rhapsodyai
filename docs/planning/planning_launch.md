# Агентный плейбук запуска продукта (supplement: launch)

## Концепция

Плейбук для supplement_launch AI-планировщика. Превращает запуск из абстрактного события в **конкретные действия с реальными данными**: найти успешные запуски в нише, скопировать работающие паттерны, найти журналистов и сообщества, собрать аудиторию до дня запуска. Агент не придумывает — он исследует и воспроизводит.

**Предусловие:** фазы `market`, `product`, `gtm`, `blueprint` выполнены.

---

## Фаза 0 — Launch Readiness Check

**Цель:** убедиться, что всё готово — через реальные проверки, не только чеклист в голове.

**Действия агента:**

### Шаг 0.1 — Найти чек-листы запуска в нише
WebSearch:
```
"{ниша}" SaaS launch checklist
product launch checklist {год}
"{тип продукта}" pre-launch checklist
startup launch preparation
site:saastr.com launch checklist
```

### Шаг 0.2 — Найти примеры провальных запусков в нише
WebSearch:
```
"{ниша}" product launch failed lessons
"{ниша}" launch mistake
startup launch post-mortem {ниша}
"Product Hunt" launch failed lessons
```

Из найденного — что конкретно шло не так, чтобы избежать.

### Шаг 0.3 — Проверить техническую готовность
WebSearch для выбора инструментов мониторинга:
```
"{стек технологий}" monitoring tool free
error tracking startup free tier
uptime monitoring free
"{платформа}" performance monitoring
```

**Выходной артефакт:**
```
Launch Readiness:

[ ] MVP работает без критических ошибок
[ ] Онбординг проходится без помощи команды (тест с {N} людьми)
[ ] Мониторинг настроен: {инструмент} (источник: {URL})
[ ] Способ принять оплату: {инструмент}
[ ] Privacy Policy / ToS опубликованы

Топ-5 ошибок запуска в {ниша} (из найденных postmortem):
1. "{урок}" — источник: {URL}
```

---

## Фаза 1 — Первые пользователи (Founding Users)

**Цель:** найти реальных людей для founding users — не абстрактно "из нашей сети".

**Действия агента:**

### Шаг 1.1 — Найти потенциальных founding users в сообществах
Из `planning_gtm.md` (фаза 1) взять список сообществ ICP.

Для каждого WebFetch топ-тредов по теме проблемы:
```
site:reddit.com r/{subreddit} "{боль}"
site:reddit.com r/{subreddit} "{проблема}"
```

Из ответов — люди, которые активно обсуждают проблему = потенциальные founding users.

### Шаг 1.2 — Найти примеры founding users программ
WebSearch:
```
"founding member" program SaaS example
"early access" program how to do
founding users acquisition strategy
"{конкурент}" early users how found
"{похожий стартап}" founding users story
```

### Шаг 1.3 — Найти примеры outreach скриптов
WebSearch:
```
"founding users" cold outreach template
early adopter email template startup
"beta user" recruitment email example
personal outreach template early stage
```

**Выходной артефакт:**
```
Founding Users Plan:

Источники (конкретные):
- r/{subreddit}: {N} активных участников обсуждающих проблему
  Метод: личное сообщение тем, кто комментировал треды о {боль}
- LinkedIn: {N} профилей {роль ICP} в {регион}
- {другое сообщество}: {N} участников

Outreach шаблон (адаптирован из найденных примеров):
"{текст сообщения}"

Привилегии founding members:
- {привилегия} — пример: {как делал конкурент} (источник: {URL})

Цель: {N} founding users за {срок}
```

---

## Фаза 2 — Нарратив запуска (Launch Narrative)

**Цель:** построить нарратив на основе реальных данных — не придуманной истории.

**Действия агента:**

### Шаг 2.1 — Найти успешные launch stories в нише
WebSearch:
```
"{ниша}" startup launch story
"{похожий продукт}" Product Hunt launch
"{ниша}" "how we launched" case study
site:ycombinator.com "{ниша}" launch story
"our launch" "{ниша}" blog post
```

WebFetch топ-3 найденных статей — что сработало в нарративе.

### Шаг 2.2 — Найти успешные Product Hunt launches в категории
WebFetch:
```
producthunt.com/topics/{категория}
producthunt.com/?ref=header_nav#tech
```

WebSearch:
```
"{ниша}" Product Hunt "#1 product of the day"
"{ниша}" Product Hunt launch successful
site:producthunt.com "{ниша}" top launch
```

Из найденных — что в описании, какие taglines, какой стиль.

### Шаг 2.3 — Найти data points для нарратива
Из `planning_research.md` взять:
- Реальные цифры о масштабе проблемы
- Данные о росте рынка
- Реальные цитаты пользователей

WebSearch дополнительно:
```
"{проблема}" statistics {год}
"{ниша}" market size {год}
"{боль}" survey results
"{роль ICP}" challenges survey
```

**Выходной артефакт:**
```
Launch Narrative:

The Big Insight:
"{non-obvious truth}" — подкреплено данными: {статистика, источник}

The Problem (в словах клиентов):
"{цитата из форума}" — {URL}
"{цитата из G2}" — {URL}

The Solution: {одно предложение}

Data Points для нарратива:
- "{факт}" (источник: {URL})

Версии по каналам:
- Product Hunt tagline (120 симв.): "{текст}"
- Tweet (280 симв.): "{текст}"
- LinkedIn post (1 абзац): "{текст}"
- Email announcement: "{текст}"

Источники вдохновения для нарратива:
- {конкурент/аналог} launch: {что сработало} (URL)
```

---

## Фаза 3 — Закрытая бета (Closed Beta)

**Цель:** найти реальных бета-пользователей через конкретные каналы.

**Действия агента:**

### Шаг 3.1 — Найти waitlist/beta примеры в нише
WebSearch:
```
"{ниша}" waitlist strategy
"{конкурент}" beta launch how
"{похожий продукт}" "early access" waitlist
startup waitlist best practices
"viral waitlist" mechanism example
```

### Шаг 3.2 — Найти инструменты для waitlist
WebSearch:
```
waitlist management tool free
beta program management software
early access waitlist platform comparison
viral referral waitlist tool
```

WebFetch pricing страниц найденных инструментов.

### Шаг 3.3 — Найти бенчмарки метрик беты
WebSearch:
```
beta program metrics benchmark
"closed beta" D30 retention benchmark
beta user activation rate average
beta to public launch conversion rate
```

**Выходной артефакт:**
```
Closed Beta Plan:

Инструмент: {waitlist tool} — цена: ${X} (источник: {URL})

Каналы набора бета-пользователей:
- {канал}: {N} потенциальных пользователей
  Метод: {конкретное действие}

Exit Criteria (на основе бенчмарков):
- D30 Retention ≥ {X}% (бенчмарк: {Y}%, источник: {URL})
- NPS ≥ {X} (бенчмарк: {Y}, источник: {URL})
- Critical bugs = 0

Длина беты: {N} недель
```

---

## Фаза 4 — Soft Launch

**Цель:** найти первые каналы для тихого открытия с реальной аудиторией.

**Действия агента:**

### Шаг 4.1 — Найти нишевые сообщества для soft launch
Из `planning_gtm.md` список сообществ. Для каждого WebFetch правила:
- Разрешает ли продвижение?
- Какой формат приветствуют (Show HN / пост / комментарий)?

WebSearch:
```
"Show HN" "{ниша}" site:news.ycombinator.com
r/{subreddit} "rules" OR "about" promotion policy
"{ниша}" community submit product rules
```

### Шаг 4.2 — Найти нишевые директории для размещения
WebSearch:
```
"{ниша}" directory listing free
"{тип продукта}" alternatives directory
"{ниша}" tools directory submit
"{ниша}" aggregator listing
site:alternativeto.net "{конкурент}"
```

Список директорий для размещения = бесплатный трафик без продвижения.

### Шаг 4.3 — Найти бенчмарки soft launch метрик
WebSearch:
```
soft launch metrics benchmark startup
"open beta" signup conversion rate
organic launch week signups benchmark
```

**Выходной артефакт:**
```
Soft Launch Plan:

Дата: {дата}

Каналы (в порядке запуска):
1. {канал}: {N} потенциальных просмотров, правила: {ОК/ограничения}
   Конкретное действие: "{пост/заголовок}"
2. ...

Нишевые директории для размещения:
| Сайт | URL | Аудитория | Метод добавления |
|------|-----|----------|----------------|

48-часовой мониторинг:
- Error rate: цель <1% (инструмент: {что настроили})
- Signup rate: цель {N}/день
```

---

## Фаза 5 — Публичный запуск (Public Launch)

**Цель:** провести запуск на Product Hunt и других каналах, используя реальные паттерны успешных launches.

**Действия агента:**

### Шаг 5.1 — Изучить успешные PH launches в категории
WebFetch: `producthunt.com/topics/{категория}?order=most_voted`

Для топ-5 продуктов по upvotes:
- Сколько upvotes собрали
- Когда запускались (день недели)
- Какой tagline
- Сколько комментариев / первых комментаторов

WebSearch:
```
"{продукт}" Product Hunt launch strategy
"#1 product of the day" "{ниша}" how
Product Hunt launch lessons {год}
best day to launch Product Hunt {год}
site:blog.producthunt.com launch tips
```

### Шаг 5.2 — Найти охотников (Hunters) в нише
WebSearch:
```
Product Hunt hunter "{ниша}"
"{ниша}" top hunters producthunt
site:producthunt.com/@{hunter} {ниша}
"hunter" Product Hunt request
```

Найти 3–5 охотников, у которых есть аудитория в нише.

### Шаг 5.3 — Найти прессу и блогеров
WebSearch:
```
"{конкурент}" press coverage
"{конкурент}" review blog
"{ниша}" journalist covers
"{ниша}" newsletter features tools
"{ниша}" "wrote about" startup
```

WebFetch: статьи о конкурентах — кто их писал? Это журналисты, которые покрывают нишу.

### Шаг 5.4 — Найти нишевые newsletter
WebSearch:
```
"{ниша}" newsletter recommendations
"{ниша}" weekly digest
"{ICP роль}" newsletter
"{ниша}" email list featured tools
```

**Выходной артефакт:**
```
Public Launch Plan:

Product Hunt:
- Дата запуска: {вторник–четверг} (бенчмарк: {URL})
- Hunter: {имя} — аудитория: {N}, история: {N} #1 продуктов
- Tagline: "{текст}" (стиль: топ-5 запусков в нише)
- Maker comment: "{текст}"
- Первые комментаторы (founding users + сеть): {N} человек

Пресса / блогеры (из анализа конкурентов):
| Имя | Издание | URL статьи о конкуренте | Контакт |
|-----|--------|------------------------|--------|

Newsletter для размещения:
| Newsletter | Аудитория | Условия | Контакт |
|-----------|---------|--------|--------|

Launch Day Timeline:
- 00:01 UTC — Product Hunt go live
- 08:00 — Email blast
- 09:00 — LinkedIn / Twitter
- 12:00 — Community posts ({список})
- EOD — Summary + thanks
```

---

## Фаза 6 — Community и PR (Community Building)

**Цель:** найти реальные сообщества и журналистов, построить постоянное присутствие.

**Действия агента:**

### Шаг 6.1 — Найти активные сообщества в нише
Из `planning_research.md` (фаза 4) взять список.

Дополнительно WebSearch:
```
"{ниша}" Slack community
"{ниша}" Discord server
"{ниша}" forum active
"{ICP роль}" professional community {регион}
"{ниша}" Facebook group members
```

Для каждого сообщества зафиксировать: размер, активность, правила о промоушене.

### Шаг 6.2 — Найти SEO-темы для контента
Из `planning_gtm.md` (фаза 5) взять SEO-кластеры.

Дополнительно WebSearch по контентным возможностям:
```
"{ниша}" blog posts that rank
"{ниша}" content gap vs competitors
"{ключевое слово}" no good article exists
"{ниша}" thought leadership topics
```

### Шаг 6.3 — Найти подкасты и YouTube каналы в нише
WebSearch:
```
"{ниша}" podcast guest
"{ICP роль}" podcast
"{ниша}" YouTube channel subscribers
"{ниша}" interview founder
```

**Выходной артефакт:**
```
Community & PR Strategy:

Сообщества (приоритизированные):
| Сообщество | Платформа | Участников | Правила промо | Приоритет |
|-----------|---------|-----------|--------------|---------|

Контент-календарь (основан на SEO-данных):
| Тема | Ключевые слова | Объём поиска | Конкуренция | Месяц |
|------|--------------|------------|------------|------|

Подкасты/YouTube для гостевых выступлений:
| Канал | Аудитория | Тематика | Контакт |
|-------|---------|---------|--------|

Цель: {N} community posts/мес, {N} статьи/мес, {N} гостевых выступлений/квартал
```

---

## Фаза 7 — 30-дневный мониторинг (Post-Launch)

**Цель:** найти реальные бенчмарки для оценки успеха первых 30 дней.

**Действия агента:**

### Шаг 7.1 — Найти бенчмарки post-launch метрик
WebSearch:
```
SaaS post-launch metrics benchmark
Product Hunt "#1" how many signups
"{ниша}" launch week signups average
D7 retention benchmark SaaS {год}
activation rate benchmark "{ниша}"
```

### Шаг 7.2 — Найти инструменты session recording
WebSearch:
```
session recording tool free tier
Hotjar vs Microsoft Clarity vs FullStory comparison
free user behavior analytics
heatmap tool free startup
```

WebFetch pricing страниц найденных инструментов.

**Выходной артефакт:**
```
30-Day Dashboard:

Инструменты:
- Analytics: {GA4 / Mixpanel / PostHog}
- Session recording: {Clarity / Hotjar} — цена: {бесплатно/X}
- Error tracking: {Sentry / Datadog}

Целевые метрики (с бенчмарками):
| Метрика | Наша цель | Бенчмарк рынка | Источник |
|---------|----------|----------------|---------|
| Signups (неделя 1) | {N} | {N} (PH #1 avg) | {URL} |
| Onboarding completion | {X}% | {X}% | {URL} |
| D7 retention | {X}% | {X}% | {URL} |
| D30 retention | {X}% | {X}% | {URL} |
| Trial→Paid | {X}% | {X}% | {URL} |

Weekly Retro формат (адаптирован из {источник}):
- Что удивило позитивно: ...
- Что удивило негативно: ...
- Топ-3 friction points: ...
- Одно изменение на следующую неделю: ...
```

---

## Фаза 8 — Быстрая итерация (Rapid Iteration)

**Цель:** приоритизировать исправления на основе реальных данных о поведении пользователей.

**Действия агента:**

### Шаг 8.1 — Найти фреймворки приоритизации багов
WebSearch:
```
bug prioritization framework startup
P0 P1 P2 bug classification SaaS
"drop-off" funnel analysis how to fix
onboarding completion optimization
```

### Шаг 8.2 — Найти примеры быстрых итераций
WebSearch:
```
"{конкурент}" changelog first month
"{ниша}" rapid iteration post-launch case study
"first 30 days" product improvements startup
```

### Шаг 8.3 — Найти метрики "activation" для типа продукта
WebSearch:
```
"{ниша}" aha moment definition
"{тип продукта}" activation event
"{ниша}" time to first value
activation metric "{ниша}" benchmark
```

**Выходной артефакт:**
```
Iteration Framework:

"Aha moment" для {ниша}: {конкретное событие}
(бенчмарк: {конкурент} считает aha-moment как X, источник: {URL})

Приоритизация:
- P0 (блокирует конверсию): fix < 24 ч
- P1 (ухудшает UX): fix < 1 неделя
- P2 (неудобство): следующий спринт

Источники данных для итераций:
- Session recordings: {инструмент}
- Drop-off: шаг {N} воронки (из данных analytics)
- Support: топ-{N} тикетов

НЕ делаем первые 30 дней: новые фичи, ребрендинг, смена messaging
```

---

## Фаза 9 — Переход к росту (Growth Transition)

**Цель:** найти реальные сигналы PMF и сравнить с рыночными бенчмарками.

**Действия агента:**

### Шаг 9.1 — Найти PMF-бенчмарки для категории
WebSearch:
```
product-market fit signals SaaS
PMF benchmark retention "{ниша}"
Sean Ellis test benchmark "{ниша}"
"40% disappointed" benchmark
NPS PMF signal startup
site:lenny.substack.com PMF signals
```

### Шаг 9.2 — Найти примеры перехода в growth mode
WebSearch:
```
"{конкурент}" when started scaling
"{ниша}" growth stage transition case study
"found PMF" "{ниша}" startup story
when to hire sales team ARR milestone
```

### Шаг 9.3 — Найти первого GTM-человека
WebSearch:
```
"{регион}" head of growth "{ниша}" salary
first sales hire SaaS when
"{ниша}" GTM hire typical profile
head of growth job description {ниша}
```

**Выходной артефакт:**
```
Growth Transition Checklist:

PMF Signals (с бенчмарками):
[ ] D30 Retention > {X}% (бенчмарк: {Y}%, источник: {URL})
[ ] NPS > 40 (или {X}% "очень разочарованы" по Sean Ellis)
[ ] Organic referrals > 20% новых пользователей
[ ] Churn стабилизировался: {данные}

Текущее состояние: {X из 4 сигналов}

При достижении PMF:
- Масштабировать: {топ-2 канала из GTM}
- Нанять: {роль} при ARR ${X}M (бенчмарк: {URL})
- Запустить referral program: {механика из плана}

Данные за 30 дней:
- Retention D30: {X}% (цель: {Y}%)
- NPS: {X} (цель: {Y})
- Organic: {X}% от трафика
```

---

## Карта фаз

```
[0] Launch Readiness — проверка через найденные postmortem ошибок
    ↓ LinkedIn + Reddit + форумы — реальные люди с проблемой
[1] Founding Users — конкретные профили, не абстрактная сеть
    ↓ PH успешные launches + data points из research
[2] Launch Narrative — история на реальных данных и цитатах
    ↓ Инструменты waitlist + бенчмарки метрик беты
[3] Closed Beta — конкретные каналы набора пользователей
    ↓ Директории + нишевые сообщества
[4] Soft Launch — первые каналы без большого push
    ↓ PH hunters + пресса из анализа конкурентов
[5] Public Launch — конкретный launch day plan
    ↓ Сообщества + SEO + подкасты
[6] Community & PR — постоянное присутствие
    ↓ Бенчмарки PH + аналитические инструменты
[7] 30-Day Monitoring — метрики с бенчмарками
    ↓ Aha-moment + drop-off анализ
[8] Rapid Iteration — исправления по данным
    ↓ PMF сигналы vs бенчмарки рынка
[9] Growth Transition — переход в рост при подтверждённом PMF
```

---

## Правила качества

1. **Founding users — реальные люди из реальных тредов.** Не "наши друзья", а активные участники обсуждения проблемы.

2. **PH tagline — из лучших примеров в категории.** Не придуманный — скопированный паттерн.

3. **Журналисты — из статей о конкурентах.** Они уже покрывают нишу.

4. **PMF по бенчмаркам, не ощущениям.** D30 Retention + NPS + Sean Ellis — конкретные числа.

5. **Growth только после PMF.** Масштабировать acquisition без retention = тратить деньги впустую.

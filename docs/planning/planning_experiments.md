# Агентный плейбук экспериментов (ручной — после появления реальных пользователей)

## Концепция

Эксперименты — это проверка гипотез через реальные данные, а не обсуждение их на встречах. Плейбук показывает агенту, **как найти бенчмарки до запуска эксперимента, как найти готовые A/B-тест фреймворки, и как оценить результат относительно рыночных норм**.

**Правило:** каждый эксперимент начинается с поиска аналогичных экспериментов в открытых источниках. Зачем придумывать, если кто-то уже это тестировал?

---

## Фаза 0 — Наблюдение и формулировка (Observation)

**Цель:** превратить наблюдение в проверяемую гипотезу, опираясь на данные, а не интуицию.

**Действия агента:**

### Шаг 0.1 — Найти данные, подтверждающие или опровергающие наблюдение
Если наблюдение: "60% пользователей уходят на шаге 3 онбординга":

WebSearch:
```
"{ниша}" onboarding drop-off benchmark
"{тип продукта}" onboarding completion rate average
"{ниша}" activation rate benchmark
"drop-off" "{аналогичный продукт}" funnel
```

Найти: нормально ли это для категории? Или наш показатель хуже/лучше рынка?

### Шаг 0.2 — Найти чужие наблюдения той же проблемы
WebSearch:
```
"{ниша}" onboarding problem site:reddit.com
"{ниша}" "drop off" OR "churn" case study
"{похожий продукт}" A/B test results blog post
"{ниша}" experiment lessons
site:growthhackers.com "{ниша}"
```

**Выходной артефакт:**
```
Наблюдение: {что заметили}
Данные: {конкретная метрика с источником}
Контекст: это {хуже/лучше/норма} для {ниша}: бенчмарк {X}% (источник: {URL})
Аналогичная проблема у других: {URL} — как они её решили
Вопрос исследования: "{конкретный вопрос с измеримым ответом}"
```

---

## Фаза 1 — Формулировка гипотезы (Hypothesis)

**Цель:** сформулировать гипотезу, основанную на реальных прецедентах.

**Действия агента:**

### Шаг 1.1 — Найти прецеденты похожих изменений
WebSearch:
```
"{планируемое изменение}" A/B test results
"{тип изменения}" conversion uplift case study
"{ниша}" "{тип изменения}" experiment results
site:cxl.com "{тип изменения}"
site:vwo.com case studies "{ниша}"
goodui.org "{тип изменения}"
```

WebFetch: найденные case studies — что именно тестировали и какой был результат.

### Шаг 1.2 — Найти типичный MDE (Minimum Detectable Effect)
WebSearch:
```
"{тип метрики}" typical uplift A/B test
"{ниша}" conversion rate improvement realistic
"practical significance" "{метрика}" SaaS
A/B test MDE benchmark "{ниша}"
```

### Шаг 1.3 — Оценить ICE score через данные
- **Impact**: из найденных прецедентов — какой uplift реалистичен?
- **Confidence**: есть ли прецеденты в нашей нише?
- **Ease**: WebSearch `"{технология}" A/B testing implementation time` — сколько займёт?

**Выходной артефакт:**
```
Гипотеза:
Если мы [изменение], то [метрика] изменится с {X}% до {Y}%
для [сегмент] потому что [механизм].

Обоснование прецедентами:
- {компания} тестировала {аналогичное} → результат {+X}% (источник: {URL})

ICE Score:
- Impact: {1–10} — основан на прецеденте: {URL}
- Confidence: {1–10} — прецеденты в нише: {да/нет}
- Ease: {1–10} — оценка трудозатрат: {N ч}
- ICE = {результат}

MDE (минимальный значимый эффект): {X}%
Источник MDE: {URL}
```

---

## Фаза 2 — Дизайн эксперимента (Experiment Design)

**Цель:** спроектировать эксперимент корректно — через реальные калькуляторы и инструменты.

**Действия агента:**

### Шаг 2.1 — Рассчитать размер выборки
WebFetch онлайн-калькулятора:
```
evanmiller.org/ab-testing/sample-size.html
abtestguide.com/calc/
calculator.optimizely.com
```

Ввести:
- Baseline conversion: {текущая метрика из аналитики}
- MDE: {из фазы 1}
- Statistical significance: 95%
- Power: 80%

Получить: необходимый размер выборки.

### Шаг 2.2 — Оценить реализуемость
Расчёт: размер выборки / дневной трафик = длительность в днях.
Если длительность > 6 недель — пересмотреть MDE или найти другой эксперимент.

### Шаг 2.3 — Выбрать инструмент для A/B тестирования
WebFetch pricing страниц:
```
posthog.com/pricing
growthbook.io/#pricing
flagsmith.com/pricing
```

WebSearch:
```
A/B testing tool free tier startup
"{стек технологий}" feature flags A/B test
self-hosted experiment framework open source
```

**Выходной артефакт:**
```
Experiment Card EXP-{N}:

Тип: A/B / Before-After / Fake Door
Гипотеза: {из фазы 1}

Расчёт выборки (калькулятор: {URL}):
- Baseline: {X}%
- MDE: {X}%
- Нужно: {N} пользователей на вариант
- Дневной трафик: {N}/день
- Длительность: {N} дней

Инструмент: {название} — цена: {X} (источник: {URL})
Primary Metric: {одна}
Guardrail Metrics: {что не должно упасть}
Split: Control 50% / Treatment 50%
Даты: {старт} – {конец}
```

---

## Фаза 3 — Определение метрик (Metrics Definition)

**Цель:** точно определить, как считаем метрики — со ссылками на стандарты.

**Действия агента:**

### Шаг 3.1 — Найти отраслевые определения метрик
WebFetch ресурсов:
```
lenny.substack.com (поиск по метрике)
mixpanel.com/blog/
amplitude.com/blog/
```

WebSearch:
```
"{метрика}" definition SaaS standard
"{метрика}" how to calculate correctly
activation rate definition "{тип продукта}"
```

### Шаг 3.2 — Найти стандарт для конкретного типа продукта
WebSearch:
```
"{ниша}" {метрика} definition standard
how does {похожий продукт} measure {метрика}
"{метрика}" "{тип продукта}" industry standard
```

**Выходной артефакт:**
```
Metrics Definition:

Primary: {название}
- Определение: {точное описание}
- Числитель: {событие}
- Знаменатель: {база}
- Временное окно: {период}
- Инструмент: {PostHog / ...}
- Источник стандарта: {URL}

Guardrail:
- {метрика}: не падает ниже {X}% (источник стандарта: {URL})

Проверка качества данных:
- Тестовые события перед запуском: {метод}
```

---

## Фаза 4 — Запуск (Launch)

**Цель:** корректно запустить через feature flags, проверить отсутствие SRM.

**Действия агента:**

### Шаг 4.1 — Найти чек-лист запуска A/B теста
WebSearch:
```
A/B test launch checklist
pre-launch experiment checks SRM
"sample ratio mismatch" check A/B test
experiment quality assurance checklist
```

### Шаг 4.2 — Проверить novelty effect
WebSearch:
```
novelty effect A/B test how long
"novelty effect" duration days
A/B test warm-up period
```

Если продукт ≥ 6 месяцев — первые 3–7 дней могут быть novelty period, не считать.

**Выходной артефакт:**
```
Launch Checklist:

[ ] Feature flag реализован
[ ] AA-тест прошёл (нет SRM)
[ ] Primary metric трекается (проверено вручную)
[ ] Guardrail metrics мониторятся
[ ] Оба варианта проверены вручную (QA)
[ ] Novelty period: {N} дней исключаем из анализа
[ ] Стоп-критерий: {условие досрочной остановки}
Дата старта: {дата/время}
```

---

## Фаза 5 — Мониторинг (Monitoring)

**Цель:** следить правильно — без peeking.

**Действия агента:**

### Шаг 5.1 — Найти правила мониторинга
WebSearch:
```
A/B test peeking problem explanation
sequential testing fixed horizon difference
"don't peek" A/B test rule
early stopping A/B test when valid
```

### Шаг 5.2 — Найти инструменты real-time мониторинга
WebSearch:
```
A/B test monitoring dashboard real-time
experiment health check tool
feature flag monitoring alerting
```

**Выходной артефакт:**
```
Monitoring Plan:

Расписание проверки: раз в {N} дней (не чаще — peeking)
Источник правила: {URL}

Досрочная остановка при:
- Primary metric: падение > {X}% в негативную сторону
- Guardrail: {метрика} ниже {X}%
- Технический инцидент

НЕ останавливаем при:
- Малых позитивных колебаниях до набора выборки
- "Ощущении" что один вариант лучше
```

---

## Фаза 6 — Анализ результатов (Analysis)

**Цель:** корректно интерпретировать — через реальные статистические инструменты.

**Действия агента:**

### Шаг 6.1 — Провести статистический анализ
WebFetch:
```
abtestguide.com/analyze/
evanmiller.org/ab-testing/chi-squared.html
```

Ввести кол-во пользователей и конверсий. Получить p-value, CI, significance.

### Шаг 6.2 — Найти аналоги для валидации
WebSearch:
```
"{тип изменения}" A/B test "{похожий результат}%"
"{изменение}" conversion uplift "{+/-X}%"
"{ниша}" experiment result similar
```

Если найден аналог с похожим результатом — это подтверждение.

### Шаг 6.3 — Проверить confounding factors
WebSearch:
```
"{период}}" seasonal effect conversion rate
"{даты эксперимента}" any major events
A/B test confounding variables checklist
```

**Выходной артефакт:**
```
Результаты EXP-{N}:

| Вариант | Пользователи | Конверсии | CR |
|---------|------------|---------|--|
| Control | {N} | {N} | {X}% |
| Treatment | {N} | {N} | {X}% |

Статистика (калькулятор: {URL}):
- Uplift: {+/-X}%
- p-value: {X} (порог: 0.05)
- CI: [{X}%, {Y}%]
- Значим: {да/нет}

Аналог в литературе: {URL — похожий результат}
Guardrail метрики: {не пострадали / пострадали}
Вывод: {Winner / No difference / Loser}
```

---

## Фаза 7 — Решение и внедрение (Decision)

**Цель:** принять решение и внедрить правильно — с gradual rollout.

**Действия агента:**

### Шаг 7.1 — Найти framework для решения при неопределённости
WebSearch:
```
A/B test inconclusive decision framework
"no significant result" what to do
low traffic A/B test conclusion making
rerun experiment vs ship it decision
```

### Шаг 7.2 — Найти best practices rollout
WebSearch:
```
gradual rollout feature flags best practice
canary deployment percentage strategy
feature flag cleanup after experiment
winner A/B test safe rollout
```

**Выходной артефакт:**
```
Decision:

Результат: {Winner / Inconclusive / Loser}
Решение: {внедрить / не внедрять / повторить с большей выборкой}
Обоснование: {данные + прецедент}

Rollout:
- {X}% → {дата} → мониторинг {N} дней
- 100% → {дата}
- Feature flag убрать: {дата}
```

---

## Фаза 8 — Документация (Knowledge Capture)

**Цель:** зафиксировать знание для следующих экспериментов.

**Действия агента:**

### Шаг 8.1 — Найти примеры хорошей документации
WebSearch:
```
experiment documentation template
A/B test learnings format
experiment wiki company examples
"experiment log" startup template
```

### Шаг 8.2 — Найти паттерны для Pattern Library
WebFetch ресурсов после каждого эксперимента:
```
goodui.org
cxl.com/blog/
conversionxl.com/research-digest/
```

Добавить релевантные внешние паттерны.

**Выходной артефакт:**
```
Experiment Log EXP-{N}:

Период: {дата} – {дата}
Гипотеза: {текст}
Результат: {+X% / незначимо / -X%}
Решение: {внедрили / нет / повторим}

Что узнали: "{инсайт}"
Следующая гипотеза: {что тестируем дальше}
Внешние аналоги: {URL}
```

---

## Фаза 9 — Институциональная память (Pattern Library)

**Цель:** накопить реальные паттерны — из наших экспериментов + из открытых источников.

**Действия агента:**

### Шаг 9.1 — Найти внешние паттерны
WebFetch регулярно (раз в квартал):
```
goodui.org (база A/B тест паттернов с результатами)
cxl.com/blog/ab-test-ideas/
vwo.com/ab-testing/case-studies/
```

WebSearch:
```
"{ниша}" A/B test results published {год}
"{тип продукта}" conversion experiment wins
"{ниша}" UX experiment results
```

### Шаг 9.2 — Найти антипаттерны
WebSearch:
```
"{ниша}" A/B test failed lessons
"{изменение}" no effect experiment
conversion optimization myths debunked
"{ниша}" UX change backfired
```

**Выходной артефакт:**
```
Pattern Library (обновляется после каждого EXP):

Работает в {ниша}:
| Паттерн | Наш uplift | Внешний прецедент | EXP-# |
|--------|-----------|------------------|-------|

Не работает:
| Паттерн | Результат | Источник | EXP-# |
|--------|---------|---------|-------|

Внешние паттерны из goodui.org + CXL:
| Паттерн | Типичный uplift | Применимость |
|--------|--------------|-------------|
```

---

## Карта фаз

```
[0] Наблюдение — данные vs бенчмарки рынка (не интуиция)
    ↓ Поиск прецедентов + ICE из данных
[1] Гипотеза — на основе case studies, не предположений
    ↓ evanmiller.org sample size calculator + выбор инструмента
[2] Дизайн — расчёт через реальный калькулятор
    ↓ Определения из lenny/amplitude/mixpanel
[3] Metrics — стандарты из индустрии
    ↓ Feature flags + AA-тест + novelty period
[4] Запуск — через чек-лист, без SRM
    ↓ Peeking rules
[5] Мониторинг — по расписанию, без преждевременных выводов
    ↓ abtestguide.com статистика
[6] Анализ — p-value + CI + аналоги для валидации
    ↓ Gradual rollout framework
[7] Решение — rollout + feature flag cleanup
    ↓ goodui.org + CXL паттерны
[8] Документация — experiment log + следующие гипотезы
    ↓ Регулярный обход goodui/CXL/VWO
[9] Pattern Library — живая база реальных знаний
```

---

## Правила качества

1. **До гипотезы — поиск прецедентов.** Если кто-то уже тестировал — стартовать с их результатов.

2. **Размер выборки — только через калькулятор.** Не "проверим неделю и посмотрим".

3. **Одна primary metric.** Три "главных" = нет главной.

4. **Не смотреть чаще расписания.** Peeking = ложноположительные выводы.

5. **Guardrail обязательны.** Улучшить конверсию за счёт retention = плохой эксперимент.

6. **Негативный результат = знание.** Документировать и добавлять в Pattern Library.

7. **goodui.org — бесплатная база реальных A/B тестов.** Использовать перед каждым новым экспериментом.

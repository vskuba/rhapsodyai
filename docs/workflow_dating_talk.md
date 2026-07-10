# Анализ workflow `dating_talk` («Чат с девушкой») и план улучшений

## 1. Как работает сейчас (11 шагов, объединенный LLM-анализ)

```
pos 0  session_messages (limit 20)             — история переписки
pos 1  fact_collection_output_format(companion) — JSON-шаблон фактов для промпта
pos 2  llm_to_json «Анализ сообщения»          — LLM#1 (объединенный): history_summary,
       category, tags, question(0/1), search_query, facts_companion, facts_talk
pos 3  workflow_invoke companion_fact_extract  — сохранение facts_companion/facts_talk (subflow 7, без LLM)
pos 4  variable_conversion                     — 3 фильтра {document_id, tags}
pos 5  qdrant_fact_search (girl, limit=6)      — query: search_query
       └─ если question == 1 → pos 16 girl_fact_create (LLM) → назад на pos 6
pos 6  qdrant_fact_search (companion, limit=6) — query: search_query
pos 7  qdrant_fact_search (talk, limit=6)      — query: search_query
pos 8  datetime_current_get (+3)
pos 9  return_response_llm                     — LLM#2: финальный ответ. КОНЕЦ
pos 16 workflow_invoke girl_fact_create        — достижим только переходом question==1
```

Сущности «мужчина» переименованы в «собеседника»: коллекция `dating_man` → `dating_companion`,
переменные `prompt_user_facts_man` → `prompt_user_facts_companion`,
`fact_collection_man_name` → `fact_collection_companion_name`.

Обычный путь: **2 последовательных LLM-вызова** (объединенный анализ + финальный ответ) + 3 запроса
в Qdrant; худший (личный вопрос) — 3 LLM-вызова. Ранее было 3-5 LLM-вызовов: извлечение фактов,
суммаризация истории и категоризация выполнялись отдельными шагами.

## 2. Найденные баги и рассинхроны

1. **[РЕШЕНО: уникальные имена переменных]** Ранее авто-переменные `{tool}_result_{key}`
   перезаписывались при повторных вызовах инструмента (qdrant_fact_search ×3), а `outputs_map`
   движком не применялся — отсюда шаги-копии pos 8/10 и рассинхрон шага 17 (придуманные факты не
   попадали в финальный промпт). Теперь имя включает ID шага: `{tool}_{step_id}_result_{key}`
   (например `qdrant_fact_search_25_result_str`) — уникально, читаемо, стабильно при перестановке
   шагов. Сиды мигрированы; шаги-копии удалены при слиянии LLM-шагов (§3). Для `workflow_invoke`
   outputs_map реализован в движке (child_scope → переменные родителя); для tool-шагов
   outputs_map в metadata игнорируется — работают только авто-переменные.
2. **[РЕШЕНО той же правкой]** Хрупкая переменная «предыдущих соглашений»: финальный промпт теперь
   читает явную `%qdrant_fact_search_39_result_str%` (talk-поиск), а не результат «последнего
   вызова».
3. **[РЕШЕНО]** `>` в переходах сравнивал строки лексикографически — теперь числа сравниваются
   численно (`_transition_condition_check`), отсутствующая переменная пропускает переход с warning.
4. **Нет score_threshold в qdrant_search** (закомментирован, `qdrant_.py:250,259`) — при limit=2 в
   контекст попадают 2 ближайших факта, даже если они нерелевантны вопросу.
5. **Дедупликация фактов — только точное совпадение текста** (`fact_collection_.py:91`) —
   перефразированный факт («у меня бмв» / «езжу на BMW») создаёт дубликат.
6. **`session_messages` отбрасывает последнее сообщение при нечётном количестве**
   (`session_.py:34`) — теряется контекст.
7. **[РЕШЕНО: %if%-блоки в шаблонах]** Пустые секции в финальном промпте: раньше при пустом
   поиске LLM видела «=== Информация о ... === (пусто)». Теперь рендер поддерживает условные
   блоки `%if var%...%else%...%endif%` (см. docs/workflow.md §3), и три секции фактов в промпте
   шага 24 обёрнуты в `%if qdrant_fact_search_result_*%...%endif%` — пустая секция не попадает
   в промпт вместе с заголовком.

## 3. Улучшения точности ответов

- ✅ **Слить LLM-шаги 1, 3, 4 в один `llm_to_json`** — сделано: шаг 27 «Анализ сообщения»
  возвращает facts_companion, facts_talk, category, tags, question, history_summary, search_query
  за один вызов (−2 LLM-вызова). Извлечение фактов переехало из subflow 7 в объединенный шаг;
  subflow 7 теперь только сохраняет переданные факты (входы `prompt_user_facts_companion/talk`).
- ✅ **Переформулировка поискового запроса** — сделано: объединенный шаг возвращает
  `search_query` (самодостаточная формулировка с референтами из истории), все три
  qdrant_fact_search используют её вместо сырого `prompt_user`.
- **История для поиска, а не только для промпта**: частично закрыто через `search_query`
  (учитывает историю); отдельное подмешивание суммаризации в query коллекции talk — опционально.
- ✅ **Убрать пустые секции** из финального промпта — сделано через условные `%if%`-блоки
  в шаблонах (см. §2.7).
- ✅ **Fresh-факты в ответ** — сделано: после `girl_fact_create` (шаг 48, pos 16) выполнение
  проваливается на шаг 97 «Влить придуманные факты» (pos 17), который дописывает результат
  subflow (`%workflow_invoke_48_result_str%` — новые факты после дедупа, в `%if%`-блоке) в
  `qdrant_fact_search_25_result_str` — именно её читает финальный промпт шага 24. В ответ
  попадают и найденные поиском, и свежепридуманные факты; переход `agent_id > 0 → 38`
  перенесен с шага 48 на шаг 97.
- ✅ **Свежесть контекста** — сделано: subflow `girl_fact_invent` теперь сам ищет биографию
  девушки широким поиском (только document_id, без tags, `fact_invent_limit` = 12) и придумывает
  факты на этом контексте, а не на 2 tag-фильтрованных фактах родителя (вход
  `girl_existing_facts` упразднен).

## 4. Улучшения Qdrant-поиска

- **Включить score_threshold** (dense ~0.45) + вернуть скор в результат — лучше пустой результат,
  чем нерелевантный.
- ✅ **`fact_collection_limit` = 2 → 6** — сделано (girl/companion/talk-поиски). Для шага
  «Новый факты» — отдельный `fact_invent_limit` = 12: собственный поиск биографии внутри
  subflow `girl_fact_invent` (шаг `qdrant_fact_search_girl_bio`, фильтр только по document_id,
  без tags), чтобы придуманное не противоречило биографии.
- **Теги — из must в should**: сейчас `tags` в `metadata_filter` жёсткий фильтр, а теги генерирует
  LLM на лету («машина» vs «авто» → отсечение релевантных фактов). Правильно: document_id — must,
  tags — should/boost. Альтернатива: два поиска (с тегами и без) с объединением.
- **Синхронизация синхронно для критичных фактов**: факты girl, влияющие на текущий ответ, писать
  в Qdrant сразу (вызов qdrant_save из fact_collection_add с флагом `sync_now=1`), а не ждать крон.
- Долгосрочно: **reranking** (cross-encoder поверх топ-20) и/или более сильная модель эмбеддингов
  для RU/UK.

## 5. Качество создания фактов

- **Семантическая дедупликация**: перед вставкой — qdrant-поиск похожего факта
  (similarity > 0.9 → пропустить/обновить вместо вставки). Инструмент `fact_add_unique` (§7).
- **Атомарность фактов**: в промпт извлечения добавить требование «один факт — одно утверждение»,
  нормализованный вид («%companion_title% владеет BMW X5», а не цитата).
- **Консистентность придуманных фактов**: ✅ шаг «Новый факты» получает больше существующих
  фактов (собственный поиск с `fact_invent_limit` = 12, см. §4); осталось — системный промпт
  девушки (girl_prompt_system) как контекст личности.
- **Валидация категорий/тегов**: закрытый словарь категорий в промпте (сейчас свободная генерация
  → расползание таксономии и бесполезность фильтров).
- **TTL/версии для фактов переписки**: договорённости устаревают («созвонимся завтра») — писать
  `created_at` в payload и учитывать при формировании контекста (сортировка/фильтр по свежести).

## 6. Разбиение на sub-workflow (subflow=1)

Естественные под-процессы, переиспользуемые и для других персонажей/нод:

1. ✅ **`companion_fact_extract`** — sub-workflow (id 7, subflow=1). После слияния LLM-шагов
   (§3) извлечение фактов ушло в объединенный шаг родителя, subflow сократился до 3 шагов:
   add_companion → add_talk → return. Входы (type='input'): `prompt_user_facts_companion`,
   `prompt_user_facts_talk`; переходы-пропуски: `facts_companion == 0` → add_talk,
   `facts_talk == 0` → return. Вызывается шагом 58 `workflow_invoke` (pos 3) ДО ответа;
   вынос после ответа — отдельная оптимизация.
2. **`context_retrieve`** (pos 0-8) — сбор контекста: история+суммаризация, 3 поиска, время.
   Вход: prompt_user, document_id, companion_name, session_uuid. Выход: context-переменные.
3. ✅ **`girl_fact_invent`** — sub-workflow (id 6, subflow=1, 6 шагов: output_format →
   переменные (fact_invent_filter) → qdrant_fact_search_girl_bio (limit 12, без tags) →
   llm_to_json «Новый факты» → fact_collection_add → return_response_text). Входы
   (type='input'): `girl_name`, `girl_title`, `companion_title`, `prompt_user` — биографию
   subflow ищет сам, вход `girl_existing_facts` упразднен. Выход: facts_str (после дедупа) —
   через outputs_map попадает в `qdrant_fact_search_result_girl` родителя. Переход
   `question == 1` ведет на шаг 48 `workflow_invoke`.
4. Главный `dating_talk`: `context_retrieve` → [`girl_fact_invent`] → ответ → `fact_extract`.

Требует типа шага `workflow_invoke` (дизайн в docs/workflow.md §9.2). Профит: изоляция изменений,
переиспользование, возможность вынести fact_extract из критического пути ответа.

## 7. Новые универсальные инструменты

| Инструмент | Что делает | Что заменяет |
|---|---|---|
| `qdrant_multi_search(searches_json, limit, score_threshold)` | Несколько поисков одним вызовом, параллельно внутри; возвращает dict по ключам | 3 шага tool_invoke + 2 шага копий переменных |
| `fact_add_unique(collection_name, data, similarity_threshold, sync_now)` | Добавление с семантическим дедупом и опц. мгновенным синком в Qdrant | fact_collection_add + крон-гонка |
| `session_summary_get(session_uuid, limit)` | История + кэшированная суммаризация в session.metadata, инкрементальное обновление | session_messages + LLM-шаг суммаризации на каждый запрос |
| `fact_context_render(results_json, empty_text)` | Форматирует результаты поисков в секции промпта, скрывая пустые | ручная сборка секций в финальном промпте |
| `qdrant_save_now(collection_name, facts_json)` | Немедленная запись в Qdrant (минуя крон) | ожидание fact_qdrant_sync |

## 8. Приоритеты

1. **Быстрые победы (движок)**: ✅ уникальные имена tool-переменных `{tool}_{step_id}_result_{key}`
   (вместо outputs_map); ✅ числовое сравнение в переходах; ✅ пропуск перехода при отсутствующей
   переменной вместо KeyError.
2. **Быстрые победы (workflow)**: ✅ слить LLM-шаги 1+3+4 (шаг «Анализ сообщения»);
   ✅ search_query вместо сырого prompt_user; ✅ fact_collection_limit = 6 и отдельный
   fact_invent_limit = 12 для «Новый факты».
3. **Инструменты**: fact_add_unique (дедуп + sync_now), qdrant_multi_search, score_threshold.
4. **Архитектура**: ✅ workflow_invoke + 2 subflow (companion_fact_extract, girl_fact_invent);
   осталось — context_retrieve и вынос fact_extract из критического пути; доделать
   «Fresh-факты в ответ» (§3).
5. **Долгосрочно**: reranking, TTL фактов, кэш суммаризации, закрытая таксономия категорий.

## 9. Регрессионное тестирование

Прогон диалога делается оболочкой **`workflow_shell_test`** (workflow 9, агент Workflow tester,
нода Dev — см. docs/workflow.md §12): мастер выбирает ноду/workflow/агента чипсами, LLM играет
собеседника по сценарию и возвращает стенограмму N итераций. Персона целевого агента передается
через переменную `prompt_system` — ответы идут «в образе» девушки, а не промптом тестера.

# Fact — факты и коллекции фактов (Qdrant-синхронизация)

`fact` — хранилище фактов по коллекциям. `fact_collection` описывает
коллекцию: `name` (системное имя, по нему Qdrant-коллекция), `field` — строка
списком допустимых полей фактов (`document_id,category,language,document,tags`
по умолчанию), `language`, `position`. Строка `fact` — один факт: динамические
поля по списку коллекции плюс служебные `document_id`, `document_title`,
`qdrant_synced`. Векторы живут в Qdrant; `document_id` — ключ записи в Qdrant
(агентский `name`, см. agent.md). Связка MySQL ↔ Qdrant: флаг `qdrant_synced`
и крон `src/cronjob/fact/fact_qdrant_sync.py` (входит в общий механизм кронов,
см. architecture.md).

> Два роутера в одной подсистеме: fact.py (факты: список с пагинацией,
> обновление, удаление, пересинк в Qdrant) и fact_collection.py (CRUD
> коллекций). Не-админы видят только собственные факты — по `fact.user_id`.
> Поля фактов динамические: набор задаёт `fact_collection.field`.

## 1. Роуты фактов — `src/uvicorn/routers/fact/fact.py`

Роутеры подключены в `main_uvicorn.py` без префикса. Контракт `{result}` —
`docs-common/api_rules.md`.

| Метод | Путь | Право | Что делает |
|-------|------|-------|-----------|
| GET | `/fact/collection/list` | `FACT_COLLECTION_VIEW` | Коллекции + `fact_count` |
| GET | `/fact/collection/{collection_name}` | `FACT_VIEW` | Факты коллекции с пагинацией и фильтрами |
| GET | `/fact/collection/{collection_name}/documents` | `FACT_VIEW` | Отдельные `document_title` коллекции |
| PUT | `/fact/{fact_id}` | `FACT_UPDATE` | Обновляет `document`/`category`/`tags`; сбрасывает `qdrant_synced = 0` |
| PUT | `/fact/collection/{collection_id}` | `FACT_CREATE` | Пакетная вставка фактов (массив объектов) |
| DELETE | `/fact/{fact_id}` | `FACT_DELETE` | Удаляет из Qdrant, затем из MySQL |
| POST | `/fact/collection/{collection_name}/resync` | `FACT_UPDATE` | Пересинк: чистит Qdrant по `document_id`, помечает несинхр., догоняет синк |

Параметры списка: `page`, `limit` (макс 100), `query` (LIKE по `document`),
`document_id`, `document_title`, `status` (`1`/`0` — по `qdrant_synced`,
`all` — все). Ответ — `{result, pagination}`.

## 2. Роуты коллекций — `src/uvicorn/routers/fact/fact_collection.py`

| Метод | Путь | Право | Что делает |
|-------|------|-------|-----------|
| GET | `/collection/list` | `FACT_COLLECTION_VIEW` | Все коллекции по `name ASC` |
| GET | `/collection/{collection_id}` | `FACT_COLLECTION_VIEW` | Коллекция + `schema` из метаданных (`ai_fact_collection_metadata_get`) |
| POST | `/collection` | `FACT_COLLECTION_CREATE` | Создаёт коллекцию; `title` по умолчанию = `name` |
| PUT | `/collection/{collection_id}` | `FACT_COLLECTION_UPDATE` | Обновляет метаданные (не `field`) |
| DELETE | `/collection/{collection_id}` | `FACT_COLLECTION_DELETE` | Удаляет коллекцию |

## 3. Видимость не-админов

Для неполноправной роли (проверка `auth_role_is_full`, см. auth.md) ко всем
выборкам фактов добавляется `f.user_id = <пользователь>`: не-админ видит
факты, созданные его workflow-запусками. Коллекции видны всем с правом
`FACT_COLLECTION_VIEW`; «свои» — только сами факты.

## 4. Динамические поля

Набор полей факта задаёт строка `fact_collection.field`. Пакетная вставка
берёт из каждого объекта только разрешённые поля, остальные молча
отбрасывает. Пустой список полей в `field` — `500` «конфигурация полей не
настроена». `field` при создании задан и при `PUT /collection` не
меняется — менять набор полей существующей коллекции API не умеет.

## 5. Пересинк в Qdrant

`POST /fact/collection/{name}/resync` с телом `{"document_title": "…"}` (или
`"all"`): собирает `document_id` по фильтру, помечает факты
`qdrant_synced = 0`, удаляет их записи из Qdrant по `document_id`, затем
гоняет `ai_fact_qdrant_sync()` пачками до тех пор, пока несинхронизированных
не станет меньше (лимит 20 итераций). Если по фильтру нет фактов с
`document_id` — `404`.

## 6. Что здесь не делать

- Не хранить в `fact` поля вне списка коллекции — они не попадут ни в MySQL,
  ни в Qdrant, и при пересинке потеряются.
- Не полагаться на `document_title` как ключ Qdrant — там лежит
  `document_id`; `document_title` только человекочитаемый фильтр.
- Не править факты и сразу ждать вектор в Qdrant — `qdrant_synced` сбрасывается,
  вектор обновит крон или ручной resync.

## Грабли

1. **`PUT /fact/{id}` без полей «успешно» ничего не делает.** Если в теле
   нет ни `document`, ни `category`, ни `tags` — SQL не выполняется, а
   ответ всё равно `{"updated": true}`. **Симптом** — «обновил факт, а он
   не изменился»: клиент не переслал ни одного из трёх полей.
2. **resync одной коллекции догоняет синк всей БД.** Пометка
   `qdrant_synced = 0` scoped на коллекцию, но цикл пересинка считает
   несинхронизированные по всей таблице и гоняет общий
   `ai_fact_qdrant_sync()` (без фильтра по коллекции). **Симптом** —
   resync одной коллекции занимает время, соразмерное всем фактам, и
   «пересинкает» чужие коллекции, у которых скопились несинкнутые.
3. **Удаление факта из MySQL не отменяется ошибкой Qdrant.** `DELETE
   /fact/{id}` сначала пытается удалить вектор, но сбой Qdrant только
   логируется, и факт всё равно режется из MySQL. **Симптом** — «факта нет
   в списке, а поиск по Qdrant его находит»: старый вектор остался.
   Чистится только resync по `document_id`.
4. **Пакетная вставка молча отбрасывает лишние поля.** Объект с полем,
   которого нет в `field` коллекции, вставится без этого поля, без
   предупреждения. **Симптом** — «залили факты, а поле не в
   Qdrant»: проверьте, что имя поля совпадает с `field` коллекции (в
   т.ч. регистром и пробелами).
5. **Коллекции ищутся по имени, факты — по номеру коллекции.**
   `GET /fact/collection/{collection_name}` — по имени,
   `GET /collection/{collection_id}` — по номеру. Путать их: «нет такой
   коллекции» на точке, где имя приняли за номер (и наоборот).

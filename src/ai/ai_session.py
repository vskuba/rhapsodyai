import json

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Сколько дней держим строку журнала вызовов. До 2026-11-07 срока не было вовсе:
# таблица росла с 19 июля и набрала 2.29 млн строк на 7.3 ГБ — 81% базы в 9.0 ГБ
# при буферном пуле MySQL в 1–3 ГБ. Цена не в месте на диске, а в том, что
# мёртвый хвост вытесняет из кэша живые страницы: 568 млн физических чтений с
# диска и 6408 ожиданий свободной страницы в пуле за 39 суток аптайма базы.
#
# Тридцать дней — чтобы разбор инцидента месячной давности ещё был возможен.
# Живому разговору срок не мешает: историю везде читают как
# `WHERE session_uuid = … ORDER BY created_at DESC LIMIT N` (`src/tool/session/`,
# `routers/chat/chat.py`), то есть по свежим, и древний хвост никто не спрашивает.
SESSION_KEEP_DAYS = 30

# Размер пачки одного `DELETE`. Строка тут весит в среднем 3.2 КБ (`content` —
# `longtext` с промптом и ответом модели), так что 500 строк — это полтора
# мегабайта на запрос: достаточно, чтобы уборка шла, и мало, чтобы замок не
# держался на таблице, в которую в этот момент пишут живые вызовы.
SESSION_TRIM_BATCH = 500

# Потолок на один заход. Первая уборка на проде разгребает 806 тыс. строк
# (замерено 2026-11-07: из 2.29 млн строк старше 30 дней ровно столько) — за один
# заход этого делать нельзя, и не нужно: часовой крон размелет завал за ~16
# часов, не держа базу.
SESSION_TRIM_MAX = 50_000


async def ai_session_message_add(session_uuid, request_uuid, llm_id, user_id, role, agent_id, kind_type, content, token=None):
    """Строка журнала вызова LLM: промпт, ответ, вызов инструмента.

    ⚠ Собеседника здесь нет и быть не должно. `agent_session` отвечает на вопрос
    «что мы спросили у модели и что она ответила»; кто с кем разговаривает —
    вопрос `companion_session`, и там у разговора своя строка на обмен. Пока
    столбец `companion_id` стоял здесь, он же был и единственным местом, куда
    переписка попадала, — но попадала слепком промпта, из которого разговор не
    выбрать ни по паре, ни по времени.
    """
    async with mysql_get_db_async() as db:
        # Используем %s для MySQL
        sql = '''
            INSERT INTO agent_session (session_uuid, request_uuid, llm_id, user_id, role, agent_id, kind_type, content, token)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        await db.execute(sql, (session_uuid, request_uuid, llm_id, user_id, role, agent_id, kind_type, content, token))
        # При autocommit=True в настройках пула, commit() произойдет автоматически


async def ai_session_trim(keep_days: int = SESSION_KEEP_DAYS,
                          batch: int = SESSION_TRIM_BATCH,
                          limit: int = SESSION_TRIM_MAX) -> int:
    """Сносит строки журнала старше срока. Пачками, по расписанию.

    Args:
        keep_days: сколько дней держим строку.
        batch: сколько строк сносим одним `DELETE`.
        limit: потолок на один заход уборки.

    Returns:
        int: сколько строк снесено.

    ## ⚠ Почему пачками и с `ORDER BY`

    Оба правила взяты у `ai_workflow_trace_trim`, и взяты не для симметрии.
    Пачка — ради замков: под `REPEATABLE-READ` `DELETE` держит next-key-замок на
    каждой просмотренной строке, а пишут в эту таблицу все живые вызовы модели.
    `ORDER BY created_at` — чтобы уборка была «сначала самое старое»: без него
    MySQL выбирает сносимые строки на своё усмотрение, пачки перемешиваются, и
    на потолке `limit` заход останавливается посреди случайного места.

    ⚠ Условию нужен индекс по `created_at` (миграция
    `20261107223000_agent_session_created_index.sql`). Без него каждая пачка —
    полный проход по таблице в 7.3 ГБ, то есть ровно та беда, от которой уборку
    и заводили.

    ⚠⚠ Место на диске сам `DELETE` не возвращает: страницы остаются в
    табличном файле и переиспользуются новыми строками. Кэшу этого достаточно —
    живых страниц становится меньше, — а вот ~2.6 ГБ на диске вернёт только
    `OPTIMIZE TABLE agent_session`, и его надо заводить руками и в тихий час:
    он перестраивает таблицу целиком.

    ⚠ Срок выбран по замеру, а не на глаз, и запас в нём небольшой. На
    2026-11-07 поток записи вырос вчетверо: за июль–октябрь набежало 806 тыс.
    строк (≈10 тыс./день), за последние две недели — 504 тыс. (≈38 тыс./день).
    При 38 тыс./день тридцать дней держат ~1.15 млн строк, то есть таблица
    осядет до ~4.8 ГБ и в буферный пул (3 ГБ) целиком не влезет — влезет
    горячая часть. Вырастет поток ещё — срок придётся сокращать; смотреть надо
    не на вес таблицы, а на `Innodb_buffer_pool_wait_free` и долю попаданий.
    """
    removed = 0
    try:
        async with mysql_get_db_async() as db:
            while removed < limit:
                await db.execute(
                    'DELETE FROM agent_session'
                    ' WHERE created_at < NOW() - INTERVAL %s DAY'
                    ' ORDER BY created_at'
                    ' LIMIT %s',
                    (int(keep_days), min(int(batch), limit - removed)))
                count = int(db.rowcount or 0)
                removed += count
                if not count:
                    break
    except Exception as e:
        # Уборка — не работа, ради которой процесс живёт: недоступная база или
        # замок отменяют заход, а не роняют кронджоб. Следующий час разгребёт.
        logger_info(f'⚠️ ai_session_trim не доделан ({removed} снесено): {e}')

    if removed:
        logger_info(f'🧹 ai_session_trim: снесено строк журнала {removed} '
                    f'(старше {keep_days} дн.)')

    return removed


async def ai_session_metadata_get(session_uuid) -> dict:
    async with mysql_get_db_async() as db:
        sql = '''
            SELECT metadata FROM session WHERE uuid = %s
        '''
        await db.execute(sql, (session_uuid,))
        row = await db.fetchone()

        if not row:
            return {}

        raw_metadata = row['metadata']

        if isinstance(raw_metadata, dict):
            return raw_metadata

        if isinstance(raw_metadata, str):
            try:
                return json.loads(raw_metadata)
            except json.JSONDecodeError as e:
                print(f"Ошибка парсинга JSON для сессии {session_uuid}: {e}")
                return {}

        return {}


async def ai_session_metadata_set(session_uuid, metadata: dict):
    async with mysql_get_db_async() as db:
        sql = '''
            SELECT id FROM session WHERE uuid = %s
        '''
        await db.execute(sql, session_uuid)
        entity_session = await db.fetchone()

        metadata_json = json.dumps(metadata, ensure_ascii=False)
        if not entity_session:
            sql = '''
                INSERT INTO session (metadata, uuid) VALUES (%s, %s)
            '''
        else:
            sql = '''
                UPDATE session SET metadata = %s WHERE uuid = %s
            '''
        await db.execute(sql, (metadata_json, session_uuid))

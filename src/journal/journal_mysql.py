"""Журнал запросов к базе: какой запрос, сколько стоил и что вернул.

Соседняя подвкладка «Ошибки» отвечает про сломавшееся. Эта — про то, что не
ломается, а просто стоит дорого. Повод прямой: разбор нагрузки на проде показал,
что 1.53 млрд из 1.55 млрд прочитанных строк приходятся на две таблицы, — и нашли
это счётчиками `performance_schema`, руками и постфактум. Числа про свои же
запросы установка может собирать сама.

## Кто что делает

```
mysql_.execute → mysql_watch_note   (общий слой: счёт в памяти процесса)
                        ↓
              mysql_watch_drain     (пачка: строка на вид запроса)
                        ↓
              journal_mysql_flush   (здесь: пачка → таблица journal_mysql)
```

Разделение не формальное. Счёт запросов нужен любому проекту и потому живёт в
общем слое; таблица и страница — только этому, и потому живут здесь. Общий слой
про `journal_mysql` не знает ничего.

## ⚠⚠ Строка одна на вид запроса, а не на его прогон

Замерено на живом сервере: воркер шлёт 6832 запроса в минуту. Строка на каждый —
десять миллионов строк в сутки и удвоенная нагрузка на ту самую базу, которую
этим журналом и собирались чинить. Поэтому строка одна на отпечаток, повторы —
в счётчики, а сброс идёт пачкой раз в `JOURNAL_MYSQL_FLUSH_SECONDS`.

## ⚠ Ответы базы не хранятся

Ни одной строки данных: только текст запроса, его значения и числа. Значения
чистятся от секретов тем же кодом, что и журнал запросов (`mysql_log_args`) —
правила общие, `.claude/docs-common/observability_rules.md`, §10.

## ⚠ Сброс не считает сам себя

`journal_mysql_flush` ходит в базу обычными запросами, и без защиты счётчик
считал бы собственную работу — заводя её заново на каждом сбросе. Защита —
`mysql_watch_hold()` общего слоя: флаг потока, как у журнала ошибок.
"""

import asyncio

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from mysql_.mysql_watch import (mysql_watch_drain, mysql_watch_hold, mysql_watch_off,
                                mysql_watch_on)
from setting_.setting_ import setting_get

# Ключ настройки-выключателя в таблице `setting` (страница `/admin/setting`).
# Пустое значение и `0/false/no/off` гасят счёт; всё остальное — считаем.
JOURNAL_MYSQL_SETTING = 'journal_mysql_enabled'

# Как часто сбрасываем накопленное в таблицу. Полминуты — чтобы страница
# показывала близкое к сейчас, и при этом одна запись на процесс в полминуты
# ничего не стоит. Этот же такт перечитывает настройку-выключатель.
JOURNAL_MYSQL_FLUSH_SECONDS = 30

# Сколько строк отдаём страницей и сколько разрешаем запросить.
JOURNAL_MYSQL_PAGE = 50
JOURNAL_MYSQL_PAGE_MAX = 200

# Сколько дней держим строку. Короче, чем у ошибок (30): ошибка недельной
# давности — всё ещё вопрос, а запрос, которого неделю не было, ушёл вместе с
# кодом, который его слал.
JOURNAL_MYSQL_KEEP_DAYS = 7

# Чем сортируем ленту. Ключи — то, что приходит с ручки; значения — куски SQL, и
# словарь здесь именно затем, чтобы имя колонки не приезжало из запроса.
JOURNAL_MYSQL_ORDER = {
    'total_ms': 'total_ms DESC',
    'max_ms':   'max_ms DESC',
    'hits':     'hits DESC',
    'avg_ms':   '(total_ms / GREATEST(hits, 1)) DESC',
    'rows':     'total_rows DESC',
    'last_at':  'last_at DESC',
}


async def journal_mysql_enabled() -> bool:
    """Считаем ли запросы. Выключатель — настройка `journal_mysql_enabled`.

    Настройкой, а не переменной окружения: счёт включают ровно тогда, когда
    что-то тормозит, — то есть на живой установке и не заходя в конфиги. Строку
    заводит миграция `20260929171126`, правится она на `/admin/setting`.

    Умолчание — «считаем»: журнал заводят затем, чтобы он был, а цена счёта —
    словарь в памяти процесса и одна запись в полминуты.

    ⚠ Свой поход в базу счётчику не показываем (`mysql_watch_hold`): иначе в
    журнале завёлся бы вид запроса, который делает сам журнал, — и рос бы он
    ровно от того, что журнал включён.

    ⚠ **Не бросает.** Недоступная настройка (база не поднялась, таблицы ещё нет
    на свежей установке) не имеет права уронить точку входа: журнал наблюдает за
    процессом, а не ведёт его. Не прочиталась — считаем по умолчанию.
    """
    try:
        with mysql_watch_hold():
            value = await setting_get(JOURNAL_MYSQL_SETTING, '1')
    except Exception as e:
        logger_info(f'[journal_mysql] настройка {JOURNAL_MYSQL_SETTING} не прочиталась: {e}')
        return True

    return str(value).strip().lower() not in ('0', 'false', 'no', 'off', '')


async def journal_mysql_watch_start(source: str) -> bool:
    """Приводит счёт запросов в соответствие с настройкой. Зовётся из точки входа.

    Args:
        source: чей это процесс — тот же ключ, что у журнала ошибок
            (`uvicorn`, `worker`, `telegram`, `cronjob`).

    Returns:
        bool: считаем или нет.

    ⚠ Не «включить», а **сверить**: долгоживущий процесс зовёт это же на каждом
    сбросе (`journal_mysql_flush_forever`), и снятая на странице галочка гасит
    счёт через полминуты, без перезапуска контейнеров. Ради этого настройку и
    предпочли переменной окружения.

    ⚠ Одного включения мало: накопленное надо ещё и сбрасывать. Долгоживущему
    процессу для этого есть `journal_mysql_flush_forever`, короткому —
    `journal_mysql_watch_stop` перед выходом.
    """
    if not await journal_mysql_enabled():
        mysql_watch_off()
        return False

    mysql_watch_on(source)
    return True


async def journal_mysql_flush() -> int:
    """Сбрасывает накопленное в таблицу. Возвращает число видов запроса в пачке.

    ⚠ **Не бросает ничего.** Журнал не имеет права уронить того, кого журналит:
    недоступная база стоит пачки счётчиков, а не процесса.

    ⚠ О своих неудачах говорит `logger_info`, а не `logger_exception`. Уровень
    ERROR попал бы в соседнюю подвкладку через обработчик корневого логгера, а
    оттуда — в ту же недоступную базу, по кругу. Так же устроен `journal_write`.
    """
    rows = mysql_watch_drain()
    if not rows:
        return 0

    try:
        # ⚠ Внутри блока счётчик молчит: иначе запись пачки попала бы в
        # следующую пачку, и та никогда бы не опустела.
        with mysql_watch_hold():
            async with mysql_get_db_async() as db:
                for one in rows:
                    await db.execute(_JOURNAL_MYSQL_INSERT, (
                        one['fingerprint'], one['source'], one['query'],
                        int(one['hits']), float(one['total_ms']), float(one['max_ms']),
                        int(one['total_rows']), int(one['max_rows']),
                        float(one['slow_ms']), int(one['slow_rows']),
                        one['slow_args'] or None, one['slow_at'],
                        one['first_at'], one['last_at'],
                    ))
    except Exception as e:
        logger_info(f'[journal_mysql] пачка не записалась ({len(rows)} видов): {e}')
        return 0

    return len(rows)


async def journal_mysql_watch_stop() -> int:
    """Сбрасывает последнее и выключает счёт. Для короткого процесса — в `finally`.

    Returns:
        int: сколько видов запроса уехало в таблицу.

    Воркер и кронджоб живут минуту и умирают: фоновая задача им не нужна, а вот
    сбросить перед смертью — обязательно, иначе вся их работа пропадёт. Ставится
    рядом с `mysql_pool_close()` и **до** него: сброс ходит в базу тем же пулом.
    """
    count = await journal_mysql_flush()
    mysql_watch_off()

    return count


async def journal_mysql_flush_forever(source: str) -> None:
    """Сбрасывает накопленное раз в `JOURNAL_MYSQL_FLUSH_SECONDS`, пока живёт процесс.

    Args:
        source: чей это процесс — нужен, чтобы вернуть счёт, если настройку
            включили обратно.

    Зовётся фоновой задачей из точки входа долгоживущего процесса.

    ⚠ На каждом такте перечитывает настройку: галочка на `/admin/setting`
    действует через полминуты, без перезапуска контейнеров. Сначала сброс, потом
    сверка — иначе выключение теряло бы последнюю накопленную пачку.

    ⚠ Отмену пропускает наружу, но перед уходом сбрасывает последнее: иначе
    работа последних тридцати секунд перед остановкой терялась бы — а это ровно
    те секунды, которые интересны, когда процесс останавливают из-за того, что
    он себя странно вёл.
    """
    try:
        while True:
            await asyncio.sleep(JOURNAL_MYSQL_FLUSH_SECONDS)
            await journal_mysql_flush()
            await journal_mysql_watch_start(source)
    except asyncio.CancelledError:
        await journal_mysql_flush()
        raise


async def journal_mysql_rows(source: str = '', q: str = '', order: str = 'total_ms',
                             page: int = 1, per_page: int = JOURNAL_MYSQL_PAGE) -> dict:
    """Страница журнала запросов.

    Args:
        source: чей процесс. Пусто — любой.
        q: подстрока в тексте запроса или в значениях.
        order: чем сортировать — ключ из `JOURNAL_MYSQL_ORDER`.
        page, per_page: страница и её размер.

    Returns:
        dict: `rows` (со средними `avg_ms` и `avg_rows`), `total`, `page`,
        `pages`, `sources`, `orders`, `enabled`, `totals` — итоги по всему
        отбору, а не по странице.

    Время в строках — UTC, как всё в проекте: сдвигает страница по настройке
    `timezone`.
    """
    from src.journal.journal import JOURNAL_SOURCES

    per_page = max(1, min(int(per_page or JOURNAL_MYSQL_PAGE), JOURNAL_MYSQL_PAGE_MAX))
    page = max(1, int(page or 1))
    order_sql = JOURNAL_MYSQL_ORDER.get(order) or JOURNAL_MYSQL_ORDER['total_ms']

    where, params = [], []
    if source:
        where.append('source = %s')
        params.append(str(source)[:32])
    if q:
        where.append('(`query` LIKE %s OR slow_args LIKE %s)')
        params += [f'%{q}%'] * 2

    where_sql = f' WHERE {" AND ".join(where)}' if where else ''

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT COUNT(*) AS qty, COALESCE(SUM(hits), 0) AS hits,'
            '       COALESCE(SUM(total_ms), 0) AS total_ms'
            f'  FROM journal_mysql{where_sql}', params)
        summary = dict(await db.fetchone() or {})
        total = int(summary.get('qty') or 0)

        pages = max(1, -(-total // per_page))
        page = min(page, pages)

        await db.execute(
            'SELECT id, fingerprint, source, `query`, hits, total_ms, max_ms,'
            '       total_rows, max_rows, slow_ms, slow_rows, slow_args, slow_at,'
            '       first_at, last_at,'
            '       total_ms / GREATEST(hits, 1) AS avg_ms,'
            '       total_rows / GREATEST(hits, 1) AS avg_rows'
            f'  FROM journal_mysql{where_sql}'
            f' ORDER BY {order_sql}, id DESC'
            ' LIMIT %s OFFSET %s',
            (*params, per_page, (page - 1) * per_page))
        rows = await db.fetchall()

    return {'rows': [_journal_mysql_row(dict(row)) for row in rows],
            'total': total, 'page': page, 'pages': pages,
            'sources': JOURNAL_SOURCES,
            'orders': list(JOURNAL_MYSQL_ORDER),
            'enabled': await journal_mysql_enabled(),
            'setting': JOURNAL_MYSQL_SETTING,
            'totals': {'hits': int(summary.get('hits') or 0),
                       'total_ms': float(summary.get('total_ms') or 0.0)}}


async def journal_mysql_delete(row_id: int) -> int:
    """Убирает одну строку — разобрались и больше не хотим её видеть."""
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM journal_mysql WHERE id = %s', (int(row_id),))
        return int(db.rowcount or 0)


async def journal_mysql_clear(source: str = '') -> int:
    """Чистит журнал запросов целиком либо по одному процессу.

    ⚠ Чистка здесь осмысленнее, чем у ошибок: счётчики копятся с начала времён, и
    после правки запроса старые числа мешают увидеть, стало ли лучше. Обнулить и
    посмотреть заново — обычный ход, а не крайняя мера.
    """
    async with mysql_get_db_async() as db:
        if source:
            await db.execute('DELETE FROM journal_mysql WHERE source = %s', (str(source)[:32],))
        else:
            await db.execute('DELETE FROM journal_mysql')
        return int(db.rowcount or 0)


async def journal_mysql_trim(keep_days: int = JOURNAL_MYSQL_KEEP_DAYS) -> int:
    """Убирает строки, которых давно не было. Зовётся при показе подвкладки.

    Отдельного расписания нет намеренно — так же чистятся соседи: журнал ошибок
    при показе, трасса workflow кроном.
    """
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM journal_mysql WHERE last_at < NOW() - INTERVAL %s DAY',
                         (int(keep_days),))
        return int(db.rowcount or 0)


# ── Приватное ────────────────────────────────────────────────────────────────

# Повтор вида запроса складывается со строкой, а не заводит новую. Счётчики
# именно складываются: пачка приносит своё «за последние полминуты».
#
# ⚠ `max_ms`, `max_rows` и `slow_*` берутся наибольшими, а не последними: худший
# случай не должен теряться от того, что следующая пачка оказалась спокойной.
# `slow_args`, `slow_rows` и `slow_at` двигаются вместе со своим `slow_ms` —
# иначе значения в строке были бы от одного прогона, а время от другого. Отсюда
# и порядок: `slow_ms` обновляется **последним**, когда тройка рядом с ним уже
# сравнила себя со старым значением.
#
# ⚠ Новая строка берётся через псевдоним (`AS fresh`), а не функцией `VALUES(col)`:
# с MySQL 8.0.20 та объявлена устаревшей и на каждую запись пишет предупреждение
# в журнал сервера. Та же форма, что в `journal.py`.
#
# ⚠⚠ **Старое значение обязано называться с таблицей** (`journal_mysql.hits`), а
# не голым именем. У псевдонима колонки зовутся так же, и `hits = hits + fresh.hits`
# — это `Column 'hits' in field list is ambiguous`, отказ всей вставки. В соседнем
# `journal.py` этого не видно: там справа стоят литералы (`hits = hits + 1`), и
# выбирать базе не из чего. Поймано на первом же сбросе — пачка молча не
# записывалась, а таблица оставалась пустой.
_JOURNAL_MYSQL_INSERT = (
    'INSERT INTO journal_mysql'
    ' (fingerprint, source, `query`, hits, total_ms, max_ms, total_rows, max_rows,'
    '  slow_ms, slow_rows, slow_args, slow_at, first_at, last_at)'
    ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS fresh'
    ' ON DUPLICATE KEY UPDATE'
    '   `query`    = fresh.`query`,'
    '   hits       = journal_mysql.hits + fresh.hits,'
    '   total_ms   = journal_mysql.total_ms + fresh.total_ms,'
    '   total_rows = journal_mysql.total_rows + fresh.total_rows,'
    '   max_ms     = GREATEST(journal_mysql.max_ms, fresh.max_ms),'
    '   max_rows   = GREATEST(journal_mysql.max_rows, fresh.max_rows),'
    '   slow_rows  = IF(fresh.slow_ms > journal_mysql.slow_ms,'
    '                   fresh.slow_rows, journal_mysql.slow_rows),'
    '   slow_args  = IF(fresh.slow_ms > journal_mysql.slow_ms,'
    '                   fresh.slow_args, journal_mysql.slow_args),'
    '   slow_at    = IF(fresh.slow_ms > journal_mysql.slow_ms,'
    '                   fresh.slow_at, journal_mysql.slow_at),'
    '   slow_ms    = GREATEST(journal_mysql.slow_ms, fresh.slow_ms),'
    '   first_at   = LEAST(journal_mysql.first_at, fresh.first_at),'
    '   last_at    = GREATEST(journal_mysql.last_at, fresh.last_at)'
)


def _journal_mysql_row(row: dict) -> dict:
    """Дополняет строку тем, что нужно странице, и не нужно базе."""
    from src.journal.journal import JOURNAL_SOURCES

    row['source_title'] = JOURNAL_SOURCES.get(row.get('source'), row.get('source') or '')
    row['avg_ms'] = float(row.get('avg_ms') or 0.0)
    row['avg_rows'] = float(row.get('avg_rows') or 0.0)

    return row

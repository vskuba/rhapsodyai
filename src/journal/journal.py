"""Журнал ошибок установки: одно место, куда стекается всё сломавшееся.

Ошибку видел только тот, кто в этот момент смотрел в `docker logs` или открыл
`data/log/app.log` внутри контейнера. Воркер упал ночью, кронджоб сорвался,
роутер отдал 500 — узнавали об этом от человека со словами «что-то не работает»,
и дальше искали по логам четырёх контейнеров. Страница трасс показывает только
падения workflow: всё, что случилось вне движка, там не видно вовсе.

Пишет сюда не код по месту, а обработчик корневого логгера
(`journal_handler.py`): любой `logger_exception` / `logging.error` в любом
процессе установки оставляет здесь строку. Поэтому новый код попадает в журнал
сам, без единой строчки про журнал в нём.

## ⚠⚠ Устройство — в общем слое `py_modules/journal_/`

Отпечаток (`journal_key`), синхронная запись своим соединением
(`journal_sink_write`) и застава на корневом логгере (`journal_catch_install`)
уехали в слой: они нужны любому проекту с базой, и у соседей их недоставало.
Здесь остаётся предмет этого проекта — таблица `journal`, реестр источников,
страницы, чистка по сроку и решение «что считать своим».

## ⚠ Строка одна на отпечаток, а не на каждое падение

Сломавшийся цикл даёт одну и ту же ошибку каждую секунду. Строка на каждую — это
десятки тысяч одинаковых записей за ночь и таблица, в которой ничего не найти.
Поэтому строка одна на `fingerprint`, а повторы считаются (`hits`, `first_at`,
`last_at`). Тот же приём — в журнале отказов соседнего проекта DatingAi
(`src/dating/error.py`), там он проверен живым трафиком.

⚠ **В отличие от DatingAi, удача строку не стирает.** Там журнал отвечает на
вопрос «что сломано прямо сейчас», и починка убирает запись. Здесь предмет
другой — «что ломалось на установке»: ошибка воркера, случившаяся ночью,
интересна утром, даже если следующий заход прошёл. Чистит журнал время
(`JOURNAL_KEEP_DAYS`) и человек кнопкой.

## ⚠⚠ Запись синхронная, и это выбрано намеренно

Логгер зовут откуда угодно: из обработчика запроса, из потока `rq`, из
кронджоба, у которого цикл событий вот-вот закроется. Асинхронная запись
«в фоне» в двух последних случаях теряется молча — задача не успевает
выполниться до конца процесса. Поэтому `journal_write` — обычная функция, а
запись идёт своим соединением под замком (`journal_sink_write` слоя):
несколько миллисекунд на ошибке, которая и так случается редко, дешевле
потерянной записи.

Чтение (`journal_rows` и соседи) — асинхронное: его зовёт роутер, и там пул
уже есть.
"""

import json

from journal_.journal_key import journal_key
from journal_.journal_sink import journal_sink_write
from mysql_.mysql_ import mysql_get_db_async

# Кто поймал ошибку. Ключи — те же слова, что ложатся в колонку `source`; подписи
# для человека страница берёт отсюда, своей копии не держит.
JOURNAL_SOURCES = {
    'uvicorn': 'сервер',
    'worker': 'воркер',
    'telegram': 'телеграм-бот',
    'cronjob': 'кронджоб',
}

# Длина текста ошибки. Обрезаем при записи, а не при показе: в базе незачем
# держать мегабайт чужого вывода, а человек читает первые строки.
JOURNAL_MESSAGE_MAX = 2000

# Трассировка длиннее этого обрезается. 20 000 — столько же, сколько хранит
# трасса workflow (`ai_workflow_trace`): разойдись цифры — и одна и та же ошибка
# выглядела бы на двух страницах по-разному.
JOURNAL_TRACEBACK_MAX = 20000

# Сколько строк отдаём страницей и сколько разрешаем запросить.
JOURNAL_PAGE = 50
JOURNAL_PAGE_MAX = 200

# Сколько дней держим запись. Журнал читают, разбираясь с тем, что случилось на
# днях; месячной давности ошибка уже не о текущем коде. Срок длиннее, чем у
# трассы workflow (там 7 дней): трасса пишется на каждый запуск, а сюда
# попадают только падения.
JOURNAL_KEEP_DAYS = 30

def journal_write(source: str, message: str, level: str = 'ERROR',
                  logger_name: str = '', traceback_text: str = '',
                  context: dict | None = None) -> None:
    """Записывает ошибку в журнал. Повтор того же отпечатка — счётчик, а не строка.

    Args:
        source: кто поймал (`JOURNAL_SOURCES`).
        message: текст ошибки — его и читает человек.
        level: `ERROR` или `CRITICAL`.
        logger_name: имя логгера, оно же подсистема.
        traceback_text: трассировка целиком, если есть.
        context: где случилось — модуль, функция, строка, `trace_id`.

    ⚠ **Не бросает ничего.** Запись ошибки не должна ронять то, что эту ошибку
    поймало: иначе недоступная база превращала бы «не отправилось письмо» в
    «упал процесс».

    ⚠ О своих неудачах сообщает через `logger_info`, а не `logger_exception`:
    обработчик журнала слушает уровень ERROR, и жалоба на недоступную базу
    пошла бы записываться в ту же недоступную базу — по кругу.

    ⚠ Синхронная намеренно: зовут её из потоков `rq` и из кронджобов, где
    фоновая задача не успевает выполниться до конца процесса (шапка модуля).
    """
    message = str(message or '').strip()[:JOURNAL_MESSAGE_MAX]
    if not message:
        return

    row = (
        str(source or '')[:32],
        str(level or 'ERROR')[:16],
        str(logger_name or '')[:255],
        message,
        (traceback_text or '')[:JOURNAL_TRACEBACK_MAX] or None,
        json.dumps(context or {}, ensure_ascii=False, default=str),
        journal_key(str(source or ''), str(logger_name or ''), message=message),
    )

    journal_sink_write(_JOURNAL_INSERT, row, what='journal')


async def journal_rows(source: str = '', level: str = '', q: str = '',
                       page: int = 1, per_page: int = JOURNAL_PAGE) -> dict:
    """Страница журнала — свежее сверху.

    Args:
        source: чей процесс (`JOURNAL_SOURCES`). Пусто — любой.
        level: `ERROR` или `CRITICAL`. Пусто — любой.
        q: подстрока в тексте ошибки, в трассировке или в имени логгера.
        page, per_page: страница и её размер.

    Returns:
        dict: `rows` — строки журнала, `total`, `page`, `pages`,
        `sources` — как звать каждый источник для человека.

    Время в строках — UTC, как всё в проекте: сдвигает страница по настройке
    `timezone`.
    """
    per_page = max(1, min(int(per_page or JOURNAL_PAGE), JOURNAL_PAGE_MAX))
    page = max(1, int(page or 1))

    where, params = [], []
    if source:
        where.append('source = %s')
        params.append(str(source)[:32])
    if level:
        where.append('level = %s')
        params.append(str(level)[:16])
    if q:
        where.append('(message LIKE %s OR logger LIKE %s OR traceback LIKE %s)')
        params += [f'%{q}%'] * 3

    where_sql = f' WHERE {" AND ".join(where)}' if where else ''

    async with mysql_get_db_async() as db:
        await db.execute(f'SELECT COUNT(*) AS qty FROM journal{where_sql}', params)
        total = int((await db.fetchone() or {}).get('qty') or 0)

        pages = max(1, -(-total // per_page))
        page = min(page, pages)

        await db.execute(
            'SELECT id, source, level, logger, message, traceback, context,'
            '       hits, first_at, last_at'
            f'  FROM journal{where_sql}'
            ' ORDER BY last_at DESC, id DESC'
            ' LIMIT %s OFFSET %s',
            (*params, per_page, (page - 1) * per_page))
        rows = await db.fetchall()

    return {'rows': [_journal_row(dict(row)) for row in rows],
            'total': total, 'page': page, 'pages': pages,
            'sources': JOURNAL_SOURCES}


async def journal_delete(row_id: int) -> int:
    """Убирает одну запись — разобрались и больше не хотим её видеть.

    Returns:
        int: сколько строк убрано; 0 — записи уже не было.
    """
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM journal WHERE id = %s', (int(row_id),))
        return int(db.rowcount or 0)


async def journal_clear(source: str = '') -> int:
    """Чистит журнал целиком либо по одному источнику.

    Args:
        source: чей процесс убрать. Пусто — все.

    Returns:
        int: сколько строк убрано.
    """
    async with mysql_get_db_async() as db:
        if source:
            await db.execute('DELETE FROM journal WHERE source = %s', (str(source)[:32],))
        else:
            await db.execute('DELETE FROM journal')
        return int(db.rowcount or 0)


async def journal_trim(keep_days: int = JOURNAL_KEEP_DAYS) -> int:
    """Убирает записи старше срока. Зовётся при показе журнала.

    Отдельного расписания у чистки нет намеренно: журнал читают редко, а строк в
    нём немного — кронджоб ради десятка удалений был бы лишней движущейся
    частью. Так же чистится трасса workflow — при показе списка запусков.

    Returns:
        int: сколько строк убрано.
    """
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM journal WHERE last_at < NOW() - INTERVAL %s DAY',
                         (int(keep_days),))
        return int(db.rowcount or 0)


# ── Приватное ────────────────────────────────────────────────────────────────

# Текст и трассировку обновляем: интересна последняя, а не первая — по ней
# смотрят, что происходит сейчас. Время ставим явно: MySQL не трогает
# `ON UPDATE`-колонку, когда все значения совпали, и у зациклившейся ошибки
# `last_at` замер бы на первом падении.
#
# ⚠ Новая строка берётся через псевдоним (`AS fresh`), а не функцией
# `VALUES(col)`: с MySQL 8.0.20 та объявлена устаревшей и на каждую запись
# пишет предупреждение в журнал сервера. В проекте есть места со старой формой —
# это не повод заводить новое.
_JOURNAL_INSERT = (
    'INSERT INTO journal'
    ' (source, level, logger, message, traceback, context, fingerprint)'
    ' VALUES (%s, %s, %s, %s, %s, %s, %s) AS fresh'
    ' ON DUPLICATE KEY UPDATE'
    '   message = fresh.message,'
    '   traceback = fresh.traceback,'
    '   context = fresh.context,'
    '   level = fresh.level,'
    '   hits = hits + 1,'
    '   last_at = NOW(3)'
)


def _journal_row(row: dict) -> dict:
    """Дополняет строку тем, что нужно странице, и не нужно базе."""
    context = row.get('context')
    if isinstance(context, str):
        try:
            context = json.loads(context or '{}')
        except ValueError:
            context = {}

    row['context'] = context or {}
    row['source_title'] = JOURNAL_SOURCES.get(row.get('source'), row.get('source') or '')
    return row

"""Журнал ошибок установки: одно место, куда стекается всё сломавшееся.

Ошибку видел только тот, кто в этот момент смотрел в `docker logs` или открыл
`data/log/app.log` внутри контейнера. Воркер упал ночью, кронджоб сорвался,
роутер отдал 500 — узнавали об этом от человека со словами «что-то не работает»,
и дальше искали по логам четырёх контейнеров. Страница трасс показывает только
падения workflow: всё, что случилось вне движка, там не видно вовсе.

Пишет сюда не код по месту, а обработчик корневого логгера
(`error_log_handler.py`): любой `logger_exception` / `logging.error` в любом
процессе установки оставляет здесь строку. Поэтому новый код попадает в журнал
сам, без единой строчки про журнал в нём.

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
(`ERROR_LOG_KEEP_DAYS`) и человек кнопкой.

## ⚠⚠ Запись синхронная, и это выбрано намеренно

Логгер зовут откуда угодно: из обработчика запроса, из потока `rq`, из
кронджоба, у которого цикл событий вот-вот закроется. Асинхронная запись
«в фоне» в двух последних случаях теряется молча — задача не успевает
выполниться до конца процесса. Поэтому `error_log_write` — обычная функция с
одним соединением pymysql на процесс: несколько миллисекунд на ошибке, которая
и так случается редко, дешевле потерянной записи.

Чтение (`error_log_rows` и соседи) — асинхронное: его зовёт роутер, и там пул
уже есть.
"""

import hashlib
import json
import re
import threading

import pymysql

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_conn_get, mysql_get_db_async

# Кто поймал ошибку. Ключи — те же слова, что ложатся в колонку `source`; подписи
# для человека страница берёт отсюда, своей копии не держит.
ERROR_LOG_SOURCES = {
    'uvicorn': 'сервер',
    'worker': 'воркер',
    'telegram': 'телеграм-бот',
    'cronjob': 'кронджоб',
}

# Длина текста ошибки. Обрезаем при записи, а не при показе: в базе незачем
# держать мегабайт чужого вывода, а человек читает первые строки.
ERROR_LOG_MESSAGE_MAX = 2000

# Трассировка длиннее этого обрезается. 20 000 — столько же, сколько хранит
# трасса workflow (`ai_workflow_trace`): разойдись цифры — и одна и та же ошибка
# выглядела бы на двух страницах по-разному.
ERROR_LOG_TRACEBACK_MAX = 20000

# Сколько строк отдаём страницей и сколько разрешаем запросить.
ERROR_LOG_PAGE = 50
ERROR_LOG_PAGE_MAX = 200

# Сколько дней держим запись. Журнал читают, разбираясь с тем, что случилось на
# днях; месячной давности ошибка уже не о текущем коде. Срок длиннее, чем у
# трассы workflow (там 7 дней): трасса пишется на каждый запуск, а сюда
# попадают только падения.
ERROR_LOG_KEEP_DAYS = 30

# Что вычёркиваем из текста, считая отпечаток: меняющиеся куски. Иначе одна и та
# же ошибка с другим id в сообщении заводит новую строку, и счётчик повторов
# теряет смысл.
_ERROR_LOG_VARIABLE = (
    # uuid целиком
    re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I),
    # адреса в памяти (`at 0x7f…`)
    re.compile(r'\b0x[0-9a-f]+\b', re.I),
    # числа от трёх знаков: id, порты, миллисекунды
    re.compile(r'\b\d{3,}\b'),
)


def error_log_fingerprint(source: str, logger_name: str, message: str) -> str:
    """Отпечаток «той же самой ошибки» — по нему повтор находит свою строку.

    Args:
        source: процесс, поймавший ошибку.
        logger_name: имя логгера — оно же подсистема.
        message: текст ошибки.

    Returns:
        str: 32 шестнадцатеричных знака (md5).

    ⚠ Из текста вычёркиваются меняющиеся куски — uuid, адреса в памяти, числа от
    трёх знаков. Без этого «задача 5219 не найдена» и «задача 5220 не найдена»
    были бы разными ошибками, и вместо одной строки со счётчиком журнал копил бы
    по строке на задачу.

    ⚠ Отпечаток считается **только по первой строке** сообщения: логгер часто
    получает текст вместе с приклеенной трассировкой, и её адреса развели бы
    одинаковые ошибки по разным строкам.
    """
    head = str(message or '').strip().split('\n', 1)[0]
    for pattern in _ERROR_LOG_VARIABLE:
        head = pattern.sub('#', head)

    raw = f'{source}|{logger_name}|{head[:ERROR_LOG_MESSAGE_MAX]}'
    return hashlib.md5(raw.encode('utf-8', errors='ignore')).hexdigest()


def error_log_write(source: str, message: str, level: str = 'ERROR',
                    logger_name: str = '', traceback_text: str = '',
                    context: dict | None = None) -> None:
    """Записывает ошибку в журнал. Повтор того же отпечатка — счётчик, а не строка.

    Args:
        source: кто поймал (`ERROR_LOG_SOURCES`).
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
    message = str(message or '').strip()[:ERROR_LOG_MESSAGE_MAX]
    if not message:
        return

    row = (
        str(source or '')[:32],
        str(level or 'ERROR')[:16],
        str(logger_name or '')[:255],
        message,
        (traceback_text or '')[:ERROR_LOG_TRACEBACK_MAX] or None,
        json.dumps(context or {}, ensure_ascii=False, default=str),
        error_log_fingerprint(str(source or ''), str(logger_name or ''), message),
    )

    with _error_log_lock:
        try:
            connection = _error_log_connection()
            with connection.cursor() as cursor:
                cursor.execute(_ERROR_LOG_INSERT, row)
            connection.commit()
        except Exception as e:
            _error_log_connection_drop()
            logger_info(f'[error_log] ошибка не записалась в журнал: {e}')


async def error_log_rows(source: str = '', level: str = '', q: str = '',
                         page: int = 1, per_page: int = ERROR_LOG_PAGE) -> dict:
    """Страница журнала — свежее сверху.

    Args:
        source: чей процесс (`ERROR_LOG_SOURCES`). Пусто — любой.
        level: `ERROR` или `CRITICAL`. Пусто — любой.
        q: подстрока в тексте ошибки, в трассировке или в имени логгера.
        page, per_page: страница и её размер.

    Returns:
        dict: `rows` — строки журнала, `total`, `page`, `pages`,
        `sources` — как звать каждый источник для человека.

    Время в строках — UTC, как всё в проекте: сдвигает страница по настройке
    `timezone`.
    """
    per_page = max(1, min(int(per_page or ERROR_LOG_PAGE), ERROR_LOG_PAGE_MAX))
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
        await db.execute(f'SELECT COUNT(*) AS qty FROM error_log{where_sql}', params)
        total = int((await db.fetchone() or {}).get('qty') or 0)

        pages = max(1, -(-total // per_page))
        page = min(page, pages)

        await db.execute(
            'SELECT id, source, level, logger, message, traceback, context,'
            '       hits, first_at, last_at'
            f'  FROM error_log{where_sql}'
            ' ORDER BY last_at DESC, id DESC'
            ' LIMIT %s OFFSET %s',
            (*params, per_page, (page - 1) * per_page))
        rows = await db.fetchall()

    return {'rows': [_error_log_row(dict(row)) for row in rows],
            'total': total, 'page': page, 'pages': pages,
            'sources': ERROR_LOG_SOURCES}


async def error_log_delete(row_id: int) -> int:
    """Убирает одну запись — разобрались и больше не хотим её видеть.

    Returns:
        int: сколько строк убрано; 0 — записи уже не было.
    """
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM error_log WHERE id = %s', (int(row_id),))
        return int(db.rowcount or 0)


async def error_log_clear(source: str = '') -> int:
    """Чистит журнал целиком либо по одному источнику.

    Args:
        source: чей процесс убрать. Пусто — все.

    Returns:
        int: сколько строк убрано.
    """
    async with mysql_get_db_async() as db:
        if source:
            await db.execute('DELETE FROM error_log WHERE source = %s', (str(source)[:32],))
        else:
            await db.execute('DELETE FROM error_log')
        return int(db.rowcount or 0)


async def error_log_trim(keep_days: int = ERROR_LOG_KEEP_DAYS) -> int:
    """Убирает записи старше срока. Зовётся при показе журнала.

    Отдельного расписания у чистки нет намеренно: журнал читают редко, а строк в
    нём немного — кронджоб ради десятка удалений был бы лишней движущейся
    частью. Так же чистится трасса workflow — при показе списка запусков.

    Returns:
        int: сколько строк убрано.
    """
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM error_log WHERE last_at < NOW() - INTERVAL %s DAY',
                         (int(keep_days),))
        return int(db.rowcount or 0)


# ── Приватное ────────────────────────────────────────────────────────────────

# Соединение на процесс и замок к нему. pymysql не умеет работать из двух потоков
# сразу, а логгер зовут откуда угодно — включая потоки `rq`.
_error_log_conn: pymysql.Connection | None = None
_error_log_lock = threading.Lock()

# Текст и трассировку обновляем: интересна последняя, а не первая — по ней
# смотрят, что происходит сейчас. Время ставим явно: MySQL не трогает
# `ON UPDATE`-колонку, когда все значения совпали, и у зациклившейся ошибки
# `last_at` замер бы на первом падении.
#
# ⚠ Новая строка берётся через псевдоним (`AS fresh`), а не функцией
# `VALUES(col)`: с MySQL 8.0.20 та объявлена устаревшей и на каждую запись
# пишет предупреждение в журнал сервера. В проекте есть места со старой формой —
# это не повод заводить новое.
_ERROR_LOG_INSERT = (
    'INSERT INTO error_log'
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


def _error_log_connection() -> pymysql.Connection:
    """Живое соединение: заводит при первом обращении, поднимает после обрыва.

    ⚠ Зовётся только под `_error_log_lock`.
    """
    global _error_log_conn

    if _error_log_conn is None:
        _error_log_conn = mysql_conn_get()
    else:
        # База рвёт простаивающие соединения по `wait_timeout`, а журнал молчит
        # сутками: без пинга первая же ночная ошибка ушла бы в закрытый сокет.
        _error_log_conn.ping(reconnect=True)

    return _error_log_conn


def _error_log_connection_drop() -> None:
    """Забывает соединение после неудачи — следующая запись заведёт новое.

    ⚠ Зовётся только под `_error_log_lock`.
    """
    global _error_log_conn

    if _error_log_conn is not None:
        try:
            _error_log_conn.close()
        except Exception:
            pass
        _error_log_conn = None


def _error_log_row(row: dict) -> dict:
    """Дополняет строку тем, что нужно странице, и не нужно базе."""
    context = row.get('context')
    if isinstance(context, str):
        try:
            context = json.loads(context or '{}')
        except ValueError:
            context = {}

    row['context'] = context or {}
    row['source_title'] = ERROR_LOG_SOURCES.get(row.get('source'), row.get('source') or '')
    return row

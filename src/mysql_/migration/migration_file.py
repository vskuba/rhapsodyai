"""
Миграции ветки: что в ней лежит, применено ли, и проверка в песочнице.

Зачем. Миграции пишутся в ветках подзадач и приезжают вместе с кодом, который их
требует: переименовали функцию инструмента — нужен `UPDATE tool_name` в шагах
workflow, иначе после слияния сломается то, что звало её по имени. Человек,
сливающий ветку, должен видеть обе половины работы на одном экране — отсюда
вкладка «Миграции» рядом с diff.

Применяет их не этот модуль, а **yoyo при старте приложения**. Здесь только
показываем: какие файлы есть в ветке, какие из них уже в журнале
`_yoyo_migration`, и что будет, если применить. Применять руками нельзя — журнал
не обновится, и yoyo прогонит файл ещё раз.

Проверка идёт **в песочнице** (`migration_sandbox`): одноразовая база со всей
папкой миграций, где новую можно прогнать без риска. Раньше здесь был сухой
прогон транзакцией по рабочей базе — он не ловил DDL (MySQL коммитит его неявно)
и всё равно трогал живые данные. Песочница честнее и умеет проверять и то, и
другое.

Журнал прогонов (`migration_manual_log`) остался: по нему видно, что проверяли,
когда и чем кончилось.
"""
import hashlib
import os
import re
import time

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Где лежат файлы. Общая папка миграций: в ветке подзадачи она своя, и новый файл
# лежит там же, где все остальные, — при слиянии он просто встаёт в общий ряд.
MIGRATION_FILE_DIR = 'migrations'

# Имя файла: метка времени и что делаем. Не украшение, а порядок применения —
# алфавитный порядок имён совпадает с хронологическим, и в нём yoyo их применяет.
# Сколько текста миграции отдаём странице. Хватает, чтобы прочитать смысл файла:
# шапка с объяснением и сами запросы. Всё, что длиннее, — обычно вставка данных, и
# читать её глазами всё равно не станут.
MIGRATION_FILE_SQL_MAX = 20000

MIGRATION_FILE_NAME_RE = re.compile(r'^\d{14}_[\w.-]+\.sql$')

# Исходы прогона.
MIGRATION_FILE_STATUS_OK = 'ok'
MIGRATION_FILE_STATUS_ERROR = 'error'
MIGRATION_FILE_STATUS_DRY = 'dry'

# Команды, которые транзакция не откатит: MySQL коммитит неявно на любом DDL.
# Сухой прогон такого файла ничего не проверяет, а меняет базу по-настоящему,
# поэтому он для них запрещён, а не «выполнен с оговоркой».
MIGRATION_FILE_DDL = ('alter table', 'create table', 'drop table', 'truncate',
                        'create index', 'drop index', 'rename table', 'create database',
                        'drop database', 'alter database')


async def migration_file_list(repo_dir: str, database: str = '',
                              own_only: bool = False) -> list[dict]:
    """
    Файлы миграций с их состоянием: применяли ли, чем кончилось, менялся ли файл.

    Args:
        repo_dir: корень репозитория или каталог подзадачи — миграция лежит в
            ветке рядом с кодом, который её требует.
        database: для какой базы смотреть журнал. Пусто — текущая рабочая.
        own_only: оставить только миграции **этой ветки** — те, которых нет в
            главной. Каталог подзадачи содержит весь репозиторий, и без фильтра
            список отдаёт все два десятка файлов проекта: свои одна-две тонут
            среди чужих, а рядом с каждой стоит кнопка «Применить». Не ветка (в
            каталоге нет git) — фильтр молча не срабатывает, и список остаётся
            полным: это честнее пустого экрана.

    Returns: `[{'name', 'bytes', 'sha1', 'ddl', 'statements', 'own', 'log': …}]`,
        свежие файлы первыми (имя начинается с даты, поэтому обратный порядок имени
        и есть обратный порядок времени). `own` — файл написан в этой ветке.
    """
    directory = os.path.join(str(repo_dir or '').rstrip('/'), MIGRATION_FILE_DIR)
    if not os.path.isdir(directory):
        return []

    names = sorted((n for n in os.listdir(directory) if MIGRATION_FILE_NAME_RE.match(n)),
                   reverse=True)
    if not names:
        return []

    own = await _branch_own_names(repo_dir)
    if own_only and own is not None:
        names = [name for name in names if name in own]
        if not names:
            return []

    log = await _log_last(names, database or await migration_file_database())
    applied = await _yoyo_applied(names)

    items = []
    for name in names:
        sql = _read(os.path.join(directory, name))
        statements = migration_file_split(sql)
        items.append({
            'name': name,
            # Сам текст — страница раскрывает файл прямо в списке: имя и число
            # запросов не говорят, что миграция делает, а решение «применять или
            # нет» принимают именно по содержимому. Обрезаем по потолку: файл со
            # вставкой данных бывает на сотни килобайт, и целиком он повесил бы
            # вкладку, ничего не добавив к пониманию.
            'sql': sql[:MIGRATION_FILE_SQL_MAX],
            'sql_cut': len(sql) > MIGRATION_FILE_SQL_MAX,
            'bytes': len(sql.encode('utf-8')),
            'sha1': _sha1(sql),
            # Файл с DDL сухим прогоном не проверить — предупреждаем заранее, а не
            # после того, как «проверка» изменила базу.
            'ddl': _statements_ddl(statements),
            'statements': len(statements),
            # Применена ли по-настоящему — знает только журнал yoyo: применяет он,
            # при старте приложения. Наш журнал помнит проверки, а не применения.
            'applied': name[:-4] in applied,
            'applied_at': applied.get(name[:-4]),
            # Написана в этой ветке или пришла из главной. `None` — сравнить не с
            # чем (каталог не ветка), и тогда поле честно говорит «неизвестно», а
            # не выдаёт чужой файл за свой.
            'own': None if own is None else (name in own),
            'log': log.get(name),
        })

    return items


async def migration_file_apply(repo_dir: str, name: str, dry: bool = False,
                                 database: str = '', by: str = '') -> dict:
    """
    Применить один файл. Возвращает исход и пишет его в журнал.

    Args:
        dry: сухой прогон — выполнить всё в транзакции и откатить. Для файла с DDL
            запрещён: MySQL коммитит DDL неявно, откат ничего не вернёт, и «проверка»
            стала бы настоящим применением.

    Returns:
        `{'ok': bool, 'status', 'statements', 'rows', 'duration_ms', 'error'}`.

    Ошибку не бросаем: применение миграции — обычная операция страницы, и
    свалившийся запрос это её результат, а не сбой приложения. Номер запроса в
    тексте ошибки обязателен — без него в файле на сорок команд искать нечего.
    """
    directory = os.path.join(str(repo_dir or '').rstrip('/'), MIGRATION_FILE_DIR)
    if not MIGRATION_FILE_NAME_RE.match(str(name or '')):
        return _result(MIGRATION_FILE_STATUS_ERROR, error='Имя файла не по шаблону')

    path = os.path.join(directory, name)
    if not os.path.isfile(path):
        return _result(MIGRATION_FILE_STATUS_ERROR, error='Файл не найден')

    sql = _read(path)
    statements = migration_file_split(sql)
    if not statements:
        return _result(MIGRATION_FILE_STATUS_ERROR, error='В файле нет ни одной команды')

    if dry and _statements_ddl(statements):
        return _result(MIGRATION_FILE_STATUS_ERROR,
                       error='Сухой прогон невозможен: в файле DDL, и MySQL коммитит его '
                             'неявно — откат ничего не вернёт. Применяйте по-настоящему, '
                             'сняв бэкап')

    database = database or await migration_file_database()
    started = time.monotonic()
    rows, failed, error = await _run(statements, dry)
    duration = int((time.monotonic() - started) * 1000)

    status = (MIGRATION_FILE_STATUS_ERROR if error
              else MIGRATION_FILE_STATUS_DRY if dry
              else MIGRATION_FILE_STATUS_OK)
    if error:
        error = f'запрос {failed} из {len(statements)}: {error}'

    await _log_write(name, database, status, len(statements), rows, duration,
                     error, _sha1(sql), by)
    logger_info(f'migration_file: {name} -> {status} ({rows} строк, {duration} мс)')

    return _result(status, statements=len(statements), rows=rows,
                   duration_ms=duration, error=error)


async def migration_file_database() -> str:
    """Имя базы, в которой мы сейчас работаем."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT DATABASE() AS name')
        row = await db.fetchone()

    return str((row or {}).get('name') or '')


def migration_file_split(sql: str) -> list[str]:
    """
    Файл на отдельные команды: по точке с запятой вне строк и комментариев.

    Свой разбор, а не `split(';')`: точка с запятой живёт внутри значений (в
    промптах workflow их десятки) и внутри комментариев с шапкой файла. Наивное
    деление рвало бы команду посередине.
    """
    statements, buf = [], []
    quote = None
    i = 0
    while i < len(sql):
        char = sql[i]

        if quote:
            buf.append(char)
            # Экранированный символ внутри строки берём парой: одиночный `\'`
            # иначе закрыл бы строку и увёл разбор в мусор.
            if char == '\\' and i + 1 < len(sql):
                buf.append(sql[i + 1])
                i += 2
                continue
            if char == quote:
                quote = None
            i += 1
            continue

        if char in ("'", '"', '`'):
            quote = char
            buf.append(char)
            i += 1
            continue

        # Комментарии до конца строки: `--` и `#`. Внутри них точка с запятой не
        # разделитель, а текст шапки.
        if sql.startswith('--', i) or char == '#':
            end = sql.find('\n', i)
            i = len(sql) if end < 0 else end
            continue

        if char == ';':
            statements.append(''.join(buf).strip())
            buf = []
            i += 1
            continue

        buf.append(char)
        i += 1

    tail = ''.join(buf).strip()
    if tail:
        statements.append(tail)

    return [s for s in statements if s]


async def _run(statements: list[str], dry: bool) -> tuple[int, int, str]:
    """
    Выполнить команды. Returns: `(строк затронуто, номер упавшей, текст ошибки)`.

    Всё в одной транзакции — и при сухом прогоне, и при настоящем: миграция это
    одно изменение, а половина применённой миграции хуже неприменённой.
    """
    rows = 0
    async with mysql_get_db_async() as db:
        await db.execute('START TRANSACTION')
        for number, statement in enumerate(statements, 1):
            try:
                await db.execute(statement)
                rows += max(0, int(db.rowcount or 0))
            except Exception as e:
                await db.connection.rollback()
                return rows, number, f'{type(e).__name__}: {str(e)[:400]}'

        if dry:
            await db.connection.rollback()
        else:
            await db.connection.commit()

    return rows, 0, ''


async def _yoyo_applied(names: list) -> dict:
    """
    Какие из файлов yoyo уже применил: `{id миграции: когда}`.

    Ключ у yoyo — имя файла без расширения (`_yoyo_migration.migration_id`).
    Спрашиваем именно его, а не свой журнал: свой помнит проверки в песочнице, а
    применяет yoyo, и путать эти два факта нельзя — «проверена» не значит «стоит
    в базе».
    """
    ids = [n[:-4] for n in names if n.endswith('.sql')]
    if not ids:
        return {}

    placeholders = ', '.join(['%s'] * len(ids))
    async with mysql_get_db_async() as db:
        await db.execute(
            f"SELECT migration_id, applied_at_utc FROM _yoyo_migration "
            f" WHERE migration_id IN ({placeholders})", ids)

        return {str(r['migration_id']): r['applied_at_utc'] for r in (await db.fetchall() or [])}


async def _log_last(names: list, database: str) -> dict:
    """Последняя запись журнала по каждому файлу: `{имя: {...}}`."""
    if not names:
        return {}

    placeholders = ', '.join(['%s'] * len(names))
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT m.file_name, m.status, m.statements, m.rows_affected, m.duration_ms, "
            "       m.error, m.sha1, m.applied_by, m.created_at "
            "  FROM migration_manual_log m "
            "  JOIN (SELECT file_name, MAX(id) AS id FROM migration_manual_log "
            f"         WHERE database_name = %s AND file_name IN ({placeholders}) "
            "          GROUP BY file_name) last ON last.id = m.id",
            [database, *names])

        return {str(row['file_name']): dict(row) for row in (await db.fetchall() or [])}


async def _log_write(name: str, database: str, status: str, statements: int, rows: int,
                     duration_ms: int, error: str, sha1: str, by: str) -> None:
    """Записать исход прогона. Сбой записи прогон не отменяет — он уже случился."""
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO migration_manual_log "
                "  (file_name, database_name, status, statements, rows_affected, "
                "   duration_ms, error, sha1, applied_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (name, database, status, statements, rows, duration_ms,
                 str(error or '')[:2000], sha1, str(by or '')[:64]))
            await db.connection.commit()
    except Exception as e:
        logger_info(f'migration_file: журнал не записан для {name}: {type(e).__name__}: {e}')


def _statements_ddl(statements: list[str]) -> bool:
    """Есть ли среди команд DDL — то, что транзакция не откатит."""
    return any(s.lstrip().lower().startswith(ddl)
               for s in statements for ddl in MIGRATION_FILE_DDL)


def _result(status: str, statements: int = 0, rows: int = 0,
            duration_ms: int = 0, error: str = '') -> dict:
    return {'ok': status != MIGRATION_FILE_STATUS_ERROR, 'status': status,
            'statements': statements, 'rows': rows, 'duration_ms': duration_ms,
            'error': error}


def _read(path: str) -> str:
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return ''


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


async def _branch_own_names(repo_dir: str) -> set | None:
    """
    Имена миграций, написанных в этой ветке. `None` — сравнить не с чем.

    Каталог подзадачи — полный чекаут репозитория, и `os.listdir` по нему отдаёт все
    файлы проекта, а не только свои. Отличает их git: `diff --name-only base...HEAD`
    показывает ровно то, что ветка добавила поверх главной.

    Три точки, а не две: нас интересует «что появилось в ветке», а не «чем ветка
    отличается от главной сейчас». Двухточечная форма показала бы ещё и файлы,
    добавленные в главную после ответвления, — они к задаче отношения не имеют.

    `None` возвращается, когда сравнивать не с чем: каталог не репозиторий, git
    недоступен, главной ветки не нашлось. Тогда вызывающий показывает список целиком
    — пустой экран на рабочем проекте хуже, чем лишние строки.
    """
    repo_dir = str(repo_dir or '').strip().rstrip('/')
    if not repo_dir or not os.path.exists(os.path.join(repo_dir, '.git')):
        return None

    try:
        # Импорт внутри: `task_worktree` тянет цепочку модулей конвейера задач, а
        # этот модуль зовут и оттуда — прямой импорт замкнул бы кольцо.
        from src.project.task.task_worktree import task_worktree_base_branch, task_worktree_git

        base = await task_worktree_base_branch(repo_dir)
        if not base:
            return None

        code, out = await task_worktree_git(
            repo_dir, 'diff', '--name-only', f'{base}...HEAD', '--', MIGRATION_FILE_DIR)
        if code:
            return None

        return {os.path.basename(line.strip()) for line in (out or '').splitlines()
                if line.strip().endswith('.sql')}
    except Exception:
        return None

r"""
Песочница: одноразовая копия схемы, где проверяют миграции и новый код.

Зачем. До сих пор всё проверялось на рабочей базе: QA гонял тесты по ней же,
миграции применялись сразу набело. Тесты за собой прибирали по префиксам, но
это уборка, а не изоляция — сбойный тест или неудачная миграция портили живые
данные, и заметить это можно было только постфактум.

Что делает. Создаёт базу с именем `<рабочая>_sandbox_<метка>`, накатывает в неё
схему из `migrations/20260101000000_initial_schema.sql` и отдаёт имя. Дальше в неё можно прогнать миграцию,
поднять тесты, что угодно — а потом снести целиком.

Почему это стало возможно только сейчас. В `20260101000000_initial_schema.sql` второй строкой стоял
`USE \`project\``, и любой прогон «в песочницу» молча переключался на рабочую базу
и сносил её. Строку убрали: имя базы теперь задаёт подключение, а не файл.

Схему берём из того же `20260101000000_initial_schema.sql`, что и рабочая. Отдельного файла для песочницы
быть не должно: он разошёлся бы с рабочим при первой же правке, и проверка стала
бы проверять не то.

Данных здесь нет и не будет. Песочница проверяет схему и миграции, а не поведение
на живых данных: копировать рабочие данные — значит носить в тесты и персональные
записи, и мусор. Нужны данные — их наливает seed, тем же путём, что и в пустую
рабочую базу.
"""
import os
import re
import time

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from sql_.sql_split import sql_split_statements

# Как называются песочницы. Общий префикс — чтобы их было видно в списке баз и
# чтобы уборка могла найти брошенные, не трогая ничего чужого.
MIGRATION_SANDBOX_PREFIX = '_sandbox_'

# Откуда берём схему: вся папка миграций, по порядку имён. Имя начинается с метки
# времени, поэтому алфавитный порядок и есть хронологический — тот же, в котором
# их применяет yoyo. Отдельного «файла схемы для песочницы» быть не должно: он
# разошёлся бы с рабочим при первой правке, и проверка проверяла бы не то.
MIGRATION_SANDBOX_DIR = 'migrations'

# Сколько живёт брошенная песочница, прежде чем её уберут. Прогон тестов идёт
# минуты; сутки — с запасом на разбор упавшего вручную.
MIGRATION_SANDBOX_TTL_HOURS = 24

# Имя базы MySQL: буквы, цифры, подчёркивание. Проверяем сами, потому что имя
# базы в SQL параметром не подставить — только текстом в запрос.
MIGRATION_SANDBOX_NAME_RE = re.compile(r'^[A-Za-z0-9_]{1,64}$')


async def migration_sandbox_create(label: str = '') -> dict:
    """
    Создать песочницу со схемой рабочей базы.

    Args:
        label: пометка в имени — например номер подзадачи. Пусто — метка времени.

    Returns:
        `{'ok': True, 'database': str, 'tables': int}` либо `{'ok': False, 'error': ...}`.
    """
    base = await _database_current()
    if not base:
        return {'ok': False, 'error': 'Не удалось определить рабочую базу'}

    name = _name_build(base, label)
    if not MIGRATION_SANDBOX_NAME_RE.match(name):
        return {'ok': False, 'error': f'Недопустимое имя песочницы: {name}'}

    files = _schema_files()
    if not files:
        return {'ok': False, 'error': f'В {MIGRATION_SANDBOX_DIR} нет ни одной миграции'}

    async with mysql_get_db_async() as db:
        await db.execute(f'DROP DATABASE IF EXISTS `{name}`')
        await db.execute(f'CREATE DATABASE `{name}` '
                         f'CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        await db.connection.commit()

    applied, error = await _schema_apply(name, files)
    if error:
        # Недоделанная песочница хуже отсутствующей: в неё пойдут проверять и
        # получат ложный отказ на половине таблиц.
        await migration_sandbox_drop(name)
        return {'ok': False, 'error': error}

    logger_info(f'migration_sandbox: создана {name}, таблиц {applied}')

    return {'ok': True, 'database': name, 'tables': applied, 'migrations': len(files)}


async def migration_sandbox_drop(name: str) -> bool:
    """
    Снести песочницу. Чужую базу не тронет: имя обязано нести общий префикс.

    Проверка не формальность — имя базы подставляется в запрос текстом, и ошибка
    вызывающего здесь означала бы `DROP DATABASE` по рабочей.
    """
    if not _is_sandbox(name):
        logger_info(f'migration_sandbox: {name} сносить отказываюсь — это не песочница')
        return False

    async with mysql_get_db_async() as db:
        await db.execute(f'DROP DATABASE IF EXISTS `{name}`')
        await db.connection.commit()

    logger_info(f'migration_sandbox: снесена {name}')

    return True


async def migration_sandbox_list() -> list[dict]:
    """Живые песочницы: имя, сколько таблиц, когда заведена."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT s.schema_name AS name, COUNT(t.table_name) AS tables, "
            "       MIN(t.create_time) AS created_at "
            "  FROM information_schema.schemata s "
            "  LEFT JOIN information_schema.tables t ON t.table_schema = s.schema_name "
            " WHERE s.schema_name LIKE %s "
            " GROUP BY s.schema_name ORDER BY s.schema_name",
            (f'%{MIGRATION_SANDBOX_PREFIX}%',))

        return [dict(row) for row in (await db.fetchall() or [])]


async def migration_sandbox_prune() -> int:
    """
    Убрать брошенные песочницы старше суток. Returns: сколько снесли.

    Брошенными они остаются от упавших прогонов: снести песочницу должен тот, кто
    её завёл, а упавший процесс этого уже не сделает. Без уборки они копятся, и
    каждая — это полная схема на шестьдесят с лишним таблиц.
    """
    dropped = 0
    for item in await migration_sandbox_list():
        created = item.get('created_at')
        if not created:
            continue
        age_hours = (time.time() - created.timestamp()) / 3600
        if age_hours >= MIGRATION_SANDBOX_TTL_HOURS and await migration_sandbox_drop(item['name']):
            dropped += 1

    return dropped


async def _schema_apply(name: str, files: list) -> tuple[int, str]:
    """
    Накатить все миграции по порядку. Returns: `(таблиц создано, ошибка)`.

    Порядок — по имени файла, то есть по метке времени: ровно тот, в котором их
    применяет yoyo. Упало — говорим, в каком файле и на каком запросе: в схеме их
    больше сотни, и «ошибка синтаксиса» без адреса бесполезна.

    Команды выполняем на подключении из общего пула, переключив его `USE` и
    вернув обратно в `finally`. Иначе следующий запрос приложения, взяв это же
    подключение, ушёл бы работать в песочницу.
    """
    async with mysql_get_db_async() as db:
        await db.execute(f'USE `{name}`')
        try:
            for path in files:
                statements = sql_split_statements(_read(path))
                for number, statement in enumerate(statements, 1):
                    try:
                        await db.execute(statement)
                    except Exception as e:
                        return 0, (f'{os.path.basename(path)}, запрос {number} из '
                                   f'{len(statements)}: {type(e).__name__}: {str(e)[:300]}')
            await db.connection.commit()
        finally:
            await db.execute(f'USE `{await _database_default()}`')

        await db.execute(
            "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = %s", (name,))
        tables = int((await db.fetchone() or {}).get('n') or 0)

    return tables, ''


async def _database_current() -> str:
    """Имя базы, к которой подключены сейчас."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT DATABASE() AS name')
        row = await db.fetchone()

    return str((row or {}).get('name') or '')


async def _database_default() -> str:
    """Рабочая база из окружения — куда возвращать подключение после песочницы."""
    return os.getenv('MYSQL_DATABASE', '').strip() or await _database_current()


def _name_build(base: str, label: str) -> str:
    """Имя песочницы: рабочая база, префикс, метка. Только допустимые символы."""
    mark = re.sub(r'[^A-Za-z0-9]', '', str(label or '')) or str(int(time.time()))

    return f'{base}{MIGRATION_SANDBOX_PREFIX}{mark}'[:64]


def _is_sandbox(name: str) -> bool:
    """Имя действительно песочницы — иначе `DROP DATABASE` уйдёт не туда."""
    name = str(name or '')

    return bool(MIGRATION_SANDBOX_NAME_RE.match(name)) and MIGRATION_SANDBOX_PREFIX in name


def _schema_files() -> list:
    """Файлы миграций по порядку имён — он же порядок применения."""
    root = os.getenv('PROJECT_DIR', '').strip() or '/app'
    directory = os.path.join(root, MIGRATION_SANDBOX_DIR)
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith('.sql'))
    except OSError as e:
        logger_info(f'migration_sandbox: {directory} не читается: {type(e).__name__}: {e}')
        return []

    return [os.path.join(directory, n) for n in names]


def _read(path: str) -> str:
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read()
    except OSError:
        return ''

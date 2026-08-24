"""
Уборка логов Cronicle: держим только последние дни, остальное сносим.

Cronicle убирает за собой наполовину. Свой суточный лог он ротирует сам —
складывает в `logs/archives/[yyyy]/[mm]/[dd]/[filename]-…log.gz` (настройка
`log_archive_path` в его `conf/config.json`), — но архивы потом не удаляет
никогда. На проде так набралось 208 файлов и 30 МБ начиная с 29 июля.

Вторая половина, `data/jobs` с историей прогонов, к этому модулю отношения не
имеет: её чистит сам Cronicle в ночное обслуживание (`maintenance: "04:00"`) по
настройке `job_data_expire_days`. Она выставляется переменной окружения
`CRONICLE_job_data_expire_days` в `docker-compose.yml` — не здесь.

Каталог виден из uvicorn потому, что корень репозитория смонтирован в контейнер
как `/app`, а логи Cronicle лежат в `./data/cronicle/logs` (см. `docker-compose.yml`).
"""
import os
import time

from logging_.logging_ import logger_info

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# Каталоги, которые чистим. Оба — внутри логов Cronicle: архивы суточной ротации
# и логи отдельных прогонов. Второй обычно пуст (Cronicle пишет их в `data/jobs`),
# но встречается на старых инсталляциях, и оставлять его расти незачем.
CRONICLE_LOG_DIRS = (
    os.path.join('data', 'cronicle', 'logs', 'archives'),
    os.path.join('data', 'cronicle', 'logs', 'jobs'),
)

# Сколько суток логов держим.
CRONICLE_LOG_KEEP_DAYS = 3

# История прогонов: её чистит сам Cronicle, мы только показываем размер. Смысл —
# увидеть, доехала ли `CRONICLE_job_data_expire_days` до его конфига: настройка
# живёт в переменной окружения и применяется в память, на диске в `config.json`
# остаётся прежнее значение, и проверить её иначе как по размеру каталога нечем.
CRONICLE_LOG_JOBS_DIR = os.path.join('data', 'cronicle', 'data', 'jobs')

# Страховка от чужого каталога: удаляем только внутри логов Cronicle. Путь
# собирается из констант выше, но модуль зовётся из кронджоба с аргументами, и
# один опечатанный `days` дешевле поймать здесь, чем в снесённом каталоге.
CRONICLE_LOG_PATH_MARK = os.path.join('data', 'cronicle', 'logs')


def cronicle_log_prune(keep_days: int = CRONICLE_LOG_KEEP_DAYS) -> dict:
    """
    Удалить логи Cronicle старше `keep_days` суток.

    Args:
        keep_days: сколько последних суток оставить. Меньше единицы не бывает:
            ноль означал бы «снести и сегодняшний лог», в том числе тот, в который
            Cronicle пишет прямо сейчас.

    Returns:
        `{'files': int, 'bytes': int, 'dirs': int, 'kept_days': int}` — сколько
        файлов и байт освободили и сколько опустевших каталогов убрали.
    """
    keep_days = max(int(keep_days or 0), 1)
    deadline = time.time() - keep_days * 86400
    stats = {'files': 0, 'bytes': 0, 'dirs': 0, 'kept_days': keep_days}

    for rel_dir in CRONICLE_LOG_DIRS:
        root = os.path.join(_BASE_DIR, rel_dir)
        if CRONICLE_LOG_PATH_MARK not in root or not os.path.isdir(root):
            continue
        _prune_dir(root, deadline, stats)

    logger_info(f"🧹 Логи Cronicle: удалено файлов {stats['files']}, "
                f"освобождено {stats['bytes'] // 1024} КБ, каталогов {stats['dirs']}, "
                f"оставлены последние {keep_days} сут.")
    return stats


def cronicle_log_sizes() -> dict:
    """
    Размер обеих куч Cronicle в байтах: архивы логов и история прогонов.

    Returns:
        `{'archives': int, 'jobs': int}`. Каталога нет — ноль, это не ошибка:
        на свежей установке Cronicle ещё ничего не ротировал.
    """
    return {
        'archives': _dir_size(os.path.join(_BASE_DIR, CRONICLE_LOG_DIRS[0])),
        'jobs': _dir_size(os.path.join(_BASE_DIR, CRONICLE_LOG_JOBS_DIR)),
    }


def cronicle_log_report(stats: dict, sizes: dict) -> str:
    """
    Строка отчёта для Telegram: что убрали и сколько осталось.

    Отчёт короткий и уходит раз в сутки, поэтому без заголовков и списков —
    человек читает его мельком в ленте уведомлений.
    """
    return (f"🧹 Логи Cronicle (держим {stats.get('kept_days', CRONICLE_LOG_KEEP_DAYS)} сут.): "
            f"убрано {stats.get('files', 0)} файлов, {_size_text(stats.get('bytes', 0))}. "
            f"Осталось: архивы {_size_text(sizes.get('archives', 0))}, "
            f"история прогонов {_size_text(sizes.get('jobs', 0))}.")


def _dir_size(path: str) -> int:
    """Суммарный размер файлов каталога. Симлинки считаем по себе, а не по цели."""
    if not os.path.isdir(path):
        return 0

    total = 0
    for dir_path, _dir_names, file_names in os.walk(path):
        for name in file_names:
            try:
                total += os.lstat(os.path.join(dir_path, name)).st_size
            except OSError:
                continue

    return total


def _size_text(size: int) -> str:
    """Байты человеку: КБ до мегабайта, дальше МБ с десятой долей."""
    size = int(size or 0)
    if size < 1024 * 1024:
        return f'{size // 1024} КБ'

    return f'{size / (1024 * 1024):.1f} МБ'


def _prune_dir(root: str, deadline: float, stats: dict) -> None:
    """Обойти каталог снизу вверх: сначала файлы, потом опустевшие каталоги."""
    for dir_path, _dir_names, file_names in os.walk(root, topdown=False):
        for name in file_names:
            path = os.path.join(dir_path, name)
            _prune_file(path, deadline, stats)

        # Сам `root` не трогаем: Cronicle пишет в него и заново не создаст.
        if dir_path != root:
            _prune_empty_dir(dir_path, stats)


def _prune_file(path: str, deadline: float, stats: dict) -> None:
    """Удалить файл, если он старше срока. Симлинки не трогаем и не разыменовываем."""
    try:
        info = os.lstat(path)
    except OSError:
        return
    if info.st_mtime >= deadline:
        return

    try:
        os.remove(path)
    except OSError as e:
        # Занятый или чужой файл — не повод ронять уборку: остальное всё равно чистим.
        logger_info(f"🧹 Логи Cronicle: не удалось убрать {path}: {type(e).__name__}")
        return

    stats['files'] += 1
    stats['bytes'] += info.st_size


def _prune_empty_dir(path: str, stats: dict) -> None:
    """Убрать каталог, если в нём ничего не осталось: иначе копятся пустые даты."""
    try:
        if os.listdir(path):
            return
        os.rmdir(path)
    except OSError:
        return

    stats['dirs'] += 1

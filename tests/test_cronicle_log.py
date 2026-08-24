"""
Уборка логов Cronicle — `src/cronicle/cronicle_log.py`.

Cronicle ротирует свой суточный лог сам, но архивы не удаляет никогда: на проде
их набралось 208 файлов и 30 МБ за месяц. Этот модуль их и сносит.

Тесты работают с временным каталогом, а не с настоящими логами: `_BASE_DIR`
подменяется монкипатчем. Проверяется в первую очередь то, что удалять **нельзя** —
свежие файлы, корневой каталог и всё, что лежит вне логов Cronicle.
"""
import os
import time

import pytest

KEEP_DAYS = 3
DAY = 86400


@pytest.fixture
def cronicle_logs(tmp_path, monkeypatch):
    """Каталог логов с парой архивов: один старый, один свежий."""
    from src.cronicle import cronicle_log

    archives = tmp_path / 'data' / 'cronicle' / 'logs' / 'archives'
    old_dir = archives / '2026' / '07' / '29'
    new_dir = archives / '2026' / '08' / '23'
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)

    old_file = old_dir / 'Cronicle-2026-07-29.log.gz'
    new_file = new_dir / 'Cronicle-2026-08-23.log.gz'
    old_file.write_bytes(b'x' * 100)
    new_file.write_bytes(b'y' * 50)

    stale = time.time() - (KEEP_DAYS + 2) * DAY
    os.utime(old_file, (stale, stale))

    monkeypatch.setattr(cronicle_log, '_BASE_DIR', str(tmp_path))
    return {'root': archives, 'old': old_file, 'new': new_file, 'old_dir': old_dir}


def test_old_archive_removed(cronicle_logs):
    from src.cronicle.cronicle_log import cronicle_log_prune

    stats = cronicle_log_prune(KEEP_DAYS)

    assert not cronicle_logs['old'].exists()
    assert stats['files'] == 1
    assert stats['bytes'] == 100


def test_fresh_archive_kept(cronicle_logs):
    """Свежий лог не трогаем — в сегодняшний Cronicle пишет прямо сейчас."""
    from src.cronicle.cronicle_log import cronicle_log_prune

    cronicle_log_prune(KEEP_DAYS)

    assert cronicle_logs['new'].exists()


def test_empty_dirs_removed_but_root_kept(cronicle_logs):
    """
    Опустевшие каталоги дат убираем, корень оставляем.

    Без уборки дат от архивов остаётся дерево пустых `[yyyy]/[mm]/[dd]`, а
    удалённый корень Cronicle заново не создаст — ротация начнёт падать.
    """
    from src.cronicle.cronicle_log import cronicle_log_prune

    stats = cronicle_log_prune(KEEP_DAYS)

    assert not cronicle_logs['old_dir'].exists()
    assert cronicle_logs['root'].is_dir()
    assert stats['dirs'] >= 1


def test_keep_days_floor_is_one(cronicle_logs):
    """
    Ноль и мусор превращаются в единицу.

    `keep_days=0` означал бы «снести и сегодняшний лог», в том числе открытый на
    запись, — такого аргумента у уборки быть не должно.
    """
    from src.cronicle.cronicle_log import cronicle_log_prune

    assert cronicle_log_prune(0)['kept_days'] == 1
    assert cronicle_log_prune(None)['kept_days'] == 1


def test_outside_cronicle_logs_untouched(tmp_path, monkeypatch):
    """
    Каталог вне логов Cronicle не чистим даже при подмене списка.

    Проверка пути (`CRONICLE_LOG_PATH_MARK`) — единственное, что стоит между
    опечаткой в константе и снесённым чужим каталогом.
    """
    from src.cronicle import cronicle_log

    victim = tmp_path / 'data' / 'seeds'
    victim.mkdir(parents=True)
    old_file = victim / 'seed.sql'
    old_file.write_text('SELECT 1;')
    stale = time.time() - 30 * DAY
    os.utime(old_file, (stale, stale))

    monkeypatch.setattr(cronicle_log, '_BASE_DIR', str(tmp_path))
    monkeypatch.setattr(cronicle_log, 'CRONICLE_LOG_DIRS', (os.path.join('data', 'seeds'),))

    stats = cronicle_log.cronicle_log_prune(KEEP_DAYS)

    assert old_file.exists(), 'уборка вышла за пределы логов Cronicle'
    assert stats['files'] == 0


def test_missing_dir_is_not_an_error(tmp_path, monkeypatch):
    """Каталога нет (свежая установка, Cronicle ещё не ротировал) — просто ноль."""
    from src.cronicle import cronicle_log

    monkeypatch.setattr(cronicle_log, '_BASE_DIR', str(tmp_path))

    assert cronicle_log.cronicle_log_prune(KEEP_DAYS)['files'] == 0

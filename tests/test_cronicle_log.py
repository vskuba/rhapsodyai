"""
Уборка логов Cronicle — `py_modules/cronicle_/cronicle_log.py`.

Cronicle ротирует свой суточный лог сам, но архивы не удаляет никогда: на проде
их набралось 208 файлов и 30 МБ за месяц. Этот модуль их и сносит.

Код общий (лежит в submodule и приезжает во все проекты), а сюита — здесь: своих
тестов у общего слоя нет, его проверяют проекты-потребители. Каталог приходит
параметром, поэтому тесты работают с временным и ничего не подменяют монкипатчем.

Проверяется в первую очередь то, что удалять **нельзя**: свежие файлы, корневой
каталог и всё, что лежит вне переданного каталога Cronicle.
"""
import os
import time

import pytest

pytestmark = pytest.mark.core

KEEP_DAYS = 3
DAY = 86400


@pytest.fixture
def cronicle_dir(tmp_path):
    """Каталог Cronicle с парой архивов: один старый, один свежий."""
    base = tmp_path / 'data' / 'cronicle'
    archives = base / 'logs' / 'archives'
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

    return {'base': str(base), 'root': archives, 'old': old_file,
            'new': new_file, 'old_dir': old_dir}


def test_old_archive_removed(cronicle_dir):
    from cronicle_.cronicle_log import cronicle_log_prune

    stats = cronicle_log_prune(KEEP_DAYS, cronicle_dir['base'])

    assert not cronicle_dir['old'].exists()
    assert stats['files'] == 1
    # Освобождённое место считается блоками, как `du`, — файл в 100 байт занимает
    # целый блок. Отсюда «не меньше длины», а не точное число.
    assert stats['bytes'] >= 100


def test_fresh_archive_kept(cronicle_dir):
    """Свежий лог не трогаем — в сегодняшний Cronicle пишет прямо сейчас."""
    from cronicle_.cronicle_log import cronicle_log_prune

    cronicle_log_prune(KEEP_DAYS, cronicle_dir['base'])

    assert cronicle_dir['new'].exists()


def test_empty_dirs_removed_but_root_kept(cronicle_dir):
    """
    Опустевшие каталоги дат убираем, корень оставляем.

    Без уборки дат от архивов остаётся дерево пустых `[yyyy]/[mm]/[dd]`, а
    удалённый корень Cronicle заново не создаст — ротация начнёт падать.
    """
    from cronicle_.cronicle_log import cronicle_log_prune

    stats = cronicle_log_prune(KEEP_DAYS, cronicle_dir['base'])

    assert not cronicle_dir['old_dir'].exists()
    assert cronicle_dir['root'].is_dir()
    assert stats['dirs'] >= 1


def test_keep_days_floor_is_one(cronicle_dir):
    """
    Ноль и мусор превращаются в единицу.

    `keep_days=0` означал бы «снести и сегодняшний лог», в том числе открытый на
    запись, — такого аргумента у уборки быть не должно.
    """
    from cronicle_.cronicle_log import cronicle_log_prune

    assert cronicle_log_prune(0, cronicle_dir['base'])['kept_days'] == 1
    assert cronicle_log_prune(None, cronicle_dir['base'])['kept_days'] == 1


def test_outside_base_untouched(tmp_path, monkeypatch):
    """
    Уборка не выходит за переданный каталог Cronicle.

    Проверка родства путей (`_inside`) — единственное, что стоит между опечаткой в
    списке каталогов и снесённым чужим деревом. Здесь список уводит на два уровня
    вверх, в соседний каталог с seed-файлами: старый маркер по подстроке такой
    путь бы пропустил, потому что `data/cronicle/logs` в нём всё-таки есть.
    """
    from cronicle_ import cronicle_log

    base = tmp_path / 'data' / 'cronicle' / 'logs'
    base.mkdir(parents=True)

    victim = tmp_path / 'data' / 'seeds'
    victim.mkdir(parents=True)
    old_file = victim / 'seed.sql'
    old_file.write_text('SELECT 1;')
    stale = time.time() - 30 * DAY
    os.utime(old_file, (stale, stale))

    monkeypatch.setattr(cronicle_log, 'CRONICLE_LOG_DIRS',
                        (os.path.join('..', '..', 'seeds'),))

    stats = cronicle_log.cronicle_log_prune(KEEP_DAYS, str(base))

    assert old_file.exists(), 'уборка вышла за пределы каталога Cronicle'
    assert stats['files'] == 0


def test_custom_base_dir_is_cleaned(tmp_path):
    """
    Чужая раскладка чистится, а не пропускается молча.

    Раньше страховка искала в пути подстроку `data/cronicle/logs`, и на установке
    с другим монтированием уборка тихо не делала ничего: каталог рос, а кронджоб
    рапортовал об успехе. Молчаливое бездействие хуже отказа.
    """
    from cronicle_.cronicle_log import cronicle_log_prune

    base = tmp_path / 'opt' / 'cron'
    archives = base / 'logs' / 'archives'
    archives.mkdir(parents=True)
    old_file = archives / 'old.log.gz'
    old_file.write_bytes(b'x' * 100)
    stale = time.time() - 30 * DAY
    os.utime(old_file, (stale, stale))

    stats = cronicle_log_prune(KEEP_DAYS, str(base))

    assert not old_file.exists()
    assert stats['files'] == 1


def test_missing_dir_is_not_an_error(tmp_path):
    """Каталога нет (свежая установка, Cronicle ещё не ротировал) — просто ноль."""
    from cronicle_.cronicle_log import cronicle_log_prune

    assert cronicle_log_prune(KEEP_DAYS, str(tmp_path))['files'] == 0


class TestSizesAndReport:
    """Размеры обеих куч и строка отчёта, которая уходит в Telegram."""

    def test_sizes_counted_per_dir(self, cronicle_dir):
        """Архивы и история прогонов считаются раздельно: чистит их разный код."""
        from cronicle_.cronicle_log import cronicle_log_sizes

        jobs = os.path.join(cronicle_dir['base'], 'data', 'jobs')
        os.makedirs(jobs)
        with open(os.path.join(jobs, 'job.json'), 'wb') as f:
            f.write(b'z' * 300)

        sizes = cronicle_log_sizes(cronicle_dir['base'])

        # В фикстуре два архива (100 и 50 байт), в истории один файл на 300.
        # Сверяем «не меньше длины»: место считается блоками, как у `du`.
        assert sizes['archives'] >= 150
        assert sizes['jobs'] >= 300
        assert sizes['archives'] != sizes['jobs'], 'кучи посчитаны как одна'

    def test_size_counts_blocks_not_length(self, tmp_path):
        """
        Место считается блоками, а не длиной файлов.

        В `data/jobs` у Cronicle 110 тысяч крошечных файлов: по длине это 121 МБ,
        а `du` показывает 1.1 ГБ — каждый занимает целый блок. Отчёт о длине
        занижал бы расход диска почти в десять раз.
        """
        from cronicle_.cronicle_log import cronicle_log_sizes

        jobs = tmp_path / 'data' / 'jobs'
        jobs.mkdir(parents=True)
        for i in range(20):
            (jobs / f'{i}.json').write_bytes(b'x')

        size = cronicle_log_sizes(str(tmp_path))['jobs']

        assert size > 20, f'20 файлов по байту не могут занимать {size} байт на диске'

    def test_sizes_zero_without_dirs(self, tmp_path):
        from cronicle_.cronicle_log import cronicle_log_sizes

        assert cronicle_log_sizes(str(tmp_path)) == {'archives': 0, 'jobs': 0}

    def test_report_mentions_both_heaps(self):
        """
        В отчёте обе кучи: по размеру истории прогонов только и видно, доехала ли
        `CRONICLE_job_data_expire_days` — в config.json на диске остаётся 180.
        """
        from cronicle_.cronicle_log import cronicle_log_report

        text = cronicle_log_report(
            {'files': 190, 'bytes': 27889979, 'dirs': 36, 'kept_days': 3},
            {'archives': 2621440, 'jobs': 1181116006})

        assert '190' in text
        assert '2.5 МБ' in text
        assert '1.10 ГБ' in text
        assert '3 сут' in text

    def test_report_gigabytes_above_1024_mb(self):
        """Гигабайты отдельной ступенью: «1765.9 МБ» с одного взгляда не читается."""
        from cronicle_.cronicle_log import cronicle_log_report

        text = cronicle_log_report({'files': 0, 'bytes': 0, 'dirs': 0, 'kept_days': 3},
                                   {'archives': 0, 'jobs': 1851645952})

        assert '1.72 ГБ' in text

    def test_report_small_sizes_in_kb(self):
        """До мегабайта — в килобайтах: «0.0 МБ» человеку ничего не говорит."""
        from cronicle_.cronicle_log import cronicle_log_report

        text = cronicle_log_report({'files': 0, 'bytes': 0, 'dirs': 0, 'kept_days': 3},
                                   {'archives': 4096, 'jobs': 0})

        assert '4 КБ' in text
        assert '0 КБ' in text

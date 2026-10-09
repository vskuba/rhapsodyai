"""Кадры E2E-прогонов на диске: куда их класть, как отдавать, когда сносить.

Кадры лежат файлами в `data/e2e/<run_uuid>/`, а в базе от них только путь. Так
же устроены материалы прототипа (`src/tool/project/planning/planning_prototype.py`):
картинка в колонке раздувает дамп и бэкап, а читается она по одной — ручкой
раздачи, которая и так проверяет право.

⚠⚠ Путь к файлу берётся **из базы по номеру строки**, а не из запроса. Отдавать
файл по присланному пути нельзя ни с какой проверкой: `..%2f` и симлинк
превращают раздачу кадров в чтение любого файла контейнера. Снаружи приходит
номер строки — число, которым дальше `../` не напишешь.

На каждый тест × ширину кадра два: с нарисованными рамками областей (его и
смотрят) и чистый. Чистый нужен, когда рамка села поверх дефекта: обрезанный
текст под красной линией не виден.
"""

import hashlib
import os
import shutil

# Корень кадров в контейнере — рядом с материалами прототипа (`/app/data/...`).
# Снаружи контейнера (прогон с хоста) путь тот же относительно корня проекта.
E2E_SHOT_DIR = '/app/data/e2e' if os.path.isdir('/app/data') else 'data/e2e'


def e2e_shot_dir(run_uuid: str) -> str:
    """Каталог кадров прогона; создаёт его, если нет.

    Args:
        run_uuid: метка прогона (`e2e_run_uuid()`).

    Returns:
        str: абсолютный или относительный путь каталога.
    """
    path = os.path.join(E2E_SHOT_DIR, _e2e_shot_safe(run_uuid))
    os.makedirs(path, exist_ok=True)
    return path


def e2e_shot_name(name: str, width: int, marked: bool = True) -> str:
    """Имя файла кадра внутри каталога прогона.

    Args:
        name: имя случая из YAML.
        width: ширина вьюпорта.
        marked: кадр с рамками областей (True) или чистый (False).

    Returns:
        str: «LLM-a1b2c3d4_1440_marked.png» — без каталога.

    ⚠⚠ Отпечаток имени в названии файла обязателен, и это не украшение.
    Имена случаев русские, а в имя файла латиница из них не попадает вовсе:
    «Журнал — ошибки» и «Настройки установки» оба сворачивались в пустую строку,
    то есть в ОДНО имя файла — и второй случай молча затирал кадры первого.
    Поймано на первом же прогоне: 12 файлов вместо 18.
    """
    tail = 'marked' if marked else 'plain'
    mark = hashlib.md5(str(name or '').encode('utf-8')).hexdigest()[:8]
    return f'{_e2e_shot_safe(name)}-{mark}_{int(width)}_{tail}.png'


def e2e_shot_path(relative: str) -> str:
    """Полный путь кадра по тому, что лежит в колонке `shot_path`.

    Args:
        relative: путь относительно корня кадров («<run_uuid>/имя.png»).

    Returns:
        str: полный путь; пусто — если значения нет или оно уводит за корень.
    """
    if not relative:
        return ''
    root = os.path.realpath(E2E_SHOT_DIR)
    full = os.path.realpath(os.path.join(root, relative))
    # ⚠ Вторая застава поверх `_e2e_shot_safe`: имена пишем мы, но колонка живёт
    # в базе, а база переживает и восстановление из чужого дампа.
    if full != root and not full.startswith(root + os.sep):
        return ''
    return full if os.path.isfile(full) else ''


def e2e_shot_drop(run_uuid: str) -> bool:
    """Снести каталог кадров прогона. Повторный вызов не ошибка."""
    path = os.path.join(E2E_SHOT_DIR, _e2e_shot_safe(run_uuid))
    if not os.path.isdir(path):
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def _e2e_shot_safe(value: str) -> str:
    """Кусок имени файла из произвольной строки: латиница, цифры, дефис.

    Кириллица и пробелы выпадают — имя файла здесь не для чтения человеком, его
    читает страница по колонке. ⚠ Поэтому результат НЕ уникален: у русских имён
    он пустой у всех сразу. Уникальность даёт отпечаток в `e2e_shot_name`, и
    убирать его оттуда нельзя.
    """
    out = ''.join(ch if (ch.isascii() and (ch.isalnum() or ch in '-_')) else '-'
                  for ch in str(value or ''))
    return out.strip('-')[:80] or 'x'

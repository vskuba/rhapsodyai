"""
Что уже сделано в каталоге подзадачи: коммиты, незакоммиченные правки, объём.

Зачем. Прогон разработчика обрывается по таймауту шага, конвейер уводит подзадачу
в повтор и перезапускает оболочку — контекст агента при этом гибнет, а **работа
остаётся**: каталог подзадачи с её веткой никто не трогает. Пойманный живьём
случай: подзадача #1028 успела закоммитить `task/1028: имена и порядок функций`,
таймаут срубил её на пуше, и следующий заход четыре минуты заново разбирал
проект, не зная про собственный коммит.

Снимок читает это состояние из git и отдаёт промпту, чтобы круг после обрыва
начинался со «сверь и продолжи», а не с чистого листа.

Инструмент, а не ход агента, по той же причине, что и `task_server_check`: три
команды git детерминированы, стоят секунды и не тратят ни токенов, ни круга
обращений к оболочке.

Каталог, git и базовую ветку берём у `task_worktree` — своя копия этих правил
разъехалась бы с оригиналом на первой правке. У `task_worktree_git` вдобавок
решены две ловушки: запуск от владельца репозитория (иначе git отвечает «dubious
ownership»: каталог принадлежит человеку, а процесс идёт от root в контейнере) и
обход uvloop, который не принимает `user`/`group` у `create_subprocess_exec`.
"""
import hashlib
import os

from src.project.task.task_worktree import (task_worktree_base_branch, task_worktree_git,
                                            task_worktree_path)

# Сколько строк показываем в каждом разделе: снимок уходит в промпт, и полный
# список изменённых файлов на большой ветке вытеснил бы оттуда саму подзадачу.
TASK_WORKTREE_STATE_LINES_MAX = 25

# Потолок всего свода в символах — вторая страховка на случай длинных путей.
TASK_WORKTREE_STATE_CHARS_MAX = 3000


async def task_worktree_state(subtask_id: int, work_dir: str = '', since: str = '') -> dict:
    """
    Собирает следы уже сделанной работы в каталоге подзадачи.
     - subtask_id: ID подзадачи (project_task.id) — по нему находится её каталог
     - work_dir: корень репозитория; пусто — каталог, из которого работает приложение
     - since: отпечаток состояния, снятый раньше — с ним сравнивается нынешнее
    Returns:
        dict: Состояние каталога подзадачи, содержащее:
            done_has (str): yes — в ветке уже есть работа; no — чисто или каталога нет.
            done_text (str): свод для промпта — коммиты, незакоммиченные файлы, объём.
            done_mark (str): короткий отпечаток состояния — его передают в since.
            done_changed (str): yes — с момента since что-то изменилось; no — ничего.
                Без since всегда yes: сравнивать не с чем.
            done_dir (str): каталог подзадачи, который смотрели.
    """
    repo_dir = str(work_dir or '').strip().rstrip('/') or os.getcwd()
    directory = task_worktree_path(repo_dir, int(subtask_id or 0))
    if not os.path.isdir(directory):
        return _result('no', '', '', since, directory)

    # Базовую ветку спрашиваем, а не пишем «master»: на инсталляции она может
    # называться иначе, и тогда `master..HEAD` молча отдало бы пустоту.
    base = await task_worktree_base_branch(repo_dir)

    blocks = []
    for title, args in (
        ('Коммиты ветки', ('log', '--oneline', '--no-decorate', f'{base}..HEAD')),
        ('Незакоммиченное', ('status', '--porcelain')),
        ('Объём изменений', ('diff', '--stat', f'{base}...HEAD')),
    ):
        text = await _git_text(directory, *args)
        if text:
            blocks.append(f'{title}:\n{_cut(text)}')

    mark = await _mark_build(directory, base)
    if not blocks:
        return _result('no', '', mark, since, directory)

    return _result('yes', '\n\n'.join(blocks)[:TASK_WORKTREE_STATE_CHARS_MAX],
                   mark, since, directory)


def _result(has: str, text: str, mark: str, since: str, directory: str) -> dict:
    """Ответ инструмента с ответом на главный вопрос: изменилось ли что-нибудь.

    `since` пуст — сравнивать не с чем, и честный ответ «изменилось»: иначе первый
    же снимок объявил бы работу несделанной.
    """
    previous = str(since or '').strip()

    return {
        'done_has': has,
        'done_text': text,
        'done_mark': mark,
        'done_changed': 'yes' if not previous or previous != mark else 'no',
        'done_dir': directory,
    }


async def _mark_build(directory: str, base: str) -> str:
    """
    Короткий отпечаток состояния ветки: по нему сверяют «было» и «стало».

    Берём вершину ветки и список незакоммиченного с хешами содержимого. Одних
    коммитов мало: работа круга часто остаётся незакоммиченной, и по `HEAD` она
    выглядела бы как отсутствие работы. Одного `status` тоже мало: агент мог всё
    закоммитить, и рабочее дерево стало бы снова чистым.

    Ошибка git — пустая строка. Вызывающий сочтёт состояние изменившимся, то есть
    ошибка сверки никогда не выдаст работу за несделанную.
    """
    head = await _git_text(directory, 'rev-parse', 'HEAD')
    dirty = await _git_text(directory, 'status', '--porcelain', '--untracked-files=all')
    if not head and not dirty:
        return ''

    digest = hashlib.sha1(f'{head}\n{dirty}'.encode('utf-8', 'replace')).hexdigest()

    return f'{head[:12]}:{digest[:16]}'


async def _git_text(directory: str, *args: str) -> str:
    """Вывод git или пустая строка при любом сбое.

    Снимок вспомогательный: не прочитался git — прогон всё равно должен пойти,
    просто без блока «что уже сделано». Ронять из-за него круг нечестно.
    """
    code, output = await task_worktree_git(directory, *args)

    return output.strip() if code == 0 else ''


def _cut(text: str) -> str:
    """Первые строки раздела; сколько срезано — говорим явно, чтобы не выглядело полным."""
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= TASK_WORKTREE_STATE_LINES_MAX:
        return '\n'.join(lines)

    hidden = len(lines) - TASK_WORKTREE_STATE_LINES_MAX

    return '\n'.join(lines[:TASK_WORKTREE_STATE_LINES_MAX] + [f'… и ещё {hidden} строк'])

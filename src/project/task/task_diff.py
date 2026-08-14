"""
Разница между главной веткой репозитория и веткой подзадачи — та самая, которую
merge request на сервере показать не может.

Зачем: конвейер режет ветку подзадачи от **локальной** главной ветки
(`task_worktree_base_branch`, и это осознанно — агент должен видеть тот же код, что
видел планировщик). Merge request на GitHub сравнивает её с `origin/master`, а
локальный master бывает на десятки коммитов впереди сервера — в этой установке на
66. Все они попадают в MR как «изменения задачи»: у подзадачи #562 MR показывал
113 файлов и 14569 добавленных строк вместо настоящих двух строк в одном файле.
Ревью такого MR невозможно.

Что здесь: то же сравнение, но обеими локальными ветками — `git diff base...branch`.
Три точки, а не две: сравниваем ветку с точкой расхождения, а не с текущей головой
главной ветки, иначе чужие коммиты, приехавшие в master после резки ветки, снова
показались бы как чужая работа — только с обратным знаком.

Чего здесь нет: записи. Модуль только читает репозиторий — ни слияния, ни коммитов,
ни push. Слияние живёт в `task_worktree.py` и делается отдельной кнопкой.
"""
import os

from src.project.task.task_worktree import (
    task_worktree_base_branch,
    task_worktree_branch,
    task_worktree_git,
    task_worktree_path,
)

# Сколько diff-а отдавать странице. Ограничение не про сервер, а про браузер: правка
# схемы или переезд шаблона дают мегабайты текста, и вкладка на них встаёт. Обрезаем
# с честной пометкой — человек увидит, что показано не всё, и пойдёт в консоль.
TASK_DIFF_MAX_CHARS = 400_000

# Сколько коммитов ветки перечислять. Ветка подзадачи короткая (обычно один-два
# коммита); длинный список тут — признак, что в неё влили что-то ещё.
TASK_DIFF_COMMIT_LIMIT = 50

# Разделители полей и записей в `git log --format`. Табуляция и перевод строки в
# этих полях встречаются (тема коммита), поэтому берём то, чего в тексте не бывает.
_LOG_FIELD_SEPARATOR = '\x1f'
_LOG_RECORD_SEPARATOR = '\x1e'


async def task_diff_build(repo_dir: str, subtask_id) -> dict:
    """
    Разница главной ветки и ветки подзадачи: коммиты, файлы, сам diff.

    Args:
        repo_dir: каталог основного чекаута проекта.
        subtask_id: номер подзадачи — из него имя ветки (`feature/task_<id>`).

    Returns:
        `{'ok', 'error', 'base', 'branch', 'commits', 'files', 'diff', 'truncated',
          'stat', 'behind_remote', 'dirty'}`.

        `behind_remote` — на сколько коммитов локальная главная ветка обогнала
        `origin/<base>`; ровно столько чужой работы и показал бы merge request.
        `dirty` — файлы, которые в каталоге подзадачи правлены, но не закоммичены:
        в diff их нет, и без предупреждения это выглядит как «агент ничего не сделал».
    """
    result = {'ok': False, 'error': '', 'base': '', 'branch': '', 'commits': [], 'files': [],
              'diff': '', 'truncated': False, 'stat': '', 'behind_remote': 0, 'dirty': []}

    repo_dir = os.path.abspath(str(repo_dir or '')) if repo_dir else ''
    branch = task_worktree_branch(subtask_id)
    result['branch'] = branch
    if not repo_dir or not branch:
        result['error'] = 'не хватает адреса: нет каталога проекта или номера подзадачи'
        return result
    if not os.path.isdir(repo_dir):
        result['error'] = (f'каталог проекта {repo_dir} не виден — проверьте монтирования '
                           f'(docker-compose.override.yml)')
        return result

    code, _ = await task_worktree_git(repo_dir, 'rev-parse', '--verify', f'refs/heads/{branch}')
    if code:
        result['error'] = f'ветки {branch} нет — разработчик ещё не оставил коммитов'
        return result

    base = await task_worktree_base_branch(repo_dir)
    result['base'] = base
    # Диапазон собираем один раз: он должен быть одним и тем же во всех четырёх
    # вызовах, иначе список файлов разойдётся с самим diff-ом.
    range_ = f'{base}...{branch}'

    result['commits'] = await _commits(repo_dir, base, branch)
    result['files'] = await _files(repo_dir, range_)
    _, result['stat'] = await task_worktree_git(repo_dir, 'diff', '--shortstat', range_)

    code, diff = await task_worktree_git(repo_dir, 'diff', range_)
    if code:
        result['error'] = f'git diff {range_} не удался: {diff}'
        return result
    if len(diff) > TASK_DIFF_MAX_CHARS:
        diff = diff[:TASK_DIFF_MAX_CHARS]
        result['truncated'] = True
    result['diff'] = diff

    result['behind_remote'] = await _behind_remote(repo_dir, base)
    result['dirty'] = await _dirty(repo_dir, subtask_id)
    result['ok'] = True

    return result


async def _commits(repo_dir: str, base: str, branch: str) -> list[dict]:
    """Коммиты, которые есть в ветке и которых нет в главной, — новые сверху."""
    code, out = await task_worktree_git(
        repo_dir, 'log', f'-{TASK_DIFF_COMMIT_LIMIT}', f'{base}..{branch}',
        f'--format=%h{_LOG_FIELD_SEPARATOR}%an{_LOG_FIELD_SEPARATOR}%ad{_LOG_FIELD_SEPARATOR}%s{_LOG_RECORD_SEPARATOR}',
        '--date=format:%Y-%m-%d %H:%M')
    if code:
        return []

    commits = []
    for record in (out or '').split(_LOG_RECORD_SEPARATOR):
        parts = record.strip().split(_LOG_FIELD_SEPARATOR)
        if len(parts) < 4:
            continue
        commits.append({'hash': parts[0], 'author': parts[1], 'date': parts[2], 'subject': parts[3]})

    return commits


async def _files(repo_dir: str, range_: str) -> list[dict]:
    """
    Файлы диапазона со счётчиком строк — `--numstat`.

    Двоичные файлы git отмечает прочерками вместо чисел; отдаём их нулями и флагом,
    иначе страница показала бы «0 строк» наравне с пустой правкой.
    """
    code, out = await task_worktree_git(repo_dir, 'diff', '--numstat', range_)
    if code:
        return []

    files = []
    for line in (out or '').splitlines():
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], parts[2]
        binary = added == '-' or deleted == '-'
        files.append({'path': path,
                      'added': 0 if binary else int(added or 0),
                      'deleted': 0 if binary else int(deleted or 0),
                      'binary': binary})

    return files


async def _behind_remote(repo_dir: str, base: str) -> int:
    """
    На сколько коммитов локальная главная ветка обогнала свою удалённую копию.

    Это и есть мера мусора в merge request: столько чужих коммитов сервер покажет
    как изменения задачи. Нет `origin/<base>` (клон без remote) — нет и разницы.
    """
    code, out = await task_worktree_git(repo_dir, 'rev-list', '--count', f'origin/{base}..{base}')
    if code:
        return 0

    return int((out or '0').strip() or 0)


async def _dirty(repo_dir: str, subtask_id) -> list[str]:
    """
    Незакоммиченные правки в каталоге подзадачи — их в diff нет.

    Отслеживаемые файлы (`-uno`) и без подмодулей: указатель подмодуля двигает сам
    конвейер (`task_worktree._submodule_align`), и это не работа агента. Каталога
    может уже не быть (сняли после слияния) — тогда и предупреждать не о чем.
    """
    path = task_worktree_path(repo_dir, subtask_id)
    if not path or not os.path.isdir(path):
        return []

    code, out = await task_worktree_git(path, 'status', '--porcelain', '-uno',
                                        '--ignore-submodules=all')
    if code:
        return []

    return [line.strip() for line in (out or '').splitlines() if line.strip()]

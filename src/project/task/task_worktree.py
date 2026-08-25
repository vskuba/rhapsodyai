"""
Отдельный рабочий каталог git на подзадачу: девелопер и QA работают в своей папке
со своей веткой и не трогают ни master, ни каталог человека.

Зачем: раньше все роли жили в одном каталоге проекта, и `git checkout -b` внутри
агента переключал ветку у всех сразу — включая человека, который в этот момент
писал код. Ветка при этом резалась от текущего HEAD, то есть от чужой ветки:
`feature/task_492` в этой установке отрезана от `feature/task_355`. Worktree
снимает и то, и другое: у каждой подзадачи свой каталог, своя ветка, отрезанная
от master, и переключать общий чекаут больше некому.

Как устроен worktree: git держит один репозиторий и несколько рабочих копий.
Объекты и ссылки общие, свои у копии только HEAD, индекс и reflog — в каталоге
лежит не папка `.git`, а файл с путём в `.git/worktrees/<имя>`. Отсюда правило,
которое видно снаружи: одна ветка выкачена ровно в один каталог, и удалить её,
пока каталог жив, git не даст.

Чего в свежем worktree нет: `git worktree add` выкладывает только отслеживаемые
файлы. Подмодуль `py_modules` окажется пустым, а `.env`, `.env.local`, `.venv` и
рабочие каталоги `data/` — в `.gitignore`, и без них ни приложение, ни тесты не
поднимутся. Поэтому создание — это не одна команда, а `add` + инициализация
подмодулей + выравнивание их на то, что выкачено у человека + ссылки на общие
файлы; см. `task_worktree_ensure`.

Каталоги лежат в `.claude/worktrees/` — он уже в `.gitignore`, иначе главный
чекаут увидел бы вложенную папку с `.git` внутри и при `git add -A` записал бы
её как gitlink.
"""
import asyncio
import os
import subprocess

from logging_.logging_ import logger_info

# Имя каталога и имя ветки — разные шаблоны: в путь слеш не годится, а ветку
# `feature/task_XXX` уже ждут промпт разработчика и открытые merge request.
TASK_WORKTREE_DIR_TEMPLATE = 'feature_task_{subtask_id}'
TASK_WORKTREE_BRANCH_TEMPLATE = 'feature/task_{subtask_id}'

# Общий корень каталогов — внутри репозитория, но в игноре.
TASK_WORKTREE_BASE_DIR = '.claude/worktrees'

# От чего режем ветку — от главной ветки репозитория, а не от текущего HEAD: HEAD
# в общем каталоге стоит на чужой ветке чаще, чем на главной. Имя не зашито: у
# проектов на машине оно разное (`master`, `main`), и спрашиваем его у самого
# репозитория (`origin/HEAD`). Список ниже — на случай, когда `origin/HEAD` не
# настроен: у клона без него этой ссылки нет вовсе.
TASK_WORKTREE_BASE_REF_FALLBACK = ('master', 'main')

# Что связываем с основным каталогом: всё, что git игнорирует, — конфиги (`.env`),
# окружение (`.venv`, `node_modules`), рабочие каталоги (логи, бэкапы). Список не
# зашит, а спрашивается у репозитория: проекты разные, и у соседнего проекта
# игнорируется совсем другое. Симлинки, а не копии: `.env` должен быть один на все
# каталоги, а окружение — сотни мегабайт.
#
# Глубина: сам каталог и его дети. Верхнего уровня хватило бы, будь игнор всегда
# на верхнем уровне, но так бывает не всегда — в этом проекте `data/` отслеживается
# (шаблоны), а игнорируются её дети (логи, бэкапы). Глубже не ходим: там начинается
# мусор, разложенный по всему дереву.
TASK_WORKTREE_SHARED_DEPTH = 2

# Кеши не связываем ни при какой глубине. Общий `__pycache__` — это байткод чужой
# ветки в каталоге подзадачи: код правится, а исполняется прежний.
TASK_WORKTREE_SHARED_SKIP = ('.git', '__pycache__', '.pytest_cache', '.mypy_cache',
                             '.ruff_cache', '.tox')

# Команды git недолгие, но сеть и подмодули могут подвиснуть; молча висеть в
# захваченной задаче нельзя — таймаут превращает это в понятную ошибку.
TASK_WORKTREE_GIT_TIMEOUT = 180

# Каталог, в котором делается слияние, когда главная ветка нигде не выкачена. Живёт
# там же, где каталоги подзадач, и снимается сразу после слияния — имя с подчёркиванием,
# чтобы не спутать его со строкой задачи (`feature_task_<id>`).
TASK_WORKTREE_MERGE_DIR = '_merge'

# Чем подписать коммит слияния, если в репозитории не настроен автор. В контейнере
# воркера так и бывает: git зовётся от uid владельца каталога, а `HOME` уведён в `/tmp`,
# где никакого `.gitconfig` нет — без подписи git отказывается коммитить вовсе.
TASK_WORKTREE_MERGE_IDENTITY = ('task pipeline', 'task-pipeline@local')


def task_worktree_branch(subtask_id) -> str:
    """Имя ветки подзадачи. Нет номера — нет и ветки, возвращаем пустую строку."""
    subtask_id = int(subtask_id or 0)

    return TASK_WORKTREE_BRANCH_TEMPLATE.format(subtask_id=subtask_id) if subtask_id else ''


def task_worktree_path(repo_dir: str, subtask_id) -> str:
    """Каталог подзадачи внутри репозитория. Пустая строка, если адреса не хватает."""
    repo_dir = str(repo_dir or '').strip().rstrip('/')
    subtask_id = int(subtask_id or 0)
    if not repo_dir or not subtask_id:
        return ''

    name = TASK_WORKTREE_DIR_TEMPLATE.format(subtask_id=subtask_id)

    return os.path.join(repo_dir, TASK_WORKTREE_BASE_DIR, name)


async def task_worktree_ensure(repo_dir: str, subtask_id) -> str:
    """
    Каталог подзадачи, готовый к работе: создаёт при первом обращении, дальше отдаёт
    существующий.

    Идемпотентность здесь не украшение, а условие работы: каждая попытка подзадачи
    заходит сюда заново, а между попытками каталог никто не убирает. Поэтому и
    `add` делается только когда каталога нет, и ветка переиспользуется, если уже
    была (`-B` вместо `-b` не годится: он сбросил бы уже сделанные коммиты).

    После `add` — обязательные добивки, без которых каталог нерабочий: подмодуль
    `py_modules` (иначе пустая папка и ImportError), выравнивание подмодулей на то,
    что выкачено у человека (`_submodule_align`), и ссылки на `.env`/`.venv`/рабочие
    каталоги `data` (иначе не стартует ни приложение, ни тесты).

    Args:
        repo_dir: каталог основного чекаута проекта.
        subtask_id: номер подзадачи — из него и имя каталога, и имя ветки.

    Returns:
        Путь каталога. Пустая строка — адреса не хватило (нет проекта или номера).

    Raises:
        RuntimeError: git отказался создавать каталог или ветку.
    """
    path = task_worktree_path(repo_dir, subtask_id)
    if not path:
        return ''

    if os.path.isdir(os.path.join(path, '.git')) or os.path.isfile(os.path.join(path, '.git')):
        await _shared_link(repo_dir, path)
        return path

    os.makedirs(os.path.dirname(path), exist_ok=True)
    branch = task_worktree_branch(subtask_id)
    base = await task_worktree_base_branch(repo_dir)

    # Ветка могла остаться от прошлого прогона (каталог сняли, ветку нет) —
    # тогда подключаем её, а не пересоздаём: в ней уже есть коммиты подзадачи.
    if await _branch_exists(repo_dir, branch):
        code, out = await task_worktree_git(repo_dir, 'worktree', 'add', path, branch)
    else:
        code, out = await task_worktree_git(repo_dir, 'worktree', 'add', '-b', branch, path, base)
    if code:
        raise RuntimeError(f'git worktree add для #{subtask_id} не удался: {out}')

    code, out = await task_worktree_git(path, 'submodule', 'update', '--init', '--recursive')
    if code:
        logger_info(f'task_worktree: подмодули в {path} не поднялись: {out}')
    await _submodule_align(repo_dir, path)
    await _shared_link(repo_dir, path)
    logger_info(f'task_worktree: создан {path} (ветка {branch} от {base})')

    return path


async def task_worktree_remove(repo_dir: str, subtask_id, force: bool = False) -> bool:
    """
    Снять каталог подзадачи. Ветку не трогает: merge request может быть ещё открыт,
    а коммиты в ней — единственное, что осталось от работы.

    `force` — снять вместе с несохранёнными правками. Без него каталог с правками
    остаётся на месте: работа упавшей задачи или человека пропадать не должна.

    Проверку «чисто ли» делаем сами, а git зовём всегда с `--force`. Своей проверки
    у него здесь нет: в каталоге есть подмодуль `py_modules`, а такой каталог git
    отказывается снимать вообще («working trees containing submodules cannot be
    moved or removed»), и обойти отказ можно только этим же флагом.
    """
    path = task_worktree_path(repo_dir, subtask_id)
    if not path or not os.path.isdir(path):
        return False

    if not force:
        # `-uall` — по файлу на строку, а не свёрнутый каталог: свёрнутая папка
        # из одних наших ссылок выглядела бы как чужая неучтённая работа.
        _, status = await task_worktree_git(path, 'status', '--porcelain', '-uall', '--ignore-submodules=all')
        dirty = _dirty_lines(path, status)
        if dirty:
            logger_info(f'task_worktree: {path} не снят — есть несохранённые правки: {dirty}')
            return False

    # Снимаем тем путём и из того корня, какими каталог записан у git, а не теми,
    # какими мы их посчитали. Репозиторий бывает виден по нескольким адресам сразу
    # (в контейнере это `/app` и путь хоста), а git сверяет обратную ссылку: на
    # чужом адресе он отвечает «is not a working tree», из чужого корня — «does not
    # point back», и каталог в обоих случаях остаётся сиротой.
    registered = await _worktree_registered(repo_dir, path)
    owner = _worktree_owner(registered) or repo_dir
    code, out = await task_worktree_git(owner, 'worktree', 'remove', '--force', registered)
    if code:
        logger_info(f'task_worktree: снять {registered} не вышло: {out}')
        return False

    logger_info(f'task_worktree: снят {path}')

    return True


def _worktree_owner(path: str) -> str:
    """
    Корень репозитория, которому принадлежит каталог. Не выяснить — пустая строка.

    Каталог подзадачи хранит обратную ссылку в своём файле `.git`:
    `gitdir: <корень>/.git/worktrees/<имя>`. Она и есть ответ на вопрос, из какого
    корня звать git: тот же репозиторий, видимый по другому адресу, git считает
    чужим и снимать каталог отказывается.
    """
    marker = '/.git/worktrees/'
    try:
        with open(os.path.join(path, '.git'), encoding='utf-8') as fh:
            gitdir = fh.read().strip()
    except OSError:
        return ''

    gitdir = gitdir.removeprefix('gitdir:').strip()

    return gitdir.split(marker)[0] if marker in gitdir else ''


async def _worktree_registered(repo_dir: str, path: str) -> str:
    """
    Путь каталога так, как он записан у git. Не нашёлся — отдаём как есть.

    Сверяем по имени каталога: оно собрано из номера строки и уникально, а вот
    полный путь у одного и того же каталога бывает разным — репозиторий виден
    и по `/app`, и по адресу хоста.
    """
    name = os.path.basename(str(path or "").rstrip("/"))
    if not name:
        return path

    code, out = await task_worktree_git(repo_dir, 'worktree', 'list', '--porcelain')
    if code:
        return path

    for line in out.splitlines():
        if not line.startswith('worktree '):
            continue
        found = line[len('worktree '):].strip()
        if os.path.basename(found.rstrip('/')) == name:
            return found

    return path


async def task_worktree_remove_tree(repo_dir: str, task_ids) -> dict:
    """
    Снять каталоги удалённых строк — своей и всех, что ушли с ней каскадом.

    Удаление строки из базы каскадом уносит её детей, но каталоги на диске
    остаются: `DELETE` про них не знает. Раньше их убирали руками, и после
    каждой отменённой подзадачи в `.claude/worktrees/` копился мусор — каталоги
    по несколько сотен мегабайт, привязанные к строкам, которых уже нет.

    Снимаем принудительно: строку удалили осознанно, и каталог без неё — сирота,
    который никто уже не откроет. **Ветку при этом не трогаем** (её сохраняет
    `task_worktree_remove`), поэтому всё закоммиченное остаётся на месте и
    достаётся обычным `git checkout feature/task_<id>`. Пропадают только
    незакоммиченные правки — и об этом вызывающий узнаёт из ответа, а не
    догадывается.

    Returns: `{removed: [id], kept: [id], dirty: [id]}` — снятые, не снявшиеся и
        те, у кого пропали несохранённые правки.
    """
    result = {'removed': [], 'kept': [], 'dirty': []}
    for task_id in task_ids or []:
        path = task_worktree_path(repo_dir, task_id)
        if not path or not os.path.isdir(path):
            continue

        # Смотрим до снятия: после него сказать, была ли работа, уже нельзя.
        _, status = await task_worktree_git(path, 'status', '--porcelain', '-uall',
                                            '--ignore-submodules=all')
        if _dirty_lines(path, status):
            result['dirty'].append(int(task_id))

        if await task_worktree_remove(repo_dir, task_id, force=True):
            result['removed'].append(int(task_id))
        else:
            result['kept'].append(int(task_id))

    if result['removed'] or result['kept']:
        logger_info(f"task_worktree: удаление строк — снято {result['removed']}, "
                    f"осталось {result['kept']}, с правками {result['dirty']}")

    return result


async def task_worktree_merge(repo_dir: str, subtask_id) -> dict:
    """
    Влить ветку подзадачи в главную ветку репозитория — и снять её каталог.

    Локально и без `push`: отправка в общий репозиторий — отдельное решение человека,
    и делать её за него по кнопке нельзя. Здесь ровно то, что можно откатить своими
    силами: `git merge --no-ff` в главную ветку и снятый каталог подзадачи.

    Где делается слияние: главная ветка выкачена ровно в один каталог, и туда мы и
    идём — если он чист. Каталог человека при этом не переключается: ветка в нём уже
    та самая. Если главная ветка не выкачена нигде (обычный случай, когда человек
    сидит на своей ветке), заводим временный каталог и снимаем его сразу же.

    Несохранённые правки — стоп на входе, до всякого git-а. Слияние переносит
    коммиты, а не правки рабочего каталога: смержив и сняв каталог, мы потеряли бы
    ровно ту работу, которую человек ещё не закоммитил.

    Args:
        repo_dir: каталог основного чекаута проекта.
        subtask_id: номер подзадачи — из него имя ветки и имя каталога.

    Returns:
        `{'ok', 'error', 'branch', 'base', 'removed', 'output'}`. `removed` — снят ли
        каталог подзадачи: слияние могло пройти, а снятие нет, и это разные новости.
    """
    result = {'ok': False, 'error': '', 'branch': '', 'base': '', 'removed': False, 'output': ''}
    branch = task_worktree_branch(subtask_id)
    repo_dir = os.path.abspath(str(repo_dir or '')) if repo_dir else ''
    result['branch'] = branch
    if not repo_dir or not branch:
        result['error'] = 'не хватает адреса: нет каталога проекта или номера подзадачи'
        return result
    if not os.path.isdir(repo_dir):
        result['error'] = (f'каталог проекта {repo_dir} не виден — проверьте монтирования '
                           f'(docker-compose.override.yml)')
        return result
    if not await _branch_exists(repo_dir, branch):
        result['error'] = f'ветки {branch} нет — разработчик не оставил коммитов'
        return result

    path = task_worktree_path(repo_dir, subtask_id)
    if os.path.isdir(path):
        _, status = await task_worktree_git(path, 'status', '--porcelain', '-uall', '--ignore-submodules=all')
        dirty = _dirty_lines(path, status)
        if dirty:
            result['error'] = (f'в каталоге подзадачи есть несохранённые правки — они не '
                               f'в ветке и пропадут при снятии: {"; ".join(dirty[:5])}')
            return result

    base = await task_worktree_base_branch(repo_dir)
    result['base'] = base
    host, temporary, error = await _merge_host(repo_dir, base)
    if error:
        result['error'] = error
        return result

    code, out = await task_worktree_git(host, *await _identity(host), 'merge', '--no-ff', branch,
                                        '-m', f'Merge {branch} into {base}')
    result['output'] = out
    if code:
        # Конфликт оставляет каталог в недоделанном слиянии; для временного это
        # неважно (снимем), а для каталога человека — важно очень.
        await task_worktree_git(host, 'merge', '--abort')
        if temporary:
            await task_worktree_git(repo_dir, 'worktree', 'remove', '--force', host)
        result['error'] = f'слияние {branch} в {base} не прошло: {out}'
        return result

    if temporary:
        await task_worktree_git(repo_dir, 'worktree', 'remove', '--force', host)

    result['ok'] = True
    result['removed'] = await task_worktree_remove(repo_dir, subtask_id)
    logger_info(f'task_worktree: {branch} влита в {base}, каталог снят: {result["removed"]}')

    return result


async def task_worktree_merge_check(repo_dir: str, subtask_id) -> dict:
    """
    Пройдёт ли слияние ветки подзадачи в главную — до самого слияния.

    Нужна кнопке «Merge» на странице разницы: отказ человек должен видеть до нажатия,
    а не после. Поэтому проверяем то же и в том же порядке, что `task_worktree_merge`,
    и теми же словами — иначе страница обещала бы одно, а кнопка отвечала другое.

    Конфликты считает `git merge-tree`: слияние в памяти, без рабочего каталога и без
    переключения веток. Объекты в базу оно всё же пишет — дерево результата, на которое
    никто не ссылается; такие подбирает `git gc`. Ни веток, ни коммитов, ни правок в
    чьём-либо каталоге проверка не делает.

    Args:
        repo_dir: каталог основного чекаута проекта.
        subtask_id: номер подзадачи — из него имя ветки.

    Returns:
        `{'can_merge', 'error', 'branch', 'base', 'conflicts', 'merged'}`. `conflicts` —
        файлы, которые git не свёл сам; они непусты ровно тогда, когда `error` про
        конфликт. `merged` — ветка уже целиком в главной, вливать нечего.
    """
    result = {'can_merge': False, 'error': '', 'branch': '', 'base': '', 'conflicts': [],
              'merged': False}
    branch = task_worktree_branch(subtask_id)
    repo_dir = os.path.abspath(str(repo_dir or '')) if repo_dir else ''
    result['branch'] = branch
    if not repo_dir or not branch:
        result['error'] = 'не хватает адреса: нет каталога проекта или номера подзадачи'
        return result
    if not os.path.isdir(repo_dir):
        result['error'] = (f'каталог проекта {repo_dir} не виден — проверьте монтирования '
                           f'(docker-compose.override.yml)')
        return result
    if not await _branch_exists(repo_dir, branch):
        result['error'] = f'ветки {branch} нет — разработчик не оставил коммитов'
        return result

    base = await task_worktree_base_branch(repo_dir)
    result['base'] = base

    # Ветка уже целиком в главной — второй раз её не вливают. Само слияние на этом не
    # спотыкается («Already up to date»), поэтому без явной проверки страница показала
    # бы живую кнопку, а нажатие сделало бы пустой ход и сняло каталог. Проверка
    # заодно ловит ветку без единого коммита: она тоже вся в главной, и вливать в ней
    # тоже нечего.
    #
    # Стоит выше остальных отказов сознательно: «уже влито» — не помеха, которую можно
    # устранить, а конец истории. Оставшийся после слияния каталог с мусором дал бы
    # жалобу на несохранённые правки, и страница показала бы устранимое препятствие
    # там, где вливать давно нечего.
    code, _ = await task_worktree_git(repo_dir, 'merge-base', '--is-ancestor', branch, base)
    if code == 0:
        result['merged'] = True
        result['error'] = f'ветка {branch} уже в {base} — вливать нечего'
        return result

    path = task_worktree_path(repo_dir, subtask_id)
    if os.path.isdir(path):
        _, status = await task_worktree_git(path, 'status', '--porcelain', '-uall', '--ignore-submodules=all')
        dirty = _dirty_lines(path, status)
        if dirty:
            result['error'] = (f'в каталоге подзадачи есть несохранённые правки — они не '
                               f'в ветке и пропадут при снятии: {"; ".join(dirty[:5])}')
            return result

    _, error = await _base_checkout(repo_dir, base)
    if error:
        result['error'] = error
        return result

    conflicts, error = await _merge_conflicts(repo_dir, base, branch)
    result['conflicts'] = conflicts
    if error:
        result['error'] = error
        return result
    if conflicts:
        more = f' и ещё {len(conflicts) - 5}' if len(conflicts) > 5 else ''
        result['error'] = (f'слияние {branch} в {base} встанет на конфликте — git не сведёт '
                           f'сам: {"; ".join(conflicts[:5])}{more}')
        return result

    result['can_merge'] = True

    return result


async def task_worktree_list(repo_dir: str) -> list[dict]:
    """Каталоги репозитория: `[{'path', 'branch', 'head'}]`, включая основной."""
    code, out = await task_worktree_git(repo_dir, 'worktree', 'list', '--porcelain')
    if code:
        return []

    items, current = [], {}
    for line in (out or '').splitlines():
        if not line.strip():
            if current:
                items.append(current)
                current = {}
            continue
        key, _, value = line.partition(' ')
        if key == 'worktree':
            current['path'] = value
        elif key == 'HEAD':
            current['head'] = value
        elif key == 'branch':
            current['branch'] = value.replace('refs/heads/', '')
    if current:
        items.append(current)

    return items


async def task_worktree_git(cwd: str, *args) -> tuple[int, str]:
    """
    git в каталоге: возвращает код и слитый вывод — вызывающему нужен текст ошибки.

    Публичная не для широкого пользования, а потому что каталогами подзадач
    интересуется не только этот модуль: `task_diff.py` показывает человеку разницу
    между главной веткой и веткой подзадачи и зовёт git по тем же правилам —
    от владельца репозитория (`_owner_run_as`) и с тем же таймаутом. Своя копия
    этих правил в соседнем модуле разъехалась бы с этой на первой же правке.

    Запускаем через обычный `subprocess` в отдельном потоке, а не через
    `asyncio.create_subprocess_exec`. Причина в `user`/`group`: воркер крутится на
    стандартном цикле asyncio и эти аргументы принимает, а uvicorn — на uvloop, и
    тот отвечает `ValueError: unexpected kwargs: user, group`. Один и тот же вызов
    работал у агента и падал на странице разницы. `subprocess` понимает их всегда,
    поток же нужен, чтобы ожидание git не держало цикл.
    """
    def run() -> tuple[int, str]:
        try:
            done = subprocess.run(
                ['git', *args], cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=TASK_WORKTREE_GIT_TIMEOUT, **_owner_run_as(cwd))
        except subprocess.TimeoutExpired:
            return 1, f'git {" ".join(args)}: превышено ожидание {TASK_WORKTREE_GIT_TIMEOUT}s'

        return int(done.returncode or 0), (done.stdout or b'').decode(errors='replace').strip()

    return await asyncio.to_thread(run)


async def task_worktree_base_branch(repo_dir: str) -> str:
    """
    Имя главной ветки репозитория — локальное, без `origin/`.

    Спрашиваем у самого репозитория: у проектов на машине оно разное. Ответ даёт
    `origin/HEAD`; у клона, где эта ссылка не настроена, пробуем известные имена и
    берём то, которое в репозитории есть.

    Без `origin/` — и на резке ветки (`task_worktree_ensure`), и на слиянии
    (`task_worktree_merge`), и на показе разницы (`task_diff.py`). На слиянии иначе
    нельзя: удалённая ветка read-only, её двигает `push`. На резке — потому что от
    `origin/` каталог агента получается не тем репозиторием, который агент
    планировал: менеджер читает главный чекаут, а там локальная ветка, и она бывает
    на десятки коммитов впереди сервера. Разработчик тогда не находит файлов, про
    которые ему пишут в плане. База и цель слияния должны быть одной веткой.
    """
    code, out = await task_worktree_git(repo_dir, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD')
    branch = (out or '').strip().split('\n')[-1].removeprefix('origin/').strip() if not code else ''
    if not branch:
        for name in TASK_WORKTREE_BASE_REF_FALLBACK:
            if await _branch_exists(repo_dir, name):
                branch = name
                break

    return branch or TASK_WORKTREE_BASE_REF_FALLBACK[0]


def _owner_run_as(cwd: str) -> dict:
    """
    От чьего имени звать git: от владельца репозитория.

    В контейнере воркера процесс — root, а сам репозиторий примонтирован с хоста и
    принадлежит человеку. Работая root-ом, git отказывается трогать чужой каталог
    («dubious ownership»), а что успел бы создать — создал бы root-овым, и живой
    Claude Code на хосте потом не смог бы туда писать. Поэтому переобуваемся в
    владельца каталога. На хосте (uid совпадает) ничего не подменяем.

    `HOME` уводим в `/tmp`: у чужого uid в контейнере домашнего каталога нет, а git
    без `HOME` шумит на каждый вызов.
    """
    try:
        owner_uid = os.stat(cwd).st_uid
        owner_gid = os.stat(cwd).st_gid
    except OSError:
        return {}

    if os.geteuid() != 0 or owner_uid == 0:
        return {}

    return {'user': owner_uid, 'group': owner_gid, 'env': {**os.environ, 'HOME': '/tmp'}}


# Имя журнала строки: его пишет конвейер в корень каталога подзадачи. Шаблон, а не
# полные имена — они живут в `task_log`, а тот сам берёт отсюда каталоги, и импорт
# в обратную сторону замкнул бы кольцо.
TASK_WORKTREE_LOG_PREFIX = '.task-'
TASK_WORKTREE_LOG_SUFFIX = '.md'


def _dirty_lines(path: str, status: str) -> list[str]:
    """
    Что из `git status --porcelain` считать несохранённой работой.

    Ссылки на общее (`.env`, окружение, рабочие каталоги) кладёт сам конвейер — это
    не правки человека. Отличаем их не по именам: имена у каждого проекта свои, а
    ссылка — всегда симлинк, чего про настоящую работу не скажешь. В свежем каталоге
    они вдобавок неотслеживаемые: `.gitignore` там выкачен из главной ветки и про
    часть из них ещё не знает.

    Подмодули сюда не доходят вовсе — вызывающие спрашивают статус с
    `--ignore-submodules=all`. Их коммит выставили мы сами (`_submodule_align`), и
    сдвиг указателя — не работа агента; без этого флага ни один каталог подзадачи
    не снимался бы и ни одно слияние не проходило.

    Журнал строки (`.task-*.md`) — по той же причине: его пишет конвейер, а не
    агент. Шаблон закрыт в `.gitignore` главной ветки, но ветка подзадачи могла
    отойти раньше, чем шаблон туда попал, — и тогда собственный журнал вставал
    поперёк слияния. Поймано на #1028: `?? .task-log.md`, `?? .task-state.md`.
    """
    dirty = []
    for line in (status or '').splitlines():
        if not line.strip():
            continue
        if line.startswith('?? ') and os.path.islink(os.path.join(path, line[3:].strip().rstrip('/'))):
            continue
        if _dirty_is_log(line):
            continue
        dirty.append(line)

    return dirty


def _dirty_is_log(line: str) -> bool:
    """Строка статуса про журнал конвейера, а не про работу агента."""
    name = os.path.basename(line[3:].strip().strip('"').rstrip('/'))

    return (name.startswith(TASK_WORKTREE_LOG_PREFIX)
            and name.endswith(TASK_WORKTREE_LOG_SUFFIX))


async def _submodule_align(repo_dir: str, path: str) -> None:
    """
    Подмодули каталога подзадачи — на тех же коммитах, что выкачены у человека.

    `submodule update --init` берёт коммит, записанный в ветке, и это не то, с чем
    работает проект: указатель подмодуля в главном чекауте бывает сдвинут вперёд и
    не закоммичен неделями (`M py_modules` в `git status`). Код главной ветки тогда
    зовёт то, чего в записанном коммите ещё нет, — в этой установке так вышло с
    `py_modules/datetime_`: у агента импорт падал, сервер задачи не поднимался, и
    проверить свою же правку он не мог.

    Правило то же, что у базовой ветки: каталог агента — копия того репозитория,
    который видел планировщик, а не того, что записан в git. Двигаем только
    подмодули со сдвигом (`+` в `submodule status`); нетронутые уже верны.

    Объекты общие с главным чекаутом, сети для этого не нужно. Молчаливая неудача
    здесь допустима: каталог рабочий и без выравнивания — просто со старым кодом,
    и это ровно то, что было до правки.
    """
    code, out = await task_worktree_git(repo_dir, 'submodule', 'status', '--recursive')
    if code:
        logger_info(f'task_worktree: состояние подмодулей не получено: {out}')
        return

    for line in (out or '').splitlines():
        if not line.startswith('+'):
            continue
        parts = line[1:].split()
        if len(parts) < 2:
            continue
        commit, name = parts[0], parts[1]
        code, out = await task_worktree_git(os.path.join(path, name), 'checkout', '--detach', commit)
        if code:
            logger_info(f'task_worktree: подмодуль {name} в {path} не выровнен на {commit}: {out}')
        else:
            logger_info(f'task_worktree: подмодуль {name} в {path} выровнен на {commit[:8]}')


async def _merge_host(repo_dir: str, base: str) -> tuple[str, bool, str]:
    """
    Каталог, в котором делать слияние в `base`.

    Returns: `(путь, временный ли, ошибка)`. Временный каталог вызывающий обязан
    снять сам — и на удачном слиянии, и на сорвавшемся.

    Порядок такой из-за правила git: одна ветка выкачена ровно в один каталог. Если
    главная где-то выкачена, слить можно только там — но лишь когда там нет правок
    по отслеживаемым файлам: в них git будет мержить поверх, а разгребать это потом
    человеку. Неотслеживаемое (`-uno`) не в счёт — своих каталогов конвейера в главном
    дереве всегда хватает, а затереть чужой новый файл git и сам не даст. Если не
    выкачена нигде — заводим свой каталог и снимаем его следом, чтобы
    `.claude/worktrees` не зарастал.
    """
    host, error = await _base_checkout(repo_dir, base)
    if error:
        return '', False, error
    if host:
        return host, False, ''

    path = os.path.join(repo_dir, TASK_WORKTREE_BASE_DIR, TASK_WORKTREE_MERGE_DIR)
    # Каталог мог остаться от слияния, которое оборвали на полпути (перезапуск,
    # kill): git тогда откажется его создавать. Снимаем молча — своего в нём нет.
    if os.path.exists(path):
        await task_worktree_git(repo_dir, 'worktree', 'remove', '--force', path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    code, out = await task_worktree_git(repo_dir, 'worktree', 'add', path, base)
    if code:
        return '', True, f'каталог для слияния не создан: {out}'

    return path, True, ''


async def _base_checkout(repo_dir: str, base: str) -> tuple[str, str]:
    """
    Каталог, где выкачена главная ветка, и причина, по которой сливать туда нельзя.

    Returns: `(путь, ошибка)`. Пустой путь без ошибки — ветка не выкачена нигде, и
    слияние заведёт себе временный каталог.

    Отдельно от `_merge_host` ради проверки: та обязана отвечать на вопрос «пройдёт
    ли», ничего в репозитории не создавая, — а `_merge_host` каталог как раз заводит.
    """
    for item in await task_worktree_list(repo_dir):
        if item.get('branch') != base:
            continue
        _, status = await task_worktree_git(item['path'], 'status', '--porcelain', '-uno', '--ignore-submodules=all')
        dirty = _dirty_lines(item['path'], status)
        if dirty:
            return '', (f'ветка {base} выкачена в {item["path"]}, а там несохранённые '
                        f'правки — слияние туда затронуло бы чужую работу')
        return item['path'], ''

    return '', ''


async def _merge_conflicts(repo_dir: str, base: str, branch: str) -> tuple[list[str], str]:
    """
    Файлы, на которых слияние встанет: `git merge-tree` считает его без рабочего каталога.

    Вывод разбираем по строкам: первая — дерево результата, дальше до пустой строки
    имена конфликтных файлов (`--name-only`), а за ней уже пояснения git-а. Код 1 —
    «свёл не всё», прочие ненулевые — что-то другое (нет ветки, git старше 2.38), и
    это ошибка проверки, а не приговор слиянию.

    Returns: `(файлы, ошибка)` — заполнено всегда не больше одного.
    """
    code, out = await task_worktree_git(repo_dir, 'merge-tree', '--write-tree', '--name-only', base, branch)
    if not code:
        return [], ''

    names = []
    for line in (out or '').splitlines()[1:]:
        if not line.strip():
            break
        names.append(line.strip())

    if code != 1 or not names:
        return [], f'проверить слияние не вышло: {(out or "").strip()[:300] or f"git вернул {code}"}'

    return names, ''


async def _identity(cwd: str) -> tuple[str, ...]:
    """
    Аргументы `-c`, которыми подписать коммит слияния, если автора в репозитории нет.

    Настроенного автора не трогаем: подписывать чужой коммит своим именем — врать об
    авторстве. Пустой ответ `git config` и означает «не настроен».
    """
    code, out = await task_worktree_git(cwd, 'config', '--get', 'user.email')
    if not code and (out or '').strip():
        return ()

    name, email = TASK_WORKTREE_MERGE_IDENTITY

    return ('-c', f'user.name={name}', '-c', f'user.email={email}')


async def _branch_exists(repo_dir: str, branch: str) -> bool:
    code, _ = await task_worktree_git(repo_dir, 'rev-parse', '--verify', f'refs/heads/{branch}')

    return not code


async def _shared_link(repo_dir: str, path: str) -> None:
    """
    Ссылки на то, чего в worktree нет по определению: на игнорируемое git-ом.

    Симлинк, а не копия: `.env` должен быть один на все каталоги, окружение
    копировать незачем, а логи и бэкапы задача пишет в общие папки — их потом ищет
    человек. Уже существующее не трогаем: в каталоге мог оказаться настоящий файл.

    Путь источника разворачиваем в абсолютный. Относительный `repo_dir` дал бы
    ссылку вида `.env -> ./.env`, а она разрешается относительно каталога самой
    ссылки — то есть на себя же, и `.venv` в каталоге подзадачи оказался бы битым.
    """
    repo_dir = os.path.abspath(str(repo_dir or '.')).rstrip('/')
    targets = [(os.path.join(repo_dir, name), os.path.join(path, name))
               for name in await _shared_names(repo_dir)]

    for source, link in targets:
        if not os.path.exists(source) or os.path.lexists(link):
            continue
        try:
            os.makedirs(os.path.dirname(link), exist_ok=True)
            os.symlink(source, link)
            # Владельца равняем на репозиторий: root-овую ссылку человек на хосте
            # не заменит, а заменять её приходится — каталоги задач живут долго.
            run_as = _owner_run_as(repo_dir)
            if run_as:
                os.chown(link, run_as['user'], run_as['group'], follow_symlinks=False)
        except OSError as e:
            logger_info(f'task_worktree: ссылка {link} не создана: {e}')


async def _shared_names(repo_dir: str) -> list[str]:
    """
    Что связать с основным каталогом — спрашиваем у самого репозитория.

    Список игнорируемого у каждого проекта свой: здесь это `.env`, `.venv` и
    рабочие каталоги `data/`, у соседнего проекта — `node_modules` и `vendor`.
    Зашитый список работал бы ровно в одном репозитории, поэтому берём то, что
    git сам называет игнорируемым: `--ignored=traditional` сворачивает целиком
    игнорируемый каталог в одну запись, то есть `.venv` приходит папкой, а не
    десятком тысяч файлов.

    Фильтруем по глубине и по кешам (`TASK_WORKTREE_SHARED_DEPTH`,
    `TASK_WORKTREE_SHARED_SKIP`) и отдельно выкидываем корень самих worktree:
    связать его с собой — значит положить каталог подзадачи внутрь себя же.

    Пустой ответ — не ошибка: репозиторий без игнорируемого файла возможен, и
    связывать в нём просто нечего.
    """
    # `-z` вместо переводов строк: имя файла с пробелом или кириллицей git иначе
    # закавычивает и экранирует, и разбирать пришлось бы уже не путь.
    code, out = await task_worktree_git(repo_dir, 'status', '--porcelain', '-z', '--ignored=traditional')
    if code:
        logger_info(f'task_worktree: список игнорируемого не получен: {out}')
        return []

    names = []
    for entry in (out or '').split('\0'):
        if not entry.startswith('!! '):
            continue
        name = entry[3:].strip().rstrip('/')
        parts = [p for p in name.split('/') if p]
        if not parts or len(parts) > TASK_WORKTREE_SHARED_DEPTH:
            continue
        if any(p in TASK_WORKTREE_SHARED_SKIP for p in parts):
            continue
        if name == TASK_WORKTREE_BASE_DIR or name.startswith(f'{TASK_WORKTREE_BASE_DIR}/'):
            continue
        names.append(name)

    return names

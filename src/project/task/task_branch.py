"""
Ветка родительской задачи как место сборки работы её подзадач.

Зачем. Ветки подзадач резались от главной и о соседях не знали: их работа сходилась
только в конце, когда задача закрывалась целиком, — и сходилась плохо. Две подзадачи,
тронувшие одно место, узнавали об этом через сутки, на сборке merge request, а до тех
пор каждая считала себя правой. Расхождение с самой главной веткой обнаруживалось там же
и тоже поздно.

Отсюда правило: **у задачи одна ветка, и вся работа течёт через неё**.

    подзадача берётся в работу  ->  ветка задачи вливается в ветку подзадачи
    подзадача прошла QA         ->  ветка подзадачи вливается в ветку задачи

Ветка задачи — та же `feature/task_<id>`, что заводит менеджер при планировании вместе
со своей выкладкой (`task_worktree_ensure`). Своего имени и своей выкладки заводить не
нужно: они уже есть, стоят на точке отреза от главной и никем не заняты — менеджер в
каталоге только читает код и пишет план, кода не меняет.

Что это даёт. Подзадача начинает работу, уже видя всё принятое соседями, а не пустое
место там, где сосед что-то сделал. Конфликт, если он есть, вылезает на входе в круг —
когда его дешевле всего чинить, — а не через сутки на сборке. И к моменту закрытия
задачи ветка уже собрана: merge request открывается как есть, сливать в него нечего.

**Конфликт между подзадачами разбирает роль, а не человек.** Параллельные круги внутри
задачи конфликты не отменяют: две подзадачи могут начать работу до приёмки друг друга.
Но здесь сталкивается своя работа со своей — обе делались по одному плану, обе знакомы
исполнителю, — и звать человека значило бы останавливать задачу из-за того, что роль и
сама разберёт. Агенту дают обе ветки, список файлов и каталог, а конвейер потом
**проверяет делом**: маркеров не осталось, слияние закоммичено, источник стал предком
приёмника. Не справился или звать некого — откатываемся и зовём человека, как раньше.

Расхождение с самой главной веткой сюда не относится и остаётся за человеком: там
сталкивается чужой код, которого роль не писала и за автора которого решать не вправе.

Коммит слияния подписываем (`_identity`): в контейнере воркера git зовётся от uid
владельца каталога, `HOME` уведён в `/tmp`, и без подписи git отказывается коммитить —
«Committer identity unknown».
"""
import os

from logging_.logging_ import logger_info

# Сколько ждём агента, разбирающего конфликт. Работа узкая — прочитать два куска и
# выбрать, — и на неё не нужен круг разработки: столько же, сколько на разбор изменений
# у QA. Не уложился — откатываем слияние и зовём человека, как раньше.
TASK_BRANCH_RESOLVE_TIMEOUT = 1200

# Файлы конвейера в каталоге подзадачи: журнал, состояние, спецификация, решения. Их
# пишет конвейер, а не работа, и в конфликт они попадают постоянно — у каждой ветки своя
# история. Разрешаются они механически, «взять свою»: чужой журнал в своём каталоге не
# нужен никому, а звать ради этого агента — тратить круг.
TASK_BRANCH_OURS_FILES = ('.task-log.md', '.task-state.md', '.task-spec.md',
                          '.task-decision.md', '.task-shell.md')


async def task_branch_of(task_id) -> str:
    """Имя ветки задачи. Нет номера — пустая строка."""
    from src.project.task.task_worktree import task_worktree_branch

    return task_worktree_branch(task_id)


async def task_branch_conflict(repo_dir: str, target_id: int, source_id: int) -> list:
    """
    Файлы, на которых слияние столкнётся. Пустой список — сойдётся само.

    Считаем `git merge-tree`: он сливает в памяти, не трогая ни каталог, ни ветку, ни
    индекс. Спрашивать этим можно когда угодно и сколько угодно — в отличие от
    настоящего `merge`, который оставляет каталог в конфликтном состоянии.

    Нужен, чтобы решить заранее, звать агента или сливать молча: конфликт между
    подзадачами одной задачи разбирает роль, а не человек (`task_branch_resolve`).
    """
    from src.project.task.task_worktree import task_worktree_branch, task_worktree_git

    target, source = task_worktree_branch(target_id), task_worktree_branch(source_id)
    if not repo_dir or not target or not source:
        return []

    code, out = await task_worktree_git(repo_dir, 'merge-tree', '--write-tree',
                                        '--name-only', target, source)
    if not code:
        return []

    # Первая строка — хеш дерева, дальше имена конфликтных файлов до пустой строки.
    names = []
    for line in str(out or '').splitlines()[1:]:
        line = line.strip()
        if not line:
            break
        names.append(line)

    return names


async def task_branch_pull(repo_dir: str, subtask_id: int, parent_id: int,
                           role: str = '', session: str = '') -> dict:
    """
    Влить ветку задачи в ветку подзадачи — перед кругом.

    Подзадача обязана начинать работу с того, что уже принято: соседи закрыли свои
    строки, их код лежит в ветке задачи, и без этого шага исполнитель увидел бы пустое
    место там, где рассчитывал на готовое.

    Ветки задачи ещё нет (план разобран старым кодом, менеджер каталога не заводил) —
    делать нечего и жаловаться не на что: `ok` с пустым `merged`.

    Returns: `{'ok', 'merged', 'conflict', 'error'}`. `conflict` — имя ветки задачи,
    если слияние развернули; `ok = False` при любой неудаче.
    """
    return await _merge(repo_dir, target_id=subtask_id, source_id=parent_id,
                        message=f'Код задачи #{parent_id} в подзадачу #{subtask_id}',
                        what='ветка задачи', role=role, session=session)


async def task_branch_push(repo_dir: str, subtask_id: int, parent_id: int,
                           role: str = '', session: str = '') -> dict:
    """
    Влить ветку подзадачи в ветку задачи — после того, как QA её принял.

    Только принятую работу: непринятую подзадача ещё будет переделывать, и её код в
    общей ветке мешал бы соседям, которые начнут круг после неё.

    Конфликта здесь быть уже не должно — подзадача перед кругом вливала ветку задачи и
    работала поверх неё. Если он всё-таки случился, значит между её кругом и приёмкой в
    ветку задачи попало чужое изменение того же места: это ошибка разбиения, и чинит её
    менеджер. Говорим словами и оставляем ветку задачи нетронутой.

    Returns: `{'ok', 'merged', 'conflict', 'error'}`.
    """
    return await _merge(repo_dir, target_id=parent_id, source_id=subtask_id,
                        message=f'Подзадача #{subtask_id} принята QA',
                        what='ветка подзадачи', role=role, session=session)


async def task_branch_resolve(path: str, target_branch: str, source_branch: str,
                              files: list, role: str, work_dir: str, session: str) -> dict:
    """
    Позвать роль разобрать конфликт слияния и довести его до коммита.

    Returns: `{'ok', 'error'}`. `ok` ставим **не по словам агента, а по факту**: слияние
    доведено, если каталог чист и ветка-источник стала предком ветки-приёмника. Агент
    охотно отчитывается «разрешил», оставив в файле конфликтные маркеры или бросив
    слияние на полдороге, и верить такому отчёту нельзя.

    Почему это отдаёт роли, хотя расхождение с главной веткой разбирает человек. Разница
    в том, чья это работа. С главной сталкивается чужой код — роль его не писала, не
    знает, зачем он такой, и выбирать за автора не вправе. А здесь сталкиваются две
    подзадачи одной задачи: обе делались по одному плану, обе свои, и роль знает про
    них всё. Звать сюда человека — останавливать задачу из-за того, что исполнитель и
    сам разберёт.

    Служебные файлы конвейера (`TASK_BRANCH_OURS_FILES`) агенту не показываем и решаем
    механически: журнал и состояние у каждой ветки свои, разрешать там нечего.

    Роли или оболочки нет — разбирать некому: `ok = False`, и вызывающий откатит
    слияние и позовёт человека, как раньше.
    """
    from src.tool.claude_shell.claude_shell import claude_shell_call
    from src.project.task.task_worktree import _identity, task_worktree_git

    if not role or not session:
        return {'ok': False, 'error': 'некого звать: у роли нет захваченной оболочки'}

    await _ours_resolve(path, files)
    left = [name for name in files if name not in TASK_BRANCH_OURS_FILES]
    if left:
        answer = await claude_shell_call(
            _resolve_prompt(path, target_branch, source_branch, left),
            role=role, timeout=TASK_BRANCH_RESOLVE_TIMEOUT, work_dir=work_dir,
            session=session)
        logger_info(f'[task] {role} разбирал конфликт {source_branch} -> {target_branch}: '
                    f"{str(answer.get('status') or '')}")

    # Агент часто правит содержимое и останавливается, не сделав `git add` и `git
    # commit`: для него работа кончилась, файл выглядит правильно. Доводим сами — но
    # только убедившись, что маркеры действительно убраны. `git add` снимает признак
    # конфликта с файла независимо от того, что в нём лежит, поэтому проверять надо
    # содержимое, а не состояние индекса: иначе в ветку задачи уехал бы файл с
    # `<<<<<<<` посередине, и следующий круг встал бы на нём.
    left_markers = _markers_left(path, files)
    if left_markers:
        return {'ok': False,
                'error': f'в файлах остались конфликтные маркеры: {", ".join(left_markers)}'}

    await task_worktree_git(path, 'add', '-A')
    await task_worktree_git(path, *await _identity(path), 'commit', '--no-edit')

    return await _merge_verify(path, target_branch, source_branch)


def _markers_left(path: str, files: list) -> list:
    """
    Файлы, в которых ещё стоят конфликтные маркеры git.

    Читаем сами, а не спрашиваем git: он о содержимом не судит — `git add` пометит
    разрешённым и файл, набитый маркерами. Нечитаемый файл (двоичный, удалён) маркеров
    не содержит по определению и в список не идёт.
    """
    left = []
    for name in files:
        full = os.path.join(path, name)
        try:
            with open(full, 'r', encoding='utf-8') as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if '<<<<<<<' in text or '>>>>>>>' in text:
            left.append(name)

    return left


async def _merge_verify(path: str, target_branch: str, source_branch: str) -> dict:
    """
    Слияние доведено? Проверяем делом, а не отчётом.

    Два признака, и нужны оба: неразрешённых файлов не осталось (иначе в коде лежат
    маркеры) и ветка-источник стала предком приёмника (иначе слияние не закоммичено, и
    работа соседа в ветку не попала).
    """
    from src.project.task.task_worktree import task_worktree_git

    code, out = await task_worktree_git(path, 'diff', '--name-only', '--diff-filter=U')
    if code or str(out or '').strip():
        return {'ok': False, 'error': f'конфликт не разобран: {str(out or "").strip()[:200]}'}

    code, _ = await task_worktree_git(path, 'merge-base', '--is-ancestor',
                                      source_branch, target_branch)
    if code:
        return {'ok': False, 'error': f'слияние не закоммичено: {source_branch} '
                                      f'не стала предком {target_branch}'}

    return {'ok': True, 'error': ''}


async def _ours_resolve(path: str, files: list) -> None:
    """Служебные файлы конвейера разрешить «взять свою» — агенту их видеть незачем."""
    from src.project.task.task_worktree import task_worktree_git

    for name in files:
        if name in TASK_BRANCH_OURS_FILES:
            await task_worktree_git(path, 'checkout', '--ours', '--', name)
            await task_worktree_git(path, 'add', '--', name)


def _resolve_prompt(path: str, target_branch: str, source_branch: str, files: list) -> str:
    """
    Задание роли: развести конфликт и закоммитить слияние.

    Пишем адресами и командами, а не пожеланиями: ветки названы обе, каталог назван,
    список файлов дан. Отдельно сказано, чего не делать, — переписывать работу под свой
    вкус агент склонен, а здесь его дело только свести две готовые версии.
    """
    listed = '\n'.join(f'  - {name}' for name in files)

    return (
        f'Слияние встало на конфликте, разбери его и доведи до коммита.\n\n'
        f'Каталог: {path}\n'
        f'Ветка-приёмник (в неё сливаем, ты в ней сейчас): {target_branch}\n'
        f'Ветка-источник (её вливаем): {source_branch}\n\n'
        f'Конфликтующие файлы:\n{listed}\n\n'
        f'Обе стороны — работа по одному плану этой же задачи: твоя и соседней '
        f'подзадачи. Значит нужно не выбрать одну, а свести обе так, чтобы уцелели оба '
        f'намерения. Выбор одной стороны целиком — только там, где второй вариант просто '
        f'старее (число, счётчик, устаревшая строка таблицы).\n\n'
        f'Что сделать:\n'
        f'1. Посмотреть конфликт: git diff, в файлах маркеры <<<<<<< ======= >>>>>>>\n'
        f'2. Свести содержимое, убрать маркеры целиком.\n'
        f'3. git add по каждому файлу и git commit --no-edit — сообщение уже готово.\n\n'
        f'Чего не делать: не менять ничего сверх конфликтных мест, не переписывать код '
        f'по своему вкусу, не откатывать слияние (git merge --abort), не трогать другие '
        f'ветки. Твоё дело — свести две готовые версии, а не улучшить их.\n\n'
        f'Ответь одной строкой: что свёл и чем проверил.')


async def _merge(repo_dir: str, target_id: int, source_id: int, message: str,
                 what: str, role: str = '', session: str = '') -> dict:
    """
    Влить ветку `source_id` в ветку `target_id`, работая в выкладке приёмника.

    Выкладку приёмника заводим, если её нет: `task_worktree_ensure` идемпотентен, а без
    каталога слить ветку некуда — git сливает в то, что выкачено.

    Конфликт разворачиваем (`merge --abort`), чтобы каталог остался рабочим: круг
    начнётся, упрётся в отсутствие кода и честно скажет об этом, а не утонет в
    конфликтных маркерах посреди файлов.
    """
    from src.project.task.task_worktree import (_identity, task_worktree_branch,
                                                task_worktree_ensure, task_worktree_git)

    result = {'ok': True, 'merged': '', 'conflict': '', 'resolved': False, 'error': ''}
    target_branch = task_worktree_branch(target_id)
    source_branch = task_worktree_branch(source_id)
    if not repo_dir or not target_branch or not source_branch:
        return result

    try:
        path = await task_worktree_ensure(repo_dir, target_id)
    except Exception as e:
        result.update(ok=False, error=f'каталог #{target_id} не готов: {e}')
        logger_info(f'[task] слияние {source_branch} -> {target_branch}: {result["error"]}')

        return result

    if not path or not os.path.isdir(path):
        return result

    # Ветки-источника может не быть вовсе: подзадача закрылась как
    # `no_code_for_testing` — работа была уже в главной, и вливать нечего.
    code, _ = await task_worktree_git(path, 'rev-parse', '--verify', source_branch)
    if code:
        return result

    code, out = await task_worktree_git(
        path, *await _identity(path), 'merge', '--no-edit', '-m', message, source_branch)
    if not code:
        result['merged'] = source_branch
        logger_info(f'[task] {source_branch} влита в {target_branch}')

        return result

    # Конфликт между подзадачами одной задачи разбирает роль, а не человек: обе стороны
    # делались по одному плану, обе свои, и исполнитель знает про них всё. Каталог
    # оставляем в конфликтном состоянии — агенту нужны маркеры; откатим, только если он
    # не справится.
    if 'CONFLICT' in str(out or '') and role and session:
        files = await task_worktree_git(path, 'diff', '--name-only', '--diff-filter=U')
        resolved = await task_branch_resolve(
            path, target_branch, source_branch,
            [n.strip() for n in str(files[1] or '').splitlines() if n.strip()],
            role, repo_dir, session)
        if resolved['ok']:
            result['merged'] = source_branch
            result['resolved'] = True
            logger_info(f'[task] {role} развёл конфликт: {source_branch} влита в '
                        f'{target_branch}')

            return result

        result['error'] = resolved['error']

    await task_worktree_git(path, 'merge', '--abort')
    result['ok'] = False
    result['error'] = str(out or '')[:400]
    # Конфликт содержимого и «слияние не состоялось» — разные новости, как и у слияния
    # предшественников (`task_depend_merge_upstream`): первое означает ошибку разбиения,
    # второе — заминку, за которую подзадачу глушить не за что.
    result['conflict'] = source_branch if 'CONFLICT' in str(out or '') else ''
    logger_info(f'[task] {what} {source_branch} не влилась в {target_branch} '
                f"({'конфликт' if result['conflict'] else 'слияние не состоялось'}): "
                f"{result['error'][:200]}")

    return result

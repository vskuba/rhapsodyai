"""
Merge request по закрытой задаче: свести ветки её подзадач и попросить слияние.

Когда. В момент, когда закрылась последняя подзадача и задача перешла в `done`
(`task_pipeline._run_finalize`). Раньше нельзя: пока хоть одна подзадача в работе,
ветка задачи неполна, и merge request показывал бы половину работы.

Почему сборочная ветка, а не merge request с ветки подзадачи. Подзадач у задачи
несколько, у каждой своя ветка, а merge request нужен один — на задачу, как её и
заказывал человек. Поэтому от главной отводится ветка `task/<id>`, в неё по очереди
вливаются ветки подзадач, и уже она просится в главную.

Почему на стороне GitHub, а не локально. Ветки подзадач разработчик пушит по ходу
работы, значит на сервере они уже есть; локальная же выкладка задачи живёт на диске
машины и в общий репозиторий не смотрит. Сборка на сервере не требует ни push из
контейнера, ни прав на запись в чужой рабочий каталог.

Конфликт останавливает сборку и **не разрешается**: merge request не заводится, а в
отчёт задачи уходит имя ветки, которая не сошлась, и ссылка на сравнение. Разбирает
его человек — это его работа, а не роли (см. `role_developer.md`).

Сбой здесь задачу не переоткрывает: работа сделана и принята, а merge request —
удобство поверх неё. Всё, что случилось, попадает в отчёт задачи, и человек сведёт
ветки руками кнопкой на `/admin/task`.
"""
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

from src.project.task.task_metadata import TASK_METADATA_KEY_MR, task_metadata_update
from src.project.task.task_worktree import task_worktree_branch, task_worktree_git
from src.tool.github.github_merge import (github_merge_branch, github_merge_branch_ensure,
                                          github_merge_branch_exists,
                                          github_merge_request_create)

# Ветка, в которую сводится работа задачи. Не `feature/...`, как у подзадач: их ветки
# заводит конвейер под работу, а эта — под сдачу, и по имени должно быть видно, что
# внутри вся задача, а не один её кусок.
TASK_MERGE_REQUEST_BRANCH_TEMPLATE = 'task/{task_id}'

# Куда просим слияние. Та же главная, от которой конвейер режет ветки подзадач.
TASK_MERGE_REQUEST_BASE = 'master'

# Состояния подзадач, чью ветку берём в сборку. Ровно те, в которых работа считается
# принятой: `done` — QA принял, `no_code_for_testing` — кода не было вовсе, и ветки у
# такой подзадачи тоже нет, она отсеется сама.
TASK_MERGE_REQUEST_DONE_STATES = ('done', 'no_code_for_testing')


async def task_merge_request_open(task_id: int, work_dir: str) -> dict:
    """
    Свести ветки подзадач задачи в одну и завести merge request в главную.

    Returns: `{'ok', 'url', 'branch', 'merged', 'conflict', 'message'}`. `ok = False`
    при любой заминке — конфликте, отсутствии токена, пустом наборе веток; что именно
    случилось, сказано словами в `message`, и его пишет в отчёт вызывающий.

    Исключений не бросает: merge request — удобство поверх уже принятой работы, и
    ронять из-за него тик конвейера незачем.
    """
    result = {'ok': False, 'url': '', 'branch': '', 'merged': [], 'conflict': '',
              'message': ''}
    try:
        repo_name = await _repo_name(work_dir)
        if not repo_name:
            result['message'] = 'merge request не заведён: у репозитория нет адреса origin'
            return result

        branches = await _subtask_branches(int(task_id or 0), repo_name)
        if not branches:
            result['message'] = ('merge request не нужен: ни одна подзадача не оставила '
                                 'ветки в репозитории')
            return result

        branch = TASK_MERGE_REQUEST_BRANCH_TEMPLATE.format(task_id=int(task_id))
        result['branch'] = branch

        ready = await github_merge_branch_ensure(repo_name, branch, TASK_MERGE_REQUEST_BASE)
        if ready['ready'] != '1':
            result['message'] = f"merge request не заведён: {ready['message']}"
            return result

        for item in branches:
            merged = await github_merge_branch(repo_name, item, branch)
            if merged['conflict'] == '1':
                result['conflict'] = item
                result['message'] = (f'merge request не заведён: ветка {item} не сходится '
                                     f'с {branch}. Конфликт разбирает человек: {merged["url"]}')
                return result
            if merged['merged'] != '1':
                result['message'] = f"merge request не заведён: {merged['message']}"
                return result
            if merged['already'] != '1':
                result['merged'].append(item)

        pull = await github_merge_request_create(
            repo_name, branch, TASK_MERGE_REQUEST_BASE,
            title=f'task/{task_id}: работа задачи',
            body=_body(int(task_id), branches))
        if pull['created'] != '1':
            result['message'] = f"merge request не заведён: {pull['message']}"
            return result

        result['ok'] = True
        result['url'] = pull['url']
        result['message'] = (f"{pull['message']}; в ветке {branch} сведены "
                             f"{len(branches)} ветк(и) подзадач: {pull['url']}")
    except Exception as e:
        result['message'] = f'merge request не заведён: {e}'
        logger_info(f'[task] task#{task_id}: сборка merge request сорвалась: {e}')

        return result

    await _mr_url_save(int(task_id), result['url'])

    return result


async def _repo_name(work_dir: str) -> str:
    """
    Полное имя репозитория (`владелец/имя`) из адреса `origin`. Нет — пустая строка.

    Берём из самого репозитория, а не из настройки: адрес у проекта один, он уже
    записан в git, и вторая его копия разошлась бы с первой в день переезда.

    Разбираем оба вида адреса — `https://github.com/o/r.git` и `git@github.com:o/r.git`:
    какой из них настроен, зависит от того, как человек клонировал, и знать это здесь
    неоткуда.
    """
    code, out = await task_worktree_git(str(work_dir or ''), 'remote', 'get-url', 'origin')
    if code:
        return ''

    url = str(out or '').strip().splitlines()[0] if out else ''
    if not url:
        return ''

    url = url.removesuffix('.git')
    if url.startswith('git@'):
        url = url.partition(':')[2]
    else:
        url = url.partition('github.com/')[2] or url.partition('github.com:')[2]

    parts = [chunk for chunk in url.split('/') if chunk]

    return '/'.join(parts[-2:]) if len(parts) >= 2 else ''


async def _subtask_branches(task_id: int, repo_name: str) -> list[str]:
    """
    Ветки принятых подзадач в порядке работы. Только те, что есть на GitHub.

    Порядок — тот же, в котором подзадачи шли по плану (`position`, затем номер):
    поздняя работа опирается на раннюю, и вливать её первой значит нарываться на
    конфликт там, где его нет.

    Подзадача без ветки на сервере пропускается молча: так выглядит работа, которой не
    было (`no_code_for_testing`) или которую не запушили. Первый случай штатный, второй
    виден в отчёте самой подзадачи.
    """
    if not task_id:
        return []

    placeholders = ', '.join(['%s'] * len(TASK_MERGE_REQUEST_DONE_STATES))
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id FROM project_task '
            f' WHERE parent_id = %s AND pipeline_state IN ({placeholders}) '
            ' ORDER BY position, id',
            (int(task_id), *TASK_MERGE_REQUEST_DONE_STATES))
        rows = await db.fetchall() or []

    out = []
    for row in rows:
        branch = task_worktree_branch(int(row['id']))
        if branch and (await github_merge_branch_exists(repo_name, branch))['exists'] == '1':
            out.append(branch)

    return out


def _body(task_id: int, branches: list) -> str:
    """Описание merge request: что за задача и из каких веток она собрана."""
    lines = [f'Задача #{task_id}. Работа сведена из веток подзадач:', '']
    lines += [f'- {branch}' for branch in branches]

    return '\n'.join(lines)


async def _mr_url_save(task_id: int, url: str) -> None:
    """
    Адрес merge request — в metadata задачи, рядом с прочими её ссылками.

    Пустой не пишем: сборка сорвалась, и затирать адрес прошлой удачной попытки
    нечем — она остаётся верной, пока ветку не переоткрыли.
    """
    if not url:
        return

    await task_metadata_update(task_id, {TASK_METADATA_KEY_MR: url})

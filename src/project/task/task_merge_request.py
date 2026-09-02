"""
Merge request по закрытой задаче: попросить слияние ветки задачи в главную.

Когда. В момент, когда закрылась последняя подзадача и задача перешла в `done`
(`task_pipeline._run_finalize`). Раньше нельзя: пока хоть одна подзадача в работе,
ветка задачи неполна, и merge request показывал бы половину работы.

Сводить здесь нечего — работа собралась по ходу дела. У задачи одна ветка
(`feature/task_<id>`, её заводит менеджер при планировании), и через неё течёт всё:
подзадача берётся в работу — ветка задачи вливается в неё, подзадача проходит QA —
вливается обратно (`task_branch`). К закрытию задачи ветка готова.

Так было не всегда, и прежний порядок стоил задачи #4915. Сборка шла здесь: заводилась
ветка `task/<id>` от **свежей** главной, и в неё вливались ветки подзадач, отрезанные от
**старой**. Первая же не сошлась — четыре принятых подзадачи остались без merge request,
а сборочная ветка так и осталась пустой копией главной.

Остаётся одно дело помимо самого merge request: отправить ветку задачи на сервер.
Ветки подзадач пушит разработчик своим кругом, а в ветку задачи сливает конвейер —
локально, и на GitHub её может не быть вовсе.

Сбой здесь задачу не переоткрывает: работа сделана и принята, а merge request —
удобство поверх неё. Всё, что случилось, попадает в отчёт задачи, и человек сведёт
ветки руками кнопкой на `/admin/task`.
"""
from logging_.logging_ import logger_info
from src.project.task.task_metadata import TASK_METADATA_KEY_MR, task_metadata_update
from src.project.task.task_worktree import task_worktree_branch, task_worktree_git
from src.tool.github.github_merge import (github_merge_branch_exists,
                                          github_merge_request_create)

# Куда просим слияние. Та же главная, от которой конвейер режет ветку задачи.
TASK_MERGE_REQUEST_BASE = 'master'


async def task_merge_request_open(task_id: int, work_dir: str) -> dict:
    """
    Открыть merge request из ветки задачи в главную.

    Сводить здесь уже нечего: работа собиралась по ходу дела. Каждая подзадача,
    принятая QA, влилась в ветку задачи в тот же момент (`task_branch_push`), а
    начиналась с того, что ветку задачи влили в неё (`task_branch_pull`). К закрытию
    задачи ветка готова — остаётся попросить слияние.

    Раньше сборка шла здесь: заводилась ветка `task/<id>` от главной, и в неё по
    очереди вливались ветки подзадач. Это работало ровно до первого расхождения —
    ветки резались от старой главной, а сборочная от свежей, и первая же подзадача
    не сходилась. Живьём #4915: четыре подзадачи приняты, merge request не заведён,
    сборочная ветка осталась пустой копией главной.

    Ветку задачи нужно ещё и запушить: подзадачи свои ветки пушат сами, а её сливал
    конвейер локально, и на сервере её может не быть вовсе.

    Returns: `{'ok', 'url', 'branch', 'message'}`. `ok = False` при любой заминке;
    что именно случилось, сказано словами в `message`, и его пишет в отчёт вызывающий.

    Исключений не бросает: merge request — удобство поверх уже принятой работы, и
    ронять из-за него тик конвейера незачем.
    """
    result = {'ok': False, 'url': '', 'branch': '', 'message': ''}
    try:
        repo_name = await _repo_name(work_dir)
        if not repo_name:
            result['message'] = 'merge request не заведён: у репозитория нет адреса origin'
            return result

        branch = task_worktree_branch(int(task_id or 0))
        result['branch'] = branch
        if not branch:
            result['message'] = 'merge request не заведён: у задачи нет ветки'
            return result

        pushed = await _branch_push(work_dir, branch, repo_name)
        if not pushed['ok']:
            result['message'] = f"merge request не заведён: {pushed['error']}"
            return result

        if (await github_merge_branch_exists(repo_name, branch))['exists'] != '1':
            result['message'] = (f'merge request не нужен: ветки {branch} нет в репозитории — '
                                 f'работа задачи никуда не коммитилась')
            return result

        pull = await github_merge_request_create(
            repo_name, branch, TASK_MERGE_REQUEST_BASE,
            title=f'{branch}: работа задачи #{task_id}',
            body=f'Задача #{task_id}. Работа подзадач собрана в ветке по ходу приёмки QA.')
        if pull['created'] != '1':
            result['message'] = f"merge request не заведён: {pull['message']}"
            return result

        result['ok'] = True
        result['url'] = pull['url']
        result['message'] = f"{pull['message']}: {pull['url']}"
    except Exception as e:
        result['message'] = f'merge request не заведён: {e}'
        logger_info(f'[task] task#{task_id}: merge request не заведён: {e}')

        return result

    await _mr_url_save(int(task_id), result['url'])

    return result


async def _branch_push(work_dir: str, branch: str, repo_name: str) -> dict:
    """
    Отправить ветку задачи в общий репозиторий. Returns: `{'ok', 'error'}`.

    Ветки подзадач пушит разработчик своим кругом, а ветку задачи никто: в неё сливает
    конвейер, локально. Без отправки merge request просить не о чем — GitHub о такой
    ветке не знает.

    **Адрес собираем с токеном, а не берём `origin`.** Разработчик пушит из своей
    оболочки на машине человека, где `git` давно настроен; конвейер живёт в контейнере,
    где нет ни `~/.gitconfig`, ни хранилища паролей, — и `git push origin` там упирается
    в «could not read Username for https://github.com». Токен же в контейнере есть, тем
    же `GITHUB_TOKEN`, которым ходит API. Живьём это стоило задаче #4996 merge request:
    работа собралась, ветка была готова, а отправить её не вышло.

    Токен подставляем в адрес одного вызова и никуда не пишем: `git remote set-url`
    оставил бы его в `.git/config` — то есть в репозитории, который читают люди и
    оболочки ролей.

    Отправляем только вперёд (без `--force`): ветка задачи растёт слияниями принятой
    работы, и переписывать её историю нам нечем и незачем.
    """
    import os

    from src.project.task.task_worktree import task_worktree_git

    token = str(os.getenv('GITHUB_TOKEN') or '').strip()
    remote = (f'https://x-access-token:{token}@github.com/{repo_name}.git'
              if token and repo_name else 'origin')
    code, out = await task_worktree_git(work_dir, 'push', remote, f'{branch}:{branch}')
    # Токен в тексте ошибки — та же утечка, что и в конфиге: сообщение уходит в отчёт
    # задачи, а его читают на странице и в Telegram.
    out = str(out or '').replace(token, '***') if token else out

    return {'ok': not code, 'error': str(out or '')[:400] if code else ''}


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


async def _mr_url_save(task_id: int, url: str) -> None:
    """
    Адрес merge request — в metadata задачи, рядом с прочими её ссылками.

    Пустой не пишем: сборка сорвалась, и затирать адрес прошлой удачной попытки
    нечем — она остаётся верной, пока ветку не переоткрыли.
    """
    if not url:
        return

    await task_metadata_update(task_id, {TASK_METADATA_KEY_MR: url})

"""
Слияние веток на стороне GitHub: влить ветку в ветку и завести merge request.

Зачем отдельным файлом, когда рядом есть `github_check_and_merge`. Тот возвращает
**строку** — и успех, и конфликт, и ошибку одинаково, текстом. Шагу workflow с таким
ответом делать нечего: развилка `transitions` сравнивает переменные, а не читает прозу,
и «Конфликт: мердж невозможен» от «Успешно: ветка влита» он не отличит. Плюс он зовёт
`webbrowser.open` — на сервере в контейнере это открывает браузер в никуда.

Здесь результат — словарь с отдельными полями, и главное из них `conflict`: по нему шаг
решает, звать человека или идти дальше. Текст для человека тоже есть, но он для чтения,
а не для условий.

**Это слияние на сервере, не в рабочем каталоге.** GitHub сливает то, что запушено, и
результат остаётся у него: локальная выкладка подзадачи о нём не узнает. Поэтому для
кода предшественников, который разработчику нужен **под руками**, служит не этот
инструмент, а `task_depend_merge_upstream` — он делает `git merge` прямо в каталоге
подзадачи перед кругом. Здешнее место — то, что происходит после работы: свести готовую
ветку с главной и показать её человеку.

Доступ — токеном `GITHUB_TOKEN` из окружения (`_github_auth` в `github_.py`), полное имя
репозитория передаётся аргументом: `vskuba/rhapsodyai`.
"""
from github import GithubException

from src.tool.github.github_ import _github_auth

# Код ответа GitHub, которым он отвечает на неразрешимое слияние. Отдельной константой,
# потому что по нему проходит единственная развилка, ради которой инструмент и написан:
# всё остальное — это либо успех, либо поломка, а конфликт — работа для человека.
GITHUB_MERGE_STATUS_CONFLICT = 409

# Ветки или репозитория нет. Отличаем от конфликта: тут человеку идти некуда, чинить
# нужно адрес.
GITHUB_MERGE_STATUS_MISSING = 404


async def github_merge_branch(repo_full_name: str, branch_head: str,
                              branch_base: str) -> dict:
    """
    Вливает ветку branch_head в ветку branch_base на GitHub.

    Сливает то, что запушено в репозиторий; локальные рабочие каталоги не трогает.
    Конфликт слиянием не считается ошибкой инструмента: он возвращается признаком
    conflict вместе со ссылкой, по которой человек разбирает расхождение руками.

    Args:
        repo_full_name (str): полное имя репозитория, например vskuba/rhapsodyai.
        branch_head (str): ветка-источник, ту, что вливают.
        branch_base (str): ветка-приёмник, в которую вливают.

    Returns:
        dict: Словарь с результатом, содержащий:
            merged (str): '1' - слияние прошло, '0' - не прошло.
            conflict (str): '1' - ветки разошлись и слияние невозможно, '0' - иное.
            already (str): '1' - вливать было нечего, ветка уже в приёмнике.
            sha (str): хеш коммита слияния; пустая строка, если коммита не было.
            url (str): адрес сравнения веток на GitHub - по нему разбирают конфликт.
            message (str): та же новость словами, для человека и журнала.
    """
    head, base = str(branch_head or '').strip(), str(branch_base or '').strip()
    repo_name = str(repo_full_name or '').strip()
    result = _result(url=_compare_url(repo_name, head, base))
    if not repo_name or not head or not base:
        result['message'] = 'не хватает адреса: нужны имя репозитория и обе ветки'
        return result

    try:
        commit = _github_auth().get_repo(repo_name).merge(
            base=base, head=head, commit_message=f'Merge {head} into {base}')
    except GithubException as e:
        return _github_error(result, e, head, base)
    except Exception as e:
        result['message'] = f'слияние не выполнено: {e}'
        return result

    # None — GitHub так отвечает, когда сливать нечего: ветка уже в приёмнике. Это
    # успех, а не пустой результат: следующий шаг вправе идти дальше.
    if commit is None:
        return _result(merged='1', already='1', url=result['url'],
                       message=f'ветка {head} уже в {base}, слияние не требуется')

    return _result(merged='1', sha=str(commit.sha), url=result['url'],
                   message=f'ветка {head} влита в {base}, коммит {str(commit.sha)[:8]}')


async def github_merge_branch_exists(repo_full_name: str, branch: str) -> dict:
    """
    Проверяет, есть ли ветка branch в репозитории на GitHub.

    Отсутствие ветки - это ответ, а не ошибка: разработчик мог не оставить коммитов,
    и сборке такую подзадачу нужно просто пропустить.

    Args:
        repo_full_name (str): полное имя репозитория, например vskuba/rhapsodyai.
        branch (str): имя ветки.

    Returns:
        dict: Словарь с результатом, содержащий:
            exists (str): '1' - ветка есть, '0' - её нет либо спросить не удалось.
            sha (str): хеш последнего коммита ветки; пустая строка, если ветки нет.
            message (str): та же новость словами, для человека и журнала.
    """
    name, repo_name = str(branch or '').strip(), str(repo_full_name or '').strip()
    if not repo_name or not name:
        return {'exists': '0', 'sha': '',
                'message': 'не хватает адреса: нужны имя репозитория и ветка'}

    try:
        found = _branch_find(_github_auth().get_repo(repo_name), name)
    except Exception as e:
        return {'exists': '0', 'sha': '', 'message': f'ветку {name} не спросить: {e}'}

    if not found:
        return {'exists': '0', 'sha': '', 'message': f'ветки {name} в репозитории нет'}

    return {'exists': '1', 'sha': str(found.commit.sha), 'message': f'ветка {name} есть'}


async def github_merge_branch_ensure(repo_full_name: str, branch: str,
                                     branch_base: str) -> dict:
    """
    Заводит ветку branch от ветки branch_base, если её ещё нет на GitHub.

    Нужна там, где работу нескольких веток сводят в одну перед merge request: слить
    пять веток подзадач в master пятью запросами нельзя - merge request нужен один,
    и ему нужна одна ветка-источник.

    Существующую ветку не трогает и не двигает: повторный вызов безопасен.

    Args:
        repo_full_name (str): полное имя репозитория, например vskuba/rhapsodyai.
        branch (str): имя заводимой ветки.
        branch_base (str): от какой ветки её отвести, обычно master.

    Returns:
        dict: Словарь с результатом, содержащий:
            ready (str): '1' - ветка есть и с ней можно работать, '0' - нет.
            created (str): '1' - ветку завели сейчас, '0' - она уже была.
            sha (str): хеш коммита, на котором стоит ветка.
            message (str): та же новость словами, для человека и журнала.
    """
    name, base = str(branch or '').strip(), str(branch_base or '').strip()
    repo_name = str(repo_full_name or '').strip()
    if not repo_name or not name or not base:
        return {'ready': '0', 'created': '0', 'sha': '',
                'message': 'не хватает адреса: нужны имя репозитория и обе ветки'}

    try:
        repo = _github_auth().get_repo(repo_name)
        existing = _branch_find(repo, name)
        if existing:
            return {'ready': '1', 'created': '0', 'sha': str(existing.commit.sha),
                    'message': f'ветка {name} уже есть'}

        sha = repo.get_branch(base).commit.sha
        repo.create_git_ref(ref=f'refs/heads/{name}', sha=sha)
    except GithubException as e:
        return {'ready': '0', 'created': '0', 'sha': '',
                'message': f'ветка {name} не заведена: {_github_message(e)}'}
    except Exception as e:
        return {'ready': '0', 'created': '0', 'sha': '',
                'message': f'ветка {name} не заведена: {e}'}

    return {'ready': '1', 'created': '1', 'sha': str(sha),
            'message': f'ветка {name} заведена от {base}'}


async def github_merge_request_create(repo_full_name: str, branch_head: str,
                                      branch_base: str, title: str = '',
                                      body: str = '') -> dict:
    """
    Заводит merge request из ветки branch_head в ветку branch_base на GitHub.

    Открытый на эти же ветки merge request вторым не заводится: возвращается адрес
    существующего. Так шаг можно повторять, не плодя дубликатов.

    Args:
        repo_full_name (str): полное имя репозитория, например vskuba/rhapsodyai.
        branch_head (str): ветка с работой, из которой просят слияние.
        branch_base (str): ветка, в которую просят слить, обычно master.
        title (str): заголовок; пусто - составится из имён веток.
        body (str): описание; пусто - останется пустым.

    Returns:
        dict: Словарь с результатом, содержащий:
            created (str): '1' - merge request заведён или уже был, '0' - нет.
            existed (str): '1' - merge request на эти ветки уже был открыт.
            number (str): номер merge request; пустая строка, если его нет.
            url (str): адрес merge request для человека.
            message (str): та же новость словами, для человека и журнала.
    """
    head, base = str(branch_head or '').strip(), str(branch_base or '').strip()
    repo_name = str(repo_full_name or '').strip()
    result = {'created': '0', 'existed': '0', 'number': '', 'url': '', 'message': ''}
    if not repo_name or not head or not base:
        result['message'] = 'не хватает адреса: нужны имя репозитория и обе ветки'
        return result

    try:
        repo = _github_auth().get_repo(repo_name)
        existing = _pull_open_find(repo, head, base)
        if existing:
            return {'created': '1', 'existed': '1', 'number': str(existing.number),
                    'url': str(existing.html_url),
                    'message': f'merge request №{existing.number} на {head} уже открыт'}

        pull = repo.create_pull(base=base, head=head,
                                title=title or f'{head} -> {base}', body=body or '')
    except GithubException as e:
        result['message'] = f'merge request не заведён: {_github_message(e)}'
        return result
    except Exception as e:
        result['message'] = f'merge request не заведён: {e}'
        return result

    return {'created': '1', 'existed': '0', 'number': str(pull.number),
            'url': str(pull.html_url),
            'message': f'merge request №{pull.number} заведён: {head} -> {base}'}


def _result(merged: str = '0', conflict: str = '0', already: str = '0', sha: str = '',
            url: str = '', message: str = '') -> dict:
    """Ответ `github_merge_branch` в одном месте: полей шесть, и они всегда все."""
    return {'merged': merged, 'conflict': conflict, 'already': already,
            'sha': sha, 'url': url, 'message': message}


def _compare_url(repo_full_name: str, branch_head: str, branch_base: str) -> str:
    """
    Адрес сравнения веток — по нему человек разбирает конфликт.

    Отдаём его при любом исходе, а не только при конфликте: посмотреть, что именно
    вливалось, бывает нужно и после удачного слияния.
    """
    if not repo_full_name or not branch_head or not branch_base:
        return ''

    return f'https://github.com/{repo_full_name}/compare/{branch_base}...{branch_head}'


def _github_error(result: dict, error: GithubException, head: str, base: str) -> dict:
    """Ответ GitHub на неудачу — в поля результата. Конфликт от поломки отличается."""
    if error.status == GITHUB_MERGE_STATUS_CONFLICT:
        result['conflict'] = '1'
        result['message'] = (f'конфликт: {head} не сливается с {base} сама — '
                             f'расхождение разбирает человек: {result["url"]}')
        return result

    if error.status == GITHUB_MERGE_STATUS_MISSING:
        result['message'] = f'не найдено: репозиторий или одна из веток ({head}, {base})'
        return result

    result['message'] = f'GitHub отказал: {_github_message(error)}'

    return result


def _branch_find(repo, branch: str):
    """Ветка репозитория или None. Отсутствие — не ошибка, а ответ на вопрос."""
    try:
        return repo.get_branch(branch)
    except GithubException:
        return None


def _pull_open_find(repo, branch_head: str, branch_base: str):
    """
    Открытый merge request на эту пару веток или None.

    Ищем по `head` в формате `владелец:ветка` — так требует GitHub, и без владельца
    фильтр молча возвращает пустоту.
    """
    owner = str(repo.full_name).split('/')[0]
    for pull in repo.get_pulls(state='open', base=branch_base, head=f'{owner}:{branch_head}'):
        return pull

    return None


def _github_message(error: GithubException) -> str:
    """Текст ошибки GitHub. Данные бывают не словарём — тогда берём как есть."""
    data = getattr(error, 'data', None)
    if isinstance(data, dict) and data.get('message'):
        return str(data['message'])

    return str(error)

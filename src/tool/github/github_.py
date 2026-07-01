import webbrowser
import os
from typing import List
from github import BadCredentialsException, Auth, Github, GithubException
from github.Commit import Commit

github_: Github | None = None


def _github_auth() -> Github:
    """
    Performs authorization on GitHub. The function returns a GitHub object for operation.
    """
    try:
        global github_
        if github_:
            return github_

        auth = Auth.Token(os.getenv('GITHUB_TOKEN'))
        github_ = Github(auth=auth)

        # Проверка "на вшивость": пробуем получить логин
        # Если токен битый, вылетит ошибка здесь
        user_login = github_.get_user().login
        print(f"✅ Робот авторизован как: {user_login}")

        return github_

    except BadCredentialsException:
        print("❌ Ошибка: Неверный GitHub токен!")
        raise
    except Exception as e:
        print(f"❌ Робот не смог подключиться: {e}")
        raise


async def github_repository_list(org: str | None = None) -> List[str]:
    """
    The function returns a list of the user's GitHub repositories as an array of names.
    If this is an organization, the argument specifies the organization name.
    Arguments 'org' - organization name
    """
    g = _github_auth()

    try:
        if org:
            organization = g.get_organization(org)
            repos = [repo.full_name for repo in organization.get_repos()]
        else:
            user = g.get_user()
            my_login = user.login
            repos = [repo.full_name for repo in g.get_user(my_login).get_repos()]

        return repos
    except Exception as e:
        return [f"Ошибка при получении списка: {str(e)}"]


async def github_search_branch_with_last_commit(repo_full_name: str) -> str | None:
    """
    The function returns the name of the branch containing the latest commit.
    The 'repo_full_name' argument is the full name of the repository.
    """
    g = _github_auth()

    try:
        repo = g.get_repo(repo_full_name)
        # Получаем только последнее событие пуша
        events = repo.get_events()
        for event in events:
            if event.type == "PushEvent":
                # ref имеет формат 'refs/heads/branch_name'
                branch_name = event.payload['ref'].replace('refs/heads/', '')
                return branch_name

        # Если событий пуша нет, возвращаем дефолтную ветку
        return repo.default_branch
    except Exception as e:
        print(f"Ошибка: {e}")
        return None


async def github_search_repo_by_last_commit() -> str | None:
    """
    This function returns the full name of the repository.
    It identifies the repository based on its most recent active commits.
    The name of the repository with the most recent commits is returned.
    This function does not accept any arguments. The authorized user is used.
    """
    g = _github_auth()
    user = g.get_user()

    repos = user.get_repos(sort='pushed', direction='desc')

    for repo in repos:
        return repo.full_name

    return None


async def github_get_branch_last_commit(repo_full_name: str, branch_name: str) -> Commit | None:
    """
    The function returns the latest commit in a branch. The function arguments are the full repository name and the branch name.
    The arguments 'repo_full_name' are the full repository name, and 'branch_name' is the name of the branch being merged.
    """
    g = _github_auth()

    return g.get_repo(repo_full_name).get_branch(branch_name).commit


async def github_check_and_merge_url_get(repo_full_name: str, branch_head: str, branch_base: str) -> str:
    """
    The function makes a merge request for two branches in a repository.
    Arguments:
    'repo_full_name' - the full name of the repository
    'branch_head' - the name of the branch being merged
    'branch_base' - the name of the branch being merged
    If the merge request is not possible due to a conflict,
    the function returns a link for manual conflict resolution.
    If the merge request is possible, it makes the merge request and notifies of a successful result.
    """

    return f"https://github.com/{repo_full_name}/compare/{branch_base}...{branch_head}"


async def github_check_and_merge(repo_full_name: str, branch_head: str, branch_base: str) -> str:
    """
    The function makes a merge request for two branches in a repository.
    Arguments:
    'repo_full_name' - the full name of the repository
    'branch_head' - the name of the branch being merged
    'branch_base' - the name of the branch being merged.
    If the merge request is not possible due to a conflict, the function returns a link for
    manual conflict resolution. If the merge request is possible, it makes the merge request and notifies of a successful
    result.
    """
    g = _github_auth()

    try:
        repo = g.get_repo(repo_full_name)

        # Пытаемся выполнить мердж
        merge_commit = repo.merge(
            base=branch_base,
            head=branch_head,
            commit_message=f"Auto-merge {branch_head} into {branch_base}"
        )

        if merge_commit is None:
            return f"Инфо: Ветка {branch_head} уже находится в ветке {branch_base}, слияние не требуется."

        return f"Успешно: Ветка {branch_head} влита в {branch_base}. SHA: {merge_commit.sha}"

    except GithubException as e:
        # Код 409 означает конфликт слияния
        if e.status == 409:
            conflict_url = f"https://github.com/{repo_full_name}/compare/{branch_base}...{branch_head}"
            webbrowser.open(conflict_url)

            return f"Конфликт: Мердж невозможен. Решите конфликты вручную: {conflict_url}"

        # Код 404 если ветки не найдены
        if e.status == 404:
            return "Ошибка: Одна из веток или репозиторий не найдены."

        return f"Ошибка GitHub API: {e.data.get('message', str(e))}"

    except Exception as e:
        return f"Непредвиденная ошибка: {e}"

async def github_user_info(random: int = 2) -> dict:
    """
    This function returns the full name of the repository.
    It identifies the repository based on its most recent active commits.
    The name of the repository with the most recent commits is returned.
    Returns:
        A dictionary containing the user's GitHub login, name, and email.
        login (str): The GitHub username of the authenticated user.
        name (str): The full name of the authenticated user.
        email (str): The email address associated with the authenticated user's GitHub account.
    """
    g = _github_auth()
    user = g.get_user()

    return {
        "login": user.login,
        "name": user.name,
        "email": user.email,
    }

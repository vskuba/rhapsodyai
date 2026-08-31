"""
Подтягивание каталога задачи к главной ветке (`task_worktree_refresh`).

Зачем оно есть. Каталог режется от master один раз и дальше стоит на месте. Для
подзадачи это верно — её работа привязана к состоянию среза. Для менеджера нет: он
планирует по коду, и вчерашний срез даёт план, разошедшийся с действительностью ещё до
начала работы. Живьём каталог задачи #4798 отстал от master на два коммита за сутки.

Главное здесь — не то, что функция подтягивает, а то, чего она **не** трогает. Она
работает без человека, на каждом круге менеджера, и цена ошибки несимметрична: не
подтянутый каталог даёт устаревшую разведку, а подтянутый силой уносит работу.

Отсюда два охранных правила, и оба проверяются: каталог с несохранёнными правками не
трогаем, ветку со своими коммитами не трогаем тоже — сливать чужую работу молча, без
человека, мы не вправе.

Тесты заводят настоящий git-репозиторий во временном каталоге: функция разговаривает с
git, и подменять его значило бы проверять заглушку.
"""

import os
import subprocess

import pytest

pytestmark = pytest.mark.pipeline


@pytest.fixture
def repo(tmp_path):
    """Репозиторий с главной веткой и одним коммитом — от него отходят ветки задач."""
    path = tmp_path / 'repo'
    path.mkdir()
    _git(path, 'init', '-b', 'master')
    _git(path, 'config', 'user.email', 'test@local')
    _git(path, 'config', 'user.name', 'test')
    (path / 'readme.md').write_text('исходный\n')
    _git(path, 'add', '.')
    _git(path, 'commit', '-m', 'первый')

    return path


class TestRefresh:
    """Что функция подтягивает."""

    async def test_behind_base_is_fast_forwarded(self, repo):
        """
        Каталог отстал от master — догоняет. Это и есть рабочий случай: менеджер
        должен планировать по нынешнему коду, а не по тому, что было при срезе.
        """
        from src.project.task.task_worktree import task_worktree_refresh

        path = _worktree_add(repo, 101)
        _master_commit(repo, 'новое в master')

        result = await task_worktree_refresh(str(repo), 101)

        assert 'подтянут' in result
        assert _head(path) == _head(repo), 'каталог должен встать на вершину master'

    async def test_already_current_is_not_an_error(self, repo):
        """Подтягивать нечего — это норма, а не сбой: круги идут один за другим."""
        from src.project.task.task_worktree import task_worktree_refresh

        _worktree_add(repo, 102)

        assert 'подтянут' in await task_worktree_refresh(str(repo), 102)

    async def test_missing_worktree_is_reported(self, repo):
        """Каталога нет — говорим словами, а не падаем: круг из-за этого не рушится."""
        from src.project.task.task_worktree import task_worktree_refresh

        assert await task_worktree_refresh(str(repo), 999) == 'каталога нет'


class TestKeeps:
    """Чего функция не трогает — здесь цена ошибки выше."""

    async def test_dirty_worktree_untouched(self, repo):
        """
        Несохранённые правки — стоп до всякого git. Перемотка поверх них либо
        оборвётся, либо перезапишет; ни того, ни другого без человека делать нельзя.
        """
        from src.project.task.task_worktree import task_worktree_refresh

        path = _worktree_add(repo, 103)
        before = _head(path)
        _master_commit(repo, 'новое в master')
        (path / 'readme.md').write_text('правка, которую никто не коммитил\n')

        result = await task_worktree_refresh(str(repo), 103)

        assert 'несохранённые правки' in result
        assert _head(path) == before, 'каталог не должен сдвинуться'

    async def test_branch_with_own_commits_untouched(self, repo):
        """
        В ветке своя работа — перемотка не проходит, и это верный исход. Слияние
        чужой работы молча, без человека, здесь недопустимо: у подзадачи в ветке
        лежит всё, что она сделала.
        """
        from src.project.task.task_worktree import task_worktree_refresh

        path = _worktree_add(repo, 104, commit='работа подзадачи')
        before = _head(path)
        _master_commit(repo, 'новое в master')

        result = await task_worktree_refresh(str(repo), 104)

        assert 'не подтянут' in result
        assert _head(path) == before
        assert 'работа подзадачи' in _git(path, 'log', '--oneline').stdout


def _git(cwd, *args) -> subprocess.CompletedProcess:
    """git в каталоге — синхронно: фикстуры готовят репозиторий, а не проверяют его."""
    return subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True)


def _head(path) -> str:
    return _git(path, 'rev-parse', 'HEAD').stdout.strip()


def _master_commit(repo, text: str) -> None:
    """Коммит в master основного чекаута — от него каталог и отстаёт."""
    (repo / f'{text}.txt').write_text(text + '\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-m', text)


def _worktree_add(repo, subtask_id: int, commit: str = ''):
    """Каталог задачи со своей веткой; `commit` — что положить в ветку сверх master."""
    path = repo / '.claude' / 'worktrees' / f'feature_task_{subtask_id}'
    _git(repo, 'worktree', 'add', '-b', f'feature/task_{subtask_id}', str(path))
    if commit:
        (path / 'work.txt').write_text(commit + '\n')
        _git(path, 'add', '.')
        _git(path, 'commit', '-m', commit)

    return path


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

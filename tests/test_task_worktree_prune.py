"""
Уборка каталогов подзадач: что снимается само, а что остаётся человеку.

Главное здесь — не то, что уборщик сносит, а то, чего он **не** сносит. Он работает
без человека, на каждом тике, и цена ошибки несимметрична: не снятый каталог заметят и
уберут руками, снятый по ошибке уносит работу, которой больше нигде нет.

Отсюда два правила, и оба проверяются:

* каталог задачи, которая ещё в работе, не трогаем — круг мог оборваться и
  продолжиться следующим тиком, а каталог его рабочее место;
* каталог с несохранёнными правками не трогаем никогда, даже если задача закрыта.

И одно свойство, ради которого уборка вообще безопасна: **ветку не удаляем**. Всё,
что задача сделала, остаётся в ней, а по ней работают и просмотр диффа, и слияние.

Тесты заводят настоящий git-репозиторий во временном каталоге: `task_worktree_prune`
разговаривает с git, и подменять его значило бы проверять заглушку.
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


class TestRemoves:
    """Что уборщик снимает."""

    async def test_removes_directory_of_deleted_task(self, repo):
        """
        Строки задачи нет — каталог не принадлежит никому и показать его негде:
        страница задач строится от списка задач.
        """
        from src.project.task.task_worktree import task_worktree_prune

        _worktree_add(repo, 101)

        result = await task_worktree_prune(str(repo), {})

        assert result['removed'] == [101]
        assert not os.path.isdir(_dir(repo, 101))

    async def test_removes_closed_task_with_merged_branch(self, repo):
        """Задача закрыта и ветка в главной — в каталоге нет ничего своего."""
        from src.project.task.task_worktree import task_worktree_prune

        _worktree_add(repo, 102, commit='работа')
        _git(repo, 'merge', '--no-ff', '-m', 'влито', 'feature/task_102')

        result = await task_worktree_prune(str(repo), {102: 'done'})

        assert result['removed'] == [102]

    async def test_branch_survives_removal(self, repo):
        """
        Ветку не удаляем никогда — по ней работают и просмотр диффа, и слияние. Это
        то свойство, из-за которого уборку вообще можно доверить машине.
        """
        from src.project.task.task_worktree import task_worktree_prune

        _worktree_add(repo, 103, commit='работа')

        await task_worktree_prune(str(repo), {})

        assert _git(repo, 'rev-parse', '--verify', 'feature/task_103').returncode == 0

    async def test_service_directory_untouched(self, repo):
        """
        Рядом лежит служебный `_merge`, заведённый слиянием. Разбор имени должен
        отличать его от подзадачи, иначе уборщик снёс бы чужое.
        """
        from src.project.task.task_worktree import task_worktree_prune

        base = repo / '.claude' / 'worktrees'
        base.mkdir(parents=True, exist_ok=True)
        (base / '_merge').mkdir()

        result = await task_worktree_prune(str(repo), {})

        assert result['removed'] == []
        assert (base / '_merge').is_dir()


class TestKeeps:
    """Чего уборщик не трогает — здесь цена ошибки выше."""

    async def test_keeps_task_in_progress(self, repo):
        """
        Круг мог оборваться и продолжиться следующим тиком: каталог — его рабочее
        место, и снять его значило бы уронить работу на ровном месте.
        """
        from src.project.task.task_worktree import task_worktree_prune

        _worktree_add(repo, 104)

        result = await task_worktree_prune(str(repo), {104: 'developing'})

        assert result['removed'] == []
        assert os.path.isdir(_dir(repo, 104))
        assert 'developing' in result['kept'][0]['why']

    async def test_keeps_closed_task_with_unmerged_branch(self, repo):
        """Закрыта, но не влита — работу ещё будут смотреть и вливать."""
        from src.project.task.task_worktree import task_worktree_prune

        _worktree_add(repo, 105, commit='работа')

        result = await task_worktree_prune(str(repo), {105: 'done'})

        assert result['removed'] == []
        assert 'не влита' in result['kept'][0]['why']

    async def test_keeps_dirty_directory(self, repo):
        """
        Несохранённые правки — стоп, даже когда задачи уже нет. Уборщик работает без
        человека, и права стирать незакоммиченную работу у него нет.
        """
        from src.project.task.task_worktree import task_worktree_prune

        _worktree_add(repo, 106)
        (_dir(repo, 106) and open(os.path.join(_dir(repo, 106), 'readme.md'), 'w')
         .write('правка, которую никто не коммитил\n'))

        result = await task_worktree_prune(str(repo), {})

        assert result['removed'] == []
        assert os.path.isdir(_dir(repo, 106))
        assert 'несохранённые' in result['kept'][0]['why']

    async def test_no_worktrees_directory_is_not_an_error(self, tmp_path):
        """Проект, где подзадач не заводили: пустой ответ, а не падение."""
        from src.project.task.task_worktree import task_worktree_prune

        assert await task_worktree_prune(str(tmp_path), {}) == {'removed': [], 'kept': []}


class TestDirName:
    """Разбор имени каталога: по нему решается, наш он или чужой."""

    def test_reads_subtask_number(self):
        from src.project.task.task_worktree import _dir_task_id

        assert _dir_task_id('feature_task_2437') == 2437

    def test_service_and_foreign_names_give_zero(self):
        """Ноль означает «не трогать»: `_merge` — служебный каталог слияния."""
        from src.project.task.task_worktree import _dir_task_id

        assert _dir_task_id('_merge') == 0
        assert _dir_task_id('feature_task_') == 0
        assert _dir_task_id('feature_task_abc') == 0
        assert _dir_task_id('что-то_чужое') == 0


def _git(cwd, *args) -> subprocess.CompletedProcess:
    """git в каталоге — синхронно: фикстуры готовят репозиторий, а не проверяют его."""
    return subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True)


def _dir(repo, subtask_id: int) -> str:
    return str(repo / '.claude' / 'worktrees' / f'feature_task_{subtask_id}')


def _worktree_add(repo, subtask_id: int, commit: str = '') -> str:
    """Каталог подзадачи со своей веткой; `commit` — что в неё положить."""
    path = _dir(repo, subtask_id)
    _git(repo, 'worktree', 'add', '-b', f'feature/task_{subtask_id}', path)
    if commit:
        with open(os.path.join(path, 'work.txt'), 'w') as fh:
            fh.write(commit + '\n')
        _git(path, 'add', '.')
        _git(path, 'commit', '-m', commit)

    return path


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

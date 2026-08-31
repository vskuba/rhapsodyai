"""
Каталоги подзадач — `src/project/task/task_worktree.py`.

Проверяется распознавание остатков и защита рекурсивного сноса. Поймано живьём
после сброса плана #1027: `git worktree remove` снял записи реестра и файлы, но
каталоги оставил — внутри лежал `__pycache__`, записанный из контейнера от root, и
удалить его владелец каталога не мог.

Дальше остаток вёл себя хуже, чем просто мусор. Своего `.git` у него нет, git ищет
репозиторий вверх по дереву и находит основной чекаут — `git status` в остатке
отвечал перечнем правок человека в корне проекта. Конвейер читал это как
«в подзадаче несохранённая работа» и каталог не снимал никогда.

Отсюда два предмета проверки: остаток должен опознаваться по файловой системе, а
не по ответу git, и рекурсивный снос должен отказываться от всего, что не является
каталогом подзадачи, — команда идёт от root.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает
`MYSQL_HOST` на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

pytestmark = pytest.mark.pipeline
def _worktree_dir(tmp_path, subtask_id=1028):
    """Пустой каталог подзадачи по тому же адресу, что строит `task_worktree_path`."""
    from src.project.task.task_worktree import TASK_WORKTREE_BASE_DIR, TASK_WORKTREE_DIR_TEMPLATE

    path = tmp_path / TASK_WORKTREE_BASE_DIR / TASK_WORKTREE_DIR_TEMPLATE.format(subtask_id=subtask_id)
    path.mkdir(parents=True)

    return path


class TestBrokenWorktree:
    """Что считается остатком снятой копии, а что живой рабочей копией."""

    def test_dir_without_git_marker_is_leftover(self, tmp_path):
        """Огрызок: файлы git снял, папку с чужим байткодом оставил."""
        from src.project.task.task_worktree import _worktree_broken

        path = _worktree_dir(tmp_path)
        (path / '__pycache__').mkdir()

        assert _worktree_broken(str(path)), \
            'без своего .git каталогом управляет уже не git — снимать его должны мы'

    def test_dangling_gitdir_is_leftover(self, tmp_path):
        """Сирота: файл `.git` на месте, служебной папки нет."""
        from src.project.task.task_worktree import _worktree_broken

        path = _worktree_dir(tmp_path)
        (path / '.git').write_text(f'gitdir: {tmp_path}/.git/worktrees/feature_task_1028\n')

        assert _worktree_broken(str(path))

    def test_live_worktree_is_not_touched(self, tmp_path):
        """Живая копия: ссылка ведёт в существующую служебную папку — снимает её git."""
        from src.project.task.task_worktree import _worktree_broken

        path = _worktree_dir(tmp_path)
        gitdir = tmp_path / '.git' / 'worktrees' / 'feature_task_1028'
        gitdir.mkdir(parents=True)
        (path / '.git').write_text(f'gitdir: {gitdir}\n')

        assert not _worktree_broken(str(path))

    def test_plain_repo_is_not_leftover(self, tmp_path):
        """Обычный репозиторий с папкой `.git` остатком не считается."""
        from src.project.task.task_worktree import _worktree_broken

        path = _worktree_dir(tmp_path)
        (path / '.git').mkdir()

        assert not _worktree_broken(str(path))


class TestDropGuard:
    """
    Что разрешено сносить рекурсивно.

    `rm -rf` идёт от root — иначе не убрать `__pycache__`, записанный из
    контейнера. Поэтому проверка пути тут не формальность: ошибка вызывающего не
    должна превращаться в снос чужой папки.
    """

    def test_subtask_dir_allowed(self, tmp_path):
        from src.project.task.task_worktree import _drop_allowed

        assert _drop_allowed(str(_worktree_dir(tmp_path)))

    def test_parent_dirs_refused(self, tmp_path):
        """Ни корень проекта, ни сам `worktrees` сносить нельзя."""
        from src.project.task.task_worktree import TASK_WORKTREE_BASE_DIR, _drop_allowed

        assert not _drop_allowed(str(tmp_path))
        assert not _drop_allowed(str(tmp_path / TASK_WORKTREE_BASE_DIR))
        assert not _drop_allowed('/')

    def test_traversal_refused(self, tmp_path):
        """`..` в середине пути не должен проводить проверку."""
        from src.project.task.task_worktree import _drop_allowed

        assert not _drop_allowed(str(_worktree_dir(tmp_path) / '..' / '..' / '..'))

    def test_foreign_names_refused(self, tmp_path):
        """Каталог слияния и имя не по шаблону — не подзадачи."""
        from src.project.task.task_worktree import (TASK_WORKTREE_BASE_DIR,
                                                    TASK_WORKTREE_MERGE_DIR, _drop_allowed)

        base = tmp_path / TASK_WORKTREE_BASE_DIR
        base.mkdir(parents=True)

        assert not _drop_allowed(str(base / TASK_WORKTREE_MERGE_DIR))
        assert not _drop_allowed(str(base / 'feature_task_abc'))
        assert not _drop_allowed(str(base / 'feature_task_'))

    def test_same_name_outside_worktrees_refused(self, tmp_path):
        """Имя правильное, место чужое — сносить нельзя."""
        from src.project.task.task_worktree import _drop_allowed

        path = tmp_path / 'src' / 'feature_task_1028'
        path.mkdir(parents=True)

        assert not _drop_allowed(str(path))

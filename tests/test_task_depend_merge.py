"""
Слияние кода предшественников в ветку подзадачи — `task_depend_merge_upstream`.

Главное, что здесь проверяется: **конфликт содержимого и «слияние не состоялось» —
разные новости**. Первое означает ошибку разбиения: две подзадачи правят одно место, и
чинит это менеджер переразбиением, а подзадача ждёт человека. Второе — заминка: занят
индекс соседним git-ом, каталог не готов, git не уложился в срок.

Раньше на любой ненулевой код возвращался `conflict`, и подзадачи гасли пачками без
единого вызова разработчика — по заминке, которую никто не видел: текст ошибки git
оставался внутри и в отчёт не попадал. Живьём #6440 блокировалась «конфликтом с
предшественником» при том, что то же слияние руками проходило чисто.

Git здесь не запускается: подменяем `task_worktree_git` и проверяем разбор его ответа —
именно в нём была ошибка. Как git ведёт себя на самом деле, проверять этим тестом
бессмысленно, а поднимать репозиторий ради разбора строки — дорого.
"""

import pytest

pytestmark = pytest.mark.pipeline

# Ответ git на конфликт содержимого: он всегда называет файлы словом CONFLICT.
GIT_CONFLICT_OUT = (
    'Auto-merging .claude/docs/testing.md\n'
    'CONFLICT (content): Merge conflict in .claude/docs/testing.md\n'
    'Automatic merge failed; fix conflicts and then commit the result.')

# Ответ git на заминку: слияние даже не начиналось.
GIT_BUSY_OUT = ("fatal: Unable to create '/repo/.git/index.lock': File exists.\n"
                'Another git process seems to be running in this repository.')


@pytest.fixture
def worktree(tmp_path, monkeypatch):
    """Каталог подзадачи #77 на диске и подменённые зависимости — без git и без базы."""
    from src.project.task import task_depend, task_worktree

    path = tmp_path / '.claude' / 'worktrees' / 'feature_task_77'
    path.mkdir(parents=True)

    async def _depends_on(ids):
        return {77: [55]}

    monkeypatch.setattr(task_depend, 'task_depend_of', _depends_on)

    return {'repo': str(tmp_path), 'task_worktree': task_worktree}


def _git_stub(monkeypatch, task_worktree, merge_code: int, merge_out: str):
    """
    Подменить git: ветка предшественника есть, слияние отвечает заданным.

    `merge` ищем в аргументах, а не первым: перед ним идёт подпись коммитера
    (`-c user.name=... -c user.email=...`), без которой git отказывается коммитить
    слияние вовсе. Привяжись проверка к первому аргументу — тест молча перестал бы
    видеть слияние, как только подпись появилась.
    """
    async def _run(cwd, *args):
        if 'rev-parse' in args:
            return 0, ''
        if 'merge' in args and '--abort' not in args:
            return merge_code, merge_out
        return 0, ''

    monkeypatch.setattr(task_worktree, 'task_worktree_git', _run)


class TestClassification:
    """Что именно вернулось: ошибка разбиения или заминка."""

    async def test_content_conflict_is_a_conflict(self, worktree, monkeypatch):
        from src.project.task.task_depend import task_depend_merge_upstream

        _git_stub(monkeypatch, worktree['task_worktree'], 1, GIT_CONFLICT_OUT)
        result = await task_depend_merge_upstream(worktree['repo'], 77)

        assert result['conflict'] == 'feature/task_55'
        assert result['failed'] == ''
        assert 'CONFLICT' in result['error'], 'текст git не дошёл до отчёта'

    async def test_busy_index_is_not_a_conflict(self, worktree, monkeypatch):
        """
        Занят индекс — работы не было, и глушить подзадачу не за что.

        Тот самый случай, из-за которого подзадачи гасли одна за другой без вызова
        разработчика.
        """
        from src.project.task.task_depend import task_depend_merge_upstream

        _git_stub(monkeypatch, worktree['task_worktree'], 128, GIT_BUSY_OUT)
        result = await task_depend_merge_upstream(worktree['repo'], 77)

        assert result['conflict'] == '', 'заминку git приняли за конфликт разбиения'
        assert result['failed'] == 'feature/task_55'
        assert 'index.lock' in result['error']

    async def test_clean_merge_reports_neither(self, worktree, monkeypatch):
        from src.project.task.task_depend import task_depend_merge_upstream

        _git_stub(monkeypatch, worktree['task_worktree'], 0, '')
        result = await task_depend_merge_upstream(worktree['repo'], 77)

        assert result['merged'] == ['feature/task_55']
        assert result['conflict'] == ''
        assert result['failed'] == ''


class TestIdentity:
    """Коммит слияния подписывается — иначе git не даст его создать."""

    async def test_merge_is_signed(self, worktree, monkeypatch):
        """
        Живая поломка: в контейнере воркера `HOME` уведён в `/tmp`, `.gitconfig` там нет,
        и git отвечает «Committer identity unknown». Слияние в главную ветку подпись
        ставило, а слияние предшественника — нет, и падало на каждой подзадаче с
        зависимостью. Падение читалось как конфликт разбиения, и подзадачи гасли одна за
        другой, ни разу не позвав разработчика.
        """
        from src.project.task.task_depend import task_depend_merge_upstream

        seen = []

        async def _run(cwd, *args):
            if 'rev-parse' in args:
                return 0, ''
            # Автор в репозитории не настроен — так и в контейнере воркера.
            if 'config' in args:
                return 1, ''
            if 'merge' in args:
                seen.append(args)
            return 0, ''

        monkeypatch.setattr(worktree['task_worktree'], 'task_worktree_git', _run)
        await task_depend_merge_upstream(worktree['repo'], 77)

        assert seen, 'слияние не звалось вовсе'
        assert '-c' in seen[0], 'коммит слияния идёт без подписи — git его не создаст'
        assert any(str(a).startswith('user.email=') for a in seen[0])


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

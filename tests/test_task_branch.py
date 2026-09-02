"""
Ветка задачи как место сборки работы подзадач — `task_branch`.

Главное, что здесь проверяется: **работа течёт через ветку задачи в обе стороны**.
Подзадача берётся в работу — ветка задачи вливается в неё; подзадача прошла QA —
вливается обратно. Из этого следует всё остальное: подзадача видит принятое соседями с
первой минуты круга, конфликт вылезает на входе, а к закрытию задачи ветка уже собрана и
merge request открывается как есть.

Прежний порядок стоил задачи #4915. Ветки подзадач резались от главной и о соседях не
знали, а сборка шла в самом конце, в отдельной ветке от **свежей** главной — первая же
подзадача, отрезанная от старой, не сошлась. Четыре принятых подзадачи остались без
merge request.

Git здесь настоящий: проверяется поведение слияний, а его на заглушках не проверить.
Репозиторий одноразовый, живёт в `tmp_path` и уносится вместе с ним.
"""

import subprocess

import pytest

pytestmark = pytest.mark.pipeline

# Номера выдуманные: в базу они не идут, нужны только для имён веток и каталогов.
TASK_ID = 900001
SUB_A = 900002
SUB_B = 900003


def _git(cwd, *args):
    """git в репозитории теста. Падает громко: молчаливый сбой сделал бы тест ложным."""
    return subprocess.run(('git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args),
                          cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    """Репозиторий с главной веткой и одним файлом на каждую будущую подзадачу."""
    _git(tmp_path, 'init', '-q', '-b', 'master')
    (tmp_path / 'shared.txt').write_text('общая строка\n', encoding='utf-8')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, 'commit', '-qm', 'начало')

    # Ветка задачи — та, что заводит менеджер при планировании.
    _git(tmp_path, 'branch', f'feature/task_{TASK_ID}')

    return tmp_path


def _commit_on(repo, branch, name, text):
    """Ветка с одним коммитом: правит свой файл, общего не трогает."""
    _git(repo, 'branch', '-f', branch, f'feature/task_{TASK_ID}')
    _git(repo, 'worktree', 'add', '-q', str(repo / f'wt_{name}'), branch)
    (repo / f'wt_{name}' / f'{name}.txt').write_text(text, encoding='utf-8')
    _git(repo / f'wt_{name}', 'add', '.')
    _git(repo / f'wt_{name}', 'commit', '-qm', f'работа {name}')
    _git(repo, 'worktree', 'remove', '--force', str(repo / f'wt_{name}'))


class TestPushAfterQa:
    """Принятая подзадача уезжает в ветку задачи."""

    async def test_accepted_work_lands_in_task_branch(self, repo):
        from src.project.task.task_branch import task_branch_push

        _commit_on(repo, f'feature/task_{SUB_A}', 'a', 'работа A\n')
        result = await task_branch_push(str(repo), SUB_A, TASK_ID)

        assert result['ok'], result
        assert result['merged'] == f'feature/task_{SUB_A}'
        files = _git(repo, 'ls-tree', '--name-only', f'feature/task_{TASK_ID}').stdout

        assert 'a.txt' in files, 'работа подзадачи не дошла до ветки задачи'

    async def test_missing_branch_is_not_an_error(self, repo):
        """
        Ветки подзадачи нет вовсе — так закрывается `no_code_for_testing`.

        Работа была уже в главной, вливать нечего, и жаловаться не на что.
        """
        from src.project.task.task_branch import task_branch_push

        result = await task_branch_push(str(repo), SUB_B, TASK_ID)

        assert result['ok']
        assert result['merged'] == ''


class TestPullBeforeRound:
    """Подзадача начинает круг, видя принятое соседями."""

    async def test_neighbour_work_is_visible(self, repo):
        """
        Ради этого всё и делается: A принята, B берётся в работу и видит код A.

        Раньше B узнала бы о работе A только на сборке в конце задачи — а до тех пор
        писала бы поверх пустого места.
        """
        from src.project.task.task_branch import task_branch_pull, task_branch_push

        _commit_on(repo, f'feature/task_{SUB_A}', 'a', 'работа A\n')
        _commit_on(repo, f'feature/task_{SUB_B}', 'b', 'работа B\n')
        await task_branch_push(str(repo), SUB_A, TASK_ID)

        result = await task_branch_pull(str(repo), SUB_B, TASK_ID)

        assert result['ok'], result
        files = _git(repo, 'ls-tree', '--name-only', f'feature/task_{SUB_B}').stdout

        assert 'a.txt' in files, 'подзадача не увидела работу соседа'
        assert 'b.txt' in files, 'своя работа потерялась'

    async def test_without_task_branch_nothing_happens(self, repo):
        """
        Ветки задачи нет — план разобран до появления правила, и это не повод падать.

        Круг просто идёт как раньше, от того среза, на котором стоит.
        """
        from src.project.task.task_branch import task_branch_pull

        _commit_on(repo, f'feature/task_{SUB_A}', 'a', 'работа A\n')
        result = await task_branch_pull(str(repo), SUB_A, 0)

        assert result['ok']
        assert result['merged'] == ''


class TestConflict:
    """Столкновение не разрешаем и не прячем."""

    async def test_same_line_gives_conflict(self, repo):
        """
        Две подзадачи правят одну строку — это ошибка разбиения, и её видно сразу.

        Именно ради «сразу» слияние и перенесено в начало круга: на сборке в конце
        задачи о том же узнавали через сутки.
        """
        from src.project.task.task_branch import task_branch_pull, task_branch_push

        _commit_on(repo, f'feature/task_{SUB_A}', 'a', 'работа A\n')
        _commit_on(repo, f'feature/task_{SUB_B}', 'b', 'работа B\n')
        for name, sub in (('a', SUB_A), ('b', SUB_B)):
            _git(repo, 'worktree', 'add', '-q', str(repo / f'edit_{name}'),
                 f'feature/task_{sub}')
            (repo / f'edit_{name}' / 'shared.txt').write_text(f'строка {name}\n',
                                                              encoding='utf-8')
            _git(repo / f'edit_{name}', 'add', '.')
            _git(repo / f'edit_{name}', 'commit', '-qm', f'{name} правит общее')
            _git(repo, 'worktree', 'remove', '--force', str(repo / f'edit_{name}'))

        await task_branch_push(str(repo), SUB_A, TASK_ID)
        result = await task_branch_pull(str(repo), SUB_B, TASK_ID)

        assert not result['ok']
        assert result['conflict'] == f'feature/task_{TASK_ID}'
        assert 'CONFLICT' in result['error']

    async def test_conflict_leaves_the_worktree_clean(self, repo):
        """
        После отката каталог рабочий: круг упрётся в отсутствие кода и скажет об этом,
        а не утонет в конфликтных маркерах посреди файлов.
        """
        from src.project.task.task_branch import task_branch_pull, task_branch_push

        _commit_on(repo, f'feature/task_{SUB_A}', 'a', 'работа A\n')
        _commit_on(repo, f'feature/task_{SUB_B}', 'b', 'работа B\n')
        for name, sub in (('a', SUB_A), ('b', SUB_B)):
            _git(repo, 'worktree', 'add', '-q', str(repo / f'edit_{name}'),
                 f'feature/task_{sub}')
            (repo / f'edit_{name}' / 'shared.txt').write_text(f'строка {name}\n',
                                                              encoding='utf-8')
            _git(repo / f'edit_{name}', 'add', '.')
            _git(repo / f'edit_{name}', 'commit', '-qm', f'{name} правит общее')
            _git(repo, 'worktree', 'remove', '--force', str(repo / f'edit_{name}'))

        await task_branch_push(str(repo), SUB_A, TASK_ID)
        await task_branch_pull(str(repo), SUB_B, TASK_ID)

        path = repo / '.claude' / 'worktrees' / f'feature_task_{SUB_B}'
        status = subprocess.run(('git', 'status', '--porcelain'), cwd=str(path),
                                capture_output=True, text=True).stdout

        assert 'UU' not in status, 'в каталоге остались конфликтные маркеры'


class TestResolveByRole:
    """
    Конфликт между подзадачами разбирает роль, а не человек.

    Параллельные круги внутри задачи конфликты не отменяют, но здесь сталкивается своя
    работа со своей: обе подзадачи делались по одному плану. Звать человека значило бы
    останавливать задачу из-за того, что исполнитель и сам разберёт.

    Агент подставной: проверяется не его сообразительность, а то, что конвейер зовёт
    его с правильными ветками и **верит только делу** — маркеров не осталось, слияние
    закоммичено.
    """

    def _conflicting(self, repo):
        """Две подзадачи, обе правят общую строку. A уже принята в ветку задачи."""
        _commit_on(repo, f'feature/task_{SUB_A}', 'a', 'работа A\n')
        _commit_on(repo, f'feature/task_{SUB_B}', 'b', 'работа B\n')
        for name, sub in (('a', SUB_A), ('b', SUB_B)):
            _git(repo, 'worktree', 'add', '-q', str(repo / f'edit_{name}'), f'feature/task_{sub}')
            (repo / f'edit_{name}' / 'shared.txt').write_text(f'строка {name}\n', encoding='utf-8')
            _git(repo / f'edit_{name}', 'add', '.')
            _git(repo / f'edit_{name}', 'commit', '-qm', f'{name} правит общее')
            _git(repo, 'worktree', 'remove', '--force', str(repo / f'edit_{name}'))

    async def test_agent_resolution_completes_the_merge(self, repo, monkeypatch):
        """Агент свёл файл — слияние доводится до конца, ветка вливается."""
        from src.project.task import task_branch
        from src.project.task.task_branch import task_branch_pull, task_branch_push

        self._conflicting(repo)
        await task_branch_push(str(repo), SUB_A, TASK_ID)
        seen = {}

        async def _agent(prompt, role='', timeout=0, work_dir='', session=''):
            # Агент делает то, что делал бы живой: убирает маркеры и оставляет обе строки.
            seen['prompt'], seen['role'] = prompt, role
            path = repo / '.claude' / 'worktrees' / f'feature_task_{SUB_B}'
            (path / 'shared.txt').write_text('строка a\nстрока b\n', encoding='utf-8')
            return {'status': 'answered', 'response': 'свёл обе строки'}

        monkeypatch.setattr('src.tool.claude_shell.claude_shell.claude_shell_call', _agent)
        result = await task_branch_pull(str(repo), SUB_B, TASK_ID,
                                        role='developer', session='shell-1')

        assert result['ok'], result
        assert result['resolved'] is True
        assert f'feature/task_{TASK_ID}' in seen['prompt'], 'агенту не назвали ветку-источник'
        assert f'feature/task_{SUB_B}' in seen['prompt'], 'агенту не назвали ветку-приёмник'
        assert seen['role'] == 'developer'

    async def test_agent_words_are_not_enough(self, repo, monkeypatch):
        """
        Агент отчитался «разрешил», а маркеры оставил — слияние не засчитывается.

        Это главная защита: агент охотно рапортует об успехе, бросив работу на
        полдороге, и поверив ему, конвейер влил бы в ветку задачи битый файл.
        """
        from src.project.task.task_branch import task_branch_pull, task_branch_push

        self._conflicting(repo)
        await task_branch_push(str(repo), SUB_A, TASK_ID)

        async def _agent(prompt, role='', timeout=0, work_dir='', session=''):
            return {'status': 'answered', 'response': 'конфликт разрешён'}

        monkeypatch.setattr('src.tool.claude_shell.claude_shell.claude_shell_call', _agent)
        result = await task_branch_pull(str(repo), SUB_B, TASK_ID,
                                        role='developer', session='shell-1')

        assert not result['ok']
        assert result['conflict'] == f'feature/task_{TASK_ID}'

    async def test_without_a_shell_nobody_is_called(self, repo, monkeypatch):
        """Оболочки у роли нет — звать некого, откатываемся и зовём человека."""
        from src.project.task.task_branch import task_branch_pull, task_branch_push

        self._conflicting(repo)
        await task_branch_push(str(repo), SUB_A, TASK_ID)
        called = []

        async def _agent(prompt, role='', timeout=0, work_dir='', session=''):
            called.append(prompt)
            return {}

        monkeypatch.setattr('src.tool.claude_shell.claude_shell.claude_shell_call', _agent)
        result = await task_branch_pull(str(repo), SUB_B, TASK_ID)

        assert not result['ok']
        assert result['conflict'] == f'feature/task_{TASK_ID}'
        assert called == [], 'агента позвали, хотя оболочки нет'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

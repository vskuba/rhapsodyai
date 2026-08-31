"""
Пути в плане приводятся к корню репозитория (`task_plan_paths_relative`).

Зачем. План читает исполнитель, а работает он в своей выкладке — отдельном каталоге
репозитория. Абсолютный путь уводит его оттуда: файл ложится в основной чекаут, а
коммит идёт следом за файлом. Так подзадача #4799 попала в главную ветку, и это не было
небрежностью — путь стоял прямо в плане, исполнитель сделал написанное.

Промпт менеджера теперь требует относительных путей, но требование в промпте держится
до первой невнимательности модели. Здесь то же правило делом.

Главное, что проверяется, — не только «абсолютный путь укорачивается», но и **что
функция не портит осмысленный текст**: чужие пути (`/etc/hosts`) не наши, и обрезать их
значило бы сломать план ради формы.
"""

import pytest

pytestmark = pytest.mark.pipeline

REPO = '/home/vasyl/PycharmProjects/RhapsodyAi'


class TestPathsRelative:
    """Что приводится, а что остаётся как есть."""

    def test_checkout_path_becomes_relative(self):
        """Ровно тот случай, что уронил #4799."""
        from src.project.task.task_plan import task_plan_paths_relative

        text = f'- Создать {REPO}/src/project/team/team_session_cleanup.py с функцией'

        assert task_plan_paths_relative(text, REPO) == \
            '- Создать src/project/team/team_session_cleanup.py с функцией'

    def test_worktree_path_becomes_relative(self):
        """
        Путь в выкладку не лучше пути в чекаут: менеджер видит свою (`feature_task_N`),
        а исполнитель работает в другой. Снимается вся приставка, включая номер.
        """
        from src.project.task.task_plan import task_plan_paths_relative

        text = f'Править {REPO}/.claude/worktrees/feature_task_4798/src/a.py'

        assert task_plan_paths_relative(text, REPO) == 'Править src/a.py'

    def test_worktree_prefix_stripped_before_root(self):
        """
        Порядок приставок важен: приставка выкладки длиннее и содержит в себе корень.
        Сними мы корень первым — остался бы бессмысленный хвост
        `.claude/worktrees/feature_task_5/src/a.py`.
        """
        from src.project.task.task_plan import task_plan_paths_relative

        out = task_plan_paths_relative(f'{REPO}/.claude/worktrees/feature_task_5/src/a.py', REPO)

        assert out == 'src/a.py'
        assert 'worktrees' not in out

    def test_foreign_absolute_paths_untouched(self):
        """
        `/etc/hosts` — не про наш репозиторий. Обрезать чужие пути значило бы испортить
        осмысленный текст плана.
        """
        from src.project.task.task_plan import task_plan_paths_relative

        text = 'Смотреть /etc/hosts и /var/log/syslog'

        assert task_plan_paths_relative(text, REPO) == text

    def test_relative_paths_untouched(self):
        """Уже верный план не должен меняться — иначе приведение само себе враг."""
        from src.project.task.task_plan import task_plan_paths_relative

        text = '- Править src/project/team/team_llm_pool.py, функция acquire'

        assert task_plan_paths_relative(text, REPO) == text

    def test_trailing_slash_in_root(self):
        """Корень приходит и со слешем на конце — приставка снимается одинаково."""
        from src.project.task.task_plan import task_plan_paths_relative

        assert task_plan_paths_relative(f'{REPO}/src/a.py', REPO + '/') == 'src/a.py'

    def test_empty_input_is_safe(self):
        """Пустой текст и пустой корень — не повод падать."""
        from src.project.task.task_plan import task_plan_paths_relative

        assert task_plan_paths_relative('', REPO) == ''
        assert task_plan_paths_relative('текст', '') == 'текст'


class TestSerialize:
    """Приведение включается сериализацией — через неё идёт каждая запись плана."""

    def test_plan_text_normalized(self):
        import json

        from src.project.task.task_plan import task_plan_serialize

        out = json.loads(task_plan_serialize(f'Создать {REPO}/src/a.py', [], repo_dir=REPO))

        assert out['plan_text'] == 'Создать src/a.py'

    def test_subtask_plans_normalized(self):
        """
        У подзадач планы свои, и путь чаще всего именно там: шаг разбиения пишет
        «какие файлы трогать». Без обхода подзадач приведение прошло бы мимо главного.
        """
        import json

        from src.project.task.task_plan import task_plan_serialize

        subtasks = [{'title': 'первая', 'plan': f'- Создать {REPO}/src/b.py'}]
        out = json.loads(task_plan_serialize('общий план', subtasks, repo_dir=REPO))

        assert out['subtasks'][0]['plan'] == '- Создать src/b.py'
        assert out['subtasks'][0]['title'] == 'первая', 'прочие поля не трогаем'

    def test_without_repo_dir_nothing_changes(self):
        """
        Без корня не гадаем: у части вызывающих его нет, и решить, что здесь путь
        проекта, а что путь из чужой системы, нечем.
        """
        import json

        from src.project.task.task_plan import task_plan_serialize

        text = f'Создать {REPO}/src/a.py'

        assert json.loads(task_plan_serialize(text, []))['plan_text'] == text

    def test_subtasks_without_plan_survive(self):
        """Подзадача без плана проходит целой, а не превращается в пустую."""
        import json

        from src.project.task.task_plan import task_plan_serialize

        out = json.loads(task_plan_serialize('x', [{'title': 'без плана'}], repo_dir=REPO))

        assert out['subtasks'] == [{'title': 'без плана'}]


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

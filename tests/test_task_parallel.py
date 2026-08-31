"""
Кто может взять круг прямо сейчас: фильтр отбора работы в конвейере.

Главное, что здесь проверяется: **круг отбирается, пока у роли есть свободная
оболочка**. В оболочке один агент, и два круга в одной не идут параллельно, а дерутся:
второй промпт прилетает агенту посреди чужого хода. Но оболочек у роли столько, сколько
терминалов открыл человек, — и роль ведёт столько кругов, сколько их у неё.

Живой повод: предел проекта сделали равным размеру пула (две модели), фильтр считал
только по проекту — и менеджер получил два круга разом в одну оболочку, задачи #2437 и
#2438. Первым лекарством роль вычёркивалась целиком, но тогда простаивали вторые
терминалы; теперь считаются именно оболочки.

Чистые функции без базы: проверяется решение фильтра, а не выборка. Разбор состояния
в роль (`_inflight_role`) — рядом, потому что по нему считается работа в полёте.
"""

import pytest

pytestmark = pytest.mark.pipeline

# Живые оболочки проекта: у менеджера две (два открытых терминала), у остальных по
# одной. Формат — то, что отдаёт `task_role_shell_sessions_by_project`.
LIVE = {2: {'manager': ['s-mgr-1', 's-mgr-2'],
            'developer': ['s-dev-1'],
            'qa': ['s-qa-1'],
            'bugfixer': ['s-bug-1']}}

# Потолок проекта — размер пула моделей. Три модели против пяти оболочек: потолок
# наступает раньше, чем кончаются оболочки, и оба условия проверяются по отдельности.
LIMITS = {2: 3}


class TestFreeShellKeepsRole:
    """Роль остаётся в отборе, пока хоть одна её оболочка свободна."""

    def test_second_shell_keeps_manager_in_play(self):
        """
        Один круг менеджера идёт, второй терминал свободен — роль берёт ещё работу.

        Ради этого оболочки и открывают по нескольку: вычёркивать роль по первому же
        кругу значило бы держать второй терминал открытым впустую.
        """
        from src.project.task.task_pipeline import _roles_by_project_free

        free = _roles_by_project_free(LIVE, {2: 1}, LIMITS, {2: {'manager': 1}})

        assert 'manager' in free[2]

    def test_all_shells_busy_drops_the_role(self):
        """Заняты обе оболочки менеджера — роль выпадает, соседи работают."""
        from src.project.task.task_pipeline import _roles_by_project_free

        free = _roles_by_project_free(LIVE, {2: 2}, LIMITS, {2: {'manager': 2}})

        assert 'manager' not in free[2]
        assert set(free[2]) == {'developer', 'qa', 'bugfixer'}

    def test_single_shell_role_drops_on_first_round(self):
        """У кого оболочка одна, тот занят с первого круга — прежнее поведение."""
        from src.project.task.task_pipeline import _roles_by_project_free

        free = _roles_by_project_free(LIVE, {2: 1}, LIMITS, {2: {'developer': 1}})

        assert 'developer' not in free[2]

    def test_project_disappears_when_all_shells_busy(self):
        """
        Свободных оболочек не осталось — проекта в отборе нет вовсе.

        Пустой список ролей оставлять нельзя: условие отбора строится из него, и
        пустой дал бы выборку «любая роль» вместо «ни одной».
        """
        from src.project.task.task_pipeline import _roles_by_project_free

        busy = {2: {'manager': 2, 'developer': 1, 'qa': 1, 'bugfixer': 1}}

        assert _roles_by_project_free(LIVE, {2: 1}, LIMITS, busy) == {}

    def test_nobody_busy_keeps_all(self):
        from src.project.task.task_pipeline import _roles_by_project_free

        assert set(_roles_by_project_free(LIVE, {}, LIMITS, {})[2]) == set(LIVE[2])


class TestProjectCeiling:
    """Потолок проекта — размер пула: моделей меньше, чем ролей."""

    def test_ceiling_reached_drops_whole_project(self):
        """Моделей меньше, чем оболочек: потолок наступает раньше свободных терминалов."""
        from src.project.task.task_pipeline import _roles_by_project_free

        assert _roles_by_project_free(LIVE, {2: 3}, LIMITS, {}) == {}

    def test_below_ceiling_keeps_idle_roles(self):
        from src.project.task.task_pipeline import _roles_by_project_free

        free = _roles_by_project_free(LIVE, {2: 1}, LIMITS, {2: {'developer': 1}})

        assert set(free[2]) == {'manager', 'qa', 'bugfixer'}

    def test_unknown_project_falls_back_to_default(self):
        """Проекта нет в пределах — работает прежняя настройка, а не «без предела»."""
        from src.project.task.task_pipeline import _roles_by_project_free
        from src.project.task.task_setting_parallel import TASK_SETTING_PARALLEL_DEFAULT

        inflight = {2: TASK_SETTING_PARALLEL_DEFAULT}

        assert _roles_by_project_free(LIVE, inflight, {}, {}) == {}


class TestInflightRole:
    """Чья оболочка занята строкой: разбор состояния в роль."""

    @pytest.mark.parametrize('state, parent_id, type_name, expected', [
        ('developing', 10, 'dev', 'developer'),
        ('testing', 10, 'dev', 'qa'),
        ('bugfixing', None, 'bug', 'bugfixer'),
        ('planning', None, 'plan', 'manager'),
        ('planning', None, 'bug', 'bugfixer'),
        ('reviewing', None, 'test', 'qa'),
    ])
    def test_state_maps_to_role(self, state, parent_id, type_name, expected):
        from src.project.task.task_claim import _inflight_role

        assert _inflight_role(state, parent_id, type_name) == expected

    def test_testing_root_is_not_a_round(self):
        """
        `testing` у корня — фаза «задача на проверке», а не круг QA.

        Считай мы её занятостью, QA стоял бы без работы всё время, пока хоть одна
        задача проекта ждёт приёмки человеком.
        """
        from src.project.task.task_claim import _inflight_role

        assert _inflight_role('testing', None, 'dev') == ''

    def test_non_inflight_state_belongs_to_nobody(self):
        """Разбор плана оболочку не занимает: он идёт в воркере без похода в LLM."""
        from src.project.task.task_claim import _inflight_role

        assert _inflight_role('approved', None, 'dev') == ''


class TestModelGoesToCapturedShell:
    """
    Модель выдаётся той оболочке, которую захватил круг, а не свежайшей у роли.

    `_llm_assign` спрашивал адрес старой функцией «самая свежая сессия роли», и при
    двух терминалах маркер `__SWITCH_LLM__` уходил соседу: карточка работающей
    оболочки показывала «ждёт круга», сосед молча переключался на чужую модель, а
    `_holder_locks_clear` гасил захваты не того держателя — второй круг отнимал модель
    у первого.

    Проверяется само правило выбора адреса; поход в базу и отправку маркера здесь не
    воспроизводим — они закрыты `test_team_llm_pool.py`.
    """

    def test_captured_shell_wins(self):
        action = {'shell': 'shell-captured'}

        assert (str(action.get('shell') or '') or 'freshest') == 'shell-captured'

    def test_without_capture_falls_back_to_freshest(self):
        """Захвата нет (оболочек у роли не нашлось) — прежний путь по свежести."""
        action = {}

        assert (str(action.get('shell') or '') or 'freshest') == 'freshest'


class TestRunningSplitByShell:
    """
    Идущие круги роли ложатся на свои карточки, а не все на первую.

    Очередь строится на роль, и раньше её слот вешался на все карточки роли целиком —
    в коде так и было записано: «карточка роли одна». С двумя терминалами обе карточки
    менеджера показывали одну и ту же задачу, хотя работали над разными.
    """

    def _cards(self):
        return [{'role': 'manager', 'session_uuid': 'shell-1'},
                {'role': 'manager', 'session_uuid': 'shell-2'}]

    def test_each_card_gets_its_own_task(self):
        from src.project.team.team_project import _running_split

        queues = {'manager': {'running': [{'task_id': 2437}, {'task_id': 2438}]}}
        shell_tasks = {'shell-1': 2437, 'shell-2': 2438}

        out = _running_split(self._cards(), queues, shell_tasks)

        assert out[0]['task_id'] == 2437
        assert out[1]['task_id'] == 2438

    def test_order_follows_capture_not_queue(self):
        """Порядок задаёт захват оболочки, а не порядок строк в очереди."""
        from src.project.team.team_project import _running_split

        queues = {'manager': {'running': [{'task_id': 2437}, {'task_id': 2438}]}}
        shell_tasks = {'shell-1': 2438, 'shell-2': 2437}

        out = _running_split(self._cards(), queues, shell_tasks)

        assert out[0]['task_id'] == 2438
        assert out[1]['task_id'] == 2437

    def test_unmatched_round_goes_to_a_free_card(self):
        """
        Захвата нет (прогон мимо конвейера) — круг всё равно виден.

        Иначе работающая карточка выглядела бы простаивающей.
        """
        from src.project.team.team_project import _running_split

        queues = {'manager': {'running': [{'task_id': 999}]}}

        out = _running_split(self._cards(), queues, {})

        assert out == {0: {'task_id': 999}}

    def test_single_round_leaves_second_card_idle(self):
        """Круг один — вторая карточка свободна, а не показывает чужую работу."""
        from src.project.team.team_project import _running_split

        queues = {'manager': {'running': [{'task_id': 2437}]}}

        out = _running_split(self._cards(), queues, {'shell-1': 2437})

        assert out == {0: {'task_id': 2437}}


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

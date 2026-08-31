"""
Возврат вставшей подзадачи менеджеру — `src/project/task/task_goal_replan.py`.

Зачем это вообще. У подзадачи с одной целью нет развилки по охвату: раздробить
единственную цель нечем, а убрать её значит отменить работу. Между тем именно
такие строки встают чаще всего, и причина у них общая — охват задали неподъёмный,
то есть ошиблось планирование, а не исполнение.

Поймано на подзадаче #1628 («порядок функций», 2668 строк контекста): круг прошёл
целиком, сорок минут, отчёт есть — а кода не появилось ни строки. Отвечать там
человеку нечего, и вопрос с кнопками «раздробить/сократить» был бы издевательством.

Отсюда предмет проверки: признак «решать нечего» должен срабатывать ровно на этом
сочетании и ни на каком другом, а возврат — быть одноразовым. Без одноразовости
связка «планирование → тупик → планирование» крутилась бы сама и плодила уровни
вложенности без конца.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает
`MYSQL_HOST` на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

pytestmark = pytest.mark.pipeline
STUCK = {'id': 1628, 'parent_id': 1027, 'pipeline_state': 'failed_qa', 'metadata': '{}'}
ONE_GOAL = [{'text': 'перенести приватные функции вниз', 'done': False}]


class TestReplanNeeded:
    """Когда решать нечего и возврат очевиден."""

    def test_one_goal_and_no_code(self):
        from src.project.task.task_goal_replan import task_goal_replan_needed

        assert task_goal_replan_needed(STUCK, ONE_GOAL, 0)

    def test_code_written_is_a_dispute_not_a_dead_end(self):
        """
        Круг что-то написал, но QA не принял — это спор о качестве.

        Там человеку есть что сказать, и подменять его мнение возвратом нельзя.
        """
        from src.project.task.task_goal_replan import task_goal_replan_needed

        assert not task_goal_replan_needed(STUCK, ONE_GOAL, 120)

    def test_several_goals_leave_the_choice_to_the_human(self):
        """С двумя целями дробление осмысленно — значит, есть о чём спрашивать."""
        from src.project.task.task_goal_replan import task_goal_replan_needed

        goals = [*ONE_GOAL, {'text': 'вторая цель', 'done': False}]

        assert not task_goal_replan_needed(STUCK, goals, 0)

    def test_closed_goals_do_not_count(self):
        """Считаем незакрытые: закрытая цель работы больше не требует."""
        from src.project.task.task_goal_replan import task_goal_replan_needed

        goals = [*ONE_GOAL, {'text': 'уже сделана', 'done': True}]

        assert task_goal_replan_needed(STUCK, goals, 0)

    def test_working_row_is_not_touched(self):
        """Строка, которая идёт своим ходом, никуда не возвращается."""
        from src.project.task.task_goal_replan import task_goal_replan_needed

        for state in ('planned', 'developing', 'testing', 'qa_pending', 'done'):
            row = {**STUCK, 'pipeline_state': state}
            assert not task_goal_replan_needed(row, ONE_GOAL, 0), state

    def test_second_dead_end_goes_to_the_human(self):
        """Возвращали однажды — второй тупик показываем вопросом, а не крутим цикл."""
        from src.project.task.task_goal_replan import task_goal_replan_needed

        row = {**STUCK, 'metadata': '{"replanned": true}'}

        assert not task_goal_replan_needed(row, ONE_GOAL, 0)


class TestReplanSend:
    """Что возврат отказывается делать."""

    async def test_root_task_refused(self):
        """У задачи целиком плана-родителя нет — возвращать её некому."""
        from src.project.task.task_goal_replan import task_goal_replan_send

        result = await task_goal_replan_send({'id': 1027, 'parent_id': None, 'metadata': '{}'})

        assert not result['ok'] and 'подзадача' in result['error']

    async def test_already_replanned_refused(self):
        from src.project.task.task_goal_replan import task_goal_replan_send

        result = await task_goal_replan_send({**STUCK, 'metadata': '{"replanned": true}'})

        assert not result['ok'] and 'уже возвращали' in result['error']


class TestStuckOptions:
    """Что предлагают человеку, когда цель одна."""

    def test_single_goal_offers_planning_not_splitting(self):
        from src.project.task.task_question import (TASK_QUESTION_ACTION_DROP,
                                                    TASK_QUESTION_ACTION_PLAN,
                                                    TASK_QUESTION_ACTION_SPLIT, _stuck_options)

        keys = [o['key'] for o in _stuck_options(ONE_GOAL)]

        assert TASK_QUESTION_ACTION_PLAN in keys, 'единственный осмысленный ход'
        assert TASK_QUESTION_ACTION_SPLIT not in keys, 'одну цель дробить нечем'
        assert TASK_QUESTION_ACTION_DROP not in keys, 'убрать единственную цель — отменить работу'

    def test_several_goals_keep_splitting(self):
        from src.project.task.task_question import TASK_QUESTION_ACTION_SPLIT, _stuck_options

        goals = [*ONE_GOAL, {'text': 'вторая', 'done': False}]

        assert TASK_QUESTION_ACTION_SPLIT in [o['key'] for o in _stuck_options(goals)]


class TestUncountedIsNotZero:
    """
    «Не посчитали» — не то же самое, что «работы не было».

    Подсчёт правок отвечает `None`, когда посчитать не вышло: каталога нет, git
    отказал, проект не определился. Принять этот ответ за ноль — значит отправить
    на переразбиение работу, которая сделана.

    Поймано живьём: подзадача #1626 с готовым коммитом на 18 строк уехала к
    менеджеру, потому что каталог искали по проекту чужой строки, получили пустой
    путь и молчаливый ноль сошёл за факт.
    """

    def test_zero_means_no_work(self):
        """Честный ноль — основание вернуть строку менеджеру."""
        from src.project.task.task_goal_replan import task_goal_replan_needed

        assert task_goal_replan_needed(STUCK, ONE_GOAL, 0)

    def test_any_code_blocks_replan(self):
        """Есть код — значит круг что-то сделал, и это спор о качестве."""
        from src.project.task.task_goal_replan import task_goal_replan_needed

        assert not task_goal_replan_needed(STUCK, ONE_GOAL, 18)

    async def test_missing_dir_gives_none_not_zero(self):
        """
        Нет каталога — подсчёт обязан сказать «не знаю», а не «ноль».

        Проверяем поведением, а не чтением исходника: важно, что вернулось, а не
        как это записано.
        """
        from src.project.task.task_pipeline import _lines_changed

        assert await _lines_changed('/каталога/нет', 1626) is None
        assert await _lines_changed('', 1626) is None

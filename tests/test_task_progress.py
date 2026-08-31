"""
«Работа была» против «работа провалилась» — от этого зависит, хоронить ли подзадачу.

Дефект. Круг разработчика, кончившийся без `ok`, конвейер закрывал одинаково: попытка
сожжена, на последней — `blocked`, дальше нужен человек. Но исходов тут два, и они
разные. «Провалился» — работы не вышло вовсе. «Не доделал, вот что осталось» — агент
разобрался, написал код, закоммитил и сам назвал недоделанное.

Живьём подзадача #5219: три прогона подряд не состоялись (оболочка молчала — такие
попытку не жгут), а четвёртый отработал честно, оставил пять коммитов и написал
«нужен следующий круг: записать миграцию, сделать push и MR». Этот содержательный
ответ сжёг последнюю попытку и увёл строку в `blocked` — при том, что работа шла и
оставалось её на один заход.

Признак объективный — код в ветке, а не слова агента: отчёт пишет он сам, и «я почти
закончил» стало бы способом крутить круги бесконечно. Причём мало, что код есть — он
остаётся от прошлых кругов. Смотрим, **прибавился** ли он.

Оба свойства проверяются здесь, и второе не менее важно первого: без него строка,
которая топчется на месте, получала бы попытки без конца.
"""

import pytest

# Подзадача, которой нет: замеры пишутся под её номером и удаляются по нему же.
TEST_TASK_ID = 987670


@pytest.fixture(autouse=True)
async def metric_cleanup():
    """Снести тестовые замеры — до теста и после."""
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestLinesAdvanced:
    """Прибавился ли код за круг."""

    async def test_more_lines_than_before_is_progress(self):
        """
        Тот самый случай #5219: было 79 строк, стало 125 — работа сдвинулась.
        """
        from src.project.task.task_metric import task_metric_lines_advanced

        await _metric_write(attempt_no=1, lines=79)
        await _metric_write(attempt_no=2, lines=79)

        assert await task_metric_lines_advanced(TEST_TASK_ID, 125, attempt_no=3) is True

    async def test_same_lines_is_not_progress(self):
        """
        Столько же строк — круг прошёл впустую. Именно это отличает «доделывает» от
        «топчется»: без такой проверки вторая строка получала бы попытки бесконечно.
        """
        from src.project.task.task_metric import task_metric_lines_advanced

        await _metric_write(attempt_no=1, lines=79)

        assert await task_metric_lines_advanced(TEST_TASK_ID, 79, attempt_no=2) is False

    async def test_current_round_is_excluded(self):
        """
        Замер текущего круга в сравнение не идёт.

        Журнал круга пишется раньше, чем принимается решение о повторе, — то есть
        «сейчас» уже лежит в таблице последней строкой. Не исключи мы его, сравнение
        шло бы с самим собой и всегда давало «нет»: проверка молча не работала бы.
        """
        from src.project.task.task_metric import task_metric_lines_advanced

        await _metric_write(attempt_no=1, lines=79)
        await _metric_write(attempt_no=3, lines=125)   # замер текущего круга

        assert await task_metric_lines_advanced(TEST_TASK_ID, 125, attempt_no=3) is True

    async def test_no_metrics_counts_as_progress(self):
        """
        Первому кругу сравнивать не с чем — отказать ему значило бы наказать за то,
        что он первый.
        """
        from src.project.task.task_metric import task_metric_lines_advanced

        assert await task_metric_lines_advanced(TEST_TASK_ID, 42, attempt_no=1) is True

    async def test_empty_branch_is_not_progress(self):
        """Кода нет вовсе — прежнее поведение, попытка жжётся как раньше."""
        from src.project.task.task_metric import task_metric_lines_advanced

        assert await task_metric_lines_advanced(TEST_TASK_ID, 0, attempt_no=2) is False


class TestSubtaskFail:
    """Что становится с подзадачей на исчерпанных попытках."""

    async def test_worked_returns_to_work_instead_of_blocked(self):
        """
        Попытки кончились, но круг оставил код — возвращаем в работу, а не хороним.
        """
        from src.project.task.task_state import task_state_subtask_fail

        subtask_id = await _subtask_create()
        state = await task_state_subtask_fail(subtask_id, attempt_no=3,
                                              error='не доделал', max_attempts=3, worked=True)

        assert state == 'failed_qa'

    async def test_no_work_still_blocks(self):
        """
        Кода нет — прежнее поведение. Иначе пустые круги шли бы бесконечно, и предел
        попыток перестал бы что-либо значить.
        """
        from src.project.task.task_state import task_state_subtask_fail

        subtask_id = await _subtask_create()
        state = await task_state_subtask_fail(subtask_id, attempt_no=3,
                                              error='сорвался', max_attempts=3, worked=False)

        assert state == 'blocked'

    async def test_attempts_left_returns_to_work_regardless(self):
        """
        Пока попытки есть, исход прежний в обоих случаях: `worked` решает только
        судьбу последней.
        """
        from src.project.task.task_state import task_state_subtask_fail

        first = await _subtask_create()
        second = await _subtask_create()

        assert await task_state_subtask_fail(first, 1, 'ошибка', 3, worked=False) == 'failed_qa'
        assert await task_state_subtask_fail(second, 1, 'ошибка', 3, worked=True) == 'failed_qa'


async def _metric_write(attempt_no: int, lines: int) -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task_metric '
            '       (task_id, task_title, role, llm_name, step_title, attempt_no, '
            '        context_lines, lines_changed, duration_ms, status) '
            "VALUES (%s, 'progress-test', 'developer', 'test', 'шаг', %s, 0, %s, 0, 'success')",
            (TEST_TASK_ID, attempt_no, lines))
        await db.connection.commit()


async def _subtask_create() -> int:
    """
    Настоящая строка подзадачи: `task_state_subtask_fail` пишет в неё состояние, и
    выдуманный номер молча ничего бы не обновил — тест был бы зелёным всегда.
    """
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_task (project_id, title, description, goals, position, "
            "                          status, task_type_id, pipeline_state) "
            "VALUES (%s, 'progress-test', '', '[]', 0, 'queued', "
            "        (SELECT id FROM project_task_type WHERE name = 'dev'), 'developing')",
            (TEST_TASK_ID,))
        task_id = db.lastrowid
        await db.connection.commit()

    return task_id


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM project_task_metric WHERE task_id = %s', (TEST_TASK_ID,))
        await db.execute('DELETE FROM project_task WHERE project_id = %s', (TEST_TASK_ID,))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

"""
«Последняя запись» — там, где выбирают одну строку из истории.

Зачем этот файл отдельно. Дефект здесь не падает и не пишет в лог: запрос
отрабатывает, строка возвращается, всё выглядит рабочим — просто строка не та.
Заметить это можно, лишь сверив содержимое с ожидаемым, и потому проверка нужна
машинная.

Живой повод. QA брал отчёт разработчика сортировкой по `attempt_no DESC`, а этот
номер считает попытки **внутри круга** и сбрасывается, когда QA возвращает работу на
доработку. Победа навсегда доставалась самому неудачному кругу — тому, где попыток
вышло больше. У подзадачи #5219 QA девять часов читал отчёт с ошибкой провайдера
(«This request requires more credits») вместо свежего, лежащего рядом: проверял
работу по описанию круга, который не состоялся.

Отсюда правило, которое здесь и закрепляется: **сортировать по монотонному ключу**.
`id` растёт и не сбрасывается ничем; счётчики внутри круга — сбрасываются.
"""

import uuid

import pytest

# Проект, которого нет: под ним заводится тестовая подзадача, и уборка сносит ровно её.
TEST_PROJECT_ID = 987661


@pytest.fixture(autouse=True)
async def subtask_row():
    """
    Завести настоящую строку подзадачи и снести её после.

    Строка нужна живая, а не выдуманный номер: у `project_task_attempt` внешний ключ
    на `project_task`, и вставка под несуществующий номер отвергается целиком. Номер
    отдаём тесту — он у строки свой, автоинкрементный.
    """
    global TEST_SUBTASK_ID

    await _cleanup()
    TEST_SUBTASK_ID = await _subtask_create()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


# Номер тестовой подзадачи: проставляется фикстурой на каждый тест.
TEST_SUBTASK_ID = 0


async def _subtask_create() -> int:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            "INSERT INTO project_task (project_id, title, description, goals, position, "
            "                          status, task_type_id, pipeline_state) "
            "VALUES (%s, 'freshness', '', '[]', 0, 'queued', "
            "        (SELECT id FROM project_task_type WHERE name = 'dev'), 'planned')",
            (TEST_PROJECT_ID,))
        task_id = db.lastrowid
        await db.connection.commit()

    return task_id


class TestDeveloperReport:
    """Отчёт, который читает QA, — от последнего круга разработчика."""

    async def test_latest_report_wins_over_higher_attempt_no(self):
        """
        Тот самый дефект. Старая запись с `attempt_no = 3` не должна перебивать свежую
        с `attempt_no = 1`: номер попытки сбрасывается между кругами, а работа — нет.
        """
        from src.project.task.task_agent_qa import _developer_report

        await _attempt_write(attempt_no=3, role='developer', status='ok',
                             output='древний отчёт, круг не состоялся')
        await _attempt_write(attempt_no=1, role='developer', status='ok',
                             output='свежий отчёт, работа сделана')

        assert await _developer_report(TEST_SUBTASK_ID) == 'свежий отчёт, работа сделана'

    async def test_failed_attempts_are_skipped(self):
        """
        Берём удачную: провальная описывает, почему работа не вышла, а QA проверяет
        то, что до него дошло.
        """
        from src.project.task.task_agent_qa import _developer_report

        await _attempt_write(attempt_no=1, role='developer', status='ok',
                             output='работа сделана')
        await _attempt_write(attempt_no=2, role='developer', status='error',
                             output='', error='прогон не состоялся')

        assert await _developer_report(TEST_SUBTASK_ID) == 'работа сделана'

    async def test_other_role_report_is_not_taken(self):
        """Отчёт QA разработчику не принадлежит: роль в условии обязательна."""
        from src.project.task.task_agent_qa import _developer_report

        await _attempt_write(attempt_no=1, role='developer', status='ok', output='от разработчика')
        await _attempt_write(attempt_no=1, role='qa', status='ok', output='от проверки')

        assert await _developer_report(TEST_SUBTASK_ID) == 'от разработчика'

    async def test_no_attempts_gives_empty(self):
        """Подзадачу отдали на проверку вручную — промпт раскроет ветку «ищи сам»."""
        from src.project.task.task_agent_qa import _developer_report

        assert await _developer_report(TEST_SUBTASK_ID) == ''


class TestStickyModel:
    """Модель прошлого круга — последняя выданная, а не любая помнящая задачу."""

    async def test_latest_used_model_wins(self):
        """
        Строка заводится на модель и живёт дальше: `task_id` в ней остаётся после
        освобождения. Отработала задача на двух моделях — обе помнят её номер, и без
        сортировки MySQL возвращал любую. Живьём так и было у задачи #4915.
        """
        from src.project.team.team_llm_pool import _task_llm_last

        await _lock_write('test_stick/старая', used_minutes_ago=120)
        await _lock_write('test_stick/свежая', used_minutes_ago=5)

        assert await _task_llm_last(TEST_SUBTASK_ID) == 'test_stick/свежая'

    async def test_dated_row_beats_undated(self):
        """
        Строка без `used_at` заведена до появления колонки: про неё не известно ничего,
        и ставить её впереди датированной значило бы предпочесть незнание.
        """
        from src.project.team.team_llm_pool import _task_llm_last

        await _lock_write('test_stick/без-даты', used_minutes_ago=None)
        await _lock_write('test_stick/с-датой', used_minutes_ago=300)

        assert await _task_llm_last(TEST_SUBTASK_ID) == 'test_stick/с-датой'

    async def test_release_keeps_used_at(self):
        """
        Освобождение гасит `locked_at`, но не `used_at`: иначе память о прошлом круге
        исчезала бы вместе с захватом, и прилипание не работало бы вовсе — ровно то,
        ради чего колонку и завели.
        """
        from src.project.team.team_llm_pool import _task_llm_last, team_llm_pool_release

        await _lock_write('test_stick/освобождённая', used_minutes_ago=5, locked=True)
        await team_llm_pool_release(llm_name='test_stick/освобождённая')

        assert await _task_llm_last(TEST_SUBTASK_ID) == 'test_stick/освобождённая'


async def _attempt_write(attempt_no: int, role: str, status: str,
                         output: str = '', error: str = '') -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO project_task_attempt '
            '       (task_id, attempt_no, role, status, output, error) '
            'VALUES (%s, %s, %s, %s, %s, %s)',
            (TEST_SUBTASK_ID, attempt_no, role, status, output, error))
        await db.connection.commit()


async def _lock_write(llm_name: str, used_minutes_ago: int | None,
                      locked: bool = False) -> None:
    from datetime import timedelta

    from datetime_.datetime_ import datetime_utc_now
    from mysql_.mysql_ import mysql_get_db_async

    now = datetime_utc_now()
    used_at = None if used_minutes_ago is None else now - timedelta(minutes=used_minutes_ago)

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO team_llm_lock (llm_name, project_id, task_id, role, '
            '                           session_uuid, locked_at, used_at) '
            "VALUES (%s, 0, %s, 'developer', %s, %s, %s)",
            (llm_name, TEST_SUBTASK_ID, str(uuid.uuid4()),
             now if locked else None, used_at))
        await db.connection.commit()


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        # Попытки уедут каскадом за строкой задачи, но сносим явно: каскад — свойство
        # схемы, а тест не должен зависеть от того, сохранится ли оно.
        await db.execute(
            'DELETE FROM project_task_attempt WHERE task_id IN '
            '   (SELECT id FROM (SELECT id FROM project_task WHERE project_id = %s) AS t)',
            (TEST_PROJECT_ID,))
        await db.execute('DELETE FROM project_task WHERE project_id = %s', (TEST_PROJECT_ID,))
        await db.execute("DELETE FROM team_llm_lock WHERE llm_name LIKE 'test_stick/%'")
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

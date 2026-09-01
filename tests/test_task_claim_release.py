"""
Возврат захваченной строки, когда круг не начался — `task_claim_release`.

Захват и работа разнесены во времени: тик переводит строку в переходное состояние
(`testing`, `developing`, `planning`), а круг начинается позже — и может не начаться
вовсе, если все оболочки роли заняты или в пуле нет свободной модели.

Раньше такая строка оставалась захваченной до реклейма, то есть две минуты, и всё это
время врала дважды. На странице задача числилась «в работе», хотя ею никто не
занимался: страница считает работой непустой `pipeline_locked_by`, и формально она
права. И, что хуже, захват занимал место в пределе параллельности проекта — то самое,
на которое могла бы прийти настоящая работа. Живьём #5238 каждые две минуты отбирал
круг у свободной облачной оболочки, не делая ничего.

Главное, что здесь проверяется: **строка возвращается в то состояние, из которого её
взяли, и блокировка снимается сразу**. Карта возврата общая с реклеймом — если она
разойдётся, подзадача уедет не в ту очередь и её никто не подберёт.

Тесты идут на живой базе и убирают за собой: строки заводятся с тестовым заголовком.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST` на
импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

pytestmark = pytest.mark.pipeline

# Заголовок тестовых строк: по нему их сносит уборка, и он же попадает под общую маску
# `__pytest%` из `conftest.py`.
TEST_TITLE = '__pytest_claim_release'

# Имя воркера, под которым тесты «захватывают» строку.
TEST_WORKER = 'test-host:1'


@pytest.fixture(autouse=True)
async def rows_cleanup():
    """Снести тестовые строки — до теста и после."""
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestSubtaskRelease:
    """Подзадача возвращается в свою очередь."""

    async def test_testing_goes_back_to_qa_pending(self):
        """Круг QA не начался — подзадача снова ждёт проверки, а не «в работе»."""
        from src.project.task.task_claim import task_claim_release

        row_id = await _row_write('testing', parent=True)

        assert await task_claim_release(row_id) == 'qa_pending'
        assert await _row_read(row_id) == ('qa_pending', '')

    async def test_developing_goes_back_to_planned(self):
        from src.project.task.task_claim import task_claim_release

        row_id = await _row_write('developing', parent=True)

        assert await task_claim_release(row_id) == 'planned'
        assert await _row_read(row_id) == ('planned', '')


class TestTaskRelease:
    """Задача возвращается по своей карте — она другая."""

    async def test_planning_goes_back_to_new(self):
        from src.project.task.task_claim import task_claim_release

        row_id = await _row_write('planning')

        assert await task_claim_release(row_id) == 'new'
        assert await _row_read(row_id) == ('new', '')

    async def test_reviewing_stays_reviewing(self):
        """
        Пересмотр возвращается в себя же: `reviewing` — это и очередь, и работа.

        Отличает их блокировка, и снять нужно ровно её.
        """
        from src.project.task.task_claim import task_claim_release

        row_id = await _row_write('reviewing')

        assert await task_claim_release(row_id) == 'reviewing'
        assert await _row_read(row_id) == ('reviewing', '')


class TestReleaseIsNarrow:
    """Возврат не трогает того, что ему не принадлежит."""

    async def test_free_row_is_not_touched(self):
        """
        Блокировки нет — возвращать нечего.

        Иначе круг, опоздавший со своим `finally`, сбросил бы состояние строки, которую
        уже взял другой воркер.
        """
        from src.project.task.task_claim import task_claim_release

        row_id = await _row_write('testing', parent=True, worker='')

        assert await task_claim_release(row_id) == ''
        assert await _row_read(row_id) == ('testing', '')

    async def test_foreign_lock_is_not_touched(self):
        """Названный воркер снимает только свой захват, чужой остаётся на месте."""
        from src.project.task.task_claim import task_claim_release

        row_id = await _row_write('testing', parent=True, worker='other-host:2')

        assert await task_claim_release(row_id, worker=TEST_WORKER) == ''
        assert await _row_read(row_id) == ('testing', 'other-host:2')

    async def test_state_outside_the_map_is_not_touched(self):
        """
        Состояние не переходное — значит круг уже что-то сделал и состояние сменил.

        Возвращать такую строку нельзя: мы стёрли бы результат работы.
        """
        from src.project.task.task_claim import task_claim_release

        row_id = await _row_write('done', parent=True)

        assert await task_claim_release(row_id) == ''
        assert await _row_read(row_id) == ('done', TEST_WORKER)

    async def test_missing_row_is_not_an_error(self):
        from src.project.task.task_claim import task_claim_release

        assert await task_claim_release(0) == ''
        assert await task_claim_release(2 ** 31 - 1) == ''


async def _row_write(state: str, parent: bool = False, worker: str = TEST_WORKER) -> int:
    """Строка в переходном состоянии с блокировкой. Возвращает её номер."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        parent_id = None
        if parent:
            await db.execute(
                'INSERT INTO project_task (title, description, goals, report, status, position) '
                "VALUES (%s, '', '', '', 'queued', 0)", (f'{TEST_TITLE}_parent',))
            parent_id = db.lastrowid

        await db.execute(
            'INSERT INTO project_task (parent_id, title, description, goals, report, status, '
            '                          position, pipeline_state, pipeline_locked_by, '
            '                          pipeline_locked_at, pipeline_from_plan) '
            "VALUES (%s, %s, '', '', '', 'queued', 0, %s, %s, NOW(), %s)",
            (parent_id, f'{TEST_TITLE}_row', state, worker, 1 if parent else 0))
        row_id = db.lastrowid
        await db.connection.commit()

    return row_id


async def _row_read(row_id: int) -> tuple[str, str]:
    """Состояние и держатель блокировки строки."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT pipeline_state, pipeline_locked_by FROM project_task WHERE id = %s',
            (int(row_id),))
        row = await db.fetchone() or {}

    return str(row.get('pipeline_state') or ''), str(row.get('pipeline_locked_by') or '')


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM project_task WHERE title LIKE %s', (f'{TEST_TITLE}%',))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

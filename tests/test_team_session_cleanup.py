"""
Уборка сессий команды — `src/project/team/team_session_cleanup.py`.

Зачем это проверять. Оболочка, закрытая по-человечески, отмечается `inactive` сама,
и её убирает уборка. Убитая — нет: закрыли окно терминала, `kill -9`, перезагрузили
машину — строка остаётся `active` навсегда, heartbeat не приходит, а карточка на
`/admin/team` продолжает числиться живой. Копятся они молча: живьём набралось
шестнадцать мёртвых при семи работающих, и выглядело это так, будто роли отваливаются
пачками.

Опасность здесь несимметрична, и тесты написаны вокруг неё. Не погасить мёртвую —
мусор на странице. Погасить живую — отнять у конвейера рабочую оболочку, вернуть
которую сможет только человек перезапуском. Поэтому проверяется обе стороны, и
граница берётся с большим запасом: час против девяноста секунд, за которые гаснет
карточка на заминке сети.

Тесты идут на живой базе и убирают за собой: сессии заводятся с узнаваемым префиксом
`uuid`, и удаляются по нему же.
"""

from datetime import timedelta

import pytest

# Префикс тестовых сессий: по нему их видно в реестре и по нему же сносит уборка.
# Настоящие `session_uuid` — обычные UUID4, так что пересечься не с чем.
TEST_UUID_PREFIX = 'test-cleanup-'


@pytest.fixture(autouse=True)
async def registry_cleanup():
    """Снести тестовые сессии — до теста и после."""
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestSilentSessions:
    """Замолчавшая `active` гасится; живая — нет."""

    async def test_silent_session_is_closed(self):
        """
        Час без heartbeat — оболочки нет. Не погаси мы её, карточка осталась бы
        живой навсегда: `inactive` она сама уже не станет, а уборка удаляет только
        `inactive`, и до строки дело не дошло бы вовсе.
        """
        from src.project.team.team_session_cleanup import (
            TEAM_SESSION_CLEANUP_SILENT_MINUTES, team_session_cleanup_silent)

        uuid = await _session_create(
            'silent', seen_minutes_ago=TEAM_SESSION_CLEANUP_SILENT_MINUTES + 10)

        await team_session_cleanup_silent()

        assert await _status(uuid) == 'inactive'

    async def test_live_session_survives(self):
        """
        Обратная сторона, и она дороже: погасив работающую оболочку, мы отняли бы её
        у конвейера — вернуть её смог бы только человек перезапуском.
        """
        from src.project.team.team_session_cleanup import team_session_cleanup_silent

        uuid = await _session_create('live', seen_minutes_ago=1)

        await team_session_cleanup_silent()

        assert await _status(uuid) == 'active'

    async def test_never_seen_session_judged_by_creation(self):
        """
        Сессия без единого heartbeat считается по времени регистрации: не проверь мы
        дату, под нож попала бы и та, что регистрируется прямо сейчас, — а она ещё
        не успела отметиться.
        """
        from src.project.team.team_session_cleanup import (
            TEAM_SESSION_CLEANUP_SILENT_MINUTES, team_session_cleanup_silent)

        fresh = await _session_create('fresh-null', seen_minutes_ago=None, created_minutes_ago=1)
        stale = await _session_create('stale-null', seen_minutes_ago=None,
                                      created_minutes_ago=TEAM_SESSION_CLEANUP_SILENT_MINUTES + 10)

        await team_session_cleanup_silent()

        assert await _status(fresh) == 'active', 'только что заведённую гасить нельзя'
        assert await _status(stale) == 'inactive', 'умершая на старте так и не отметится'

    async def test_threshold_outlasts_card_staleness(self):
        """
        Порог списания обязан быть много больше порога свежести карточки: тот решает,
        как рисовать живую строку при заминке сети, а этот — когда списать её совсем.
        Сравняй их, и одна сетевая заминка сносила бы оболочки вместо мигания.
        """
        from src.project.team.team_session_cleanup import TEAM_SESSION_CLEANUP_SILENT_MINUTES
        from src.project.task.task_setting_timeout import (
            TASK_SETTING_TIMEOUT_PING_STALE, task_setting_timeout_get)

        stale_seconds = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_PING_STALE)

        assert TEAM_SESSION_CLEANUP_SILENT_MINUTES * 60 >= stale_seconds * 5


class TestCleanupReport:
    """Отчёт уборки называет и погашенные — иначе шаг не виден вызывающему."""

    async def test_report_counts_silent(self):
        from src.project.team.team_session_cleanup import (
            TEAM_SESSION_CLEANUP_SILENT_MINUTES, cleanup_inactive_sessions)

        await _session_create('report',
                              seen_minutes_ago=TEAM_SESSION_CLEANUP_SILENT_MINUTES + 10)

        report = await cleanup_inactive_sessions()

        assert report['silent_closed'] >= 1


class TestSweepRunsOnSchedule:
    """
    Уборка идёт по расписанию, а не только при регистрации оболочки.

    Дефект был живой. Уборка звалась из одного места — регистрации новой сессии, — а
    её не происходит, пока человек не откроет терминал. Между перезапусками мёртвые
    строки копились и висели на `/admin/team` живыми карточками: после обрыва сети их
    набралось шесть при восьми работающих, и команда выглядела так, будто роли
    отваливаются пачками.
    """

    def test_sweep_is_registered_as_runner(self):
        """Без записи в карте раннеров job уборки уходил бы в отказ «неизвестный вид»."""
        from src.project.task.task_pipeline import _RUNNERS

        assert 'session_sweep' in _RUNNERS

    def test_sweep_is_a_periodic_sweeper(self):
        """
        Подметальщик: без захвата строки и вне бюджета действий, раз в пять минут.

        Считайся он действием, при `max_actions=1` тик уходил бы на уборку, а задачи
        стояли бы в очереди.
        """
        from src.worker.project.task_worker import (TASK_WORKER_FLIGHT_PERIOD,
                                                    TASK_WORKER_SINGLE_FLIGHT)

        assert 'session_sweep' in TASK_WORKER_SINGLE_FLIGHT
        assert TASK_WORKER_FLIGHT_PERIOD.get('session_sweep') == 300

    async def test_sweep_closes_silent_session(self):
        """
        Тот самый случай целиком: молчащая строка гаснет прогоном подметальщика, без
        всякой регистрации новой оболочки.
        """
        from src.project.task.task_pipeline import _run_session_sweep

        uuid = await _session_create('sweep', seen_minutes_ago=90)

        await _run_session_sweep({'kind': 'session_sweep'})

        assert await _status(uuid) == 'inactive'


async def _session_create(suffix: str, seen_minutes_ago: int | None,
                          created_minutes_ago: int = 0) -> str:
    """Завести `active`-сессию с нужной давностью heartbeat. Returns: её uuid."""
    from datetime_.datetime_ import datetime_utc_now
    from mysql_.mysql_ import mysql_get_db_async

    now = datetime_utc_now()
    uuid = f'{TEST_UUID_PREFIX}{suffix}'
    seen = None if seen_minutes_ago is None else now - timedelta(minutes=seen_minutes_ago)

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO ai_claude_session_registry '
            '       (session_uuid, role, role_index, project_label, status, '
            '        server_llm, created_at, last_seen_at) '
            "VALUES (%s, 'developer', 99, 'test-cleanup', 'active', 'test', %s, %s)",
            (uuid, now - timedelta(minutes=created_minutes_ago), seen))
        await db.connection.commit()

    return uuid


async def _status(uuid: str) -> str:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('SELECT status FROM ai_claude_session_registry WHERE session_uuid = %s',
                         (uuid,))

        return (await db.fetchone() or {}).get('status', '')


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM ai_claude_session_registry WHERE session_uuid LIKE %s',
                         (f'{TEST_UUID_PREFIX}%',))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

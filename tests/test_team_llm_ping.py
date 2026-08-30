"""
Пинг моделей пула и вывод мёртвых из выдачи (`src/project/team/team_llm_ping.py`).

Зачем это проверять. Модель отвалилась у провайдера — `qwen/qwen3.7-flash` перестала
отвечать, — а конвейер продолжал выдавать её ролям: круг уходил в неё, падал, тратил
попытку, и так каждый тик. Со стороны это неотличимо от неисправного конвейера.

Главное здесь — **правило выдачи**, а не сам запрос. Постучаться в провайдера умеет
любой HTTP-клиент; ценность в том, кому после этого достанется работа. Поэтому
запросы наружу подменяются, а проверяется именно захват: пропускает ли он
неотвечающую модель, и — не менее важно — **не** пропускает ли лишнего.

Два случая, где ошибка была бы дороже самой поломки:

- модель не пинговали ни разу (свежая установка, воркер не поднимался) — молчание
  значит «не знаем», и работа обязана идти, как шла до появления пинга. Прими мы
  молчание за смерть, механизм, заведённый чинить конвейер, останавливал бы его;
- не отвечают все — работаем по полному списку. Пустой пул означал бы, что роли не
  берут работу вовсе; отправить круг в модель вопреки пингу дешевле, чем встать.

Тесты идут на живой базе и убирают за собой: имена моделей и номер проекта тестовые,
таких в установке нет.
"""

import json

import pytest

# Номер проекта, которого в базе нет: пул пишется под ним, и уборка сносит ровно его.
TEST_PROJECT_ID = 987655

# Модели тестовые — попади сюда настоящая, тест переписал бы её пинг и отнял бы её у
# работающего конвейера на весь прогон.
TEST_LLM_LIVE = 'test_ping/model-live'
TEST_LLM_DEAD = 'test_ping/model-dead'


@pytest.fixture(autouse=True)
async def ping_cleanup():
    """Снести пул, захваты и пинги тестовых моделей — до теста и после."""
    await _cleanup()
    yield
    await _cleanup()

    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestPingStorage:
    """Результат пинга как значение настройки: что записали, то и прочли."""

    async def test_unknown_model_is_recorded_not_raised(self):
        """
        Модели нет в каталоге — записанный `unknown`, а не исключение и не `error`.

        Пинг зовут из воркера конвейера, и падать он там не имеет права. А `unknown`
        вместо `error` здесь принципиален: круг роли идёт через LiteLLM оболочки с её
        собственным каталогом, и наша неспособность найти запись ничего не говорит о
        работоспособности модели. Смешай мы эти случаи — забытое монтирование каталога
        объявило бы мёртвым весь пул разом.
        """
        from src.project.team.team_llm_ping import (TEAM_LLM_PING_UNKNOWN,
                                                    team_llm_ping_get, team_llm_ping_one)

        ping = await team_llm_ping_one(TEST_LLM_DEAD)

        assert ping['status'] == TEAM_LLM_PING_UNKNOWN
        assert ping['at'], 'без отметки времени пинг не отличить от «не проверяли»'
        assert 'каталог' in str(ping['error'])
        assert await team_llm_ping_get(TEST_LLM_DEAD) == ping

    async def test_map_returns_empty_for_never_pinged(self):
        """
        Не пинговали — пустой словарь, а не отказ.

        Разница существенная: по ней страница рисует серую точку вместо красной, а
        захват не выводит модель из выдачи.
        """
        from src.project.team.team_llm_ping import team_llm_ping_map

        pings = await team_llm_ping_map([TEST_LLM_LIVE, TEST_LLM_DEAD])

        assert pings == {TEST_LLM_LIVE: {}, TEST_LLM_DEAD: {}}


class TestPingDead:
    """Кто считается выведенным из выдачи."""

    async def test_failed_ping_marks_dead(self):
        from src.project.team.team_llm_ping import team_llm_ping_dead

        await _ping_write(TEST_LLM_DEAD, 'error')
        await _ping_write(TEST_LLM_LIVE, 'ok')

        assert await team_llm_ping_dead([TEST_LLM_LIVE, TEST_LLM_DEAD]) == {TEST_LLM_DEAD}

    async def test_never_pinged_is_not_dead(self):
        """
        Молчание — не смерть. На свежей установке не пинговали никого, и трактуй мы
        это как отказ, пул опустел бы целиком, а роли перестали бы брать работу.
        """
        from src.project.team.team_llm_ping import team_llm_ping_dead

        assert await team_llm_ping_dead([TEST_LLM_LIVE, TEST_LLM_DEAD]) == set()

    async def test_unknown_is_not_dead(self):
        """
        «Проверить не смогли» тоже не выводит модель.

        Это состояние установки, а не модели: каталог оболочки не смонтирован, ключ
        провайдера не назван в нашем `.env`. Круг при этом идёт через LiteLLM с её
        собственными настройками и вполне может пройти.
        """
        from src.project.team.team_llm_ping import (TEAM_LLM_PING_UNKNOWN,
                                                    team_llm_ping_dead)

        await _ping_write(TEST_LLM_DEAD, TEAM_LLM_PING_UNKNOWN)

        assert await team_llm_ping_dead([TEST_LLM_DEAD]) == set()


class TestPoolSkipsDead:
    """Ради чего всё заведено: неотвечающая модель не получает кругов."""

    async def test_acquire_skips_dead_model(self):
        """
        В пуле две модели, одна не отвечает — захват отдаёт вторую.

        Порядок в пуле мёртвая занимает первой: возьми захват «первую свободную», не
        глядя на пинг, — тест поймает это сразу.
        """
        from src.project.team.team_llm_pool import team_llm_pool_acquire, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_DEAD, TEST_LLM_LIVE])
        await _ping_write(TEST_LLM_DEAD, 'error')
        await _ping_write(TEST_LLM_LIVE, 'ok')

        got = await team_llm_pool_acquire(TEST_PROJECT_ID, task_id=0, role='developer')

        assert got == TEST_LLM_LIVE

    async def test_acquire_ignores_pings_when_all_dead(self):
        """
        Не отвечают все — работаем по полному списку.

        Пустой пул означал бы, что роли не берут работу вовсе; лучше отправить круг в
        модель, которая может ответить вопреки пингу, чем остановить конвейер по
        данным одной проверки.
        """
        from src.project.team.team_llm_pool import team_llm_pool_acquire, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_DEAD, TEST_LLM_LIVE])
        await _ping_write(TEST_LLM_DEAD, 'error')
        await _ping_write(TEST_LLM_LIVE, 'error')

        got = await team_llm_pool_acquire(TEST_PROJECT_ID, task_id=0, role='developer')

        assert got == TEST_LLM_DEAD, 'при полностью мёртвом пуле выдаётся первая модель'

    async def test_dead_model_beats_stickiness(self):
        """
        Прилипание к прежней модели задачи не перевешивает пинг.

        Прилипание экономит контекст агента, но отдать круг модели, которая не
        отвечает, — значит потратить попытку задачи ради этой экономии.
        """
        from src.project.team.team_llm_pool import (team_llm_pool_acquire,
                                                    team_llm_pool_release,
                                                    team_llm_pool_set)

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_LIVE, TEST_LLM_DEAD])
        await _ping_write(TEST_LLM_LIVE, 'ok')
        await _ping_write(TEST_LLM_DEAD, 'ok')

        # Задача #1 отработала круг на «мёртвой» — теперь она её прилипшая.
        first = await team_llm_pool_acquire(TEST_PROJECT_ID, task_id=1, role='developer')
        assert first == TEST_LLM_LIVE
        second = await team_llm_pool_acquire(TEST_PROJECT_ID, task_id=1, role='qa')
        assert second == TEST_LLM_DEAD
        await team_llm_pool_release(llm_name=TEST_LLM_DEAD)
        await team_llm_pool_release(llm_name=TEST_LLM_LIVE)

        await _ping_write(TEST_LLM_DEAD, 'error')
        got = await team_llm_pool_acquire(TEST_PROJECT_ID, task_id=1, role='developer')

        assert got == TEST_LLM_LIVE


class TestPingSchedule:
    """Периодичность: пинг идёт раз в две минуты, а не каждый тик."""

    def test_ping_is_a_sweeper(self):
        """
        Пинг ходит подметальщиком — без захвата строки и вне бюджета действий.

        Считайся он действием, при `max_actions=1` тик уходил бы на пинг, а задачи
        стояли бы в очереди.
        """
        from src.worker.project.task_worker import TASK_WORKER_SINGLE_FLIGHT

        assert 'llm_ping' in TASK_WORKER_SINGLE_FLIGHT

    def test_period_key_is_not_released(self):
        """
        Ключ пинга — расписание, а не защита от дублей, и снимать его по завершении
        работы нельзя: тик идёт каждую минуту, и снятый ключ дал бы опрос вдвое чаще
        заявленного.
        """
        from src.worker.project.task_worker import TASK_WORKER_FLIGHT_PERIOD

        assert TASK_WORKER_FLIGHT_PERIOD.get('llm_ping') == 120

    def test_runner_registered(self):
        """Без записи в карте раннеров job'ы пинга уходили бы в отказ «неизвестный вид»."""
        from src.project.task.task_pipeline import _RUNNERS

        assert 'llm_ping' in _RUNNERS


async def _ping_write(name: str, status: str) -> None:
    """Записать пинг напрямую, не ходя к провайдеру: проверяем правило, а не запрос."""
    from setting_.setting_ import setting_set
    from src.project.team.team_llm_ping import TEAM_LLM_PING_KEY_PREFIX

    ping = {'status': status, 'http_status': '200' if status == 'ok' else '503',
            'ms': 10, 'at': '2026-08-30 12:00:00', 'error': None}
    await setting_set(f'{TEAM_LLM_PING_KEY_PREFIX}{name}',
                      json.dumps(ping, ensure_ascii=False), dynamic=1)


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async
    from src.project.team.team_llm_ping import TEAM_LLM_PING_KEY_PREFIX
    from src.project.team.team_llm_pool import TEAM_LLM_POOL_KEY_PREFIX

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM setting WHERE `key` = %s',
                         (f'{TEAM_LLM_POOL_KEY_PREFIX}{TEST_PROJECT_ID}',))
        await db.execute('DELETE FROM setting WHERE `key` IN (%s, %s)',
                         (f'{TEAM_LLM_PING_KEY_PREFIX}{TEST_LLM_LIVE}',
                          f'{TEAM_LLM_PING_KEY_PREFIX}{TEST_LLM_DEAD}'))
        await db.execute('DELETE FROM team_llm_lock WHERE llm_name IN (%s, %s)',
                         (TEST_LLM_LIVE, TEST_LLM_DEAD))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

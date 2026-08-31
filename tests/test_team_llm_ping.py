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

pytestmark = pytest.mark.team

# Номер проекта, которого в базе нет: пул пишется под ним, и уборка сносит ровно его.
TEST_PROJECT_ID = 987655

# Модели тестовые — попади сюда настоящая, тест переписал бы её пинг и отнял бы её у
# работающего конвейера на весь прогон.
TEST_LLM_LIVE = 'test_ping/model-live'
TEST_LLM_DEAD = 'test_ping/model-dead'

# Имя для проверок сетевых сбоев: запись каталога у них настоящая (по ней выбирается
# стратегия провайдера), а имя обязано быть тестовым — под ним пинг пишет результат
# в `setting`, и с боевым именем тест выводил бы рабочую модель из выдачи.
TEST_LLM_NETWORK = 'test_ping/network'


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


    async def test_stale_error_expires(self):
        """
        Отказ протухает. Занятую кругом модель не опрашивают вовсе, и её последняя
        запись бывает какой угодно давности; держи мы старый отказ бессрочно,
        освободившаяся модель не получила бы ни одного круга, хотя проверять её
        никто больше не пытался. Поймано живьём на `gx10/qwen-large`.
        """
        from src.project.team.team_llm_ping import (TEAM_LLM_PING_DEAD_SECONDS,
                                                    team_llm_ping_dead)

        await _ping_write(TEST_LLM_DEAD, 'error',
                          age_seconds=TEAM_LLM_PING_DEAD_SECONDS + 60)

        assert await team_llm_ping_dead([TEST_LLM_DEAD]) == set()

    async def test_fresh_error_still_counts(self):
        """Обратная половина: свежий отказ обязан выводить, иначе проверка ни о чём."""
        from src.project.team.team_llm_ping import team_llm_ping_dead

        await _ping_write(TEST_LLM_DEAD, 'error', age_seconds=30)

        assert await team_llm_ping_dead([TEST_LLM_DEAD]) == {TEST_LLM_DEAD}


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


class TestPingNetworkFailure:
    """Граница «наша сеть» / «модель»: не дозвонились — не приговор."""

    async def test_connect_failure_is_unknown(self):
        """
        Пропади интернет у этой установки — приговор получили бы разом все сетевые
        модели, и конвейер остался бы без работы по причине, к ним не относящейся.
        Поймано живьём: три модели дали `ConnectTimeout` ровно за 5 секунд — столько
        стоит `connect`, и совпадение до миллисекунд выдало общую причину.
        """
        import httpx

        from src.project.team.team_llm_ping import TEAM_LLM_PING_UNKNOWN

        ping = await _ping_with_transport_error(httpx.ConnectTimeout('нет сети'))

        assert ping['status'] == TEAM_LLM_PING_UNKNOWN
        assert 'не дозвонились' in ping['error']

    async def test_read_timeout_is_error(self):
        """
        Обратная половина: соединение установилось, ответа нет — это про модель.
        Запрос принят, справиться не удалось; такую выводим из выдачи.
        """
        import httpx

        ping = await _ping_with_transport_error(httpx.ReadTimeout('молчит'))

        assert ping['status'] == 'error'
        assert 'ReadTimeout' in ping['error']


class TestPingSkipsLocal:
    """Локальную модель не пингуем: проверка отняла бы у неё карту."""

    async def test_local_model_is_marked_skipped(self):
        """
        Запрос не уходит вовсе, а в записи стоит `skipped` — не `error` и не `unknown`.

        Разница существенна: `skipped` это наше решение, а не неудача, и на странице
        оно читается иначе.

        Каталог подменяем: на хосте, где идут тесты, он не смонтирован — это чужой
        репозиторий, — и `team_llm_catalog_models` отдаёт запасную запись. Она сейчас
        как раз локальная, так что тест был бы зелёным и без проверяемого правила:
        совпадение, на которое опираться нельзя.
        """
        from unittest.mock import patch

        import src.project.team.team_llm_ping as ping_module

        async def _entry(name):
            return {'name': 'gx10/qwen-large', 'target': 'openai/qwen3.6',
                    'key_env': 'GX10_API_KEY', 'url_env': 'GX10_URL', 'port': 4000}

        with patch.object(ping_module, 'team_llm_catalog_entry', _entry):
            ping = await ping_module.team_llm_ping_one('gx10/qwen-large')

        assert ping['status'] == ping_module.TEAM_LLM_PING_SKIPPED
        assert ping['ms'] is None, 'запрос не отправлялся — замеру взяться неоткуда'

    async def test_skipped_model_is_not_dead(self):
        """Пропущенная получает круги как обычно: мы её не проверяли, а не забраковали."""
        from src.project.team.team_llm_ping import (TEAM_LLM_PING_SKIPPED,
                                                    team_llm_ping_dead)

        await _ping_write(TEST_LLM_DEAD, TEAM_LLM_PING_SKIPPED)

        assert await team_llm_ping_dead([TEST_LLM_DEAD]) == set()

    def test_local_is_decided_by_strategy(self):
        """
        Кто локальный — знает стратегия провайдера, а не список имён в пинге.

        Иначе новая локальная модель молча попала бы под опрос и начала делиться
        картой с проверкой.
        """
        from src.project.team.team_llm_ping import team_llm_ping_skipped

        assert team_llm_ping_skipped({'name': 'gx10/qwen-large', 'target': 'openai/qwen3.6'})
        assert not team_llm_ping_skipped(
            {'name': 'deepseek-v4-flash-0731-2',
             'target': 'openrouter/deepseek/deepseek-v4-flash-0731'})

    def test_unknown_service_is_not_treated_as_local(self):
        """
        Неопознанный сервис скорее сетевой: ошибиться безопаснее в сторону лишнего
        запроса, чем непроверенной модели.
        """
        from src.project.team.team_llm_ping import team_llm_ping_skipped

        assert not team_llm_ping_skipped({'name': 'что-то', 'target': 'вообще-непонятно'})


class TestPingSkipsBusy:
    """Занятую кругом модель не пингуем: она и так доказала, что работает."""

    async def test_busy_model_is_skipped(self):
        """
        Пинг встаёт в очередь за кругом роли. Локальная модель, занятая кругом QA, не
        ответила и за 100 секунд — работая при этом безупречно; пометь её проверка
        «не отвечает», конвейер лишился бы ровно той модели, которая делает работу.
        """
        from src.project.team.team_llm_ping import team_llm_ping_all
        from src.project.team.team_llm_pool import team_llm_pool_acquire, team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_DEAD])
        got = await team_llm_pool_acquire(TEST_PROJECT_ID, task_id=0, role='developer')
        assert got == TEST_LLM_DEAD, 'модель должна быть захвачена — иначе тест ни о чём'

        result = await team_llm_ping_all([TEST_LLM_DEAD])

        assert result == {}, 'занятая модель в опрос не попадает'

    async def test_free_model_is_pinged(self):
        """Обратная половина: свободную опрашиваем — иначе пропуск съел бы проверку целиком."""
        from src.project.team.team_llm_ping import team_llm_ping_all
        from src.project.team.team_llm_pool import team_llm_pool_set

        await team_llm_pool_set(TEST_PROJECT_ID, [TEST_LLM_DEAD])

        result = await team_llm_ping_all([TEST_LLM_DEAD])

        assert set(result) == {TEST_LLM_DEAD}


class TestPingSchedule:
    """Периодичность: пинг идёт раз в пять минут, а не каждый тик."""

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
        работы нельзя: тик идёт каждую минуту, и снятый ключ дал бы опрос впятеро
        чаще заявленного.
        """
        from src.worker.project.task_worker import TASK_WORKER_FLIGHT_PERIOD

        assert TASK_WORKER_FLIGHT_PERIOD.get('llm_ping') == 300

    def test_runner_registered(self):
        """Без записи в карте раннеров job'ы пинга уходили бы в отказ «неизвестный вид»."""
        from src.project.task.task_pipeline import _RUNNERS

        assert 'llm_ping' in _RUNNERS


async def _ping_with_transport_error(error: Exception) -> dict:
    """
    Пропинговать сетевую модель, подменив каталог оболочки и транспорт.

    Подменяем ровно два внешних куска: файл каталога (на хосте, где идут тесты, он не
    смонтирован — это чужой репозиторий) и `httpx.AsyncClient.post`. Всё, что между
    ними, настоящее: выбор стратегии по имени, адрес из `.env`, сборка тела. Заглуши
    мы весь пинг, тест подтверждал бы только сам себя.

    **Имя модели тестовое, хотя запись каталога настоящая.** `team_llm_ping_one`
    пишет результат в `setting` — в ту же таблицу, по которой конвейер решает, кому
    выдавать круги. С настоящим именем тест оставлял бы боевой модели фиктивный
    отказ и выводил бы её из работы; поймано живьём: в базе висело
    `team_llm_ping_deepseek-v4-flash-0731-1` со словами «ReadTimeout: молчит» —
    текстом из этого самого теста.

    `target` при этом настоящий: по нему выбирается стратегия провайдера, а её выбор
    мы и проверяем. Подменять его значило бы проверять заглушку.
    """
    from unittest.mock import patch

    import httpx

    import src.project.team.team_llm_ping as ping_module

    entry = {'name': TEST_LLM_NETWORK,
             'target': 'openrouter/deepseek/deepseek-v4-flash-0731',
             'key_env': 'OPENROUTER_API_KEY', 'url_env': '', 'port': 4001}

    async def _entry(name):
        return entry

    async def _raise(*args, **kwargs):
        raise error

    with patch.object(ping_module, 'team_llm_catalog_entry', _entry), \
         patch.object(httpx.AsyncClient, 'post', _raise):
        return await ping_module.team_llm_ping_one(entry['name'])


async def _ping_write(name: str, status: str, age_seconds: int = 0) -> None:
    """
    Записать пинг напрямую, не ходя к провайдеру: проверяем правило, а не запрос.

    `age_seconds` — насколько состарить отметку. Время берётся тем же способом, что и
    в самом пинге (UTC): разойдись они, «свежий» отказ уезжал бы на целый пояс, и
    тест на протухание проверял бы разницу часовых поясов, а не срок.
    """
    from datetime import timedelta

    from datetime_.datetime_ import datetime_utc_now
    from setting_.setting_ import setting_set
    from src.project.team.team_llm_ping import TEAM_LLM_PING_KEY_PREFIX

    at = (datetime_utc_now() - timedelta(seconds=age_seconds)).strftime('%Y-%m-%d %H:%M:%S')
    ping = {'status': status, 'http_status': '200' if status == 'ok' else '503',
            'ms': 10, 'at': at, 'error': None}
    await setting_set(f'{TEAM_LLM_PING_KEY_PREFIX}{name}',
                      json.dumps(ping, ensure_ascii=False), dynamic=1)


async def _cleanup() -> None:
    from mysql_.mysql_ import mysql_get_db_async
    from src.project.team.team_llm_ping import TEAM_LLM_PING_KEY_PREFIX
    from src.project.team.team_llm_pool import TEAM_LLM_POOL_KEY_PREFIX

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM setting WHERE `key` = %s',
                         (f'{TEAM_LLM_POOL_KEY_PREFIX}{TEST_PROJECT_ID}',))
        await db.execute('DELETE FROM setting WHERE `key` IN (%s, %s, %s)',
                         (f'{TEAM_LLM_PING_KEY_PREFIX}{TEST_LLM_LIVE}',
                          f'{TEAM_LLM_PING_KEY_PREFIX}{TEST_LLM_DEAD}',
                          f'{TEAM_LLM_PING_KEY_PREFIX}{TEST_LLM_NETWORK}'))
        await db.execute('DELETE FROM team_llm_lock WHERE llm_name IN (%s, %s)',
                         (TEST_LLM_LIVE, TEST_LLM_DEAD))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

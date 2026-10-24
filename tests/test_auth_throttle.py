"""Заслон от подбора пароля: пауза между неудачами входа удваивается.

## ⚠⚠⚠ Что здесь главное

**Смена адреса не обходит заслон.** Счёт ведётся и по логину, и по адресу, и
держит строгий из двух; будь он только по адресу — перебор шёл бы с десяти
машин и упирался бы в десять независимых счётчиков, то есть ни во что.

Остальное — про то, что заслон обещает:

* первая же неудача заводит паузу, следующая попытка получает `429` с
  `Retry-After`, а не `401`: человек должен отличить «пароль не тот» от
  «подожди», иначе он начнёт менять верный пароль на другой верный;
* пауза **растёт**: 1, 2, 4, 8 … до потолка в 15 минут;
* стучать в закрытую дверь бесполезно, но и безвредно — `429` счёт **не**
  увеличивает, иначе любой желающий догонял бы чужой логин до потолка простым
  спамом, не зная ни одного пароля;
* удачный вход всё забывает.

## ⚠⚠ Только HTTP, в базу отсюда не ходим

Первая запись случаев чистила `auth_attempt` своим запросом и разваливалась на
втором же тесте: `RuntimeError: got Future attached to a different loop`. Пул
MySQL привязан к циклу событий, в котором заведён, а `pytest-asyncio` даёт
случаю свой цикл. Поэтому сюита и ходит по HTTP — а уборка живёт в
`conftest.cleanup_test_tasks`, у которого цикл свой.

Отсюда же форма проверок: «счёт сброшен» подтверждается не строкой в базе, а
тем, что следующая попытка получает `401`, а не `429`.

## ⚠⚠ Случаи не запирают живых людей

Логины выдуманные (`__pytest_throttle_*`), адреса — из диапазона RFC 5737,
отведённого стандартом под примеры. `X-Forwarded-For` сюда доезжает, потому что
сервер запущен с `--proxy-headers` и доверяет частным сетям; свой адрес у
каждого случая означает ещё и то, что случаи не мешают друг другу.

⚠ Клиент заводится `httpx.AsyncClient` напрямую — как и вся сюита
(`test_login.py`). Общий транспорт слоя (`http_pool_transport`) тут не при чём:
он про переиспользование соединений и прокси на внешних запросах.
"""
import asyncio
import os
import uuid
from typing import AsyncGenerator

import httpx
import pytest

from tests.constants import TEST_AUTH

pytestmark = pytest.mark.auth

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

# ⚠ Потолок роста из `panel_auth_throttle.py`. Здесь он нужен только как
# граница ожиданий: случаи до него не доходят — это были бы четверть часа сна.
THROTTLE_MAX_SECONDS = 900

# Сеть из RFC 5737 — та, что отведена стандартом под примеры.
THROTTLE_NET = '203.0.113'


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=20.0) as one:
        yield one


@pytest.fixture
def spot() -> tuple:
    """Выдуманные логин и адрес — свои у каждого случая.

    Returns:
        tuple: `(login, ip)`.
    """
    mark = uuid.uuid4().hex[:8]

    return (f'__pytest_throttle_{mark}',
            f'{THROTTLE_NET}.{int(mark[:2], 16) % 200 + 1}')


class TestChangingAddressDoesNotHelp:
    """⚠⚠⚠ Главное. Заслон, который обходится сменой IP, — не заслон."""

    async def test_the_login_stays_locked_from_another_address(self, client, spot):
        login, ip = spot

        first = await _miss(client, login, ip)
        assert first.status_code == 401, first.text

        # Тот же логин, другой адрес — счёт логина про адрес не знает.
        again = await _miss(client, login, f'{THROTTLE_NET}.254')

        assert again.status_code == 429, 'смена адреса сняла запрет'
        assert int(again.headers.get('Retry-After', 0)) > 0


class TestTheFirstMissAlreadyCosts:

    async def test_a_wrong_password_answers_401(self, client, spot):
        login, ip = spot

        assert (await _miss(client, login, ip)).status_code == 401

    async def test_the_next_attempt_is_429_with_retry_after(self, client, spot):
        """⚠ Именно `429`, а не `401`: иначе человек решит, что пароль неверен,
        и начнёт перебирать свои собственные."""
        login, ip = spot
        await _miss(client, login, ip)

        said = await _miss(client, login, ip)

        assert said.status_code == 429, said.text
        assert int(said.headers.get('Retry-After', 0)) >= 1


class TestThePauseGrows:
    """⚠⚠ Рост — вся суть: постоянная пауза в секунду дала бы 86 400 попыток
    в сутки, растущая даёт около сотни."""

    async def test_each_miss_doubles_the_wait(self, client, spot):
        login, ip = spot
        seen = []

        for _ in range(3):
            await _miss(client, login, ip)
            wait = int((await _miss(client, login, ip))
                       .headers.get('Retry-After', 0))
            seen.append(wait)
            await asyncio.sleep(wait + 0.3)

        assert seen == sorted(seen), f'пауза не росла: {seen}'
        assert seen[-1] > seen[0], f'пауза не выросла за три промаха: {seen}'
        assert max(seen) <= THROTTLE_MAX_SECONDS


class TestKnockingDoesNotAddTime:
    """⚠⚠ `429` счёт не увеличивает — иначе чужой логин догоняли бы до потолка
    спамом, не зная ни одного пароля."""

    async def test_ten_refusals_do_not_extend_the_pause(self, client, spot):
        login, ip = spot
        await _miss(client, login, ip)

        first = int((await _miss(client, login, ip)).headers.get('Retry-After', 0))

        for _ in range(10):
            await _miss(client, login, ip)

        after = int((await _miss(client, login, ip)).headers.get('Retry-After', 0))

        assert after <= first, f'стук в стену удлинил паузу: {first} → {after}'


class TestASuccessfulLoginForgetsEverything:

    async def test_after_a_real_login_the_pause_is_gone(self, client):
        """⚠⚠ Проверяется наблюдаемое: следующая неудача получает `401`, то
        есть её вообще пустили считать. Останься счёт — был бы `429`.

        ⚠ Между промахом и входом ждём назначенную паузу: без этого удачный
        вход сам упёрся бы в заслон, и случай проверял бы не то.
        """
        login = TEST_AUTH['username']
        ip = f'{THROTTLE_NET}.230'

        await _miss(client, login, ip)

        entered = await _enter(client, ip)
        assert entered.status_code == 200, entered.text

        after = await _miss(client, login, ip)

        assert after.status_code == 401, 'счёт пережил удачный вход'

        # ⚠⚠⚠ Убрать за собой ОБЯЗАТЕЛЬНО, и это куплено упавшей сюитой:
        # проверка выше заканчивается промахом, то есть оставляет тестовую
        # учётку под паузой в секунду. Соседний файл (`test_login.py`) входит
        # под ней же и получал `429` — семнадцать его случаев проходили по
        # одиночке и падали в общем прогоне.
        #
        # ⚠ Счёт логина общий на всю сюиту: своим адресом тут не отгородиться,
        # в этом и смысл заслона (`TestChangingAddressDoesNotHelp`).
        assert (await _enter(client, ip)).status_code == 200


class TestTheDoorStillWorks:
    """⚠ Заслон не имеет права мешать обычному входу — ради этого он и стоит."""

    async def test_a_valid_login_passes(self, client):
        said = await _enter(client, f'{THROTTLE_NET}.231')

        assert said.status_code == 200, said.text


async def _miss(client: httpx.AsyncClient, login: str, ip: str) -> httpx.Response:
    """Попытка входа с заведомо неверным паролем от названного адреса."""
    return await client.post(
        '/auth/login',
        json={'username': login, 'password': 'definitely-not-the-password'},
        headers={'X-Forwarded-For': ip})


async def _enter(client: httpx.AsyncClient, ip: str) -> httpx.Response:
    """Войти по-настоящему; упёрлись в паузу — переждать и повторить однажды.

    ⚠⚠ Пробовать «не настоящим» паролем, чтобы узнать срок, **нельзя**: такая
    проба сама идёт в счёт, и функция, призванная дождаться свободной двери,
    оставляла бы за собой новую паузу. Первая запись случаев делала именно так
    и держалась на том, что между запросами успевала пройти секунда.

    ⚠ Повтор один: пауза длиннее круга означает, что случай мерит не то, и
    честнее упасть, чем ждать четверть часа.
    """
    said = await client.post('/auth/login', json=TEST_AUTH,
                             headers={'X-Forwarded-For': ip})

    if said.status_code != 429:
        return said

    await asyncio.sleep(min(int(said.headers.get('Retry-After', 1)),
                            THROTTLE_MAX_SECONDS) + 0.3)

    return await client.post('/auth/login', json=TEST_AUTH,
                             headers={'X-Forwarded-For': ip})

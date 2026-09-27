"""Pytest configuration for RhapsodyAi tests."""
import os
import pytest
import asyncio
import httpx
import uuid
from typing import AsyncGenerator

from tests.constants import TEST_SESSION_UUID, TEST_SESSION_AGENT_ID, TEST_AUTH, TEST_AUTH_ROLE

# Тесты идут с хоста, а `MYSQL_HOST=mysql` — имя сервиса внутри compose-сети.
#
# Правкой одного `os.environ` тут не обойтись: `mysql_.mysql_` читает адрес
# один раз, на импорте модуля, а `config.config` вдобавок накатывает `.env.local`
# с `override=True` — то есть любое значение, выставленное до импорта, вернётся
# обратно в `mysql`. Поэтому переопределяем и окружение (для всего, что читает
# конфиг позже), и уже связанные атрибуты модуля.
#
# Делается на импорте conftest — раньше, чем pytest импортирует модули тестов, и
# значит раньше любого их `from mysql_.mysql_ import ...`.
MYSQL_TEST_HOST = 'localhost'
MYSQL_TEST_PORT = '3302'

os.environ['MYSQL_HOST'] = MYSQL_TEST_HOST
os.environ['MYSQL_PORT'] = MYSQL_TEST_PORT

import mysql_.mysql_ as _mysql_module  # noqa: E402  импорт после правки окружения — намеренно

_mysql_module.host = MYSQL_TEST_HOST
_mysql_module.port = int(MYSQL_TEST_PORT)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Configure pytest-asyncio for async fixtures
pytestmark = pytest.mark.asyncio


def pytest_configure(config):
    """Configure pytest with custom settings."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring running services"
    )


@pytest.fixture
async def client():
    """Вошедший в панель клиент — под учёткой сюиты, не под админской.

    ⚠⚠ **Завелась потому, что этих четырёх строк в `tests/` было двадцать три копии.**
    Двадцать три файла объявляли свой `client` слово в слово: адрес, `follow_redirects`,
    таймаут, вход. Это далеко за порогом правила трёх (`code_rules.md`, §4.2): смени
    таймаут или способ входа — и правка нужна в двадцати трёх местах, а разойдутся они
    молча.

    Внутри — общий `uvicorn_panel_client` из слоя, а не своя сборка httpx: вход
    контрактом панели (JSON-телом, на форме она отвечает 422) и перезаход на 401 уже
    написаны там.

    ⚠⚠⚠ **Учётка передаётся явно, и это не перестраховка.** По умолчанию тот клиент
    входит под `ADMIN_*` из `.env` — то есть под человеком. Сюита обязана ходить под
    своей неадминской учёткой (`testing_rules.md`, §3), и на этом стоит уборка за
    прогоном: `cleanup_test_rows` находит строки **по хозяину**. Войди сюита админом —
    её мусор стал бы неотличим от рабочих данных, а уборка перестала бы его видеть.

    ⚠ Адрес тоже явно: сам он выводит его из compose, а сюите нужен `BASE_URL` — тот,
    что переключает прогон на сервер ветки.

    ⚠⚠ **Клиент не закрывается намеренно.** Транспорт у него общий на процесс
    (`http_pool_transport`), и `aclose()` унёс бы его у всех, кто ещё работает.

    ⚠ Своя копия остаётся законной там, где фикстура **делает ещё что-то** — заводит
    данные, убирает за собой, отдаёт пару «клиент + номер». Таких восемнадцать, и
    сводить их нельзя: у них разные обязанности, а не разные имена одной. Двадцать три
    простые сводятся, **когда их и так правят** (§4.2): одновременная правка
    двадцати трёх чужих файлов — риск больше пользы.
    """
    from uvicorn_.uvicorn_panel import uvicorn_panel_client

    yield await uvicorn_panel_client(base=BASE_URL,
                                     user=TEST_AUTH['username'],
                                     password=TEST_AUTH['password'])


# Адрес сервера, который проверяет сюита.
#
# По умолчанию это основной `uvicorn` установки — так сюиту запускает человек.
# Но QA конвейера проверяет не его, а сервер ветки подзадачи (`uvicorn_task`,
# свой порт): на общем `:8011` работает код основного чекаута, и сюита там
# зелёная независимо от того, что сделал разработчик.
#
# Поэтому адрес можно подменить окружением на один прогон:
#   BASE_URL=http://localhost:8013 .venv/bin/python3 -m pytest tests/
#
# Имя переменной то же, что уже читают `test_team_task_pages.py` и
# `manual_test_team_task.py`, — одна команда должна переключать всю сюиту.
BASE_URL = os.getenv('BASE_URL', '').strip().rstrip('/') or "http://localhost:8011"
TEST_USER_PREFIX = "test_"
TEST_AGENT_PREFIX = "test_agent_"


TEST_ROLE_NAMES = ("test_role", "updated_role")


@pytest.fixture(scope="session", autouse=True)
async def cleanup_test_users() -> AsyncGenerator[None, None]:
    """Session-scoped fixture to clean up test users before and after all tests."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        await client.post(
            "/auth/login",
            json=TEST_AUTH,
        )
        await _cleanup_test_users(client)
        await _cleanup_test_agents(client)
        await _cleanup_test_roles(client)
    yield
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        await client.post(
            "/auth/login",
            json=TEST_AUTH,
        )
        await _cleanup_test_users(client)
        await _cleanup_test_agents(client)
        await _cleanup_test_roles(client)


# ── Уборка за кодом под тестом: строки, у которых нет имени ──────────────────
#
# ⚠⚠ Фикстуры выше убирают **по имени**: пользователь с префиксом `test_`, агент
# `test_agent_`, роль из списка. Это работает, пока запись заводит сам тест и знает,
# как он её назвал.
#
# Но большую часть мусора заводит не тест, а **код под тестом**. Один вызов
# `/chat/ask` оставляет после себя сессию агента, след прогона workflow с деревом
# шагов, строки запросов к модели и сколько-то фактов, которые агент сочинил сам.
# Имён у этих строк нет, номеров их тест не знает, и «подчистить за собой» ему
# нечем: он не видел, что именно завелось.
#
# Общее у них одно — **хозяин**. Сюита ходит под отдельной неадминской учёткой
# ровно затем, чтобы по строке было видно, кто её завёл: сюита или человек
# (`testing_rules.md`, §3). Этого признака для уборки достаточно, и другого нет.
#
# ⚠ Замер до первой уборки, три дня прогонов: 95 268 строк тестовой учётки в
# таблицах ниже плюс 76 744 шага следов каскадом — около 172 тысяч.
TEST_SWEEP_TABLES = (
    # ⚠ Порядок между ними не важен: внешних ключей друг на друга у этих четырёх
    # нет. А `agent_workflow_trace_step` уедет **сам** — он висит на следе через
    # `ON DELETE CASCADE`, и удалять его отдельной строкой значило бы записать это
    # правило вторым местом, своими словами.
    'fact',
    'agent_workflow_trace',
    'agent_session',
    'llm_request',
)

# ⚠⚠ Список **белый, а не чёрный**, и это не вкусовщина. У тестовой учётки есть
# строки, которые мусором не являются: её токен доступа (`user_access_token`), её
# узлы (`user_node`), её настройки (`setting`), её проекты. Снеси их «за компанию» —
# и следующий прогон не войдёт. Поэтому перечисляем то, что убираем, а не то, что
# бережём: забытое в чёрном списке стоит сломанного прогона, забытое в белом —
# всего лишь неубранного хвоста.

# Снимает уборку целиком: `KEEP_TEST_DATA=1 .venv/bin/python -m pytest …`
TEST_SWEEP_KEEP = 'KEEP_TEST_DATA'

# Адрес Qdrant **с хоста**: снаружи compose-сети он опубликован другим портом
# (`0.0.0.0:6335->6333`). Тот же приём и тот же довод, что у `MYSQL_TEST_*` выше.
QDRANT_TEST_HOST = os.getenv('QDRANT_TEST_HOST', 'localhost').strip() or 'localhost'
QDRANT_TEST_PORT = int(os.getenv('QDRANT_PORT', '6335') or 6335)


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_rows():
    """Уборка строк тестовой учётки — и до прогона, и после него.

    ⚠ **До** — потому что хвост остаётся и от упавшего прогона, и от прерванного
    `Ctrl-C`, когда до уборки дело не дошло вовсе. Без этого шага база копит мусор
    ровно в тех случаях, ради которых уборка и нужна.

    ⚠⚠ **После** — то, о чём просили: прогон не оставляет следов. Цена известна и
    принята: упавший прогон уносит с собой и свои следы, а смотреть в них иногда
    надо. На этот случай `KEEP_TEST_DATA=1` снимает уборку целиком — и ту, что до,
    тоже: «не трогай мои данные» значит не трогай.
    """
    keep = str(os.getenv(TEST_SWEEP_KEEP, '')).strip().lower() in ('1', 'true', 'yes')

    if keep:
        print(f'\n⚠ {TEST_SWEEP_KEEP} — уборка за прогоном снята, строки останутся')
        yield
        return

    _test_rows_drop()
    yield
    counted = _test_rows_drop()

    if counted:
        said = ', '.join(f'{name}: {qty}' for name, qty in counted.items())
        print(f'\nУбрано за прогоном — {said}')


# Все задачи сюиты называются с этого префикса (`test_task_pipeline`, `test_task_tree`,
# `test_task_metadata`, `test_planning`). Подчёркивания экранированы: в LIKE `_` — это
# любой один символ, и без экранирования шаблон подошёл бы к чужому заголовку.
TEST_TASK_TITLE_LIKE = r'\_\_pytest%'

# ⚠ Уборка забытых вкладок и имя сайта-закладки уехали в `tests_browser/conftest.py`
# вместе с браузерными тестами: они про контейнер-браузер, то есть про ту папку.
# Здесь она ходила бы к нему на каждом прогоне впустую — и мимо сторожа сети ниже.


# ── Сторож сети ──────────────────────────────────────────────────────────────
#
# ⚠ **Сюита не имеет права ходить наружу.** Ни в чужой проект, ни на чужой сайт,
# ни к платному API. Причин три, и все проверены делом в соседнем проекте:
#
# * **тест против чужой системы проверяет не нас.** Он краснеет от чужого
#   перезапуска, от занятого пула, от переименованной записи — и молчит про то,
#   ради чего написан;
# * **он ДЕЛАЕТ там работу.** Заход в чужой API — действие под живой учёткой;
#   вызов модели занимает очередь ноды, общей с продом;
# * **важного им не проверить.** Оборванная связь, протухший токен, отказ 429 —
#   ждать этого в нужную секунду нельзя, а с заглушкой это строка в тесте.
#
# Обещание тут не работает: заглушку забывают, а **забытая заглушка не видна** —
# тест зеленеет, просто идёт к чужой системе.
#
# ⚠⚠ **Сторож стоит на транспорте httpx, а не на сокете.** Сокетный — первое, что
# приходит в голову, и он не ловит: в DatingAi сюита четыре раза за прогон входила
# на живой сайт знакомств, а `socket.connect` этого не видел. Причина в том, что
# часть работы уходит в **фоновые задачи**, которых тест не ждёт: задача доживает
# до следующего теста, когда сторож, снятый вместе со своим, уже не стоит.
#
# Отсюда `scope='session'`: ставится один раз на прогон и не снимается.
#
# Сам сторож — в общем слое (`py_modules/http_/http_mock.py`): правило не наше
# личное, соседним проектам оно нужно ровно так же.


@pytest.fixture(scope="session", autouse=True)
def no_outside_http():
    """⚠⚠ **Ни одного живого HTTP-запроса за пределы своей установки.**

    Разрешена ровно одна дверь — **своя панель** (`BASE_URL`): через неё сюита и
    работает, это её способ. Всё прочее — ошибка, даже если адрес выглядит
    безобидно.

    ⚠ Контейнер-браузер (`:8014`) в списке **не значится намеренно**: ходившие в
    него тесты уехали в `tests_browser/`, и здесь такой запрос означал бы, что
    кто-то завёл живой браузер в общей сюите. Пусть красное скажет об этом сразу.

    ⚠⚠ **Чего сторож не видит в принципе.** Он стоит на транспорте httpx **в
    нашем процессе** — значит запрос, сделанный чужим процессом, ему невидим. Так
    ходит наружу контейнер-браузер: Chromium внутри него открывает страницу сам.
    Ровно поэтому браузерные тесты вынесены из автоматического прогона, а не
    прикрыты сторожем: прикрыть их отсюда нечем.
    """
    from http_.http_mock import http_mock_guard

    # ⚠⚠ Подменная модель — **своя установка, а не «наружу»**. Она поднимается
    # фикстурой `tests_llm` на этой же машине и отвечает вместо живой ноды;
    # запрет к ней означал бы, что тесты workflow нельзя гонять вместе со
    # всеми — то есть ровно то, ради отмены чего подмена и сделана.
    #
    # ⚠ Адрес берётся из той же настройки, что читают тесты, а не переписан
    # числом: сменят порт — список разрешённого сменится вместе с ним.
    from tests_llm.conftest import LLM_FAKE_URL

    with http_mock_guard(allow=_own_hosts_ports(BASE_URL, LLM_FAKE_URL)):
        yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_tasks():
    """
    Снести задачи сюиты до и после прогона.

    Фикстуры тестов убирают за собой сами, но прерванный прогон (Ctrl-C, таймаут,
    упавший сервер) оставляет строки в рабочей БД — а конвейер их подхватывает
    всерьёз. Задача без плана уходит живому Менеджеру независимо от статуса
    (`task_claim_task_unplanned`), и агентское время тратится на пустышку в общей
    очереди с настоящими задачами. Найдено на живой установке: 57 брошенных строк,
    15 из них ждали Менеджера, трём план был уже написан.

    Одним DELETE и по всем проектам: подзадачи, попытки и ревизии уходят каскадом
    (`fk_pt_parent`, `fk_pta_task`, `fk_ptpr_task` в `migrations/0001.sql`), а
    тестовые задачи заводятся и без проекта, и внутри него.

    Свой цикл событий и `mysql_pool_close()` — по той же причине, что у
    `create_test_user`: пул модульный и привязан к циклу, в котором создан.
    """
    from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

    async def _sweep() -> None:
        async with mysql_get_db_async() as db:
            await db.execute(
                "DELETE FROM project_task WHERE title LIKE %s", (TEST_TASK_TITLE_LIKE,))
            await db.connection.commit()

    def _run() -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_sweep())
            loop.run_until_complete(mysql_pool_close())
        finally:
            loop.close()

    _run()
    yield
    _run()


@pytest.fixture(scope="session", autouse=True)
def create_test_user():
    """
    Убедиться, что QA-учётка из `TEST_AUTH` существует, и починить ей пароль.

    Пользователя (`vova.tkachenko`, роль `qa`) заводит человек, а не тесты, поэтому
    после прогона он **не удаляется** — снести чужую учётку сюита не вправе. Раньше
    фикстура создавала `test_runner` и удаляла его в конце; вдобавок его сносил
    `_cleanup_test_users()` по префиксу `test_`, и следующий прогон падал на 401.

    Пароль перезаписываем: он живёт в `.env`, и расхождение с БД — единственная
    причина, по которой вся сюита валится на логине, а выглядит это как
    «сломалась авторизация».
    """
    test_username = TEST_AUTH['username']
    test_password = TEST_AUTH['password']
    if not test_username or not test_password:
        yield
        return

    import bcrypt
    from mysql_.mysql_ import mysql_get_db_async, mysql_pool_close

    password_hash = bcrypt.hashpw(test_password.encode(), bcrypt.gensalt()).decode()

    async def _ensure():
        async with mysql_get_db_async() as db:
            await db.execute("SELECT id FROM `user` WHERE username = %s", (test_username,))
            row = await db.fetchone()
            if row:
                await db.execute(
                    "UPDATE `user` SET password_hash = %s WHERE id = %s", (password_hash, row['id']))
            else:
                # Роль ищем по имени: id роли `qa` на разных инсталляциях разный.
                await db.execute("SELECT id FROM `role` WHERE name = %s", (TEST_AUTH_ROLE,))
                role = await db.fetchone()
                await db.execute(
                    "INSERT INTO `user` (username, email, password_hash, role_id, dynamic) "
                    "VALUES (%s, %s, %s, %s, 0)",
                    (test_username, f"{test_username}@test.local", password_hash,
                     role['id'] if role else None)
                )
            await db.connection.commit()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_ensure())
    loop.run_until_complete(mysql_pool_close())
    loop.close()

    yield


@pytest.fixture(scope="session", autouse=True)
def seed_test_session():
    """Seed a known agent_session row used by session tests, clean up after."""
    from src.ai.ai_session import ai_session_message_add
    from mysql_.mysql_ import mysql_get_db_async

    req_uuid = str(uuid.uuid4())

    async def _seed():
        await ai_session_message_add(TEST_SESSION_UUID, req_uuid, None, 1,
                                     'user', TEST_SESSION_AGENT_ID, 'user-prompt', 'test prompt')
        await ai_session_message_add(TEST_SESSION_UUID, req_uuid, None, 1,
                                     'assistant', TEST_SESSION_AGENT_ID, 'response-final', 'test response')

    from mysql_.mysql_ import mysql_pool_close

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_seed())
    loop.run_until_complete(mysql_pool_close())
    loop.close()

    yield

    async def _cleanup():
        async with mysql_get_db_async() as db:
            await db.execute("DELETE FROM agent_session WHERE session_uuid = %s", (TEST_SESSION_UUID,))
            await db.connection.commit()
        await mysql_pool_close()

    loop2 = asyncio.new_event_loop()
    loop2.run_until_complete(_cleanup())
    loop2.close()


async def _cleanup_test_users(client: httpx.AsyncClient) -> None:
    """Delete all users with username starting with TEST_USER_PREFIX."""
    try:
        response = await client.get("/user/list")
        if response.status_code != 200:
            return
        users = response.json().get("result", [])
        test_users = [u for u in users if u.get("username", "").startswith(TEST_USER_PREFIX)]
        for user in test_users:
            try:
                await client.delete(f"/user/{user['id']}")
            except Exception:
                pass  # Ignore individual deletion errors
    except Exception:
        pass  # Ignore cleanup errors


async def _cleanup_test_agents(client: httpx.AsyncClient) -> None:
    """Delete all agents with name starting with TEST_AGENT_PREFIX."""
    try:
        response = await client.get("/agent/list")
        if response.status_code != 200:
            return
        agents = response.json().get("result", [])
        test_agents = [a for a in agents if a.get("name", "").startswith(TEST_AGENT_PREFIX)]
        for agent in test_agents:
            try:
                await client.delete(f"/agent/{agent['id']}")
            except Exception:
                pass  # Ignore individual deletion errors
    except Exception:
        pass  # Ignore cleanup errors


async def _cleanup_test_roles(client: httpx.AsyncClient) -> None:
    """Delete leftover roles created by test_role_crud.py."""
    try:
        response = await client.get("/role/list")
        if response.status_code != 200:
            return
        roles = response.json().get("result", [])
        test_roles = [r for r in roles if r.get("name") in TEST_ROLE_NAMES]
        for role in test_roles:
            try:
                await client.delete(f"/role/{role['id']}")
            except Exception:
                pass  # Ignore individual deletion errors
    except Exception:
        pass  # Ignore cleanup errors


def _test_user_id() -> int:
    """Номер тестовой учётки — по имени входа, а не числом.

    ⚠ Зашить число нельзя: автономер у каждой инсталляции свой. Здесь 170, на
    соседней машине другой — и уборка молча не нашла бы ничего.

    ⚠⚠ Ходим `mysql_query_run`, а не пулом приложения, по тому же доводу, что и
    уборка в `tests_llm/conftest.py`: пул живёт в процессе приложения, а сюита —
    отдельный процесс, и адрес базы у неё свой (`mysql_host_address`).
    """
    from mysql_.mysql_query import mysql_query_run

    got = mysql_query_run('SELECT `id` FROM `user` WHERE `username` = %s',
                          (str(TEST_AUTH.get('username') or ''),))
    rows = got.get('rows') or []
    return int(rows[0]['id']) if rows else 0


def _test_vectors_drop(rows: list) -> int:
    """Убрать из Qdrant точки удаляемых фактов; вернуть, сколько их было.

    ⚠⚠ Зовётся **до** удаления строк: точка адресуется номером строки MySQL —
    `uuid5(NAMESPACE_DNS, 'fact_id_<id>')`, см. `qdrant_save`, — и после `DELETE`
    этих номеров уже не узнать. Строки уйдут, вектора останутся навсегда.

    ⚠ Удаляем **по номерам точек**, а не фильтром `qdrant_remove_by` по
    `document_id`: у половины тестовых фактов ключ пуст (их пишет
    `companion_fact_extract`), а с пустым фильтром та функция честно не делает
    ничего — и молча.
    """
    if not rows:
        return 0

    async def _drop() -> int:
        from qdrant_client import AsyncQdrantClient, models

        # ⚠⚠ Свой клиент, а НЕ `_qdrant_db_get_client()`. Тот зашивает
        # `host="qdrant", port=6333` — имя сервиса внутри compose-сети, — и с хоста,
        # где идёт сюита, не разрешается вовсе. Первая версия этой уборки звала его
        # и молча падала в `except`: строки в MySQL исчезали, а 92 точки оставались
        # при 55 живых фактах. Ровно тот же разрыв «хост против сети compose», что
        # разобран выше для MySQL, и лечится он так же.
        #
        # ⚠ Клиент **местный, а не подменённый глобально**: singleton в
        # `qdrant_.qdrant_` трогать нельзя — им пользуется код под тестом, и
        # подмена сделала бы достижимым то, что тесты считают недоступным.
        client = AsyncQdrantClient(host=QDRANT_TEST_HOST, port=QDRANT_TEST_PORT)
        by_collection = {}
        for one in rows:
            point = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"fact_id_{int(one['id'])}"))
            by_collection.setdefault(str(one['collection']), []).append(point)

        gone = 0
        try:
            for name, points in by_collection.items():
                if not await client.collection_exists(name):
                    continue
                await client.delete(collection_name=name,
                                    points_selector=models.PointIdsList(points=points))
                gone += len(points)
        finally:
            await client.close()

        return gone

    # ⚠ Отказ Qdrant не должен ронять прогон — уборка не то, ради чего он запущен.
    # Но и промолчать нельзя: невидимый отказ значит, что вектора копятся годами.
    try:
        return asyncio.run(_drop())
    except Exception as err:
        print(f'\n⚠ уборка Qdrant не удалась ({err}) — вектора остались')
        return 0


def _test_rows_drop() -> dict:
    """Снести строки тестовой учётки из таблиц-накопителей.

    Returns:
        `{имя таблицы: сколько удалено}`, плюс ключ `qdrant` — сколько снято точек.
        Пустой словарь значит «убирать было нечего».
    """
    from mysql_.mysql_query import mysql_query_run

    who = _test_user_id()
    if not who:
        return {}

    # Факты — первыми и с номерами: по ним снимаются вектора (см. ⚠⚠ выше).
    facts = mysql_query_run(
        'SELECT f.`id`, fc.`name` AS `collection`'
        '  FROM `fact` f JOIN `fact_collection` fc ON fc.`id` = f.`collection_id`'
        ' WHERE f.`user_id` = %s', (who,)).get('rows') or []

    counted = {}
    # ⚠ Пишем счёт векторов **всегда, когда были факты**, даже если он нулевой:
    # «qdrant: 0» при непустом `fact` — это и есть примета молчаливого отказа, ради
    # которой строка и нужна. Без неё уборка однажды уже провалилась незаметно.
    vectors = _test_vectors_drop(facts)
    if facts:
        counted['qdrant'] = vectors

    for table in TEST_SWEEP_TABLES:
        # ⚠ Имя таблицы уезжает в SQL текстом — потому и берётся только из
        # `TEST_SWEEP_TABLES`, а не из ответа базы и уж тем более не из окружения.
        got = mysql_query_run(f'DELETE FROM `{table}` WHERE `user_id` = %s', (who,))
        gone = int(got.get('affected') or 0)
        if gone:
            counted[table] = gone

    return counted


def _own_hosts_ports(*urls) -> list:
    """Пары «хост, порт» из адресов своей установки. Для списка разрешённого.

    ⚠ Адрес берётся **из той же настройки, что читают тесты** (`BASE_URL`), а не
    переписывается сюда числом. Иначе прогон против сервера ветки
    (`BASE_URL=http://localhost:8013`) упирался бы в собственного сторожа: адрес
    сменился, а список разрешённого остался прежним.
    """
    pairs = []

    for url in urls:
        one = httpx.URL(str(url))
        port = one.port or (443 if one.scheme == 'https' else 80)

        # Локальные имена перечисляем все: `localhost` и `127.0.0.1` в настройках
        # встречаются вперемешку, а сравнение идёт по строке.
        for host in {one.host, 'localhost', '127.0.0.1', '::1'}:
            pairs.append((host, port))

    return pairs

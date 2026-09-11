"""
Переменные сайта и шифрование секретных значений.

Главное, что здесь проверяется: **пароль не лежит в базе открытым текстом**. Всё
остальное — про то, чтобы это свойство нельзя было потерять по невнимательности:
список не отдаёт секретов, ключ обязателен при сохранении, смена пометки переписывает
значение целиком.

Отдельно проверяется, что шифрование именно обратимое, а не хэш: значение должно
возвращаться из базы целиком, иначе его нечем подставить в поле формы.

Тесты заводят свой сайт и сносят его в конце — переменные уходят каскадом
(`fk_bsv_site`).

Модули импортируются внутри тестов: они тянут `mysql_`, который читает `MYSQL_HOST` на
импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

pytestmark = pytest.mark.browser

TEST_SITE_NAME = '__pytest_variable_site'
TEST_SCENARIO_NAME = '__pytest_variable_scenario'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def site():
    """Сайт, которому принадлежат переменные."""
    await _drop()
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO browser_site (name, url) VALUES (%s, %s)',
            (TEST_SITE_NAME, 'https://stand.example'))
        site_id = db.lastrowid
        await db.connection.commit()

    yield site_id

    await _drop()


class TestSecretCrypto:
    """Шифрование само по себе — без базы и HTTP."""

    async def test_encrypt_is_reversible(self):
        """
        Обратимость — то, ради чего здесь шифрование, а не хэш: значение
        подставляют в поле формы, значит его нужно получить целиком.
        """
        from browser_.browser_secret import browser_secret_decrypt, browser_secret_encrypt

        assert browser_secret_decrypt(browser_secret_encrypt('пароль-42')) == 'пароль-42'

    async def test_ciphertext_hides_the_value(self):
        """В шифротексте исходного значения нет — именно это увидит дамп базы."""
        from browser_.browser_secret import browser_secret_encrypt

        assert 'пароль-42' not in browser_secret_encrypt('пароль-42')

    async def test_same_value_gives_different_ciphertext(self):
        """
        Fernet подмешивает случайный вектор, и два одинаковых пароля выглядят в базе
        по-разному. Иначе по совпадению строк было бы видно, у каких сайтов пароль
        один и тот же, — а это уже половина ответа.
        """
        from browser_.browser_secret import browser_secret_encrypt

        assert browser_secret_encrypt('одно и то же') != browser_secret_encrypt('одно и то же')

    async def test_marked_with_version_prefix(self):
        """
        Метка отличает зашифрованное от открытого: в одной колонке лежит и то, и
        другое, и гадать по виду строки нельзя.
        """
        from browser_.browser_secret import BROWSER_SECRET_PREFIX, browser_secret_encrypt

        assert browser_secret_encrypt('x').startswith(BROWSER_SECRET_PREFIX)

    async def test_plain_value_passes_through(self):
        """Без метки значение возвращается как есть — так читаются открытые переменные."""
        from browser_.browser_secret import browser_secret_decrypt

        assert browser_secret_decrypt('https://stand.example') == 'https://stand.example'

    async def test_double_encryption_does_not_stack(self):
        """
        Правка соседнего поля не должна наматывать слои: расшифровать такое можно было
        бы только столько же раз подряд.
        """
        from browser_.browser_secret import browser_secret_encrypt

        once = browser_secret_encrypt('пароль')
        assert browser_secret_encrypt(once) == once

    async def test_missing_key_refuses_to_store(self, monkeypatch):
        """
        Без ключа — исключение, а не тихое сохранение открытым текстом. Молчаливая
        подмена поведения здесь худший исход: обнаружится она при утечке.
        """
        from browser_.browser_secret import BROWSER_SECRET_ENV_KEY, browser_secret_encrypt

        monkeypatch.delenv(BROWSER_SECRET_ENV_KEY, raising=False)

        with pytest.raises(RuntimeError):
            browser_secret_encrypt('пароль')

    async def test_wrong_key_does_not_return_garbage(self, monkeypatch):
        """
        Чужой ключ даёт признак «не расшифровать», а не мусор и не пустоту: пустое
        значение человек принял бы за незаполненное и завёл бы запись заново поверх.
        """
        from cryptography.fernet import Fernet

        from browser_.browser_secret import (BROWSER_SECRET_ENV_KEY,
                                                BROWSER_SECRET_UNREADABLE,
                                                browser_secret_decrypt,
                                                browser_secret_encrypt)

        encrypted = browser_secret_encrypt('пароль')
        monkeypatch.setenv(BROWSER_SECRET_ENV_KEY, Fernet.generate_key().decode())

        assert browser_secret_decrypt(encrypted) == BROWSER_SECRET_UNREADABLE


class TestStorage:
    """Что в самом деле оказывается в таблице."""

    async def test_secret_is_encrypted_in_db(self, site):
        """
        Главная проверка: пароль в базе не лежит открытым. Смотрим саму колонку, а не
        ответ API, — в дамп и в бэкап уезжает именно она.
        """
        from mysql_.mysql_ import mysql_get_db_async
        from browser_.browser_secret import browser_secret_encrypt

        await _variable_add(site, 'password', browser_secret_encrypt('тайна-777'), is_secret=1)

        async with mysql_get_db_async() as db:
            await db.execute('SELECT value FROM browser_site_variable WHERE site_id = %s', (site,))
            stored = (await db.fetchone())['value']

        assert 'тайна-777' not in stored
        assert stored.startswith('enc:v1:')

    async def test_plain_value_stays_readable(self, site):
        """Открытая переменная лежит как есть: прятать адрес стенда не от кого."""
        from mysql_.mysql_ import mysql_get_db_async

        await _variable_add(site, 'login', 'stand-user', is_secret=0)

        async with mysql_get_db_async() as db:
            await db.execute("SELECT value FROM browser_site_variable "
                             " WHERE site_id = %s AND name = 'login'", (site,))
            assert (await db.fetchone())['value'] == 'stand-user'

    async def test_name_unique_within_site_only(self, site):
        """
        `login` есть у каждого сайта, и это разные логины. Уникальность нужна внутри
        сайта: подстановка ищет по имени и при двойнике брала бы произвольный из двух.
        """
        from mysql_.mysql_ import mysql_get_db_async

        await _variable_add(site, 'login', 'первый', is_secret=0)

        async with mysql_get_db_async() as db:
            await db.execute('INSERT INTO browser_site (name, url) VALUES (%s, %s)',
                             (TEST_SITE_NAME + '_2', 'https://other.example'))
            other = db.lastrowid
            await db.connection.commit()

        await _variable_add(other, 'login', 'второй', is_secret=0)

        # Считаем только по своим сайтам: `login` — имя ходовое, и в рабочей базе
        # оно есть у настоящих сайтов тоже. Счёт по всей таблице ловил бы их.
        async with mysql_get_db_async() as db:
            await db.execute('SELECT COUNT(*) c FROM browser_site_variable '
                             " WHERE name = 'login' AND site_id IN (%s, %s)", (site, other))
            assert (await db.fetchone())['c'] == 2

    async def test_site_delete_takes_variables(self, site):
        """Без сайта переменные бессмысленны — уходят каскадом, а не сиротеют."""
        from mysql_.mysql_ import mysql_get_db_async

        await _variable_add(site, 'login', 'stand-user', is_secret=0)

        async with mysql_get_db_async() as db:
            await db.execute('DELETE FROM browser_site WHERE id = %s', (site,))
            await db.connection.commit()
            await db.execute('SELECT COUNT(*) c FROM browser_site_variable WHERE site_id = %s',
                             (site,))
            assert (await db.fetchone())['c'] == 0


class TestApi:
    """Ответы ручек: что уходит наружу, а что нет."""

    async def test_list_masks_secrets(self, site):
        """
        Список не отдаёт секретов даже полноправному: он рисуется на каждой смене
        сайта, и пароли пачкой осели бы в журнале прокси и в истории браузера.
        """
        from browser_.browser_secret import browser_secret_encrypt
        from src.uvicorn.routers.browser.browser_site_variable import (
            BROWSER_SITE_VARIABLE_MASK, browser_site_variable_list)

        await _variable_add(site, 'password', browser_secret_encrypt('тайна-777'), is_secret=1)
        await _variable_add(site, 'login', 'stand-user', is_secret=0)

        data = await browser_site_variable_list(site_id=site, user=None)
        by_name = {item['name']: item['value'] for item in data['items']}

        assert by_name['password'] == BROWSER_SITE_VARIABLE_MASK
        assert 'тайна-777' not in str(data)
        assert by_name['login'] == 'stand-user', 'открытую переменную прятать не от кого'

    async def test_reveal_returns_raw(self, site):
        """Сырое значение выдаётся поштучно — на явное действие человека."""
        from mysql_.mysql_ import mysql_get_db_async
        from browser_.browser_secret import browser_secret_encrypt
        from src.uvicorn.routers.browser.browser_site_variable import browser_site_variable_reveal

        await _variable_add(site, 'password', browser_secret_encrypt('тайна-777'), is_secret=1)
        async with mysql_get_db_async() as db:
            await db.execute('SELECT id FROM browser_site_variable WHERE site_id = %s', (site,))
            variable_id = (await db.fetchone())['id']

        data = await browser_site_variable_reveal(variable_id=variable_id, user=None)

        assert data['value'] == 'тайна-777'

    async def test_run_values_split_plain_and_secret(self, site):
        """
        Прогону значения уходят двумя сумками: обычные попадают в журнал, секретные
        замазываются. Одна сумка с флажком дала бы потребителю возможность
        залогировать всё скопом.
        """
        from browser_.browser_secret import browser_secret_encrypt
        from src.uvicorn.routers.browser.browser_site_variable import browser_site_variable_values

        await _variable_add(site, 'login', 'stand-user', is_secret=0)
        await _variable_add(site, 'password', browser_secret_encrypt('тайна-777'), is_secret=1)

        plain, secret = await browser_site_variable_values(site)

        assert plain == {'login': 'stand-user'}
        assert secret == {'password': 'тайна-777'}, 'прогону значение нужно расшифрованным'


class TestScenarioRun:
    """Подстановка в прогон: три слоя значений и защита секретов от журнала."""

    async def test_site_values_reach_the_run(self, site):
        """
        Ради этого переменные и заводят на сайт: сценарий не хранит логин у себя, а
        получает его на прогоне.
        """
        payload = await _run_payload(site, steps_vars=['login', 'password'], scenario_vars={})

        assert payload['variables']['login'] == 'site-user'
        assert payload['secrets']['password'] == 'site-pass-999'

    async def test_secret_goes_to_the_secret_bag(self, site):
        """
        Не формальность: контейнер замазывает `secrets` в трассе и в тексте ошибок, а
        `variables` кладёт в журнал как есть. Пароль в неверной сумке уехал бы в
        `browser_scenario_run.trace` открытым текстом — ровно то, от чего его шифруют.
        """
        payload = await _run_payload(site, steps_vars=['password'], scenario_vars={})

        assert 'password' not in payload['variables']
        assert payload['secrets']['password'] == 'site-pass-999'

    async def test_scenario_default_wins_over_site(self, site):
        """
        Более частное побеждает. Сценарии со своими значениями заведены до появления
        этой таблицы; окажись сайт выше, любой такой сценарий сменил бы поведение
        молча, на первом же прогоне.
        """
        payload = await _run_payload(site, steps_vars=['host'],
                                     scenario_vars={'host': 'https://scenario-host'})

        assert payload['variables']['host'] == 'https://scenario-host'

    async def test_run_time_value_wins_over_all(self, site):
        """Переданное на запуск — самое частное: им проверяют стенд, не трогая базу."""
        payload = await _run_payload(site, steps_vars=['login'], scenario_vars={},
                                     variables={'login': 'разовый'})

        assert payload['variables']['login'] == 'разовый'

    async def test_empty_override_does_not_erase_site_value(self, site):
        """
        Пустое поле не должно стирать сохранённое: прогон упал бы на пустом поле формы
        вместо понятного «переменная не задана», и искать причину пришлось бы в шагах.
        """
        payload = await _run_payload(site, steps_vars=['login', 'password'], scenario_vars={},
                                     variables={'login': ''}, secrets={'password': ''})

        assert payload['variables']['login'] == 'site-user'
        assert payload['secrets']['password'] == 'site-pass-999'

    async def test_scenario_without_site_runs_as_before(self):
        """
        Сценарий без сайта получает пустые сумки: связь с сайтом появилась позже самих
        сценариев, и такие в базе есть.
        """
        payload = await _run_payload(None, steps_vars=['host'],
                                     scenario_vars={'host': 'https://scenario-host'})

        assert payload['variables'] == {'host': 'https://scenario-host'}
        assert payload['secrets'] == {}


class TestPermissions:
    """Право на показ пароля отдельно от права видеть список."""

    def test_secret_view_is_not_granted_by_browser_view(self):
        """
        `browser:view` есть у `dating_service` — учётки, которой правит код соседнего
        проекта. Отдай мы расшифровку по нему, автоматика получила бы доступ ко всем
        паролям установки разом.
        """
        from src.auth.auth_permission import AuthPermission
        from src.auth.auth_role import auth_role_permissions

        rights = auth_role_permissions('dating_service')

        assert AuthPermission.BROWSER_VIEW in rights
        assert AuthPermission.BROWSER_SECRET_VIEW not in rights

    def test_full_roles_keep_secret_view(self):
        """Полноправные роли получают новое право сами — набор у них полный."""
        from src.auth.auth_permission import AuthPermission
        from src.auth.auth_role import auth_role_permissions

        for role in ('admin', 'qa'):
            assert AuthPermission.BROWSER_SECRET_VIEW in auth_role_permissions(role)

    def test_service_role_reads_llm_usage_but_writes_nothing(self):
        """⚠ `llm:view` у `dating_service` — **только чтение**, и это осознанно.

        Набор прав служебной учётки узкий намеренно: ею правит не человек, а
        автоматика, и лишнее право здесь — не удобство, а возможность снести чужое
        по ошибке в коде. Право добавлено под вкладку «Статистика» у соседа: сколько
        запросов к LLM ушло и сколько токенов потрачено, считает только эта
        установка (`llm_request`), и второй копии быть не должно.

        Оговорка про «снести чужое» относится к правам, которые **пишут**.
        `llm:view` открывает `GET /llm/list`, `/llm/status` и `/llm/usage/stats`;
        очистка журнала живёт за отдельным `llm:delete`, и его здесь нет.
        """
        from src.auth.auth_permission import AuthPermission
        from src.auth.auth_role import auth_role_permissions

        rights = auth_role_permissions('dating_service')

        assert AuthPermission.LLM_VIEW in rights
        assert AuthPermission.LLM_DELETE not in rights
        assert AuthPermission.LLM_UPDATE not in rights

    def test_service_role_stays_narrow(self):
        """⚠ Сторож объёма: у служебной учётки пять прав, и не больше.

        Права ей добавляют по одному и с доводом (браузер, агент, теперь чтение
        LLM). Без этой проверки набор рос бы незаметно: каждое следующее «ну ещё
        одно» выглядит безобидным, а вместе они дают учётке автоматики то, чего
        никто не решал.
        """
        from src.auth.auth_role import auth_role_permissions

        assert len(auth_role_permissions('dating_service')) == 5


async def _run_payload(site_id, steps_vars: list, scenario_vars: dict,
                       variables: dict | None = None, secrets: dict | None = None) -> dict:
    """
    Что ушло бы в контейнер: перехватываем запрос вместо живого прогона.

    Живой Chromium здесь не нужен — проверяется сборка значений, а не выполнение
    шагов. Заодно сюита не зависит от поднятого контейнера-браузера.
    """
    import json
    from unittest.mock import patch

    from mysql_.mysql_ import mysql_get_db_async
    from browser_.browser_secret import browser_secret_encrypt
    import src.uvicorn.routers.browser.browser_scenario as scenario_module

    if site_id:
        await _variable_add(site_id, 'login', 'site-user', is_secret=0)
        await _variable_add(site_id, 'password', browser_secret_encrypt('site-pass-999'),
                            is_secret=1)

    steps = [{'action': 'fill', 'selector': f'#{name}', 'value': '{{' + name + '}}'}
             for name in steps_vars]
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO browser_scenario (site_id, name, goal, steps, variables) '
            'VALUES (%s, %s, %s, %s, %s)',
            (site_id, TEST_SCENARIO_NAME, 'проба', json.dumps(steps),
             json.dumps(scenario_vars, ensure_ascii=False)))
        scenario_id = db.lastrowid
        await db.connection.commit()

    captured = {}

    async def _fake(method, path, payload, timeout=None):
        captured.update(payload)

        return {'status': 'ok', 'steps': [], 'extract': {}, 'duration_ms': 1, 'session_id': ''}

    try:
        with patch.object(scenario_module, 'browser_upstream_request', _fake):
            await scenario_module.browser_scenario_run_one(
                scenario_id, '', variables or {}, secrets or {}, False)
    finally:
        async with mysql_get_db_async() as db:
            await db.execute('DELETE FROM browser_scenario WHERE id = %s', (scenario_id,))
            await db.connection.commit()

    return captured


async def _variable_add(site_id: int, name: str, value: str, is_secret: int) -> int:
    """Строка переменной напрямую в базу — без HTTP и без прав."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO browser_site_variable (site_id, name, value, is_secret) '
            'VALUES (%s, %s, %s, %s)', (int(site_id), name, value, int(is_secret)))
        row_id = db.lastrowid
        await db.connection.commit()

    return row_id


async def _drop() -> None:
    """Снести тестовые сайты — переменные уходят каскадом."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        # Сценарии явно: у `browser_scenario.site_id` внешний ключ `ON DELETE SET NULL`
        # — сценарий переживает свой сайт намеренно, но тестовый переживать не должен.
        await db.execute('DELETE FROM browser_scenario WHERE name = %s', (TEST_SCENARIO_NAME,))
        await db.execute("DELETE FROM browser_site WHERE name LIKE %s", (TEST_SITE_NAME + '%',))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

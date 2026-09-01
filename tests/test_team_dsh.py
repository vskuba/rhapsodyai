"""
Включатель ролей DeepSeek Harness (`src/project/team/team_dsh.py`, `team_dsh_panel.py`,
`team_dsh_card.py`, `team_dsh_project.py`).

Что здесь проверяется. Не то, что httpx умеет ходить по HTTP, а **граница с чужой
машиной**: пульты живут на ноутбуке разработчика, за пределами установки, и половина
интересных случаев — это их отсутствие, а не их ответ.

Четыре правила, ради которых тесты и написаны:

- **состояние не падает.** `team_dsh_state` зовётся при каждом обновлении страницы
  команды. Выключенный ноутбук — обычное состояние прода, где оболочки нет вовсе;
  бросай состояние исключение, страница про всю команду отдавала бы 502 из-за
  ненайденного посредника;
- **молчание одного пульта не гасит остальных.** Пультов столько, сколько машин с
  оболочкой, и работающими они бывают вразнобой. Кнопки живого проекта обязаны остаться
  на месте, когда сосед не поднят;
- **переключение падает.** За ним стоит нажатая кнопка, и молчаливое «ничего не
  произошло» человек прочтёт как сделанное. Причём код ответа обязан различать
  «не тот проект или роль» (наш кривой запрос — 422) и «пульт недоступен или ему плохо»
  (502): на странице это разные слова, и обвинять ноутбук в своей опечатке нельзя;
- **проект адресуется всегда.** Один пульт обслуживает несколько проектов, а роли у них
  одноимённые: и выбор пульта, и тело запроса обязаны называть корень каталога, иначе
  нажатие поднимет агента в чужом проекте — том, что у пульта домашний.

Сеть подменяется на уровне `httpx.AsyncClient.request` — ниже неё в модуле ничего
своего нет. Всё, что выше (список адресов, сборка URL, заголовок с секретом, разбор
ответа, выбор пульта по проекту, отображение кодов), настоящее: заглуши мы весь запрос,
тест подтверждал бы сам себя.

К живым пультам сюита не ходит намеренно. `POST /roles/on` завёл бы на хосте Harness
настоящую карточку, а сервис поднял бы по ней оболочку роли — то есть тест запустил бы
агента на машине разработчика.
"""

from unittest.mock import patch

import httpx
import pytest

pytestmark = pytest.mark.team

# Роли берём вымышленные: с настоящим именем неудачный мок однажды уйдёт в живой пульт
# и заведёт карточку роли, которая начнёт брать круги.
TEST_DSH_ROLE = 'test_dsh_role'

TEST_DSH_PANEL_A = 'http://panel-a:8791'
TEST_DSH_PANEL_B = 'http://panel-b:8792'

# Меняющие пути пульта: на них заглушка отвечает телом `post`, а не состоянием ролей.
TEST_DSH_PANEL_POSTS = ('/roles/on', '/roles/off', '/roles/add', '/roles/drop',
                        '/projects/add', '/projects/drop', '/host/restart')

TEST_DSH_PROJECT_A = '/home/user/PycharmProjects/RhapsodyAi'
TEST_DSH_PROJECT_B = '/home/user/PycharmProjects/DatingAi'
TEST_DSH_PROJECT_NEW = '/home/user/PycharmProjects/BlogAi'

# Две карточки одной роли: базовая (номер 1 — на ней выключатель) и добавочная (номер 2
# — на ней крестик). Сессии реестра к ним нарочно привязаны в обратном порядке: номера
# карточки Harness и карточки страницы назначаются независимо, и совпади они здесь,
# тест не заметил бы, если бы страница сопоставляла их по номеру вместо `session_uuid`.
TEST_DSH_CARD_BASE = 'card-developer-99c6cac6-1'
TEST_DSH_CARD_EXTRA = 'card-developer-99c6cac6-2'
TEST_DSH_SESSION_BASE = '11111111-1111-1111-1111-111111111111'
TEST_DSH_SESSION_EXTRA = '22222222-2222-2222-2222-222222222222'

# Один проект в ответе пульта. Домашний (`home`) — тот, в чьём каталоге подняли сервис:
# из его `.env` взят секрет, и отключить его нельзя. Остальные подключены кнопкой.
DSH_PROJECT_A = {
    'project': TEST_DSH_PROJECT_A,
    'label': 'RhapsodyAi',
    'home': True,
    'roles': [
        {'role': 'developer', 'title': 'Разработчик', 'enabled': True,
         'cards': [TEST_DSH_CARD_BASE, TEST_DSH_CARD_EXTRA]},
        {'role': 'qa', 'title': 'QA', 'enabled': False, 'cards': []},
    ],
    'attached': {
        TEST_DSH_CARD_EXTRA: {'role': 'developer', 'index': 2,
                              'session_uuid': TEST_DSH_SESSION_EXTRA},
        TEST_DSH_CARD_BASE: {'role': 'developer', 'index': 1,
                             'session_uuid': TEST_DSH_SESSION_BASE},
    },
}

DSH_PROJECT_B = {
    'project': TEST_DSH_PROJECT_B,
    'label': 'DatingAi',
    'home': False,
    'roles': [{'role': 'developer', 'title': 'Разработчик', 'enabled': False, 'cards': []}],
}

# Ответ пульта на `GET /roles` — в том виде, в каком его отдаёт `dsh_control._state`.
# `project` наверху — домашний проект пульта, `projects` — все, кого он обслуживает.
DSH_STATE_OK = {
    'project': TEST_DSH_PROJECT_A,
    'projects': [DSH_PROJECT_A],
    'harness_url': 'http://127.0.0.1:8790/',
    'alive': True,
}

DSH_STATE_B = {
    'project': TEST_DSH_PROJECT_B,
    'projects': [{**DSH_PROJECT_B, 'home': True}],
    'harness_url': 'http://127.0.0.1:8790/',
    'alive': True,
}

# Один пульт, два проекта: домашний и подключённый кнопкой. Ради этого случая всё и
# затевалось — раньше на каждый проект поднимали отдельный сервис на своём порту.
DSH_STATE_BOTH = {
    'project': TEST_DSH_PROJECT_A,
    'projects': [DSH_PROJECT_A, DSH_PROJECT_B],
    'harness_url': 'http://127.0.0.1:8790/',
    'alive': True,
}


class TestDshPanelUrls:
    """Список адресов: сколько проектов, столько пультов."""

    def test_urls_split_on_commas_and_spaces(self):
        """
        Список в одной строке `.env` режется и по запятой, и по пробелам.

        Требовать ровно один вид разделителя значило бы ловить опечатки вместо работы:
        строку правит человек, а не генератор.
        """
        urls = _urls('http://a:8791, http://b:8792  http://c:8793')

        assert urls == ['http://a:8791', 'http://b:8792', 'http://c:8793']

    def test_urls_drop_trailing_slash_and_repeats(self):
        """
        Хвостовой слэш срезается, повтор адреса не удваивает опрос.

        Иначе один и тот же пульт спросили бы дважды, а его проект попал бы в ответ
        двумя одинаковыми записями — лишний круг по сети на каждое обновление страницы.
        """
        urls = _urls('http://a:8791/, http://a:8791')

        assert urls == ['http://a:8791']

    def test_urls_fall_back_to_default_when_empty(self):
        """
        Пустой ключ в `.env` — это не «пультов нет», а «адрес не задан».

        `config_get(key, default)` на пустом значении возвращает пустую строку, до
        умолчания не дойдя, поэтому умолчание подставляется через `or`.
        """
        from src.project.team.team_dsh_panel import TEAM_DSH_PANEL_URL_DEFAULT

        assert _urls('') == [TEAM_DSH_PANEL_URL_DEFAULT]


class TestDshState:
    """Состояние ролей: что пришло от пультов, то и увидит страница."""

    async def test_state_maps_roles_by_name(self):
        """
        Список пульта превращается в словарь `роль → состояние`.

        Страница ищет в нём по имени роли карточки блока, а порядок задаёт свой — тот,
        в котором стоят карточки. Списком ей пришлось бы искать перебором на каждой.
        """
        state = await _state_from({TEST_DSH_PANEL_A: DSH_STATE_OK})
        roles = state['projects'][TEST_DSH_PROJECT_A]['roles']

        assert state['problem'] == ''
        assert state['alive'] is True
        assert state['harness_url'] == 'http://127.0.0.1:8790/'
        assert set(roles) == {'developer', 'qa'}
        assert roles['developer']['enabled'] is True
        assert roles['developer']['cards'] == [TEST_DSH_CARD_BASE, TEST_DSH_CARD_EXTRA]
        assert roles['qa']['enabled'] is False

    async def test_state_maps_sessions_to_harness_cards(self):
        """
        `attached` пульта превращается в `сессия реестра → карточка Harness`.

        По этому соответствию страница и раскладывает кнопки: карточка с номером 1
        базовая — на ней выключатель роли, номер 2 и дальше добавочные — на них
        крестик. Ключ именно `session_uuid`: номер карточке страницы выдаёт реестр при
        регистрации, номер карточки Harness — её место в проекте, и назначаются они
        независимо друг от друга.
        """
        state = await _state_from({TEST_DSH_PANEL_A: DSH_STATE_OK})
        sessions = state['projects'][TEST_DSH_PROJECT_A]['sessions']

        assert set(sessions) == {TEST_DSH_SESSION_BASE, TEST_DSH_SESSION_EXTRA}
        assert sessions[TEST_DSH_SESSION_BASE] == {'card_id': TEST_DSH_CARD_BASE,
                                                   'role': 'developer', 'index': 1}
        assert sessions[TEST_DSH_SESSION_EXTRA]['index'] == 2
        assert sessions[TEST_DSH_SESSION_EXTRA]['card_id'] == TEST_DSH_CARD_EXTRA

    async def test_state_skips_sessions_without_uuid(self):
        """
        Записи без сессии и кривые пропускаются, целые остаются.

        Карточка Harness живёт раньше своей сессии: сервис заводит оболочку и лишь
        потом регистрирует её в реестре, так что запись без `session_uuid` — обычное
        состояние на первых секундах, а не поломка. Приложить её страница всё равно не
        к чему: карточки блока она находит по сессии.
        """
        state = await _state_from({TEST_DSH_PANEL_A: {
            'project': TEST_DSH_PROJECT_A,
            'projects': [{
                'project': TEST_DSH_PROJECT_A,
                'attached': {'card-a-1': 'строка',
                             'card-b-1': {'role': 'qa'},
                             'card-c-1': {'role': 'qa', 'session_uuid': '  '},
                             'card-d-2': {'role': 'qa', 'session_uuid': TEST_DSH_SESSION_BASE}},
            }],
        }})
        sessions = state['projects'][TEST_DSH_PROJECT_A]['sessions']

        assert set(sessions) == {TEST_DSH_SESSION_BASE}
        assert sessions[TEST_DSH_SESSION_BASE]['card_id'] == 'card-d-2'

    async def test_state_survives_non_numeric_index(self):
        """
        Номер карточки не числом — это 0, а не падение страницы.

        Пульт чужой процесс, и `index` для нас входные данные. Ноль при этом безопасен
        сам по себе: он меньше базового номера, значит крестика такая карточка не
        получит и в архив по ошибке не уйдёт.
        """
        state = await _state_from({TEST_DSH_PANEL_A: {
            'project': TEST_DSH_PROJECT_A,
            'projects': [{
                'project': TEST_DSH_PROJECT_A,
                'attached': {'card-a-1': {'role': 'qa', 'index': 'первая',
                                          'session_uuid': TEST_DSH_SESSION_BASE}},
            }],
        }})

        assert state['projects'][TEST_DSH_PROJECT_A]['sessions'][
            TEST_DSH_SESSION_BASE]['index'] == 0

    async def test_state_without_attached_keeps_sessions_empty(self):
        """Пульт не прислал `attached` — пустое соответствие, а не отсутствующий ключ."""
        state = await _state_from({TEST_DSH_PANEL_B: DSH_STATE_B})

        assert state['projects'][TEST_DSH_PROJECT_B]['sessions'] == {}

    async def test_state_keys_roles_by_project_root(self):
        """
        Роли разложены по корню проекта — по нему страница находит свой блок.

        Блоков на странице столько же, сколько проектов, а имена ролей у всех
        одинаковые. Потеряйся ключ — кнопки встали бы на карточки чужого блока и
        переключали бы чужого агента.
        """
        state = await _state_from({TEST_DSH_PANEL_A: DSH_STATE_OK,
                                   TEST_DSH_PANEL_B: DSH_STATE_B})

        assert set(state['projects']) == {TEST_DSH_PROJECT_A, TEST_DSH_PROJECT_B}
        assert state['projects'][TEST_DSH_PROJECT_A]['url'] == TEST_DSH_PANEL_A
        assert state['projects'][TEST_DSH_PROJECT_B]['url'] == TEST_DSH_PANEL_B
        assert state['projects'][TEST_DSH_PROJECT_B]['roles']['developer']['enabled'] is False

    async def test_state_spreads_one_panel_over_its_projects(self):
        """
        Один пульт называет несколько проектов — блоки получают каждый свои роли.

        Ради этого всё и затевалось: раньше проект значил отдельный сервис на своём
        порту, и новый оставался без ролей, пока кто-нибудь не сходил на машину.
        Проекты одного пульта равноправны, различает их только `home` — домашний, тот,
        в чьём каталоге сервис подняли, и его нельзя отключить.
        """
        state = await _state_from({TEST_DSH_PANEL_A: DSH_STATE_BOTH})

        assert set(state['projects']) == {TEST_DSH_PROJECT_A, TEST_DSH_PROJECT_B}
        assert state['projects'][TEST_DSH_PROJECT_A]['url'] == TEST_DSH_PANEL_A
        assert state['projects'][TEST_DSH_PROJECT_B]['url'] == TEST_DSH_PANEL_A
        assert state['projects'][TEST_DSH_PROJECT_A]['home'] is True
        assert state['projects'][TEST_DSH_PROJECT_B]['home'] is False
        assert state['projects'][TEST_DSH_PROJECT_A]['roles']['developer']['enabled'] is True
        assert state['projects'][TEST_DSH_PROJECT_B]['roles']['developer']['enabled'] is False

    async def test_state_lists_panels_apart_from_projects(self):
        """
        Пульты приходят отдельным списком — блоку без проекта нужен именно он.

        Блок, чьего каталога нет ни у кого, показывает кнопку «подключить», и без
        списка пультов страница не отличила бы «проект не подключён» (кнопка поможет)
        от «пультов нет вовсе» (не поможет, машина выключена).
        """
        state = await _state_from({TEST_DSH_PANEL_A: DSH_STATE_OK,
                                   TEST_DSH_PANEL_B: httpx.ConnectError('нет такого хоста')})
        panels = {item['url']: item for item in state['panels']}

        assert set(panels) == {TEST_DSH_PANEL_A, TEST_DSH_PANEL_B}
        assert panels[TEST_DSH_PANEL_A]['alive'] is True
        assert panels[TEST_DSH_PANEL_A]['home'] == TEST_DSH_PROJECT_A
        assert panels[TEST_DSH_PANEL_A]['problem'] == ''
        assert panels[TEST_DSH_PANEL_B]['alive'] is False
        assert 'недоступен' in panels[TEST_DSH_PANEL_B]['problem']

    async def test_state_keeps_live_panels_when_a_neighbour_is_dead(self):
        """
        Один пульт молчит — кнопки остальных проектов остаются на месте.

        Ради этого состояние и собирается со всех разом: пульты поднимают по одному, и
        «не поднят DatingAi» не повод отобрать кнопки у RhapsodyAi. Причина при этом
        всё равно приходит словами — иначе молчание было бы неотличимо от порядка.
        """
        state = await _state_from({TEST_DSH_PANEL_A: DSH_STATE_OK,
                                   TEST_DSH_PANEL_B: httpx.ConnectError('нет такого хоста')})

        assert set(state['projects']) == {TEST_DSH_PROJECT_A}
        assert 'недоступен' in state['problem']
        assert TEST_DSH_PANEL_B in state['problem'], 'по причине должно быть видно, чей пульт'
        assert state['alive'] is True, 'хост Harness жив, раз о нём сказал хоть кто-то'

    async def test_state_survives_dead_panel(self):
        """
        Пульт не отвечает — причина словами, а не исключение.

        Ради этого ручка и вынесена из `/projects`: на проде оболочки нет вовсе, и
        падай состояние, страница команды не показала бы ни одной карточки.
        """
        state = await _state_from({TEST_DSH_PANEL_A: httpx.ConnectError('нет такого хоста')})

        assert state['problem'], 'без причины страница нарисует пустоту без объяснений'
        assert 'недоступен' in state['problem']
        assert state['projects'] == {}
        assert state['alive'] is False

    async def test_state_keeps_harness_url_when_panel_is_dead(self):
        """
        Ссылка на Harness остаётся живой и без пультов.

        Хост Harness переживает и оболочку, и сервис, а человеку ссылка нужна ровно
        тогда, когда что-то не работает: по ней он и увидит, что там на самом деле.
        """
        from src.project.team.team_dsh_panel import TEAM_DSH_PANEL_HARNESS_URL

        state = await _state_from({TEST_DSH_PANEL_A: httpx.ConnectTimeout('молчит')})

        assert state['harness_url'] == TEAM_DSH_PANEL_HARNESS_URL

    async def test_state_skips_panel_without_projects(self):
        """
        Пульт не назвал проектов — говорим об этом словами и советуем перезапуск.

        Так отвечает старый `ds-shell`, не знающий про список проектов: он присылал
        роли плоским списком, без каталога при них. Кнопки в таком ответе некуда
        ставить, и молчаливая пустота выглядела бы как «ролей нет» — то есть как
        поломка ноутбука, а не как невыполненное обновление.
        """
        state = await _state_from({TEST_DSH_PANEL_A: {'roles': [{'role': 'qa'}]}})

        assert state['projects'] == {}
        assert 'не назвал проект' in state['problem']
        assert 'перезапустите' in state['problem'], 'причина должна называть и лечение'

    async def test_state_skips_projects_without_a_root(self):
        """
        Запись проекта без каталога пропускается, соседние по списку остаются.

        Адресовать кнопки такой записи нечем — общий признак у страницы и пульта
        только корень каталога. Урони весь список одна запись, пульт потерял бы и
        здоровые проекты разом.
        """
        state = await _state_from({TEST_DSH_PANEL_A: {
            'project': TEST_DSH_PROJECT_A,
            'projects': ['строка', {'project': '  '}, {'no': 'project'}, DSH_PROJECT_A],
        }})

        assert set(state['projects']) == {TEST_DSH_PROJECT_A}
        assert state['problem'] == ''

    async def test_state_skips_malformed_rows(self):
        """
        Кривые записи пропускаются, целые остаются.

        Пульт — чужой процесс чужого репозитория, и его ответ для нас входные данные.
        Урони весь список одна запись без имени — блок потерял бы кнопки всех ролей.
        """
        state = await _state_from({TEST_DSH_PANEL_A: {
            'project': TEST_DSH_PROJECT_A,
            'projects': [{
                'project': TEST_DSH_PROJECT_A,
                'roles': ['строка', {'role': ''}, {'no': 'role'}, {'role': 'qa'}],
            }],
        }})
        roles = state['projects'][TEST_DSH_PROJECT_A]['roles']

        assert set(roles) == {'qa'}
        assert roles['qa']['title'] == 'qa', 'без title подставляется имя роли'
        assert roles['qa']['enabled'] is False

    async def test_state_without_secret_reports_problem(self):
        """
        Секрета нет — говорим об этом словами, а в пульт не стучимся.

        Заголовок общий с team API, и его отсутствие — забытая переменная установки, а
        не поломка ноутбука. Пульт всё равно ответил бы 401, но узнать причину по
        коду уже нельзя.
        """
        state = await _state_from({TEST_DSH_PANEL_A: DSH_STATE_OK}, secret='')

        assert 'TELEGRAM_TOKEN_RHAPSODY' in state['problem']
        assert state['projects'] == {}


class TestDshSwitch:
    """Переключение роли: заводим карточку или отправляем её в архив."""

    async def test_switch_on_asks_for_a_new_card(self):
        """Включение идёт в `/roles/on` и возвращает заведённую карточку."""
        result, calls = await _switch(
            {TEST_DSH_PANEL_A: DSH_STATE_OK},
            answer={'role': TEST_DSH_ROLE, 'card_id': 'card-x-1', 'cards': ['card-x-1'],
                    'changed': True, 'attached': {}},
            project=TEST_DSH_PROJECT_A, enabled=True)

        assert calls[-1]['method'] == 'POST'
        assert calls[-1]['url'] == TEST_DSH_PANEL_A + '/roles/on'
        assert calls[-1]['json'] == {'project': TEST_DSH_PROJECT_A, 'role': TEST_DSH_ROLE}
        assert result == {'project': TEST_DSH_PROJECT_A, 'role': TEST_DSH_ROLE, 'enabled': True,
                          'changed': True, 'cards': ['card-x-1'], 'card_id': 'card-x-1'}

    async def test_switch_goes_to_the_panel_of_the_project(self):
        """
        Из нескольких пультов выбирается тот, что назвал этот каталог.

        Адрес пульта страница не присылает вовсе — сервер находит его сам. Иначе
        браузер выбирал бы, к кому в сети сходит сервер, а имена ролей у всех проектов
        одинаковые: ошибись выбор — включился бы агент чужого проекта.
        """
        _, calls = await _switch({TEST_DSH_PANEL_A: DSH_STATE_OK,
                                  TEST_DSH_PANEL_B: DSH_STATE_B},
                                 answer={'role': TEST_DSH_ROLE, 'changed': True},
                                 project=TEST_DSH_PROJECT_B, enabled=True)

        assert calls[-1]['url'].startswith(TEST_DSH_PANEL_B)

    async def test_switch_names_the_project_in_the_body(self):
        """
        Корень проекта уходит и в тело запроса, не только в выбор пульта.

        Пульт обслуживает несколько проектов, роли у них одноимённые, а запрос без
        `project` он относит к своему домашнему. Потеряйся корень — нажатие у второго
        проекта подняло бы агента в первом, и человек увидел бы это не сразу.
        """
        _, calls = await _switch({TEST_DSH_PANEL_A: DSH_STATE_BOTH},
                                 answer={'role': TEST_DSH_ROLE, 'changed': True},
                                 project=TEST_DSH_PROJECT_B, enabled=True)

        assert calls[-1]['json']['project'] == TEST_DSH_PROJECT_B

    async def test_switch_off_archives_the_card(self):
        """Выключение идёт в `/roles/off`; карточки не остаётся, id заводить нечего."""
        result, calls = await _switch(
            {TEST_DSH_PANEL_A: DSH_STATE_OK},
            answer={'role': TEST_DSH_ROLE, 'cards': [], 'changed': True, 'attached': {}},
            project=TEST_DSH_PROJECT_A, enabled=False)

        assert calls[-1]['url'].endswith('/roles/off')
        assert result['enabled'] is False
        assert result['cards'] == []
        assert result['card_id'] == ''

    async def test_switch_reports_nothing_changed(self):
        """
        Роль уже в нужном состоянии — `changed` ложно, но это не ошибка.

        Обе ручки пульта идемпотентны, а кнопку нажимают повторно постоянно: страница
        обновляется раз в 15 секунд, и её картинка отстаёт от хоста. Стань повтор
        отказом, человек видел бы ошибку, сделав ровно то, что хотел.
        """
        result, _ = await _switch(
            {TEST_DSH_PANEL_A: DSH_STATE_OK},
            answer={'role': TEST_DSH_ROLE, 'cards': ['card-x-1'], 'changed': False},
            project=TEST_DSH_PROJECT_A, enabled=True)

        assert result['changed'] is False

    async def test_switch_sends_the_shared_secret(self):
        """
        Секрет уходит заголовком `X-Claude-Secret` — тем же, что у team API.

        Другой аутентификации у пульта нет: он стоит на `0.0.0.0`, чтобы его достал
        контейнер, и без заголовка любой сосед по сети поднимал бы агентов.
        """
        from src.project.team.team_dsh_panel import TEAM_DSH_PANEL_SECRET_HEADER

        _, calls = await _switch({TEST_DSH_PANEL_A: DSH_STATE_OK},
                                 answer={'role': TEST_DSH_ROLE},
                                 project=TEST_DSH_PROJECT_A, enabled=True)

        assert calls[-1]['headers'][TEAM_DSH_PANEL_SECRET_HEADER] == 'test-secret'

    async def test_switch_raises_when_panel_is_dead(self):
        """
        Пульт не отвечает — исключение, а не тихий пустой ответ.

        Здесь, в отличие от состояния, за вызовом стоит нажатая кнопка. Верни мы
        «ничего не произошло», человек прочёл бы это как выполненное и ждал бы
        агента, которого никто не поднимал.
        """
        from src.project.team.team_dsh import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _switch({TEST_DSH_PANEL_A: httpx.ConnectError('нет такого хоста')},
                          answer={}, project=TEST_DSH_PROJECT_A, enabled=True)

        assert error.value.status == 502

    async def test_switch_to_unknown_project_is_422(self):
        """
        Все пульты ответили, а такого проекта у них нет — вина наша, не ноутбука.

        Это «на этом проекте сервис не подняли», и человеку надо сказать именно так, а
        не гнать его чинить сеть.
        """
        from src.project.team.team_dsh import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _switch({TEST_DSH_PANEL_A: DSH_STATE_OK},
                          answer={}, project='/home/user/PycharmProjects/BlogAi', enabled=True)

        assert error.value.status == 422
        assert 'BlogAi' in str(error.value)

    async def test_switch_blames_the_silent_panel_not_the_request(self):
        """
        Проекта нет среди ответивших, но кто-то молчал — это 502, а не 422.

        Молчащий пульт мог быть как раз нужным: назови мы это кривым запросом, человек
        пошёл бы искать опечатку в каталоге вместо невставшего сервиса.
        """
        from src.project.team.team_dsh import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _switch({TEST_DSH_PANEL_A: DSH_STATE_OK,
                           TEST_DSH_PANEL_B: httpx.ConnectError('молчит')},
                          answer={}, project=TEST_DSH_PROJECT_B, enabled=True)

        assert error.value.status == 502

    async def test_switch_maps_unknown_role_to_422(self):
        """
        400 пульта — «нет такой роли», то есть наш кривой запрос, а не его поломка.

        Наружу он обязан уйти как 422: иначе страница напишет «пульт недоступен», и
        чинить пойдут ноутбук вместо опечатки в имени роли.
        """
        from src.project.team.team_dsh import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _switch({TEST_DSH_PANEL_A: DSH_STATE_OK},
                          answer={'detail': 'нет роли rogue'}, answer_status=400,
                          project=TEST_DSH_PROJECT_A, enabled=True)

        assert error.value.status == 422
        assert 'нет роли rogue' in str(error.value)

    async def test_switch_maps_panel_failure_to_502(self):
        """Обратная половина: сломался пульт — 502, вина на той стороне."""
        from src.project.team.team_dsh import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _switch({TEST_DSH_PANEL_A: DSH_STATE_OK},
                          answer={'detail': 'хост не поднялся'}, answer_status=500,
                          project=TEST_DSH_PROJECT_A, enabled=True)

        assert error.value.status == 502

    async def test_switch_rejects_empty_role(self):
        """
        Пустая роль отсекается до сети.

        Без проверки запрос ушёл бы в пульт и вернулся 400 — то есть цена опечатки
        выросла бы до похода на чужую машину, а причина стала бы менее внятной.
        """
        from src.project.team.team_dsh import TeamDshError, team_dsh_switch

        with pytest.raises(TeamDshError) as error:
            await team_dsh_switch(TEST_DSH_PROJECT_A, '   ', True)

        assert error.value.status == 422

    async def test_switch_rejects_empty_project(self):
        """
        Без проекта роль не адресована никому — отсекаем до сети.

        Пультов несколько, роли у них одноимённые; «включить developer» без каталога
        пришлось бы гадать, а гадание здесь поднимает агента.
        """
        from src.project.team.team_dsh import TeamDshError, team_dsh_switch

        with pytest.raises(TeamDshError) as error:
            await team_dsh_switch('', TEST_DSH_ROLE, True)

        assert error.value.status == 422


class TestDshCard:
    """Добавочные карточки роли: «плюс» рядом с выключателем и крестик на карточке."""

    async def test_add_asks_the_panel_for_one_more_card(self):
        """
        Нажатие «+» уходит в `/roles/add` и возвращает заведённую карточку с номером.

        Номер выбирает пульт, а не страница: между показом блока и нажатием кнопки
        карточки могли завестись и уйти в архив, и присланный страницей номер уже
        ничего бы не значил. Поэтому в теле только проект и роль.
        """
        result, calls = await _card_add(
            {TEST_DSH_PANEL_A: DSH_STATE_OK},
            answer={'role': TEST_DSH_ROLE, 'card_id': 'card-x-3', 'index': 3,
                    'cards': ['card-x-1', 'card-x-2', 'card-x-3'], 'changed': True},
            project=TEST_DSH_PROJECT_A)

        assert calls[-1]['method'] == 'POST'
        assert calls[-1]['url'] == TEST_DSH_PANEL_A + '/roles/add'
        assert calls[-1]['json'] == {'project': TEST_DSH_PROJECT_A, 'role': TEST_DSH_ROLE}
        assert result == {'project': TEST_DSH_PROJECT_A, 'role': TEST_DSH_ROLE,
                          'card_id': 'card-x-3', 'index': 3, 'changed': True,
                          'cards': ['card-x-1', 'card-x-2', 'card-x-3']}

    async def test_add_goes_to_the_panel_of_the_project(self):
        """
        Пульт ищется по каталогу проекта — как и у выключателя, а не по адресу извне.

        Адрес пульта в запросе означал бы, что браузер выбирает, к кому сервер сходит в
        сети; имена ролей у всех проектов одинаковые, и промах завёл бы карточку чужому.
        """
        _, calls = await _card_add({TEST_DSH_PANEL_A: DSH_STATE_OK,
                                    TEST_DSH_PANEL_B: DSH_STATE_B},
                                   answer={'role': TEST_DSH_ROLE, 'index': 2},
                                   project=TEST_DSH_PROJECT_B)

        assert calls[-1]['url'].startswith(TEST_DSH_PANEL_B)

    async def test_drop_names_the_card_by_id(self):
        """
        Крестик уходит в `/roles/drop` и называет карточку по имени, а не по номеру.

        Номер живёт до первого перезавода поколения (`…-2` → `…-2-g2`), а страница
        показывает состояние прошлой сверки. Id же пульт разберёт целиком — проект,
        роль, номер, поколение, — и промах кнопкой станет отказом, а не архивом чужой
        сессии.
        """
        result, calls = await _card_drop(
            {TEST_DSH_PANEL_A: DSH_STATE_OK},
            answer={'role': TEST_DSH_ROLE, 'card_id': TEST_DSH_CARD_EXTRA, 'index': 2,
                    'cards': [TEST_DSH_CARD_BASE], 'changed': True},
            project=TEST_DSH_PROJECT_A, card_id=TEST_DSH_CARD_EXTRA)

        assert calls[-1]['url'] == TEST_DSH_PANEL_A + '/roles/drop'
        assert calls[-1]['json'] == {'project': TEST_DSH_PROJECT_A, 'role': TEST_DSH_ROLE,
                                     'card_id': TEST_DSH_CARD_EXTRA}
        assert result['cards'] == [TEST_DSH_CARD_BASE]
        assert result['changed'] is True

    async def test_drop_reports_nothing_changed(self):
        """
        Карточка уже в архиве — `changed` ложно, но это не ошибка.

        Страница обновляется раз в 15 секунд, и её картинка отстаёт от хоста: крестик
        нажимают по карточке, которой уже нет. Стань это отказом, человек видел бы
        ошибку, получив ровно то, чего хотел.
        """
        result, _ = await _card_drop({TEST_DSH_PANEL_A: DSH_STATE_OK},
                                     answer={'role': TEST_DSH_ROLE, 'changed': False},
                                     project=TEST_DSH_PROJECT_A, card_id=TEST_DSH_CARD_EXTRA)

        assert result['changed'] is False
        assert result['card_id'] == TEST_DSH_CARD_EXTRA, 'своё имя карточки — запасное'

    async def test_drop_rejects_empty_card_id(self):
        """
        Крестик без имени карточки отсекается до сети.

        Пустое имя пульт разобрал бы как «не карточка этой роли» и ответил 400, но
        цена опечатки выросла бы до похода на чужую машину. К тому же выбирать
        карточку за человека здесь нельзя: соседняя — чужой круг работы.
        """
        from src.project.team.team_dsh_card import team_dsh_card_drop
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await team_dsh_card_drop(TEST_DSH_PROJECT_A, TEST_DSH_ROLE, '   ')

        assert error.value.status == 422

    async def test_drop_maps_base_card_refusal_to_422(self):
        """
        Базовую карточку убрать нельзя, и отказ пульта — наш кривой запрос, не поломка.

        Убрать базовую значит выключить роль, а на это есть выключатель. 400 пульта
        обязан уйти наружу как 422: иначе страница напишет «пульт недоступен», и
        чинить пойдут ноутбук.
        """
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _card_drop({TEST_DSH_PANEL_A: DSH_STATE_OK},
                             answer={'detail': 'базовую карточку роли не убирают, а выключают'},
                             answer_status=400, project=TEST_DSH_PROJECT_A,
                             card_id=TEST_DSH_CARD_BASE)

        assert error.value.status == 422
        assert 'не убирают' in str(error.value)

    async def test_add_raises_when_panel_is_dead(self):
        """
        Пульт молчит — исключение, а не тихий пустой ответ.

        За «+» стоит нажатая кнопка: верни мы «ничего не произошло», человек прочёл бы
        это как заведённую карточку и ждал бы второго круга, которого никто не начинал.
        """
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _card_add({TEST_DSH_PANEL_A: httpx.ConnectError('нет такого хоста')},
                            answer={}, project=TEST_DSH_PROJECT_A)

        assert error.value.status == 502

    async def test_add_to_unknown_project_is_422(self):
        """Все пульты ответили, а такого проекта у них нет — сервис не подняли, 422."""
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _card_add({TEST_DSH_PANEL_A: DSH_STATE_OK}, answer={},
                            project='/home/user/PycharmProjects/BlogAi')

        assert error.value.status == 422

    async def test_card_calls_reject_empty_project_and_role(self):
        """
        Без проекта или роли карточка не адресована никому — отсекаем до сети.

        Пультов несколько, роли у них одноимённые: «добавить карточку developer» без
        каталога пришлось бы гадать, а гадание здесь заводит агента чужому проекту.
        """
        from src.project.team.team_dsh_card import team_dsh_card_add, team_dsh_card_drop
        from src.project.team.team_dsh_panel import TeamDshError

        for project, role in (('', TEST_DSH_ROLE), (TEST_DSH_PROJECT_A, '  ')):
            with pytest.raises(TeamDshError) as error:
                await team_dsh_card_add(project, role)
            assert error.value.status == 422

            with pytest.raises(TeamDshError) as error:
                await team_dsh_card_drop(project, role, TEST_DSH_CARD_EXTRA)
            assert error.value.status == 422


class TestDshProject:
    """
    Подключение проекта к пульту: кнопка в шапке блока вместо команды на машине.

    Главный вопрос здесь — **какому пульту отдать проект**. Адрес от страницы не
    принимают нигде (иначе браузер выбирал бы, к кому сервер ходит в сети), а сам сервер
    знать не может, на какой машине лежит каталог. Поэтому подключение пробуют у всех
    ответивших по очереди и берут первого, кто согласился: согласиться может лишь тот, у
    кого этот каталог есть, — проверку делает сам пульт.
    """

    async def test_attach_takes_the_first_panel_that_agrees(self):
        """
        Пробуем все пульты подряд, берём согласившегося — выбор за файловой системой.

        Отказ соседа не конец: каталог лежит на одной машине, и у второго пульта он
        может быть. Остановись перебор на первом отказе, подключить проект с другой
        машины стало бы нельзя вовсе.
        """
        result, calls = await _attach(
            {TEST_DSH_PANEL_A: DSH_STATE_OK, TEST_DSH_PANEL_B: DSH_STATE_B},
            posts={TEST_DSH_PANEL_A: (400, {'detail': 'нет каталога'}),
                   TEST_DSH_PANEL_B: (200, {'project': TEST_DSH_PROJECT_NEW,
                                            'label': 'BlogAi', 'added': True})},
            project=TEST_DSH_PROJECT_NEW)
        asked = [item['url'] for item in calls if item['url'].endswith('/projects/add')]

        assert asked == [TEST_DSH_PANEL_A + '/projects/add',
                         TEST_DSH_PANEL_B + '/projects/add'], 'отказ первого не конец перебора'
        assert result == {'project': TEST_DSH_PROJECT_NEW, 'label': 'BlogAi',
                          'panel': TEST_DSH_PANEL_B, 'attached': True, 'changed': True}

    async def test_attach_names_the_root_in_the_body(self):
        """Каталог уходит в тело: другого общего признака у страницы и пульта нет."""
        _, calls = await _attach({TEST_DSH_PANEL_A: DSH_STATE_OK},
                                 post={'project': TEST_DSH_PROJECT_NEW, 'added': True},
                                 project=TEST_DSH_PROJECT_NEW)

        assert calls[-1]['method'] == 'POST'
        assert calls[-1]['json'] == {'project': TEST_DSH_PROJECT_NEW}

    async def test_attach_of_a_served_project_asks_nobody(self):
        """
        Проект уже в списке пульта — `changed` ложно, и в сеть за этим не ходим.

        Страница обновляется раз в 15 секунд, и кнопку жмут по отставшей картинке.
        Стань повтор отказом, человек видел бы ошибку, получив ровно то, чего хотел.
        """
        result, calls = await _attach({TEST_DSH_PANEL_A: DSH_STATE_OK},
                                      project=TEST_DSH_PROJECT_A)

        assert [item for item in calls if item['method'] == 'POST'] == []
        assert result == {'project': TEST_DSH_PROJECT_A, 'label': 'RhapsodyAi',
                          'panel': TEST_DSH_PANEL_A, 'attached': True, 'changed': False}

    async def test_attach_without_takers_is_422(self):
        """
        Все ответили и все отказали — каталога нет ни на одной машине, вина наша.

        Это 422, а не 502: сеть в порядке, чинить нечего. Человеку надо сказать про
        каталог, а не гнать его поднимать сервис, который и так поднят.
        """
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _attach({TEST_DSH_PANEL_A: DSH_STATE_OK, TEST_DSH_PANEL_B: DSH_STATE_B},
                          post={'detail': 'нет каталога /home/user/PycharmProjects/BlogAi'},
                          post_status=400, project=TEST_DSH_PROJECT_NEW)

        assert error.value.status == 422
        assert 'каталога' in str(error.value)
        assert TEST_DSH_PANEL_A in str(error.value), 'по причине должно быть видно, кто отказал'

    async def test_attach_with_all_panels_silent_is_502(self):
        """Пульты молчат — вина на той стороне: машина выключена, а не запрос кривой."""
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _attach({TEST_DSH_PANEL_A: httpx.ConnectError('нет такого хоста')},
                          project=TEST_DSH_PROJECT_NEW)

        assert error.value.status == 502
        assert 'не отвечают' in str(error.value)

    async def test_attach_rejects_empty_project(self):
        """Без каталога подключать нечего — отсекаем до сети."""
        from src.project.team.team_dsh_panel import TeamDshError
        from src.project.team.team_dsh_project import team_dsh_project_attach

        with pytest.raises(TeamDshError) as error:
            await team_dsh_project_attach('   ')

        assert error.value.status == 422

    async def test_detach_goes_to_the_owner(self):
        """
        Отключение уходит тому пульту, у кого проект в списке, и называет погашенные роли.

        Перебирать здесь нечего: владелец известен из состояния. Роли в ответе нужны
        странице словами — человек только что оборвал их переписку и должен видеть, чью.
        """
        result, calls = await _detach(
            {TEST_DSH_PANEL_A: DSH_STATE_OK, TEST_DSH_PANEL_B: DSH_STATE_B},
            post={'project': TEST_DSH_PROJECT_B, 'dropped': True, 'roles': ['developer']},
            project=TEST_DSH_PROJECT_B)

        assert calls[-1]['url'] == TEST_DSH_PANEL_B + '/projects/drop'
        assert calls[-1]['json'] == {'project': TEST_DSH_PROJECT_B, 'force': False}
        assert result == {'project': TEST_DSH_PROJECT_B, 'panel': TEST_DSH_PANEL_B,
                          'attached': False, 'changed': True, 'roles': ['developer']}

    async def test_detach_passes_force_through(self):
        """
        `force` уходит как есть: это ответ на уже заданный человеку вопрос.

        Пульт при живых ролях откажет и назовёт их — страница спросит, и второе нажатие
        придёт с `force`. Подставь мы его сами, вопрос никто бы не задал, а карточки
        ушли бы в архив вместе с перепиской.
        """
        _, calls = await _detach({TEST_DSH_PANEL_A: DSH_STATE_OK},
                                 post={'dropped': True}, project=TEST_DSH_PROJECT_A, force=True)

        assert calls[-1]['json']['force'] is True

    async def test_detach_of_unattached_project_asks_nobody(self):
        """
        Проекта нет ни у кого, и все ответили — значит он уже отключён, это не ошибка.

        Ходить некуда: владельца нет. Отказ здесь означал бы ошибку на кнопке, которая
        сделала ровно то, чего от неё хотели.
        """
        result, calls = await _detach({TEST_DSH_PANEL_A: DSH_STATE_OK},
                                      project=TEST_DSH_PROJECT_NEW)

        assert [item for item in calls if item['method'] == 'POST'] == []
        assert result['attached'] is False
        assert result['changed'] is False
        assert result['panel'] == ''

    async def test_detach_blames_the_silent_panel(self):
        """
        Кто-то молчал — «уже отключён» соврало бы: владельцем мог быть как раз он.

        Разница видна человеку сразу: тихое «готово» он прочтёт как сделанное и уйдёт,
        а проект останется подключённым на невставшей машине.
        """
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _detach({TEST_DSH_PANEL_A: DSH_STATE_OK,
                           TEST_DSH_PANEL_B: httpx.ConnectError('молчит')},
                          project=TEST_DSH_PROJECT_NEW)

        assert error.value.status == 502

    async def test_detach_maps_refusal_to_422(self):
        """
        400 пульта — «домашний проект не отключают» либо «роли живы», то есть наш запрос.

        Наружу это 422 с причиной пульта: иначе страница напишет «пульт недоступен», и
        человек пойдёт чинить ноутбук вместо того, чтобы погасить роли.
        """
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _detach({TEST_DSH_PANEL_A: DSH_STATE_OK},
                          post={'detail': 'домашний проект сервиса не отключают'},
                          post_status=400, project=TEST_DSH_PROJECT_A)

        assert error.value.status == 422
        assert 'домашний проект' in str(error.value)


class TestDshHostRestart:
    """
    Кнопка «Перезапуск» наверху страницы: хост Harness сам собой не поднимается никогда.

    Случай, ради которого кнопку и завели, — хост лёг. Пока он молчит, сервис лишь
    пропускает сверку карточек, и включённые роли не поднимутся ни через минуту, ни
    через час: чинить это некому. Отсюда и правила ниже — адресуемся всем машинам разом,
    молчание одной не отменяет остальных, а полная неудача обязана быть слышной.
    """

    async def test_restart_goes_to_every_panel(self):
        """
        Пульт — это машина, хост у машины свой: перезапускаем на всех ответивших.

        Выбирать машину человеку нечем — адреса пультов страница не видит и видеть не
        должна, а точка «жив» наверху горит по правилу «жив хоть у кого-то».
        """
        result, calls = await _host_restart({TEST_DSH_PANEL_A: DSH_STATE_OK,
                                             TEST_DSH_PANEL_B: DSH_STATE_B},
                                            post={'started': True, 'pid': 4242})

        posted = [call for call in calls if call['url'].endswith('/host/restart')]
        assert [call['url'] for call in posted] == [TEST_DSH_PANEL_A + '/host/restart',
                                                    TEST_DSH_PANEL_B + '/host/restart']
        assert result['restarted'] == 2
        assert result['total'] == 2
        assert result['problem'] == ''

    async def test_restart_names_no_project(self):
        """
        Единственная ручка dsh с пустым телом: хост общий, адресовать нечего.

        Назови мы проект — пульт понял бы это как «перезапусти хост проекта», которого
        не существует: процесс один на машину, и его перезапуск задевает все проекты.
        """
        _, calls = await _host_restart({TEST_DSH_PANEL_A: DSH_STATE_BOTH},
                                       post={'started': True, 'pid': 4242})

        assert calls[-1]['json'] is None

    async def test_restart_waits_longer_than_the_rest(self):
        """
        У перезапуска свой потолок: он гасит процесс, ждёт порт и поднимает заново.

        Общий срок пульта оборвал бы это на середине, и страница сказала бы «пульт не
        ответил» ровно в тот миг, когда хост как раз поднимался, — а человек нажал бы
        второй раз и погасил уже поднятый.
        """
        from src.project.team.team_dsh_host import TEAM_DSH_HOST_TIMEOUT
        from src.project.team.team_dsh_panel import (TEAM_DSH_PANEL_CONNECT_TIMEOUT,
                                                     TEAM_DSH_PANEL_TIMEOUT)

        _, calls = await _host_restart({TEST_DSH_PANEL_A: DSH_STATE_OK},
                                       post={'started': True, 'pid': 4242})

        assert calls[0]['timeout'].read == TEAM_DSH_PANEL_TIMEOUT, 'опрос ролей — общий срок'
        assert calls[-1]['timeout'].read == TEAM_DSH_HOST_TIMEOUT
        # Дозвон сроком не меняется никогда: пульта либо нет, либо он рядом. Раздуй его
        # перезапуск — выключенный ноутбук держал бы страницу все полторы минуты.
        assert calls[-1]['timeout'].connect == TEAM_DSH_PANEL_CONNECT_TIMEOUT

    async def test_silent_panel_does_not_stop_the_others(self):
        """
        Машины независимы: до одной не дозвонились — вторую всё равно чиним.

        Молчащий пульт в `total` не идёт. Он не машина с лежачим хостом, а машина, про
        хост которой нам ничего не известно: посчитай мы её, «1 из 2» читалось бы как
        «на одной не получилось».
        """
        result, _ = await _host_restart(
            {TEST_DSH_PANEL_A: DSH_STATE_OK,
             TEST_DSH_PANEL_B: httpx.ConnectError('ноутбук выключен')},
            post={'started': True, 'pid': 4242})

        assert result['restarted'] == 1
        assert result['total'] == 1, 'молчащий пульт — не машина, у которой не вышло'
        assert TEST_DSH_PANEL_B in result['problem']
        assert result['panels'][0]['url'] == TEST_DSH_PANEL_A

    async def test_failed_panel_is_named_but_not_fatal(self):
        """Один пульт отказал, второй поднял — это успех с причиной в `problem`."""
        result, _ = await _host_restart(
            {TEST_DSH_PANEL_A: DSH_STATE_OK, TEST_DSH_PANEL_B: DSH_STATE_B},
            posts={TEST_DSH_PANEL_A: (502, {'detail': 'порт занят и после остановки'}),
                   TEST_DSH_PANEL_B: (200, {'started': True, 'pid': 4242})})

        assert result['restarted'] == 1
        assert result['total'] == 2
        assert 'порт занят' in result['problem']
        assert [item['restarted'] for item in result['panels']] == [False, True]
        assert [item['pid'] for item in result['panels']] == [0, 4242]

    async def test_nobody_restarted_is_an_error(self):
        """
        Ни один хост не поднялся — молчаливое «готово» человек прочтёт как сделанное.

        Он вернётся к своим ролям, увидит, что они по-прежнему не берут кругов, и
        станет искать поломку в них, а не в лежачем хосте.
        """
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _host_restart({TEST_DSH_PANEL_A: DSH_STATE_OK},
                                post={'detail': 'порт занят и после остановки'},
                                post_status=502)

        assert error.value.status == 502
        assert 'порт занят' in str(error.value)

    async def test_all_panels_silent_is_an_error(self):
        """Все пульты молчат — перезапускать было негде, и сказать об этом обязаны."""
        from src.project.team.team_dsh_panel import TeamDshError

        with pytest.raises(TeamDshError) as error:
            await _host_restart({TEST_DSH_PANEL_A: httpx.ConnectError('ноутбук выключен')})

        assert error.value.status == 502
        assert TEST_DSH_PANEL_A in str(error.value)

    async def test_no_panels_at_all_is_our_own_setup(self):
        """
        Адресов нет вовсе — это ненастроенная установка, а не поломка чужой машины.

        Отсюда 422, а не 502: винить нечего, пульта в этой установке никто не заводил.
        Пустым `DSH_CONTROL_URL` этого не добиться — там умолчание, мост docker; список
        пустеет от значения из одних разделителей, то есть от вычищенной настройки.
        """
        import src.project.team.team_dsh_panel as panel
        from src.project.team.team_dsh_host import team_dsh_host_restart
        from src.project.team.team_dsh_panel import TeamDshError

        with patch.object(panel, 'config_get', lambda key, default='': ','):
            with pytest.raises(TeamDshError) as error:
                await team_dsh_host_restart()

        assert error.value.status == 422
        assert 'DSH_CONTROL_URL' in str(error.value)

    async def test_pid_of_a_foreign_process_is_a_number(self):
        """
        Пульт — чужой процесс чужого репозитория, и его `pid` для нас входные данные.

        Страница печатает его в сообщении об успехе; приди оттуда строка или `null`,
        падать посреди удавшегося перезапуска было бы худшим из исходов.
        """
        result, _ = await _host_restart({TEST_DSH_PANEL_A: DSH_STATE_OK},
                                        post={'started': True, 'pid': 'не число'})

        assert result['restarted'] == 1
        assert result['panels'][0]['pid'] == 0


class TestDshRoutes:
    """Ручки страницы команды: права и обязательные поля."""

    def test_routes_are_guarded(self):
        """
        Все ручки под `AuthChecker`, причём меняющие — под правом на изменение.

        Просмотр состояния и поднятие агента не одно и то же: вторым распоряжается
        тот, кому позволено менять конвейер. Карточки здесь наравне с выключателем:
        «+» поднимает ещё одного агента, крестик гасит работающего. Подключение проекта
        — тоже изменение конвейера, а отключение вдобавок гасит работающие роли.
        Перезапуск хоста — тем более: он обрывает круги всех ролей всех проектов разом.
        """
        from src.auth.auth import AuthChecker
        from src.auth.auth_permission import AuthPermission
        from src.uvicorn.routers.project import project_team

        paths = ('/api/team/dsh', '/api/team/dsh/switch', '/api/team/dsh/project',
                 '/api/team/dsh/card/add', '/api/team/dsh/card/drop',
                 '/api/team/dsh/restart')
        checkers = {}
        for route in project_team.router.routes:
            if getattr(route, 'path', '') not in paths:
                continue
            for dependency in route.dependant.dependencies:
                if isinstance(dependency.call, AuthChecker):
                    checkers[route.path] = dependency.call.required_permissions

        assert set(checkers) == set(paths), 'ручка без AuthChecker открыта всем'
        assert checkers['/api/team/dsh'] == [AuthPermission.PLANNING_VIEW]
        assert checkers['/api/team/dsh/switch'] == [AuthPermission.PLANNING_UPDATE]
        assert checkers['/api/team/dsh/card/add'] == [AuthPermission.PLANNING_UPDATE]
        assert checkers['/api/team/dsh/card/drop'] == [AuthPermission.PLANNING_UPDATE]
        assert checkers['/api/team/dsh/project'] == [AuthPermission.PLANNING_UPDATE]
        assert checkers['/api/team/dsh/restart'] == [AuthPermission.PLANNING_UPDATE]

    def test_switch_request_requires_project(self):
        """
        Проект — обязательное поле запроса, а не необязательное с умолчанием.

        Умолчание означало бы «первый попавшийся пульт», то есть запуск агента не в
        том проекте от старой страницы, кэшированной в браузере.
        """
        import pydantic

        from src.uvicorn.routers.project.project_team import TeamDshRequest

        with pytest.raises(pydantic.ValidationError):
            TeamDshRequest(role=TEST_DSH_ROLE, enabled=True)

    def test_card_request_requires_project_and_role(self):
        """
        У запроса карточки обязательны проект и роль, а `card_id` — нет.

        Проект и роль без умолчаний по той же причине, что у выключателя: умолчание
        означало бы «первый попавшийся пульт». А `card_id` пустым приходит законно —
        его шлёт только крестик, «+» карточку не называет.
        """
        import pydantic

        from src.uvicorn.routers.project.project_team import TeamDshCardRequest

        with pytest.raises(pydantic.ValidationError):
            TeamDshCardRequest(role=TEST_DSH_ROLE)
        with pytest.raises(pydantic.ValidationError):
            TeamDshCardRequest(project=TEST_DSH_PROJECT_A)

        assert TeamDshCardRequest(project=TEST_DSH_PROJECT_A, role=TEST_DSH_ROLE).card_id == ''

    def test_project_request_requires_project_and_attached(self):
        """
        У запроса подключения обязательны каталог и само действие, а `force` — нет.

        Умолчание у `attached` пришлось бы выбрать, и любое было бы неверным: «включено»
        подключало бы проект на пустом запросе, «выключено» — гасило бы его роли.
        А `force` законно приходит пустым: его шлёт только второе нажатие, после
        вопроса человеку.
        """
        import pydantic

        from src.uvicorn.routers.project.project_team import TeamDshProjectRequest

        with pytest.raises(pydantic.ValidationError):
            TeamDshProjectRequest(attached=True)
        with pytest.raises(pydantic.ValidationError):
            TeamDshProjectRequest(project=TEST_DSH_PROJECT_A)

        assert TeamDshProjectRequest(project=TEST_DSH_PROJECT_A, attached=False).force is False


def _urls(raw: str) -> list:
    """Список адресов при заданном значении `DSH_CONTROL_URL`."""
    import src.project.team.team_dsh_panel as panel

    with patch.object(panel, 'config_get', lambda key, default='': raw):
        return panel.team_dsh_panel_urls()


async def _state_from(answers: dict, secret: str = 'test-secret') -> dict:
    """Состояние при заданных ответах пультов: `{адрес: тело или исключение}`."""
    async with _panels(answers, secret=secret):
        from src.project.team.team_dsh import team_dsh_state
        return await team_dsh_state()


async def _switch(answers: dict, answer: dict, project: str, enabled: bool,
                  answer_status: int = 200) -> tuple:
    """
    Переключение роли: `answers` — ответы на `GET /roles`, `answer` — на сам `POST`.

    Возвращает результат и список запросов: в нём сначала опрос всех пультов, потом
    само переключение — его и проверяют по `calls[-1]`.
    """
    async with _panels(answers, post=answer, post_status=answer_status) as calls:
        from src.project.team.team_dsh import team_dsh_switch
        return await team_dsh_switch(project, TEST_DSH_ROLE, enabled), calls


async def _card_add(answers: dict, answer: dict, project: str,
                    answer_status: int = 200) -> tuple:
    """Нажатие «+»: `answers` — ответы на `GET /roles`, `answer` — на `POST /roles/add`."""
    async with _panels(answers, post=answer, post_status=answer_status) as calls:
        from src.project.team.team_dsh_card import team_dsh_card_add
        return await team_dsh_card_add(project, TEST_DSH_ROLE), calls


async def _card_drop(answers: dict, answer: dict, project: str, card_id: str,
                     answer_status: int = 200) -> tuple:
    """Нажатие крестика: то же самое, но `POST /roles/drop` и названная карточка."""
    async with _panels(answers, post=answer, post_status=answer_status) as calls:
        from src.project.team.team_dsh_card import team_dsh_card_drop
        return await team_dsh_card_drop(project, TEST_DSH_ROLE, card_id), calls


async def _host_restart(answers: dict, post: dict = None, post_status: int = 200,
                        posts: dict = None) -> tuple:
    """
    Нажатие «Перезапуск»: `answers` — ответы на `GET /roles`, `post` — на `/host/restart`.

    Проекта у перезапуска нет, поэтому и аргумента нет: адресуемся всем ответившим
    пультам разом. `posts` нужен, когда один пульт поднял хост, а другой отказал.
    """
    async with _panels(answers, post=post, post_status=post_status, posts=posts) as calls:
        from src.project.team.team_dsh_host import team_dsh_host_restart
        return await team_dsh_host_restart(), calls


async def _attach(answers: dict, project: str, post: dict = None, post_status: int = 200,
                  posts: dict = None) -> tuple:
    """
    Подключение проекта. `posts` — свой ответ каждого пульта: `{адрес: (код, тело)}`.

    Он и нужен здесь чаще общего `post`: подключение пробуют у всех подряд, и весь
    смысл в том, что один отказывает, а другой соглашается.
    """
    async with _panels(answers, post=post, post_status=post_status, posts=posts) as calls:
        from src.project.team.team_dsh_project import team_dsh_project_attach
        return await team_dsh_project_attach(project), calls


async def _detach(answers: dict, project: str, post: dict = None, post_status: int = 200,
                  force: bool = False) -> tuple:
    """Отключение проекта: перебирать пульты не нужно, владелец известен из состояния."""
    async with _panels(answers, post=post, post_status=post_status) as calls:
        from src.project.team.team_dsh_project import team_dsh_project_detach
        return await team_dsh_project_detach(project, force), calls


class _panels:
    """
    Пульты-заглушки: подменяют `httpx.AsyncClient.request`, список адресов и секрет.

    Подменяются ровно три внешних куска — сеть и две настройки. Сборка URL, заголовок,
    разбор ответа, выбор пульта по проекту и отображение кодов остаются настоящими:
    их мы и проверяем.

    Секрет фиксируем своим: в окружении разработчика лежит боевой, и тест, который его
    читает, отправил бы его в мок, а на машине без `.env` падал бы на пустом значении —
    то есть проверял бы установку, а не код.

    Адреса берём вымышленные (`panel-a`, `panel-b`): промахнись мок мимо подмены, такой
    хост не разрешится, а не постучится в живой пульт на соседнем порту.
    """

    def __init__(self, answers: dict, post: dict = None, post_status: int = 200,
                 posts: dict = None, secret: str = 'test-secret'):
        self.answers = answers
        self.post = post if post is not None else {}
        self.post_status = post_status
        # `posts` — свой ответ на меняющую ручку для каждого пульта: `{адрес: (код, тело)}`.
        # Им и различают согласившегося от отказавшего, когда проект пробуют подключить
        # всем подряд; общего `post` для этого мало — там ответ у всех одинаковый.
        self.posts = posts or {}
        self.secret = secret
        self.calls = []

    async def __aenter__(self):
        import src.project.team.team_dsh_panel as panel

        async def _request(client, method, url, json=None, headers=None, **kwargs):
            # `timeout` записываем с клиента, а не из аргументов: срок задаётся при его
            # создании. Отдельным сроком живёт перезапуск хоста, и проверить его иначе
            # нечем — в самом запросе он не виден.
            self.calls.append({'method': method, 'url': str(url), 'json': json,
                               'headers': dict(headers or {}),
                               'timeout': getattr(client, 'timeout', None)})
            status, answer = self._answer_for(str(url))
            if isinstance(answer, Exception):
                raise answer
            return httpx.Response(status, json=answer,
                                  request=httpx.Request(method, url))

        self._patches = [
            patch.object(httpx.AsyncClient, 'request', _request),
            patch.object(panel, 'config_get', self._config),
        ]
        for item in self._patches:
            item.start()

        return self.calls

    async def __aexit__(self, *exc):
        for item in self._patches:
            item.stop()
        return False

    def _config(self, key: str, default: str = '') -> str:
        from src.project.team.team_dsh_panel import TEAM_DSH_PANEL_URL_KEY

        if key == TEAM_DSH_PANEL_URL_KEY:
            return ','.join(self.answers)
        return self.secret

    def _answer_for(self, url: str) -> tuple:
        """Ответ того пульта, чей адрес стоит в начале URL: `(код, тело или исключение)`."""
        for base, answer in self.answers.items():
            if not url.startswith(base):
                continue
            if isinstance(answer, Exception):
                return 0, answer
            if not url.endswith(TEST_DSH_PANEL_POSTS):
                return 200, answer
            return self.posts.get(base, (self.post_status, self.post))

        return 200, {}


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

"""Переменные запроса: пускаем только объявленные, остальное — 400.

## ⚠⚠ Что здесь стережётся

Дыра, найденная 23 сентября. `POST /chat/ask` подмешивал `variables` запроса
**последними**, поверх всего:

    workflow_variables_all = {**базовые, **агентские, **json_request.variables}

То есть вызывающий переопределял **любую** внутреннюю переменную workflow — не
только предназначенную ему.

Проверено живьём, не выведено из чтения кода: в запрос клалось
`fact_collection_girl_name: 'ЧУЖАЯ_КОЛЛЕКЦИЯ'`, и в трассе прогона стояло именно
оно. Поиск и запись фактов уводились в чужое хранилище одним полем запроса. Тем
же способом уводились `prompt_user`, `girl_id`, имя агента.

## Правило

Пускаем `input` (то, что вызывающий обязан прислать) и `global` (переменные
запроса, у них своя роль в движке). Внутренние `workflow` — нет.

## ⚠⚠ Ни один тест здесь не доводит вызов до модели

Файл лежит в обычной сюите, а она идёт сама, на каждую правку. Значит **цена
каждого вызова умножается на число прогонов** — и платит её не время, а очередь
ноды: модель одна на тесты и на прод, та же, что отвечает живым людям на сайте
знакомств.

Отсюда деление проверок на две половины, и оно не стилистическое:

| Что проверяем | Чем | Доходит до модели |
|---|---|---|
| сторож стоит и отвергает | живой `POST /chat/ask` | **нет**: 400 раньше прогона |
| список объявленных верен | `GET /workflow/{id}/variables` | нет: это чтение |

⚠⚠ **Так было не сразу, и вот чего это стоило.** Первая версия проверяла
согласие **поведением**: слала каждую переменную DatingAi и смотрела, не
отвергли ли. Довод был «так сильнее — проверяется то самое, что делает живой
вызов». Довод неверен: объявленная переменная проходит сторожа и **запускает
workflow целиком**. Замерено на прогоне — 57 секунд в одном тесте, 14 живых
вызовов модели за сюиту, и столько же брошенных прогонов в статусе `running`,
потому что клиент отваливался по таймауту раньше.

Сторож — это вычитание множеств. «Не отвергает объявленное» доказывается тем же
списком, из которого он читает, а не запуском модели за ним.
"""

import uuid

import httpx
import pytest

from tests.conftest import BASE_URL
from tests.constants import TEST_AUTH

pytestmark = pytest.mark.ai

# Агент чата: по нему находится workflow `dating_talk`.
#
# ⚠ Ищем **по имени**, а не по номеру: номер разъезжается между установками
# (локально 1663, на проде свой), и прибитая константа сломала бы тест на первом
# же переносе базы.
AGENT_NAME = 'dating_girl_universal'

# Внутренняя переменная `dating_talk`: имя коллекции фактов девушки. Ровно ею и
# была показана дыра.
INNER = 'fact_collection_girl_name'

# Типы, которые сторож пускает. ⚠ Список повторяет `_variables_allowed` в
# `chat.py`: разойдись они — тест зеленел бы при отвергнутом вызове.
ALLOWED_TYPES = ('input', 'global')

# То, что кладёт `answer.py` в DatingAi.
#
# ⚠⚠ **При правке там — править и здесь.** Тест на то и стоит: разойдись списки,
# занятие встанет целиком и молча для того, кто правил реестр, — он увидит `400`
# в журнале чужого проекта.
DATING_SENDS = ('talk_history', 'companion_uid', 'companion_bio', 'girl_bio',
                'answer_anyway', 'make_initiative', 'initiative_kind',
                'girl_name', 'girl_id', 'companion_name', 'companion_title',
                'chat_timeout')


@pytest.fixture
async def client():
    """Вошедший клиент. Тот же приём, что в соседних файлах сюиты."""
    async with httpx.AsyncClient(base_url=BASE_URL, follow_redirects=False,
                                 timeout=30.0) as got:
        await got.post('/auth/login', json=TEST_AUTH)
        yield got


class TestTheHoleIsClosed:
    """⚠ Внутреннюю переменную снаружи не подменить.

    ⚠⚠ Эти вызовы **до модели не доходят**: сторож стоит перед сборкой промпта и
    отвечает `400` раньше, чем запускается прогон. Оттого они и остались
    поведенческими — в отличие от обратной стороны ниже.
    """

    async def test_an_inner_variable_is_refused(self, client):
        got = await _ask(client, {INNER: 'ЧУЖАЯ_КОЛЛЕКЦИЯ'})

        assert got.status_code == 400, \
            f'внутреннюю переменную приняли: {got.status_code}'
        assert INNER in got.text, \
            f'отказ не называет, какая переменная лишняя: {got.text[:200]}'

    async def test_the_refusal_says_what_to_do(self, client):
        """⚠ Отказ обязан объяснять. «400 Bad Request» без имени переменной
        отправляет искать ошибку в запросе целиком."""
        got = await _ask(client, {INNER: 'x'})

        assert 'не объявлены входящими' in got.text, got.text[:200]

    async def test_a_typo_is_refused_too(self, client):
        """⚠⚠ И опечатка — тоже отказ, а не молчание.

        Прислав `girl_i` вместо `girl_id`, вызывающий до этой правки получал бы
        зелёный ответ и молчащую ветку промпта: переменная легла бы в сборку под
        своим кривым именем, а `%if girl_id%` осталась бы пустой.
        """
        got = await _ask(client, {'girl_i': 'опечатка'})

        assert got.status_code == 400, 'опечатку в имени приняли молча'


class TestWhatDatingAiSendsIsDeclared:
    """⚠⚠ Сторож договора: всё, что шлёт DatingAi, объявлено у соседа.

    Обратная сторона запрета, и она важнее самого запрета: он отвергает всё
    незнакомое — значит любая забытая в реестре переменная останавливает занятие
    целиком.

    ⚠ Спрашиваем **тот же список**, из которого читает сторож
    (`ai_workflow_variables_input_get` + глобальные), но ручкой, а не запуском
    workflow за ней. Ручка отдаёт и переменные типа `workflow` — их отсеиваем
    здесь же, иначе тест пропустил бы ровно то, что сторож и ловит.
    """

    async def test_every_sent_variable_is_declared(self, client):
        declared = await _declared(client, await _workflow_id(client))

        missing = sorted(set(DATING_SENDS) - declared)

        assert not missing, \
            (f'DatingAi шлёт необъявленное — вызовы упадут с 400: {missing}.'
             f' Объявите их входящими у `dating_talk` либо уберите из'
             f' `answer.py`')

    async def test_the_agent_create_handle_variables_are_declared(self, client):
        """⚠⚠ Ручка `/agent/create` добавляет переменные САМА, и её забыли.

        Она кладёт их всем мастерам без разбора, а вызывающий об этом не знает:

            variables['agent_name'] = data.name
            variables.setdefault('chat_timeout', AGENT_CREATE_CHAT_TIMEOUT)

        `agent_name` проходит — он `global`. `chat_timeout` был объявлен у
        `dating_talk`, но не у `dating_girl_create` — а именно его гоняет
        заведение агента анкеты. На проде это значило бы, что **ни одна новая
        анкета не заводится**: `400` вместо агента.

        ⚠ Поймано прогоном миграций на копии прод-базы перед выкладкой, а не
        тестами: локальная база уже имела нужные строки от прошлых заходов, и
        проверка была зелёной при сломанном проде.

        ⚠⚠ Проверяются **все мастера сразу**, а не `dating_girl_create` по имени:
        ручка добавляет переменные каждому, кого зовёт, и второй мастер упал бы
        ровно так же.
        """
        masters = await _masters(client)

        if not masters:
            pytest.skip('мастеров (workflow с агентом *_runner) в этой базе нет')

        broken = []
        for workflow_id, name in masters:
            declared = await _declared(client, workflow_id)
            missing = sorted({'agent_name', 'chat_timeout'} - declared)
            if missing:
                broken.append(f'{name}: {", ".join(missing)}')

        assert not broken, \
            (f'ручка /agent/create шлёт необъявленное — заведение агента упадёт'
             f' с 400: {"; ".join(broken)}')

    async def test_an_inner_variable_is_not_among_them(self, client):
        """⚠ Сторож проверки: список объявленных не должен разрастись до
        внутренних.

        Без этого теста стоило бы кому-нибудь объявить `fact_collection_girl_name`
        входящей ради удобства — и дыра открылась бы заново, а проверка выше
        осталась бы зелёной.
        """
        declared = await _declared(client, await _workflow_id(client))

        assert INNER not in declared, \
            (f'внутренняя переменная {INNER} объявлена входящей — дыра открыта'
             f' заново')


# ── Приватное ────────────────────────────────────────────────────────────────

async def _workflow_id(client) -> int:
    """Номер workflow чата — через агента, по его системному имени."""
    answer = await client.get(f'/agent/name/{AGENT_NAME}')

    if answer.status_code != 200:
        pytest.skip(f'агента «{AGENT_NAME}» нет в этой базе')

    return int((answer.json().get('result') or {}).get('workflow_id') or 0)


async def _masters(client) -> list:
    """Workflow, которые гоняет ручка `/agent/create`, — по её же признаку.

    Она ищет агента с именем `<workflow>_runner`; тем же условием находим их и
    здесь. Перечисли мы имена руками — список разошёлся бы с ручкой при заведении
    нового мастера, и тест молчал бы о сломанном.
    """
    answer = await client.get('/agent/list')

    if answer.status_code != 200:
        return []

    runners = {str(one.get('name') or '') for one in
               (answer.json().get('result') or [])
               if str(one.get('name') or '').endswith('_runner')}

    listed = await client.get('/workflow/list')

    if listed.status_code != 200:
        return []

    return [(int(one['id']), str(one.get('name') or ''))
            for one in (listed.json().get('result') or [])
            if f"{one.get('name')}_runner" in runners]


async def _declared(client, workflow_id: int) -> set:
    """Имена, которые сторож пропустит: входящие этого workflow и глобальные.

    ⚠ Ручка отдаёт **все** переменные, связанные с workflow, включая внутренние
    (`workflow`) и переменные ноды. Отбираем по типу — тем же правилом, что у
    сторожа.
    """
    answer = await client.get(f'/workflow/{workflow_id}/variables')

    assert answer.status_code == 200, \
        f'список переменных не читается ({answer.status_code}): {answer.text[:200]}'

    return {str(row.get('name')) for row in (answer.json().get('result') or [])
            if str(row.get('type')) in ALLOWED_TYPES}


async def _ask(client, variables: dict):
    """Вопрос агенту чата. Возвращает ответ как есть — код проверяет тест.

    ⚠⚠ Зовётся **только с заведомо лишней переменной**. Сторож отвечает на неё
    `400` до запуска workflow, и модель не тревожится. Пошли сюда объявленную —
    и каждый прогон сюиты занимал бы очередь ноды вместо живых собеседников.
    """
    agent = (await client.get(f'/agent/name/{AGENT_NAME}')).json()
    agent_id = (agent.get('result') or {}).get('id')

    companions = (await client.get('/companion/list')).json().get('result') or []
    companion = next((one for one in companions
                      if one.get('name') == 'test_llm_companion'), None)

    if not agent_id or not companion:
        pytest.skip('агента или собеседника тестов нет в этой базе')

    return await client.post('/chat/ask', json={
        'question': f'probe {uuid.uuid4().hex[:6]}',
        'agent_id': agent_id, 'companion_id': companion['id'],
        'session_uuid': str(uuid.uuid4()),
        'variables': variables})

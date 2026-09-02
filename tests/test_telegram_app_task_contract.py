"""
Мини-приложение говорит с сервером телом ровно тем, что рисует `flags.js` и
`questions.js`, — и сервер это тело принимает так, как обещает карточка.

Зачем этот файл, когда разметка проверена браузером в
`test_telegram_app_task_ui.py`. Тот прогон подменяет ответы сервера заглушкой:
он доказывает, что чип отправляет `{patch: {to_planning: false}}`, а не то, что
после такого запроса в задаче меняется `metadata`. Граница проходит по телу
запроса — значит она и проверяется живым запросом: та же байтовая последовательность,
что отдаёт фронтенд, уходит настоящему обработчику, а результат читается из БД.

Прокси-точки (`/telegram-app/task/*`) рисует соседняя подзадача, и на момент
написания этого круга их нет — требовать их здесь значило бы проверять чужую
работу. Берётся то, что уже лежит в master и вызывается из тех же точек:
`POST /task/{id}/metadata` и `POST /task/{id}/question/answer`. Прокси повторяет
их контракт точь-в-точь (`telegram_app_task.py` в плане задачи), поэтому проверка
здесь — проверка того же обещания, что человек получит в мини-приложении.

Тело запроса не переписывается по памяти: константы ниже сверяются с модулями
фронтенда тестом `test_frontend_sends_exactly_these_bodies`. Совпадёт тело —
совпадёт и смысл: рассинхронится `flags.js`, проверка покраснеет.
"""
import json

import pytest

TEST_TITLE = '__pytest_miniapp_contract'
# Родитель подзадачи: на него вешается FK `parent_id`, поэтому заводим настоящей
# строкой, а не номером — чужой id в тестовой базе то существует, то нет.
TEST_TITLE_ROOT = '__pytest_miniapp_contract_root'

# --- Тела, которые реально отправляет фронтенд ---
#
# `flags.js:157` — postData(ENDPOINT(id), {patch: {[key]: _flagValue(key, checked)}}),
# `_flagValue` (там же, ниже публичного) даёт для снятого «в планирование» false, для
# возвращённого — None (ключ стирается), для «в разработку» — true/null.
FLAG_BODY_PLAN_OFF = {'patch': {'to_planning': False}}
FLAG_BODY_PLAN_BACK = {'patch': {'to_planning': None}}
FLAG_BODY_DEV_ON = {'patch': {'to_development': True}}
FLAG_BODY_TEST_OFF = {'patch': {'to_testing': False}}

# `questions.js:531` — одиночный вопрос: postData(API_ANSWER(id), {answers, note,
# goal_indexes}); пачка (`:488`) дописывает index — номер вопроса в ней.
ANSWER_BODY_SINGLE = {'answers': ['split'], 'note': 'Кроме третьей цели', 'goal_indexes': []}
ANSWER_BODY_BATCH_FIRST = {'answers': ['yes'], 'note': '', 'goal_indexes': [], 'index': 0}


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def app():
    """Приложение с точками задач и правом тестовой учётки.

    Право подменяем на входе, а не подменяем `AuthChecker`: саму проверку прав
    здесь доказывать не за чем — она своя в тесте #5235 («доступность точки ответа
    на вопрос»), и подмена `auth_get_current_user` оставила бы её как есть, ровно
    как делают тесты других точек (`test_gx10.py`).
    """
    from fastapi import FastAPI

    from src.auth import auth as auth_module
    from src.auth.auth_session import AuthSession
    from src.uvicorn.routers.project.project_task import router as task_router
    from src.uvicorn.routers.project.project_task_question import router as question_router

    async def _qa_user(request):
        return AuthSession(user_id=1, username='qa_contract', role='qa')

    original = auth_module.auth_get_current_user
    auth_module.auth_get_current_user = _qa_user
    try:
        application = FastAPI()
        application.include_router(task_router)
        application.include_router(question_router)
        yield application
    finally:
        auth_module.auth_get_current_user = original


@pytest.fixture
async def client(app):
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://contract.test') as c:
        yield c


class TestFlagContract:
    """Чекбокс фазы: то же тело, что шлёт чип, — и настоящая запись в `metadata`."""

    async def test_plan_flag_off_is_written_as_false(self, client):
        """Снятие «в планирование» — явный false: умолчание «ключа нет» читается включённым."""
        task_id = await _create()
        try:
            response = await client.post(f'/task/{task_id}/metadata', json=FLAG_BODY_PLAN_OFF)

            assert response.status_code == 200, response.text
            assert await _metadata(task_id) is False, \
                'снятый флажок не долетел до metadata — карточка нарисует его включённым'
        finally:
            await _drop(task_id)

    async def test_plan_flag_returned_deletes_the_key(self, client):
        """Возврат флажка — `null`: ключ стирается, и задача снова «по умолчанию»."""
        task_id = await _create(metadata={'to_planning': False})
        try:
            response = await client.post(f'/task/{task_id}/metadata', json=FLAG_BODY_PLAN_BACK)

            assert response.status_code == 200, response.text
            assert 'to_planning' not in await _metadata(task_id, full=True), \
                'ключ пережил снятие — следующего отбора менеджера задача не дождётся'
        finally:
            await _drop(task_id)

    async def test_dev_flag_on_is_written_as_true(self, client):
        """"В разработку" — одноразовый триггер, включённое хранится явным true."""
        task_id = await _create()
        try:
            response = await client.post(f'/task/{task_id}/metadata', json=FLAG_BODY_DEV_ON)

            assert response.status_code == 200, response.text
            assert await _metadata(task_id) is True
        finally:
            await _drop(task_id)

    async def test_other_keys_survive_the_patch(self, client):
        """Один флажок не уносит чужие ключи: в мешке живут вопрос, решения и ветка."""
        task_id = await _create(metadata={'question': {'text': 'Спрашивает роль'},
                                          'branch': 'feature/task_5238'})
        try:
            await client.post(f'/task/{task_id}/metadata', json=FLAG_BODY_TEST_OFF)

            stored = await _metadata(task_id, full=True)
            assert stored['to_testing'] is False
            assert stored['question']['text'] == 'Спрашивает роль'
            assert stored['branch'] == 'feature/task_5238'
        finally:
            await _drop(task_id)

    def test_frontend_sends_exactly_these_bodies(self):
        """Тела выше совпадают с `flags.js` — иначе проверка краснеет на пустом месте.

        Ключи метаданных читаются прямо из текста модуля: правка фронтом (новое
        имя ключа, другая форма тела) обязана быть замечена здесь, а не в браузере
        на странице задач.
        """
        source = _read('data/uvicorn/public/js/telegram_app/flags.js')

        assert "'to_planning'" in source and "'to_development'" in source \
               and "'to_testing'" in source, 'ключи фаз ушли из flags.js — сверь константы'
        # Значения `_flagValue`: инверсия для plan/test, явное true для dev.
        assert 'checked ? null : false' in source, '_flagValue перестал писать false у выключенного'
        assert 'checked ? true : null' in source, '_flagValue перестал писать true у «в разработку»'
        assert '{ patch: { [key]:' in source, 'тело записи больше не {patch: {[key]: …}}'


class TestQuestionContract:
    """Панель вопросов: ответ тем же телом — и решение в `metadata.decisions`."""

    async def test_single_answer_is_accepted_as_decision(self, client):
        """Вопрос снят из мешка, ответ лёг в решения — роль прочтёт его следующим кругом."""
        task_id = await _create(metadata={'question': {
            'text': 'Раздробить цели?', 'role': 'qa',
            'options': [{'key': 'split', 'label': 'Раздробить'},
                        {'key': 'keep', 'label': 'Оставить как есть'}]}},
            parent_id=True)
        try:
            response = await client.post(f'/task/{task_id}/question/answer', json=ANSWER_BODY_SINGLE)

            assert response.status_code == 200, response.text
            stored = await _metadata(task_id, full=True)
            decisions = stored.get('decisions') or []
            assert decisions, 'ответ не стал решением — роль следующим кругом спросит снова'
            assert 'Раздробить' in decisions[-1]['answer'], \
                f'в решении нет подписи варианта: {decisions[-1]["answer"]!r}'
            assert 'Кроме третьей цели' in decisions[-1]['answer']
            assert not stored.get('question'), 'вопрос пережил ответ — карточка снова зовёт отвечать'
        finally:
            await _drop(task_id)

    async def test_free_answer_without_options_is_accepted(self, client):
        """Вариантов может и не быть — открытый вопрос, от человека ждут текст."""
        task_id = await _create(metadata={'question': {'text': 'Что делаем с реестром?',
                                                       'role': 'developer'}},
                                parent_id=True)
        try:
            response = await client.post(f'/task/{task_id}/question/answer',
                                         json={'answers': [], 'note': 'Только staging',
                                               'goal_indexes': []})

            assert response.status_code == 200, response.text
            decisions = (await _metadata(task_id, full=True)).get('decisions') or []
            assert decisions and decisions[-1]['answer'] == 'Только staging'
        finally:
            await _drop(task_id)

    async def test_batch_answer_keeps_the_batch_open_until_last(self, client):
        """Пачка разведки: ответ на один вопрос — черновик, `done=false`, задача стоит.

        Ровно то, ради чего `questions.js` не закрывает панель после первого
        ответа: половина развилок, поданная роли как решённая, хуже ни одной.
        """
        task_id = await _create(metadata={'questions': [
            {'text': 'Первый', 'role': 'manager', 'options': [{'key': 'yes', 'label': 'Да'}]},
            {'text': 'Второй', 'role': 'manager', 'options': [{'key': 'no', 'label': 'Нет'}]}]},
            parent_id=True)
        try:
            response = await client.post(f'/task/{task_id}/question/answer',
                                         json=ANSWER_BODY_BATCH_FIRST)

            assert response.status_code == 200, response.text
            body = response.json()
            assert body['done'] is False and body['left'] == 1, \
                f'пачка закрылась на первом ответе: {body}'
            assert not (await _metadata(task_id, full=True)).get('decisions'), \
                'половина развилок ушла в решения — роль спланирует по ней'

            second = await client.post(f'/task/{task_id}/question/answer',
                                       json={'answers': ['no'], 'note': '', 'goal_indexes': [],
                                             'index': 1})
            assert second.status_code == 200, second.text
            assert second.json()['done'] is True
            assert len((await _metadata(task_id, full=True)).get('decisions') or []) == 2
        finally:
            await _drop(task_id)

    def test_frontend_sends_exactly_this_shape(self):
        """Форма ответа панели совпадает с полем `TaskQuestionAnswer` роутера.

        Тело пачки собирает `_batchBody` — именованное место, а не расширение формы
        по месту вызова: у пачки и одиночного вопроса разные поля (`index` против
        `goal_indexes`), и собирать их врозь двумя литералами значит держать два
        описания одного контракта.
        """
        source = _read('data/uvicorn/public/js/telegram_app/questions.js')

        for field in ('answers', 'note', 'goal_indexes'):
            assert field in source, f'`{field}` исчез из questions.js — сверь ANSWER_BODY_SINGLE'
        assert 'function _batchBody(form, index)' in source, 'тело пачки собирается не там'
        assert '{ answers: form.answers, note: form.note, index }' in source, \
            'пачка перестала дописывать index или начала слать цели — сверь тело'


# --- Служебное ниже публичного ---

async def _create(metadata: dict | None = None, parent_id: bool = False) -> int:
    """Строка задачи со своим мешком.

    `parent_id` — подзадача: действия над целями и автовопрос у корневой задачи
    запрещены самим роутером (409), и проверка не должна спотыкаться о чужое
    правило. Флаги же, наоборот, человек ставит у корневой — их проверяем на ней.
    Родителя заводим настоящей строкой: `fk_pt_parent` не принимает номер, под
    которым в тестовой базе ничего нет.
    """
    from mysql_.mysql_ import mysql_get_db_async

    await _drop(None)
    async with mysql_get_db_async() as db:
        root_id = None
        if parent_id:
            await db.execute(
                "INSERT INTO project_task (title, pipeline_state) VALUES (%s, 'planned')",
                (TEST_TITLE_ROOT,))
            root_id = int(db.lastrowid)
        await db.execute(
            "INSERT INTO project_task (title, parent_id, pipeline_state, metadata) "
            "VALUES (%s, %s, 'new', CAST(%s AS JSON))",
            (TEST_TITLE, root_id, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        task_id = db.lastrowid
        await db.connection.commit()
    return int(task_id)


async def _metadata(task_id: int, full: bool = False):
    """Нужный ключ мешка целиком, без разбора строки в словарь."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute("SELECT metadata FROM project_task WHERE id = %s", (task_id,))
        row = await db.fetchone()
    raw = (row or {}).get('metadata')
    stored = json.loads(raw) if isinstance(raw, str) else (raw or {})
    if full:
        return stored or {}
    for key in ('to_planning', 'to_development', 'to_testing'):
        if key in stored:
            return stored[key]
    return None


async def _drop(task_id: int | None) -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_task WHERE title = %s", (TEST_TITLE,))
        await db.connection.commit()


def _read(relative: str) -> str:
    """Текст модуля фронтенда — чтобы сверять тела запросов со словом в коде."""
    import pathlib

    return (pathlib.Path(__file__).resolve().parent.parent / relative).read_text(encoding='utf-8')

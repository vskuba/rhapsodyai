"""Сценарии: хранение, запуск и журнал прогонов.

Разделение обязанностей такое: шаги выполняет контейнер (там живут страницы),
а хранит их и журналирует `uvicorn` — у него уже есть пул MySQL. Поэтому здесь
нет ни строчки Playwright: сценарий уезжает телом запроса, трасса приезжает
ответом, и в базу ложится ровно она.

Секреты в базу не попадают никогда. `variables` таблицы — это значения по
умолчанию для необязательных подстановок (адрес стенда, имя проекта), а логины
и пароли передаются полем `secrets` в момент запуска и живут только в памяти
запроса: в шагах остаётся `{{password}}`, в трассе — `***`.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from browser_.browser_scenario import (BROWSER_SCENARIO_ACTIONS,
                                       BROWSER_SCENARIO_RETURNS,
                                       BROWSER_SCENARIO_STEP_TIMEOUT_MS,
                                       BrowserScenario,
                                       browser_scenario_variables_used)
from mysql_.mysql_ import mysql_get_db_async

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.browser.scenario_repository import BrowserScenarioRepository
from src.uvicorn.routers.browser.browser_proxy_net import browser_proxy_net_url
from src.uvicorn.routers.browser.browser_site_variable import browser_site_variable_values
from src.uvicorn.routers.browser.browser_upstream import (
    BROWSER_UPSTREAM_SCENARIO_TIMEOUT,
    browser_upstream_request,
)

router = APIRouter(prefix='/api/browser/scenario', tags=['browser'])

# Журнал прогонов растёт быстрее всего остального: один сценарий на расписании
# даёт сотни записей в сутки. Страница истории показывает последние — за более
# старыми есть `offset`.
BROWSER_SCENARIO_RUN_PAGE = 50


class BrowserScenarioSave(BaseModel):
    """Тело создания и правки. Шаги проверяются схемой контейнера — той же самой."""

    site_id: int | None = Field(None, description='Сайт-закладка, к которому относится сценарий')
    name: str = Field(..., min_length=1, max_length=100)
    goal: str = Field('', max_length=255)
    start_url: str = Field('', max_length=500)
    steps: list = Field(..., min_length=1)
    variables: dict[str, str] = Field(default_factory=dict, description='Значения по умолчанию; секретов здесь нет')
    status: str = Field('draft', pattern='^(draft|active|broken)$')


class BrowserScenarioRun(BaseModel):
    """Запуск сохранённого сценария."""

    session_id: str = Field('', description='Пусто — контейнер заведёт временную сессию')
    variables: dict[str, str] = Field(default_factory=dict, description='Поверх значений сценария; попадут в журнал')
    secrets: dict[str, str] = Field(default_factory=dict, description='Пароли и токены; ни в базу, ни в журнал')
    keep_session: bool = Field(False, description='Оставить сессию живой — посмотреть результат в /admin/browser')
    proxy_id: int = Field(0, ge=0,
                          description='Выход из реестра «Proxy» для временной вкладки прогона')


@router.get('/action')
async def browser_scenario_action_list(user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Справочник действий: какое действие какие поля требует.

    Отдаётся из той же схемы, что проверяет шаги (`BROWSER_SCENARIO_ACTIONS`), —
    форма редактора спрашивает ровно обязательные поля, и второй список действий,
    который разошёлся бы с ней на первой правке, заводить не приходится.

    Путь до `/{scenario_id}`: иначе `action` уехал бы в него номером и вернул 422.
    """
    return {'result': {'actions': {name: list(fields)
                                   for name, fields in BROWSER_SCENARIO_ACTIONS.items()},
                       'timeout_ms': BROWSER_SCENARIO_STEP_TIMEOUT_MS}}


@router.get('')
async def browser_scenario_list(site_id: int = 0,
                                user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """
    Сценарии сайта, свежие сверху.

    `site_id` — чьи сценарии. Ноль означает «все»: так список открывается там, где
    сайт ещё не выбран, и так же он вёл себя раньше.

    Фильтр обязателен на странице сайта: сценарии принадлежат сайту (`site_id` в
    строке), и без отбора при выборе нового сайта показывались бы чужие — ровно
    это и происходило, пока параметра не было.
    """
    where, params = ('WHERE site_id = %s', [int(site_id)]) if site_id else ('', [])

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, site_id, name, goal, start_url, status, created_at, updated_at '
            f'FROM browser_scenario {where} ORDER BY id DESC', params
        )
        rows = await db.fetchall()

    return {'result': rows}


@router.get('/parser')
async def browser_scenario_parser_list(site_id: int = 0,
                                       user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """
    Сценарии, которые возвращают данные, — с описанием того, что именно вернут.

    Это ответ на вопрос клиента «что я вообще могу отсюда получить». Соседний
    проект не должен знать ни селекторов, ни разметки: он берёт отсюда список,
    выбирает нужный номер и зовёт обычный `POST /{id}/run`. Разметка чужого сайта
    меняется — правится сценарий здесь, клиента это не касается и выкладки не
    требует.

    Отдельной ручкой, а не полем общего списка: там строки без шагов, и разбирать
    их у каждого сценария ради признака «отдаёт ли он данные» значило бы читать
    `steps` всей таблицы на каждый показ страницы.

    В `fields` — плоские имена полей записи, с точкой на вложенности
    (`фото.адрес`). Клиенту нужен состав записи, а не дерево селекторов: селекторы
    — наше внутреннее дело, и показывать их наружу значило бы снова привязать
    клиента к разметке, от которой мы его и уводим.

    Путь объявлен до `/{scenario_id}`: иначе FastAPI разобрал бы `parser` как номер
    сценария и ответил 422 про непарсящееся число.
    """
    where, params = ('WHERE site_id = %s', [int(site_id)]) if site_id else ('', [])

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, site_id, name, goal, status, steps '
            f'FROM browser_scenario {where} ORDER BY id DESC', params)
        rows = await db.fetchall() or []

    result = []
    for row in rows:
        models = _parser_models(row.get('steps'))
        if not models:
            continue
        result.append({'id': int(row['id']), 'site_id': row.get('site_id'),
                       'name': row.get('name'), 'goal': row.get('goal'),
                       'status': row.get('status'), 'returns': models})

    return {'result': result}


@router.post('', status_code=201)
async def browser_scenario_create(data: BrowserScenarioSave,
                                  user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Заводит сценарий, предварительно прогнав шаги через схему."""
    scenario = _scenario_check(data)

    try:
        scenario_id = await BrowserScenarioRepository().add({
            'site_id': data.site_id,
            'name': data.name,
            'goal': data.goal,
            'start_url': data.start_url,
            'steps': json.dumps([step.model_dump() for step in scenario.steps], ensure_ascii=False),
            'variables': json.dumps(data.variables, ensure_ascii=False),
            'status': data.status,
        })
    except Exception as e:
        # Имя уникально: сценарий зовут по имени и из задачи, и из расписания.
        raise HTTPException(status_code=409, detail=f'не удалось сохранить сценарий: {e}')

    return {'result': scenario_id}


@router.get('/{scenario_id}')
async def browser_scenario_get(scenario_id: int, user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Сценарий целиком: шаги и имена переменных, которые он ждёт."""
    row = await _scenario_row(scenario_id)
    variables_used = _variables_used(row)
    # Драйвер отдаёт JSON-столбцы строкой; форма запуска ждёт массив и словарь.
    row['steps'] = _json_load(row.get('steps'), [])
    row['variables'] = _json_load(row.get('variables'), {})

    return {'result': row, 'variables_used': variables_used}


@router.put('/{scenario_id}')
async def browser_scenario_update(scenario_id: int, data: BrowserScenarioSave,
                                  user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Переписывает сценарий целиком — так же, как это сделает агент этапа 7."""
    await _scenario_row(scenario_id)
    scenario = _scenario_check(data)

    await BrowserScenarioRepository().update(scenario_id, {
        'site_id': data.site_id,
        'name': data.name,
        'goal': data.goal,
        'start_url': data.start_url,
        'steps': json.dumps([step.model_dump() for step in scenario.steps], ensure_ascii=False),
        'variables': json.dumps(data.variables, ensure_ascii=False),
        'status': data.status,
    })

    return {'status': 'success'}


@router.delete('/{scenario_id}')
async def browser_scenario_delete(scenario_id: int,
                                  user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Удаляет сценарий вместе с его журналом (каскадом по внешнему ключу)."""
    await _scenario_row(scenario_id)
    await BrowserScenarioRepository().delete(scenario_id)

    return {'status': 'success'}


@router.post('/{scenario_id}/run')
async def browser_scenario_run(scenario_id: int, data: BrowserScenarioRun,
                               user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Гонит сценарий в контейнере и кладёт трассу в журнал.

    Удачные прогоны журналируются наравне с неудачными: по одним ошибкам не видно,
    что сценарий стал вдвое медленнее, — а это первый признак, что вёрстка поехала.
    """
    result = await browser_scenario_run_one(scenario_id, data.session_id, data.variables,
                                           data.secrets, data.keep_session, data.proxy_id)

    return {'result': result}


async def browser_scenario_run_one(scenario_id: int, session_id: str, variables: dict,
                                   secrets: dict, keep_session: bool,
                                   proxy_id: int = 0) -> dict:
    """Один прогон сценария: отдать контейнеру, записать журнал, поправить метку.

    Отдельной функцией, а не только ручкой: прогон зовут и изнутри — например,
    когда сценарий гонят несколько раз подряд по одной сессии. Второй такой же
    код разошёлся бы с этим, и журнал писался бы не у всех вызовов.

    Возвращает ответ контейнера как есть: код запроса тут ни при чём, упавший на
    третьем шаге сценарий — это `status: "error"` с трассой, а не ошибка HTTP.

    ⚠ `proxy_id` действует только на **временную** вкладку (`session_id` пуст): у
    готовой сессии выход задан при открытии, и менять его на ходу Playwright не
    умеет. Номер разворачивается здесь — у контейнера базы нет.
    """
    row = await _scenario_row(scenario_id)
    scenario = _scenario_load(row)

    # Переменные сайта — общий запас для всех его сценариев: логин и пароль заводятся
    # один раз на сайт, а не переписываются в каждый сценарий (`browser_site_variable`).
    # Сценарий без сайта (`site_id IS NULL`) получает пустые сумки и работает как
    # раньше — такие есть, связь с сайтом появилась позже самих сценариев.
    site_plain, site_secret = ({}, {})
    if row.get('site_id'):
        site_plain, site_secret = await browser_site_variable_values(int(row['site_id']))

    payload = {
        'scenario': scenario.model_dump(),
        'session_id': session_id,
        # Три слоя, от общего к частному: переменные сайта, свои значения сценария,
        # переданные на запуск. Побеждает более частное — обычное правило настроек.
        #
        # Почему сайт снизу, а не сверху. Значения сценария заводили руками до
        # появления этой таблицы, и они у сценариев уже есть; окажись сайт выше, любой
        # такой сценарий молча сменил бы поведение на первом же прогоне. Снизу он
        # закрывает то, чего у сценария нет, и ничего не ломает. Хочется
        # централизации — значение в сценарии чистят, и остаётся сайтовое.
        'variables': {**site_plain, **_variables_default(row), **_filled(variables)},
        # Секреты — отдельной сумкой, и это не формальность: контейнер замазывает их
        # в трассе и в тексте ошибок, а `variables` попадают в журнал как есть
        # (`browser_scenario_mask`). Пароль, положенный не в ту сумку, уехал бы в
        # `browser_scenario_run.trace` открытым текстом — то самое, от чего его здесь
        # и шифруют.
        'secrets': {**site_secret, **_filled(secrets)},
        'keep_session': keep_session,
        # Выход временной вкладки. Разворачиваем номер в адрес здесь: реестр наш,
        # и пароль канала не должен ездить через сеть ради того, что мы знаем.
        'proxy': await browser_proxy_net_url(proxy_id) if proxy_id and not session_id else '',
    }

    result = await browser_upstream_request('POST', '/browser/scenario/run', payload,
                                            timeout=BROWSER_UPSTREAM_SCENARIO_TIMEOUT)

    await _run_save(scenario_id, result)

    # Упавший прогон в журнал ошибок больше не дублируется. Всё, что о нём писалось
    # — текст ошибки, номер шага, сессия, — `_run_save` только что положил в
    # `browser_scenario_run` вместе с трассой по шагам, и вкладка «Журналы» показывает
    # это на месте, рядом с самим сценарием. Вторая запись о том же событии в другой
    # таблице заставляла сверять два списка и вводила в заблуждение счётчиком: одна
    # поломка считалась дважды.
    #
    # Страница ошибок теперь про другое — про то, о чём сообщили клиенты, соседние
    # проекты, ходящие в браузер и сценарии по API. У них своего журнала здесь нет, и
    # рассказать о сбое им больше негде.

    # Сломанный сценарий помечается сразу: по метке видно, что чинить, без чтения журнала.
    status = 'broken' if result.get('status') == 'error' else 'active'
    if row.get('status') != status:
        await BrowserScenarioRepository().update(scenario_id, {'status': status})

    return result


@router.get('/{scenario_id}/run')
async def browser_scenario_run_list(scenario_id: int, limit: int = BROWSER_SCENARIO_RUN_PAGE, offset: int = 0,
                                    user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Журнал прогонов: свежие сверху, с трассой каждого."""
    await _scenario_row(scenario_id)
    limit = max(1, min(limit, BROWSER_SCENARIO_RUN_PAGE))

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, session_id, status, step_no, error, trace, extract, duration_ms, created_at '
            'FROM browser_scenario_run WHERE scenario_id = %s ORDER BY id DESC LIMIT %s OFFSET %s',
            (scenario_id, limit, max(0, offset))
        )
        rows = await db.fetchall()

    for row in rows:
        row['trace'] = _json_load(row.get('trace'), [])
        row['extract'] = _json_load(row.get('extract'), {})

    return {'result': rows}


def _json_load(value, default):
    """JSON-столбец приезжает то структурой, то строкой — зависит от драйвера."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default

    return value if value is not None else default


def _scenario_check(data: BrowserScenarioSave) -> BrowserScenario:
    """Проверяет шаги схемой контейнера: ошибку лучше увидеть при сохранении."""
    try:
        return BrowserScenario(name=data.name, goal=data.goal, steps=data.steps)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f'сценарий не проходит проверку: {e}')


def _scenario_load(row: dict) -> BrowserScenario:
    """Строка базы → сценарий для контейнера."""
    return BrowserScenario(name=row['name'], goal=row.get('goal', ''),
                           steps=_json_load(row.get('steps'), []))


async def _scenario_row(scenario_id: int) -> dict:
    """Сценарий из базы или 404 — иначе правка несуществующего молча ничего не делает."""
    row = await BrowserScenarioRepository().find(scenario_id)
    if not row:
        raise HTTPException(status_code=404, detail='сценарий не найден')

    return row


def _filled(values: dict | None) -> dict:
    """
    Переданные значения без пустых. Пустое не должно стирать значение сайта.

    Пустая строка не бывает осмысленным паролем: приходит она от незаполненного поля,
    а не от намерения. Пропусти мы её наверх — она перекрыла бы сохранённое значение
    сайта, и прогон упал бы на пустом поле формы вместо понятного «переменная не
    задана». Страница пустые поля и так не шлёт (`scenarioSubstitutions`), но ручка
    публичная, и полагаться на аккуратность вызывающего здесь не за что.

    Настоящее отсутствие переменной ловится не здесь, а проверкой контейнера
    (`browser_scenario_variables_missing`): она смотрит, что все `{{имена}}` шагов
    закрыты, и отвечает 422 со списком недостающих.
    """
    return {name: value for name, value in (values or {}).items() if str(value or '') != ''}


def _parser_models(steps) -> list[dict]:
    """
    Что вернёт сценарий: `[{'name', 'kind', 'fields'}]`. Пусто — данных не отдаёт.

    Смотрим шаги, а не отдельную таблицу: сбор данных и есть шаг сценария, и второй
    источник правды разошёлся бы с ним на первой же правке шагов.

    `kind` различает две формы ответа, потому что разбирать их клиенту по-разному:
    `rows` — список записей, `text` — строка (у неё несколько совпадений склеены
    переносами, это старое поведение `extract`).

    Какое действие что отдаёт, знает схема (`BROWSER_SCENARIO_RETURNS`), а не
    развилка здесь: сбор данных умеют полдесятка действий, и своя копия этого
    списка отставала бы от схемы на каждое новое — новый сбор молча не появлялся
    бы в модели, которую читают соседние проекты.
    """
    out = []
    for step in _json_load(steps, []) or []:
        if not isinstance(step, dict) or not step.get('name'):
            continue
        kind = BROWSER_SCENARIO_RETURNS.get(step.get('action'))
        if not kind:
            continue
        # Имена полей есть только у построчного сбора: у прочих их взять негде —
        # что придёт в записи `net_dump` или `console_dump`, решает не сценарий.
        fields = _field_names(step.get('fields') or []) if step.get('fields') else []
        out.append({'name': step['name'], 'kind': kind, 'fields': fields})

    return out


def _field_names(fields, prefix: str = '') -> list[str]:
    """Имена полей записи, вложенные — через точку: `фото.адрес`."""
    out = []
    for field in fields:
        if not isinstance(field, dict) or not field.get('name'):
            continue
        name = prefix + str(field['name'])
        nested = field.get('fields') or []
        out.extend(_field_names(nested, name + '.') if nested else [name])

    return out


def _variables_default(row: dict) -> dict:
    """Значения по умолчанию из базы, приведённые к строкам."""
    values = _json_load(row.get('variables'), {})

    return {str(k): str(v) for k, v in values.items()} if isinstance(values, dict) else {}


def _variables_used(row: dict) -> list[str]:
    """Какие подстановки сценарий ждёт — чтобы форма запуска спросила именно их."""
    try:
        return browser_scenario_variables_used(_scenario_load(row))
    except Exception:
        return []


async def _run_save(scenario_id: int, result: dict):
    """Кладёт трассу в журнал. Секретов в ней нет — контейнер маскирует их до ответа."""
    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO browser_scenario_run '
            '(scenario_id, session_id, status, step_no, error, trace, extract, duration_ms) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (
                scenario_id,
                str(result.get('session_id', ''))[:32],
                'error' if result.get('status') == 'error' else 'ok',
                int(result.get('step_no', 0) or 0),
                str(result.get('error', '')),
                json.dumps(result.get('steps', []), ensure_ascii=False),
                json.dumps(result.get('extract', {}), ensure_ascii=False),
                int(result.get('duration_ms', 0) or 0),
            )
        )

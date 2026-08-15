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

from mysql_.mysql_ import mysql_get_db_async

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.browser.browser_scenario import BrowserScenario, browser_scenario_variables_used
from src.mysql_.repository.browser.scenario_repository import BrowserScenarioRepository
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


@router.get('')
async def browser_scenario_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Все сценарии, свежие сверху."""
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, name, goal, start_url, status, created_at, updated_at '
            'FROM browser_scenario ORDER BY id DESC'
        )
        rows = await db.fetchall()

    return {'result': rows}


@router.post('', status_code=201)
async def browser_scenario_create(data: BrowserScenarioSave,
                                  user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Заводит сценарий, предварительно прогнав шаги через схему."""
    scenario = _scenario_check(data)

    try:
        scenario_id = await BrowserScenarioRepository().add({
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
async def browser_scenario_get(scenario_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Сценарий целиком: шаги и имена переменных, которые он ждёт."""
    row = await _scenario_row(scenario_id)
    variables_used = _variables_used(row)
    # Драйвер отдаёт JSON-столбцы строкой; форма запуска ждёт массив и словарь.
    row['steps'] = _json_load(row.get('steps'), [])
    row['variables'] = _json_load(row.get('variables'), {})

    return {'result': row, 'variables_used': variables_used}


@router.put('/{scenario_id}')
async def browser_scenario_update(scenario_id: int, data: BrowserScenarioSave,
                                  user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Переписывает сценарий целиком — так же, как это сделает агент этапа 7."""
    await _scenario_row(scenario_id)
    scenario = _scenario_check(data)

    await BrowserScenarioRepository().update(scenario_id, {
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
                                  user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Удаляет сценарий вместе с его журналом (каскадом по внешнему ключу)."""
    await _scenario_row(scenario_id)
    await BrowserScenarioRepository().delete(scenario_id)

    return {'status': 'success'}


@router.post('/{scenario_id}/run')
async def browser_scenario_run(scenario_id: int, data: BrowserScenarioRun,
                               user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Гонит сценарий в контейнере и кладёт трассу в журнал.

    Удачные прогоны журналируются наравне с неудачными: по одним ошибкам не видно,
    что сценарий стал вдвое медленнее, — а это первый признак, что вёрстка поехала.
    """
    row = await _scenario_row(scenario_id)
    scenario = _scenario_load(row)

    payload = {
        'scenario': scenario.model_dump(),
        'session_id': data.session_id,
        # Значения сценария — основа, переданные при запуске перекрывают их:
        # адрес стенда в базе, а на проверке хочется другой.
        'variables': {**_variables_default(row), **data.variables},
        'secrets': data.secrets,
        'keep_session': data.keep_session,
    }

    result = await browser_upstream_request('POST', '/browser/scenario/run', payload,
                                            timeout=BROWSER_UPSTREAM_SCENARIO_TIMEOUT)

    await _run_save(scenario_id, result)

    # Сломанный сценарий помечается сразу: по метке видно, что чинить, без чтения журнала.
    status = 'broken' if result.get('status') == 'error' else 'active'
    if row.get('status') != status:
        await BrowserScenarioRepository().update(scenario_id, {'status': status})

    return {'result': result}


@router.get('/{scenario_id}/run')
async def browser_scenario_run_list(scenario_id: int, limit: int = BROWSER_SCENARIO_RUN_PAGE, offset: int = 0,
                                    user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
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

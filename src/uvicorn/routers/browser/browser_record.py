"""Запись сценария за человеком: команды в контейнер, готовый черновик — в базу.

Разделение то же, что у прогона: действия видит контейнер (там страницы), а
хранит их `uvicorn` — у него пул MySQL. Поэтому здесь нет ни Playwright, ни
разбора событий: наружу уходит «начать/закончить», обратно приезжают шаги.

Сценарий из записи сохраняется черновиком: человек показал проход руками, но
имена подстановок, цель и лишние шаги он поправит уже в форме — до того, как
сценарий пойдёт в расписание.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from mysql_.mysql_ import mysql_get_db_async

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.browser.browser_scenario import BrowserScenario
from src.mysql_.repository.browser.scenario_repository import BrowserScenarioRepository
from src.uvicorn.routers.browser.browser_upstream import browser_upstream_request

router = APIRouter(prefix='/api/browser/session', tags=['browser'])

BROWSER_RECORD_NAME_DEFAULT = 'новый сценарий'
BROWSER_RECORD_NAME_LIMIT = 100

# Хвост `(2)`, `(3)`… к занятому имени. Предел нужен, чтобы кривой ввод не крутил
# цикл: сотня одноимённых черновиков — это уже не запись, а недоразумение.
BROWSER_RECORD_NAME_TRIES = 100


class BrowserRecordStart(BaseModel):
    name: str = Field('', max_length=BROWSER_RECORD_NAME_LIMIT)


class BrowserRecordStop(BaseModel):
    name: str = Field('', max_length=BROWSER_RECORD_NAME_LIMIT,
                      description='Имя черновика; пусто — возьмётся то, с которым начинали')
    site_id: int | None = Field(None, description='Сайт, к которому отнести записанный сценарий')


@router.get('/{session_id}/record')
async def browser_record_state(session_id: str, user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Идёт ли запись в сессии и сколько шагов уже набралось."""
    return await browser_upstream_request('GET', f'/browser/session/{session_id}/record')


@router.post('/{session_id}/record/start')
async def browser_record_start(session_id: str, data: BrowserRecordStart,
                               user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Включает запись действий: дальше человек просто работает в живом окне."""
    return await browser_upstream_request(
        'POST', f'/browser/session/{session_id}/record/start', {'name': _name_clean(data.name)})


@router.post('/{session_id}/record/stop')
async def browser_record_stop(session_id: str, data: BrowserRecordStop,
                              user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Останавливает запись и сохраняет снятые шаги черновиком сценария."""
    result = await browser_upstream_request('POST', f'/browser/session/{session_id}/record/stop')
    record = result.get('record') or {}
    steps = record.get('steps') or []

    # Считаем снятые действия, а не шаги: первым шагом контейнер сам дописывает
    # переход на стартовый адрес, и по нему запись без единого клика выглядела бы
    # состоявшейся — а сохранился бы сценарий «открыть страницу и ничего не делать».
    if not record.get('step_count'):
        raise HTTPException(status_code=409, detail='записывать было нечего: ни одного действия')

    name = _name_clean(data.name) or _name_clean(record.get('name', '')) or BROWSER_RECORD_NAME_DEFAULT
    name = await _name_free(name)
    scenario = _scenario_check(name, steps)
    start_url = str(record.get('start_url', ''))[:500]

    scenario_id = await BrowserScenarioRepository().add({
        # Сайт берём от страницы, на которой писали: сценарий заводят от закладки,
        # и без привязки он потерялся бы в общем списке.
        'site_id': data.site_id,
        'name': name,
        'goal': '',
        'start_url': start_url,
        'steps': json.dumps([step.model_dump() for step in scenario.steps], ensure_ascii=False),
        'variables': json.dumps({}, ensure_ascii=False),
        'status': 'draft',
    })

    return {'result': scenario_id, 'name': name, 'record': record}


def _name_clean(name) -> str:
    return str(name or '').strip()[:BROWSER_RECORD_NAME_LIMIT]


def _scenario_check(name: str, steps: list) -> BrowserScenario:
    """Шаги проверяются той же схемой, что и написанные руками.

    Запись собрана нашим же кодом, но проверка здесь не лишняя: предел на число
    шагов и длину значений — часть контракта сценария, а не свойство записи.
    """
    try:
        return BrowserScenario(name=name, goal='', steps=steps)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f'запись не складывается в сценарий: {e}')


async def _name_free(name: str) -> str:
    """Свободное имя рядом с занятым: имя сценария уникально в базе.

    Черновики пишутся с именем по умолчанию, и вторая запись падала бы на
    ограничении — а человек потерял бы вместе с ней все свои действия.
    """
    # Хвост может не влезть в столбец — тогда укорачивается основа, а не имя целиком.
    base = name[:BROWSER_RECORD_NAME_LIMIT - 6]

    async with mysql_get_db_async() as db:
        await db.execute('SELECT name FROM browser_scenario WHERE name = %s OR name LIKE %s',
                         (name, f'{base} (%)'))
        rows = await db.fetchall()

    taken = {row['name'] for row in rows}
    if name not in taken:
        return name

    for number in range(2, BROWSER_RECORD_NAME_TRIES):
        candidate = f'{base} ({number})'
        if candidate not in taken:
            return candidate

    raise HTTPException(status_code=409, detail=f'слишком много сценариев с именем «{name}»')

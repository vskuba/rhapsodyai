"""Workflow — цепочка сценариев: «войти» → «открыть раздел» → «проверить».

Сценарии остаются самостоятельными: каждый прогоняется и по отдельности, а
цепочка задаёт порядок и общий прогон **в одной сессии** — состояние страницы
переходит от звена к звену, ради этого цепочка и нужна. Иначе после входа
следующий сценарий начинал бы с чистого контекста и упирался в форму логина.

Звенья лежат отдельной таблицей, а не списком id в столбце: удалённый сценарий
не должен оставлять ссылку в никуда, и внешний ключ с каскадом убирает звено сам.
Порядок хранит `position` — тот же приём, что у карточек сайтов.

Прогон одного звена делает `browser_scenario_run_one` — та же функция, что и
одиночный запуск: журнал и метка `active`/`broken` пишутся одинаково, откуда бы
сценарий ни гнали.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from mysql_.mysql_ import mysql_get_db_async

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.browser.browser_scenario import BROWSER_SCENARIO_VAR_RE
from src.mysql_.repository.browser.workflow_repository import BrowserWorkflowRepository
from src.uvicorn.routers.browser.browser_scenario import browser_scenario_run_one

router = APIRouter(prefix='/api/browser/workflow', tags=['browser'])

# Цепочка длиной в сотню звеньев — это уже не цепочка, а сценарий, который надо
# писать шагами: у него и трасса читается, и чинится он одним местом.
BROWSER_WORKFLOW_STEP_LIMIT = 20


class BrowserWorkflowSave(BaseModel):
    """Тело создания и правки цепочки."""

    site_id: int | None = Field(None, description='Сайт-закладка, к которому относится цепочка')
    name: str = Field(..., min_length=1, max_length=100)
    scenario_ids: list[int] = Field(..., min_length=1, max_length=BROWSER_WORKFLOW_STEP_LIMIT,
                                    description='Сценарии по порядку прогона')


class BrowserWorkflowResponse(BaseModel):
    """Цепочка в списке. Сами звенья отдаёт `GET /api/browser/workflow/{id}`."""

    id: int = Field(..., description='Идентификатор цепочки', examples=[3])
    site_id: int | None = Field(None, description='Сайт-закладка, к которому относится цепочка',
                                examples=[19])
    name: str = Field(..., description='Название цепочки', examples=['вход и проверка кабинета'])
    position: int = Field(..., description='Порядок в списке; список отсортирован по нему', examples=[1])
    steps: int = Field(..., description='Сколько сценариев в цепочке', examples=[2])
    created_at: datetime | None = Field(None, description='Когда заведена')
    updated_at: datetime | None = Field(None, description='Когда правилась последний раз')


class BrowserWorkflowListResponse(BaseModel):
    result: list[BrowserWorkflowResponse] = Field(..., description='Цепочки в порядке раскладки')

    model_config = ConfigDict(
        json_schema_extra={
            'example': {
                'result': [
                    {
                        'id': 3,
                        'site_id': 19,
                        'name': 'вход и проверка кабинета',
                        'position': 1,
                        'steps': 2,
                        'created_at': '2026-08-15T14:01:38',
                        'updated_at': '2026-08-15T14:01:38',
                    }
                ]
            }
        }
    )


class BrowserWorkflowRun(BaseModel):
    """Запуск цепочки. Сессия одна на все звенья — в этом весь смысл."""

    session_id: str = Field('', description='Пусто — контейнер заведёт временную сессию')
    variables: dict[str, str] = Field(default_factory=dict, description='Поверх значений сценариев')
    secrets: dict[str, str] = Field(default_factory=dict, description='Ни в базу, ни в журнал')
    keep_session: bool = Field(True, description='Своя сессия остаётся живой — посмотреть, где встали')


@router.get(
    '',
    response_model=BrowserWorkflowListResponse,
    summary='Получить список цепочек сценариев браузера',
    description='Возвращает workflow-цепочки — сценарии, которые гонятся по порядку в одной '
                'сессии, — в порядке раскладки на вкладке «Workflow» страницы `/admin/browser`. '
                'В списке только сами цепочки и число звеньев; звенья по порядку отдаёт '
                '`GET /api/browser/workflow/{workflow_id}`. Нужна сессия админки или заголовок '
                '`X-API-KEY` с токеном доступа пользователя, имеющего право `PLANNING_VIEW`.',
    response_description='Успешный ответ со списком цепочек',
)
async def browser_workflow_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Цепочки в порядке раскладки, с числом звеньев."""
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT w.id, w.site_id, w.name, w.position, w.created_at, w.updated_at, '
            '       COUNT(s.id) AS steps '
            '  FROM browser_workflow w '
            '  LEFT JOIN browser_workflow_step s ON s.workflow_id = w.id '
            ' GROUP BY w.id ORDER BY w.position, w.id'
        )
        rows = await db.fetchall()

    return {'result': rows}


@router.post('', status_code=201, include_in_schema=False)
async def browser_workflow_create(data: BrowserWorkflowSave,
                                  user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Заводит цепочку вместе со звеньями."""
    try:
        workflow_id = await BrowserWorkflowRepository().add({
            'site_id': data.site_id, 'name': data.name, 'position': await _position_next()})
    except Exception as e:
        raise HTTPException(status_code=409, detail=_save_error(e, data.name))

    try:
        await _steps_save(workflow_id, data.scenario_ids)
    except Exception:
        # Цепочка без звеньев никому не нужна: не сложилось — не заводим её вовсе,
        # иначе в списке остаётся пустая строка, которую человек не просил.
        await BrowserWorkflowRepository().delete(workflow_id)
        raise

    return {'result': workflow_id}


@router.get('/{workflow_id}', include_in_schema=False)
async def browser_workflow_get(workflow_id: int,
                               user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Цепочка целиком: звенья по порядку с именами сценариев и их подстановками.

    `variables_used` — объединение подстановок всех звеньев: спрашивать их надо
    один раз на прогон, а не по разу на сценарий, — значения общие.
    """
    row = await _workflow_row(workflow_id)
    steps = await _steps_load(workflow_id)

    used: list[str] = []
    defaults: dict[str, str] = {}
    for step in steps:
        for name in _variables_of(step):
            if name not in used:
                used.append(name)
        defaults.update(_defaults_of(step))

    row['steps'] = steps

    return {'result': row, 'variables_used': used, 'variables': defaults}


@router.put('/{workflow_id}', include_in_schema=False)
async def browser_workflow_update(workflow_id: int, data: BrowserWorkflowSave,
                                  user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Переписывает цепочку целиком — имя, сайт и порядок звеньев."""
    await _workflow_row(workflow_id)

    try:
        await BrowserWorkflowRepository().update(workflow_id, {'site_id': data.site_id,
                                                               'name': data.name})
    except Exception as e:
        raise HTTPException(status_code=409, detail=_save_error(e, data.name))

    await _steps_save(workflow_id, data.scenario_ids)

    return {'status': 'success'}


@router.delete('/{workflow_id}', include_in_schema=False)
async def browser_workflow_delete(workflow_id: int,
                                  user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Удаляет цепочку вместе со звеньями (каскадом). Сценарии остаются."""
    await _workflow_row(workflow_id)
    await BrowserWorkflowRepository().delete(workflow_id)

    return {'status': 'success'}


@router.post('/{workflow_id}/run', include_in_schema=False)
async def browser_workflow_run(workflow_id: int, data: BrowserWorkflowRun,
                               user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Гонит звенья по порядку в одной сессии.

    **Первое упавшее звено останавливает цепочку.** Следующие рассчитывают, что
    предыдущее сработало: продолжать после неудачного входа — значит получить
    лавину ошибок вместо одной настоящей, ровно как у шагов внутри сценария.

    Код ответа — про запрос, а не про результат: цепочка, вставшая на втором
    звене, это 200 со `status: "error"`, номером звена и трассами пройденного.
    Иначе журнал прогонов пришлось бы собирать из кодов HTTP.
    """
    await _workflow_row(workflow_id)
    steps = await _steps_load(workflow_id)
    if not steps:
        raise HTTPException(status_code=422, detail='в цепочке нет ни одного сценария')

    runs = []
    extract: dict = {}
    for number, step in enumerate(steps, start=1):
        result = await browser_scenario_run_one(int(step['scenario_id']), data.session_id,
                                                data.variables, data.secrets, True)
        runs.append({'step_no': number, 'scenario_id': step['scenario_id'],
                     'name': step['name'], 'result': result})
        # Забранное предыдущим звеном отдаём целиком: цепочку гонят ради итога, а
        # он собирается по кусочкам у разных сценариев.
        extract.update(result.get('extract') or {})

        if result.get('status') == 'error':
            return {'result': {'status': 'error', 'step_no': number, 'name': step['name'],
                               'error': result.get('error', ''), 'runs': runs, 'extract': extract}}

        # Дальше идём по той же странице: сессию берём из первого прогона, если её
        # завёл контейнер, — иначе второе звено открыло бы чистый контекст.
        data.session_id = data.session_id or str(result.get('session_id') or '')

    return {'result': {'status': 'ok', 'runs': runs, 'extract': extract,
                       'session_id': data.session_id}}


async def _position_next() -> int:
    """Позиция в конце списка."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT COALESCE(MAX(position), 0) + 1 AS next FROM browser_workflow')
        row = await db.fetchone()

    return int((row or {}).get('next') or 1)


async def _workflow_row(workflow_id: int) -> dict:
    """Цепочка из базы или 404."""
    row = await BrowserWorkflowRepository().find(workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail='цепочка не найдена')

    return dict(row)


async def _steps_load(workflow_id: int) -> list[dict]:
    """Звенья по порядку — вместе с именем и подстановками своего сценария."""
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT s.id, s.scenario_id, s.position, c.name, c.status, c.steps, c.variables '
            '  FROM browser_workflow_step s '
            '  JOIN browser_scenario c ON c.id = s.scenario_id '
            ' WHERE s.workflow_id = %s ORDER BY s.position, s.id',
            (workflow_id,)
        )
        rows = await db.fetchall()

    return [dict(row) for row in (rows or [])]


async def _steps_save(workflow_id: int, scenario_ids: list[int]) -> None:
    """Переписывает звенья целиком: страница присылает весь порядок сразу.

    Несуществующий сценарий ловим **до** записи, а не внешним ключом на вставке:
    иначе половина звеньев уже лежала бы в базе, а цепочка осталась бы битой на
    середине. Тот же ключ остаётся страховкой от гонки с удалением сценария.
    """
    await _scenarios_check(scenario_ids)

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM browser_workflow_step WHERE workflow_id = %s', (workflow_id,))
        for position, scenario_id in enumerate(scenario_ids, start=1):
            await db.execute(
                'INSERT INTO browser_workflow_step (workflow_id, scenario_id, position) '
                'VALUES (%s, %s, %s)', (workflow_id, int(scenario_id), position))
        await db.connection.commit()


async def _scenarios_check(scenario_ids: list[int]) -> None:
    """422 на первый номер, которого нет в базе."""
    marks = ', '.join(['%s'] * len(scenario_ids))
    async with mysql_get_db_async() as db:
        await db.execute(f'SELECT id FROM browser_scenario WHERE id IN ({marks})',
                         tuple(int(i) for i in scenario_ids))
        rows = await db.fetchall()

    known = {int(row['id']) for row in (rows or [])}
    missing = [i for i in scenario_ids if int(i) not in known]
    if missing:
        raise HTTPException(status_code=422, detail=f'нет сценария с номером {missing[0]}')


def _variables_of(step: dict) -> list[str]:
    """Имена подстановок звена — по тексту его шагов, как и на странице сценария."""
    return BROWSER_SCENARIO_VAR_RE.findall(str(step.get('steps') or ''))


def _defaults_of(step: dict) -> dict:
    """Значения по умолчанию звена: столбец `variables` сценария."""
    raw = step.get('variables')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}

    return {str(k): str(v) for k, v in (raw or {}).items()} if isinstance(raw, dict) else {}


def _save_error(error: Exception, name: str) -> str:
    """Человеческая причина отказа вместо текста драйвера."""
    text = str(error)
    if '1062' in text or 'Duplicate entry' in text:
        return f'цепочка с названием «{name}» уже есть'

    return f'не удалось сохранить цепочку: {text}'

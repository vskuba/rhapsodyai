from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.project.team.team_member import (team_member_activate, team_member_deactivate,
                                          team_member_get, team_member_get_by_role,
                                          team_member_list, team_member_ping)
from src.project.team.team_project import (team_project_blocks_get,
                                           team_project_id_by_work_dir,
                                           team_project_session_work_dir_sync)
from src.project.team.team_session import team_session_restart
from src.project.team.team_task_type import team_task_type_list
from src.project.task.task_setting_parallel import (
    TASK_SETTING_PARALLEL_OPTIONS,
    task_setting_parallel_set)
from src.project.task.task_setting_step import (task_setting_step_all,
                                                task_setting_step_key_is,
                                                task_setting_step_set)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_PING_STALE,
    task_setting_timeout_all,
    task_setting_timeout_get,
    task_setting_timeout_ladder_problem,
    task_setting_timeout_set)

router = APIRouter(prefix='/api/team', tags=['team'])


class TeamPingRequest(BaseModel):
    """Пинг от запущенной оболочки claude-shell.

    Идентификация — либо member_id (кнопки на /admin/team), либо role: оболочка
    знает свою роль из флага запуска (--manager/--developer/--qa), а числовой ID
    строки в project_team ей неизвестен.
    """

    member_id: int | None = None
    role: str | None = None
    pid: int | None = None
    session_uuid: str | None = None
    work_dir: str | None = None

    def session_get(self) -> dict:
        """Данные запущенной оболочки для записи в project_team."""
        return {'pid': self.pid, 'session_uuid': self.session_uuid,
                'work_dir': self.work_dir}


class TeamSessionRequest(BaseModel):
    """Действие над конкретной оболочкой claude-shell с карточки команды."""

    session_uuid: str


class TeamTimeoutRequest(BaseModel):
    """Правка одного таймаута с карточки команды."""

    key: str
    value: int


class TeamParallelRequest(BaseModel):
    """Правка предела «Parallel LLM» в шапке блока проекта.

    `project_id = 0` — блок «Без проекта» (оболочки вне проектов).
    """

    project_id: int
    value: int


class TeamStatusResponse(BaseModel):
    id: int
    name: str
    role: str
    command: str
    work_dir: str
    status: str
    last_ping_at: datetime | None
    pid: int | None
    session_uuid: str | None


@router.get('', response_model=list[TeamStatusResponse])
async def project_team_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Получить список всех членов команды.

    Отдаёт work_dir, pid и session_uuid, поэтому требует авторизации — в отличие
    от POST-ов /ping, /activate, /deactivate, которые дёргает внешняя оболочка.
    """
    members = await team_member_list()
    return members


@router.post('/ping')
async def project_team_ping(request: TeamPingRequest):
    """Обновить пинг члена команды — оболочка шлёт его, пока жива."""
    member = await _member_resolve(request)
    await team_member_ping(member['id'], request.session_get())
    await team_project_session_work_dir_sync(request.session_uuid or '', request.work_dir or '')

    return {'success': True, 'member_id': member['id']}


@router.get('/projects')
async def project_team_projects_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Команда в разрезе проектов: блок на проект, внутри карточки ролей.

    Активность карточки считается на сервере — в реестре last_seen_at пишется в
    часовом поясе настройки, и браузер не знает, какой это пояс.
    """
    blocks = await team_project_blocks_get()
    stale_seconds = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_PING_STALE)
    return {'result': {'blocks': blocks, 'stale_seconds': stale_seconds,
                       'parallel_options': list(TASK_SETTING_PARALLEL_OPTIONS)}}


@router.post('/parallel')
async def project_team_parallel_set(parallel_request: TeamParallelRequest,
                                    user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Записать предел «Parallel LLM» проекта — селект в шапке блока.

    `project_id = 0` — блок «Без проекта». Значение вне списка вариантов — 422.
    Отдельного GET нет: текущие пределы приходят вместе с блоками (`/projects`).
    """
    try:
        value = await task_setting_parallel_set(parallel_request.project_id, parallel_request.value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    return {'result': {'project_id': parallel_request.project_id, 'value': value}}


@router.get('/types')
async def project_team_task_types_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Получить все типы задач."""
    types = await team_task_type_list()
    return types


@router.get('/timeout')
async def project_team_timeout_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Все таймауты конвейера с текущими значениями — блок на карточке команды.

    Кроме настроек отдаются сроки шагов агентских workflow (`task_setting_step`):
    прогон обрывается по ним раньше, чем по потолку роли, и карточка, где их нет,
    обещает час там, где на деле десять минут.

    `problem` — непустая строка, если лестница таймаутов нарушена (прогон агента
    обязан срываться раньше job'а, а job — раньше возврата блокировки). Считается
    по настройкам: шаги в лестницу не входят, их срок меньше потолка роли по самому
    смыслу. Это предупреждение, а не запрет: поднять все три значения разом одним
    запросом нельзя, и промежуточное состояние законно.
    """
    items = await task_setting_timeout_all()
    problem = task_setting_timeout_ladder_problem({item['key']: item['value'] for item in items})

    return {'result': {'items': items + await task_setting_step_all(), 'problem': problem}}


@router.post('/timeout')
async def project_team_timeout_set(timeout_request: TeamTimeoutRequest,
                                   user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Записать одно значение таймаута. Неизвестный ключ или выход за границы — 422.

    Ключ `step_timeout_<id>` — срок шага workflow: он лежит не в таблице настроек,
    а в определении самого шага, и пишется туда же. Развилка по ключу, а не
    отдельный endpoint: для страницы это одна и та же строка в одном блоке.
    """
    try:
        item = (await task_setting_step_set(timeout_request.key, timeout_request.value)
                if task_setting_step_key_is(timeout_request.key)
                else await task_setting_timeout_set(timeout_request.key, timeout_request.value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    items = await task_setting_timeout_all()
    problem = task_setting_timeout_ladder_problem({row['key']: row['value'] for row in items})

    return {'result': {'item': item, 'problem': problem}}


@router.post('/session/restart')
async def project_team_session_restart(session_request: TeamSessionRequest,
                                       user=Depends(AuthChecker([AuthPermission.PLANNING_UPDATE]))):
    """Перезапустить watch-процесс оболочки — кнопка на активной карточке команды.

    Авторизацию требуем, в отличие от /ping и /activate: те дёргает сама оболочка,
    а это действие приходит из браузера и меняет состояние чужого процесса.
    """
    status = await team_session_restart(session_request.session_uuid)
    if status is None:
        raise HTTPException(status_code=404, detail='Session not found')

    return {'result': status}


@router.post('/activate')
async def project_team_activate(member_request: TeamPingRequest):
    """Активировать члена команды (взять на работу)."""
    member = await _member_resolve(member_request)
    await team_member_activate(member['id'], member_request.session_get())
    return {'success': True, 'member_id': member['id'], 'status': 'active'}


@router.post('/deactivate')
async def project_team_deactivate(member_request: TeamPingRequest):
    """Деактивировать члена команды (отпустить)."""
    member = await _member_resolve(member_request)
    await team_member_deactivate(member['id'])
    return {'success': True, 'member_id': member['id'], 'status': 'inactive'}


async def _member_resolve(request: TeamPingRequest):
    """Найти члена команды по member_id или по роли; 404, если не нашли.

    Карточки заведены на проект, а роль в пинге одна на все проекты, поэтому
    проект берём из каталога запуска оболочки: `/home/.../RhapsodyAi` — это
    карточка проекта RhapsodyAi, а не первая строка с ролью `manager`.
    """
    if request.member_id is not None:
        member = await team_member_get(request.member_id)
    elif request.role:
        project_id = await team_project_id_by_work_dir(request.work_dir or '')
        member = await team_member_get_by_role(request.role, project_id)
    else:
        raise HTTPException(status_code=422, detail='member_id or role is required')

    if not member:
        raise HTTPException(status_code=404, detail='Team member not found')

    return member

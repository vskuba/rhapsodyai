from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.project.team.team_member import (team_member_activate, team_member_deactivate,
                                          team_member_get, team_member_get_by_role,
                                          team_member_list, team_member_ping)
from src.project.team.team_project import (TEAM_PROJECT_PING_STALE_SECONDS,
                                          team_project_blocks_get,
                                          team_project_session_work_dir_sync)
from src.project.team.team_task_type import team_task_type_list

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
    return {'result': {'blocks': blocks, 'stale_seconds': TEAM_PROJECT_PING_STALE_SECONDS}}


@router.get('/types')
async def project_team_task_types_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Получить все типы задач."""
    types = await team_task_type_list()
    return types


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
    """Найти члена команды по member_id или по роли; 404, если не нашли."""
    if request.member_id is not None:
        member = await team_member_get(request.member_id)
    elif request.role:
        member = await team_member_get_by_role(request.role)
    else:
        raise HTTPException(status_code=422, detail='member_id or role is required')

    if not member:
        raise HTTPException(status_code=404, detail='Team member not found')

    return member

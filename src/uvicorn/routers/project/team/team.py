from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.project.team.team_service import TeamService

router = APIRouter(prefix='/api/team', tags=['team'])

team_service = TeamService()


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


async def team_member_resolve(request: TeamPingRequest):
    """Найти члена команды по member_id или по роли; 404, если не нашли."""
    member = None
    if request.member_id is not None:
        member = await team_service.team_member_get(request.member_id)
    elif request.role:
        member = await team_service.team_member_get_by_role(request.role)
    else:
        raise HTTPException(status_code=422, detail='member_id or role is required')

    if not member:
        raise HTTPException(status_code=404, detail='Team member not found')
    return member


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
async def team_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Получить список всех членов команды.

    Отдаёт work_dir, pid и session_uuid, поэтому требует авторизации — в отличие
    от POST-ов /ping, /activate, /deactivate, которые дёргает внешняя оболочка.
    """
    members = await team_service.team_list_get()
    return members


@router.post('/ping')
async def team_ping(request: TeamPingRequest):
    """Обновить пинг члена команды — оболочка шлёт его, пока жива."""
    member = await team_member_resolve(request)
    await team_service.team_ping(member['id'], request.session_get())
    return {'success': True, 'member_id': member['id']}


@router.get('/types')
async def team_task_types_list(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """Получить все типы задач."""
    types = await team_service.team_task_types_get()
    return types


@router.post('/activate')
async def team_activate(member_request: TeamPingRequest):
    """Активировать члена команды (взять на работу)."""
    member = await team_member_resolve(member_request)
    await team_service.team_activate(member['id'], member_request.session_get())
    return {'success': True, 'member_id': member['id'], 'status': 'active'}


@router.post('/deactivate')
async def team_deactivate(member_request: TeamPingRequest):
    """Деактивировать члена команды (отпустить)."""
    member = await team_member_resolve(member_request)
    await team_service.team_deactivate(member['id'])
    return {'success': True, 'member_id': member['id'], 'status': 'inactive'}

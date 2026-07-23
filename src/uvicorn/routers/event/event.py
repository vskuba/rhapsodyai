from typing import Annotated, Literal, Optional, Union

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel, Field

from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.event_log_repository import EventLogRepository
from src.uvicorn.routers.telegram_app.telegram_app_common import _require_claude_secret, _require_telegram_owner

router = APIRouter()


# ── system ────────────────────────────────────────────────────────────────────

class SystemPayload(BaseModel):
    event_type: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    role: Optional[str] = None


class EventLogSystemRequest(BaseModel):
    type: Literal['system']
    payload: SystemPayload


# ── github ────────────────────────────────────────────────────────────────────

class GithubDeployStartedPayload(BaseModel):
    event: Literal['deploy.started']
    branch: str
    commit: str
    actor: str
    run_url: str


class GithubDeployFinishedPayload(BaseModel):
    event: Literal['deploy.finished']
    branch: str
    commit: str
    actor: str
    run_url: str
    status: str  # success | failure | cancelled | timed_out


GithubPayload = Annotated[
    Union[GithubDeployStartedPayload, GithubDeployFinishedPayload],
    Field(discriminator='event')
]


class EventLogGithubRequest(BaseModel):
    type: Literal['github']
    payload: GithubPayload


# ── claude_session ────────────────────────────────────────────────────────────

class ClaudeSessionPayload(BaseModel):
    event_type: str
    session_uuid: str
    project_label: Optional[str] = None
    role: Optional[str] = None


class EventLogClaudeSessionRequest(BaseModel):
    type: Literal['claude_session']
    payload: ClaudeSessionPayload


# ── agent ─────────────────────────────────────────────────────────────────────

class AgentPayload(BaseModel):
    event_type: str
    agent_name: Optional[str] = None
    node_id: Optional[int] = None
    session_uuid: Optional[str] = None


class EventLogAgentRequest(BaseModel):
    type: Literal['agent']
    payload: AgentPayload


# ── llm ───────────────────────────────────────────────────────────────────────

class LlmPayload(BaseModel):
    event_type: str
    model: Optional[str] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    session_uuid: Optional[str] = None


class EventLogLlmRequest(BaseModel):
    type: Literal['llm']
    payload: LlmPayload


# ── discriminated union ───────────────────────────────────────────────────────

EventLogRequest = Annotated[
    Union[
        EventLogSystemRequest,
        EventLogGithubRequest,
        EventLogClaudeSessionRequest,
        EventLogAgentRequest,
        EventLogLlmRequest,
    ],
    Field(discriminator='type')
]


@router.get("/events")
async def event_list(request: Request):
    _require_telegram_owner(request)

    repo = EventLogRepository()
    rows = await repo.find_by({}, order_by="created_at DESC")

    return {"result": rows[:50]}


@router.delete("/events")
async def event_clear(request: Request):
    _require_telegram_owner(request)

    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM event_log")

    return {"result": {"ok": True}}


@router.post("/event-log")
async def event_log_create(request: Request, data: EventLogRequest = Body(...)):
    """
    Добавляет запись в event_log.
    Авторизация: X-Claude-Secret (TELEGRAM_TOKEN_RHAPSODY).

    Пример curl:
        curl -X POST http://localhost:8011/event-log \\
             -H "Content-Type: application/json" \\
             -H "X-Claude-Secret: <token>" \\
             -d '{"type": "github", "payload": {"event": "deploy.started", "branch": "master", "commit": "abc123", "actor": "vskuba", "run_url": "https://..."}}'
    """
    _require_claude_secret(request)

    repo = EventLogRepository()
    created_id = await repo.add({
        'type': data.type,
        'payload': data.payload.model_dump_json(),
    })

    return {"result": {"id": created_id, "type": data.type}}

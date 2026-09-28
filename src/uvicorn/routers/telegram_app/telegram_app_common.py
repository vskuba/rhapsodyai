import asyncio
import hmac
import uuid

from fastapi import Request, HTTPException

from src.ai.ai_llm import ai_llm_node_get
from config.config import config_get
from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository
from src.project.team.team_session import TEAM_SESSION_RESTART_MARKER

agent_manager = AiFrameworkAgentManager()

TELEGRAM_CHAT_USER_ID = 1
TELEGRAM_CHAT_AGENT_NAME = 'telegram_assistant'
TELEGRAM_CLAUDE_AGENT_NAME = 'telegram_claude'

SESSION_CLEANUP_MARKER = '__SESSION_CLEANUP__'
# Перезапуск watch просят из двух мест — Mini App и карточки на /admin/team, —
# поэтому маркер живёт в `team_session`, а здесь только имя для местных вызовов.
RESTART_WATCH_MARKER = TEAM_SESSION_RESTART_MARKER
QUOTA_CHECK_MARKER = '__QUOTA_CHECK__'


def _require_telegram_owner(request: Request):
    if not request.session.get("telegram_owner_id"):
        raise HTTPException(status_code=403, detail="Not authorized")


def _require_claude_secret(request: Request):
    expected = config_get("TELEGRAM_TOKEN_RHAPSODY")
    provided = request.headers.get("X-Claude-Secret")
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Not authorized")


async def _telegram_agent_chat_ask(data: dict, agent_name: str) -> dict:
    message = str(data.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    session_uuid = data.get("session_uuid") or str(uuid.uuid4())

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({"name": agent_name})
    if not entity_agent:
        raise HTTPException(status_code=500, detail=f"Agent '{agent_name}' not found")

    workflow_id = entity_agent["workflow_id"]
    workflow_data = await ai_workflow_load(workflow_id)

    workflow_variables_all = {
        **ai_workflow_variables_base(
            prompt_user=message,
            user_id=TELEGRAM_CHAT_USER_ID,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
        ),
        **json_from_string(entity_agent.get("workflow_variable") or "{}"),
    }
    ai_workflow_variables_defaults_apply(workflow_variables_all, workflow_data["variables"])

    entities_llm = await ai_llm_node_get(entity_agent.get("node_id"))

    async with mysql_get_db_async() as db:
        await db.execute("SELECT name, path FROM tool WHERE id > 0")
        raw_tools = await db.fetchall()
    tools = {t['name'].strip(): t['path'].strip() for t in raw_tools if t.get('name') and t.get('path')}

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    framework_model = await agent_manager.framework_model_create({
        "entity_agent": entity_agent,
        "entities_llm": entities_llm,
        "workflow_steps": workflow_data["steps"],
        "workflow_variables": workflow_variables_all,
        "prompt_user": message,
        "user_id": TELEGRAM_CHAT_USER_ID,
        "session_uuid": session_uuid,
        "tools": tools,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=60.0)
        return {"result": result_text, "session_uuid": framework_model.session_uuid}
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=504, detail="Превышено время ожидания ответа от ИИ")

import asyncio
import uuid

from fastapi import APIRouter, Request, HTTPException

from ai.ai_llm import ai_llm_node_get
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.mysql_.repository.agent_repository import AgentRepository
from src.mysql_.repository.plan_repository import PlanRepository
from src.uvicorn.routers.telegram_app.telegram_app import (
    TELEGRAM_CHAT_USER_ID,
    _require_telegram_owner,
    agent_manager,
)

router = APIRouter()

TELEGRAM_PLAN_USER_ID = TELEGRAM_CHAT_USER_ID
TELEGRAM_PLAN_AGENT_NAME = 'plan_editor'


@router.get("/telegram-app/plans")
async def telegram_app_plans_list(request: Request):
    _require_telegram_owner(request)

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, title, status, position, updated_at FROM `plan` "
            "WHERE user_id = %s ORDER BY FIELD(status, 'active', 'archived'), updated_at DESC",
            (TELEGRAM_PLAN_USER_ID,)
        )
        rows = await db.fetchall()

    return {"result": rows}


@router.get("/telegram-app/plans/{plan_id}")
async def telegram_app_plan_get(request: Request, plan_id: int):
    _require_telegram_owner(request)

    entity_plan = await PlanRepository().find(plan_id)
    if not entity_plan or entity_plan.get("user_id") != TELEGRAM_PLAN_USER_ID:
        raise HTTPException(status_code=404, detail="Plan not found")

    return {"result": entity_plan}


@router.post("/telegram-app/plans/{plan_id}/edit")
async def telegram_app_plan_edit(request: Request, plan_id: int, data: dict):
    _require_telegram_owner(request)

    entity_plan = await PlanRepository().find(plan_id)
    if not entity_plan or entity_plan.get("user_id") != TELEGRAM_PLAN_USER_ID:
        raise HTTPException(status_code=404, detail="Plan not found")

    instruction = str(data.get("instruction") or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="Instruction is required")

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({"name": TELEGRAM_PLAN_AGENT_NAME})
    if not entity_agent or not entity_agent.get("workflow_id"):
        raise HTTPException(status_code=500, detail="Plan editor agent not found")

    workflow_id = entity_agent["workflow_id"]
    workflow_data = await ai_workflow_load(workflow_id)

    # Отдельная одноразовая сессия: правки плана не смешиваются с историей чата
    session_uuid = str(uuid.uuid4())
    workflow_variables_all = {
        **ai_workflow_variables_base(
            prompt_user=instruction,
            user_id=TELEGRAM_PLAN_USER_ID,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
        ),
        "plan_current_content": entity_plan["content"],
    }
    ai_workflow_variables_defaults_apply(workflow_variables_all, workflow_data["variables"])

    entities_llm = await ai_llm_node_get(entity_agent.get("node_id"))
    if not entities_llm:
        raise HTTPException(status_code=404, detail="LLM models not found for agent 'plan_editor'")

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    framework_model = await agent_manager.framework_model_create({
        "entity_agent": entity_agent,
        "entities_llm": entities_llm,
        "workflow_steps": workflow_data["steps"],
        "workflow_variables": workflow_variables_all,
        "prompt_user": instruction,
        "user_id": TELEGRAM_PLAN_USER_ID,
        "companion_id": None,
        "session_uuid": session_uuid,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=60.0)
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=504, detail="Превышено время ожидания правки плана (60 сек.)")

    updated_content = str(result_text).strip()
    await PlanRepository().update(plan_id, {"content": updated_content})

    return {"result": {"content": updated_content}, "instruction": instruction}

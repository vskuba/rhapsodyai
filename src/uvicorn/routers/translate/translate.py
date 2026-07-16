import asyncio
import uuid

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel

from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.auth.auth import AuthChecker
from src.mysql_.repository.agent_repository import AgentRepository

router = APIRouter()


class TranslateJsonRequest(BaseModel):
    text: str
    language_from: str = 'ru'
    language_to: str = 'en'


@router.post("/translate")
async def translate(
        request: Request,
        json_request: TranslateJsonRequest,
        user=Depends(AuthChecker([]))
):
    """Автоперевод текста служебным workflow 'translator' (вне ноды — доступен всем).
    Используется кнопкой перевода в переключателе языков форм."""
    text = json_request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустой текст для перевода")

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'name': 'translator'})
    if not entity_agent or not entity_agent.get('workflow_id'):
        raise HTTPException(status_code=404, detail="Агент 'translator' с workflow не найден")

    workflow_id = entity_agent['workflow_id']

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT l.* FROM `llm` l
            JOIN `user_llm` ul ON l.id = ul.llm_id
            WHERE ul.user_id = %s
            ORDER BY ul.rate_limit_at ASC, ul.position ASC
            """,
            (user.user_id,)
        )
        entities_llm = await db.fetchall()

    if not entities_llm:
        raise HTTPException(status_code=404, detail=f"LLM models not found for user ID: {user.user_id}")

    workflow_data = await ai_workflow_load(workflow_id)

    # Отдельная одноразовая сессия: переводы не смешиваются с историей чатов
    session_uuid = str(uuid.uuid4())
    workflow_variables_all = {
        **ai_workflow_variables_base(
            prompt_user=text,
            user_id=user.user_id,
            user_username=user.username,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
        ),
        'language_from': json_request.language_from.strip() or 'ru',
        'language_to': json_request.language_to.strip() or 'en',
    }
    ai_workflow_variables_defaults_apply(workflow_variables_all, workflow_data['variables'])

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    agent_manager = request.app.state.agent_manager
    framework_model = await agent_manager.framework_model_create({
        "entity_agent": entity_agent,
        "entities_llm": entities_llm,
        "workflow_steps": workflow_data['steps'],
        "workflow_variables": workflow_variables_all,
        "prompt_user": text,
        "user_id": user.user_id,
        # None, не 0: agent_session.companion_id имеет FK на companion — 0 нарушает его, NULL допустим
        "companion_id": None,
        "session_uuid": session_uuid,
        "tools": {},
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=60.0)
        return {"result": result_text}
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=504, detail="Превышено время ожидания перевода (60 сек.)")

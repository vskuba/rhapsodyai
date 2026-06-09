import asyncio
import os
import traceback

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from fastapi import UploadFile, File

from ai.framework.agent.ai_framework_model import AiFrameworkAgentModel
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from queue_.queue_ import queue_get
from src.faster_whisper.faster_whisper_model import faster_whisper_create_model
from src.mysql_.repository.agent_repository import AgentRepository

router = APIRouter()


class ChatAskJsonRequest(BaseModel):
    agent_id: int
    question: str
    user_id: int
    llm: str
    session_uuid: str | None = None
    metadata: dict | None = None


class ChatMessagesJsonRequest(BaseModel):
    session_uuid: str
    limit: int = 10


@router.post("/chat/ask")
async def ask_ai(request: Request, json_request: ChatAskJsonRequest):
    logger_info('Чат запрос: ' + str(json_request))

    repo = AgentRepository()
    agent = await repo.find_one_by({'id': json_request.agent_id})

    agent_manager = request.app.state.agent_manager
    framework_model: AiFrameworkAgentModel = await agent_manager.create_framework_model(
        agent,
        json_request.metadata
    )

    framework_model.prompt = json_request.question
    framework_model.is_gui_mode = False
    framework_model.user_id = json_request.user_id
    framework_model.llm = json_request.llm

    if json_request.session_uuid:
        framework_model.session_uuid = json_request.session_uuid

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def on_complete(response_text: str):
        if not future.done():
            loop.call_soon_threadsafe(future.set_result, response_text)

    framework_model.on_complete = on_complete
    timeout = 60.0

    try:
        queue_get('agent').put(framework_model)

        result_text = await asyncio.wait_for(future, timeout=timeout)

        return {"result": result_text}
    except asyncio.TimeoutError:
        # Пытаемся отменить future, чтобы не висела в памяти
        future.cancel()
        raise HTTPException(status_code=504, detail=f"AI response timeout: {timeout}")
    except Exception as e:
        backtrace = traceback.format_exc()
        logger_info(
            f"❌ Ошибка при ответе web чата: {e}."
            f"Полный стек вызовов:\n{backtrace}"
        )
        raise


@router.post("/chat/messages")
async def chat_messages(request: Request, json_request: ChatMessagesJsonRequest, db=Depends(mysql_get_db_async)):
    async with db:
        await db.execute(
            "SELECT content, role "
            "FROM agent_session "
            "WHERE kind_type in ('user-prompt', 'response-final') AND session_uuid = %s "
            "ORDER BY created_at DESC, id DESC LIMIT %s", (json_request.session_uuid, json_request.limit)
        )
        rows = await db.fetchall()

        return {"result": list(reversed(rows))}


@router.post("/chat/voice")
async def voice_to_text(file: UploadFile = File(...)):
    temp_file = f"temp_{file.filename}.wav"

    # Асинхронно читаем и записываем
    content = await file.read()
    with open(temp_file, "wb") as buffer:
        buffer.write(content)

    # Здесь логика Faster Whisper
    segments, _ = faster_whisper_create_model().transcribe(
        temp_file,
        beam_size=5,
        best_of=5,
        language=None,
        condition_on_previous_text=False
    )
    text = "".join([s.text for s in segments])

    os.remove(temp_file)

    return {"result": text.strip()}

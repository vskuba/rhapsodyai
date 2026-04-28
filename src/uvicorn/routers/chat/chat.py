import asyncio
import os
import traceback

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from fastapi import UploadFile, File

from logging_.logging_ import logger_info
from queue_.queue_ import queue_get
from src.ai_pydantic.ai_framework_agent_model_pydantic import AiFrameworkAgentModelPydantic
from src.faster_whisper.faster_whisper_model import faster_whisper_create_model

router = APIRouter()


class JsonRequest(BaseModel):
    agent: str
    question: str
    user_id: int
    llm: str


@router.post("/chat/ask")
async def ask_ai(request: Request, json_request: JsonRequest):
    framework_model: AiFrameworkAgentModelPydantic = request.app.state.agent_manager.load(json_request.agent)
    framework_model.prompt = json_request.question
    framework_model.is_gui_mode = False
    framework_model.user_id = json_request.user_id
    framework_model.llm = json_request.llm

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def on_complete(response_text: str):
        if not future.done():
            loop.call_soon_threadsafe(future.set_result, response_text)

    framework_model.on_complete = on_complete

    try:
        queue_get('agent').put(framework_model)

        result_text = await asyncio.wait_for(future, timeout=20.0)

        return {"result": result_text}
    except asyncio.TimeoutError:
        # Пытаемся отменить future, чтобы не висела в памяти
        future.cancel()
        raise HTTPException(status_code=504, detail="AI response timeout")
    except Exception as e:
        backtrace = traceback.format_exc()
        logger_info(
            f"❌ Ошибка при ответе web чата: {e}."
            f"Полный стек вызовов:\n{backtrace}"
        )
        raise


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

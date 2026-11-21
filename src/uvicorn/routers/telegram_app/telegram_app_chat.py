import os

from fastapi import APIRouter, Request, UploadFile, File

from src.faster_whisper.faster_whisper_model import faster_whisper_model_transcribe
from src.uvicorn.routers.telegram_app.telegram_app_common import _require_telegram_owner

router = APIRouter()


@router.post("/telegram-app/chat/voice")
async def telegram_app_chat_voice(request: Request, file: UploadFile = File(...)):
    _require_telegram_owner(request)

    temp_file = f"temp_{file.filename}.wav"
    content = await file.read()
    with open(temp_file, "wb") as buffer:
        buffer.write(content)

    try:
        text = await faster_whisper_model_transcribe(temp_file)
    finally:
        os.remove(temp_file)

    return {"result": text}

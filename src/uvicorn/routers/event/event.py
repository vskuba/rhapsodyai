from fastapi import APIRouter, Request, HTTPException

from src.mysql_.repository.event_log_repository import EventLogRepository
from src.uvicorn.routers.telegram_app.telegram_app_common import _require_claude_secret

router = APIRouter()


@router.post("/event-log")
async def event_log_create(request: Request, data: dict):
    """
    Добавляет запись в event_log.
    Авторизация: X-Claude-Secret (TELEGRAM_TOKEN_RHAPSODY).

    Пример curl:
        curl -X POST http://localhost:8011/event-log \\
             -H "Content-Type: application/json" \\
             -H "X-Claude-Secret: <token>" \\
             -d '{"type": "deploy.started", "payload": {"branch": "master", "commit": "abc123"}}'
    """
    _require_claude_secret(request)

    event_type = str(data.get("type") or "").strip()
    if not event_type:
        raise HTTPException(status_code=400, detail="type is required")

    payload = data.get("payload")

    repo = EventLogRepository()
    row = {"type": event_type}
    if payload is not None:
        import json
        row["payload"] = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload

    created_id = await repo.add(row)

    return {"result": {"id": created_id, "type": event_type}}

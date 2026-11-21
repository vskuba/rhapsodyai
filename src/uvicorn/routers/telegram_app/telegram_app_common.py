
from fastapi import Request, HTTPException

from src.auth.auth import auth_claude_secret_ok
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.project.team.team_session import TEAM_SESSION_RESTART_MARKER

agent_manager = AiFrameworkAgentManager()

TELEGRAM_CHAT_USER_ID = 1
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
    """⚠ Сравнение — в `auth_claude_secret_ok`, одно на установку: тот же ключ
    проверяет застава `auth_middleware`, и две копии условия разошлись бы."""
    if not auth_claude_secret_ok(request):
        raise HTTPException(status_code=403, detail="Not authorized")

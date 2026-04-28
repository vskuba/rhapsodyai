from fastapi import APIRouter

from config.config import config_get

router = APIRouter()


@router.get("/llm/list")
async def llm_list():
    allowed_llms = [m.strip() for m in config_get("LLM_ALLOWED").split(",")]
    return {"result": allowed_llms}

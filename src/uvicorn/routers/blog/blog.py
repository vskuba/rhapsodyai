"""Агенты «Блокнота» для BlogAi: разметка черновиков тегами.

Черновики живут в BlogAi, агенты — здесь, под нодой `Blog`. Точка своя, а не
общий `/chat/ask`, по той же причине, что и у STT: соседу незачем знать про
workflow, session_uuid и идентификаторы агентов. Он присылает текст и словарь
тегов, получает теги.

**Словарь — не подсказка, а условие работы.** Без него агент размечает каждый
черновик независимо, и через сотню записей получаются «бизнес», «про бизнес»,
«бизнес-идеи» и «business» — четыре полки вместо одной. Поэтому словарь идёт в
промпт, а агенту велено переиспользовать существующее.
"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import (ai_workflow_load, ai_workflow_variables_base,
                                ai_workflow_variables_defaults_apply)
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.agent_repository import AgentRepository

router = APIRouter(prefix="/api/blog", tags=["blog"])

agent_manager = AiFrameworkAgentManager()

BLOG_TAGGER_AGENT_NAME = "blog_tagger"

# От чьего имени идёт запрос. Учётка владельца: черновики — его личные мысли,
# и разводить их по пользователям пока незачем.
#
# `companion_id` = 1 (`user_admin`), а НЕ 3 как в телеграмных константах: там
# число из другой установки, и у нас запись в `agent_session` падала на внешнем
# ключе `fk_memory_companion` — собеседника с id 3 в таблице нет.
BLOG_USER_ID = 1
BLOG_COMPANION_ID = 1

# Ждём разметку не дольше минуты. Черновик короткий, и если модель думает
# дольше — что-то не так, а BlogAi не должен висеть на этом запросе.
BLOG_AGENT_TIMEOUT = 60.0

# Сколько тегов из словаря показать агенту. Весь словарь в промпт не влезет,
# когда он разрастётся, а ходовые и есть те, которые надо переиспользовать.
BLOG_VOCABULARY_MAX = 120


@router.post("/tag")
async def blog_tag(data: dict, user=Depends(AuthChecker([AuthPermission.STT_CREATE]))):
    """Текст черновика + словарь → теги и заголовок.

    Право то же, что у расшифровки: это одна и та же учётка соседа, делающая
    одну и ту же работу — превращает надиктованное в черновик. Заводить второе
    право ради второй точки того же сценария незачем.
    """
    text = str(data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="пустой текст — размечать нечего")

    vocabulary = [str(v).strip() for v in (data.get("vocabulary") or []) if str(v).strip()]
    vocabulary = vocabulary[:BLOG_VOCABULARY_MAX]

    answer = await _agent_ask(BLOG_TAGGER_AGENT_NAME, _prompt(text, vocabulary))
    parsed = json_from_string(answer) or {}

    tags = [str(t).strip() for t in (parsed.get("tags") or []) if str(t).strip()]
    if not tags:
        # Пустая разметка — это либо модель ответила не JSON, либо решила, что
        # тегов нет. Различить можно только по сырому ответу, поэтому он идёт
        # в журнал: без него такой случай не разобрать.
        logger_info(f"[blog] разметка ПУСТАЯ, сырой ответ: {answer[:300]}")
    logger_info(f"[blog] разметка: {len(text)} знаков, словарь {len(vocabulary)} → "
                f"{', '.join(tags) or 'ничего'}")

    return {"result": {"tags": tags, "title": str(parsed.get("title") or "").strip()}}


# ---------------------------------------------------------------------------

def _prompt(text: str, vocabulary: list) -> str:
    """Промпт с словарём впереди текста.

    Словарь идёт ПЕРВЫМ намеренно: модель сильнее держит начало инструкции, а
    переиспользование существующих тегов — главное требование, а не приписка.
    """
    if vocabulary:
        head = ("Существующие теги (переиспользуй подходящие, новый заводи только "
                "если ни один не годится):\n" + ", ".join(vocabulary))
    else:
        head = "Словарь пока пуст — это первые черновики, теги задаёшь ты."

    return f"{head}\n\n=== Черновик ===\n{text}"


async def _agent_ask(agent_name: str, message: str) -> str:
    """Спрашивает агента и ждёт ответа.

    Повторяет путь `_telegram_agent_chat_ask`, но без телеграмных подробностей:
    сессия одноразовая, история не нужна — разметка не диалог.
    """
    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({"name": agent_name})
    if not entity_agent:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"агент '{agent_name}' не найден")

    workflow_id = entity_agent["workflow_id"]
    workflow_data = await ai_workflow_load(workflow_id)
    session_uuid = str(uuid.uuid4())

    variables = {
        **ai_workflow_variables_base(
            prompt_user=message, user_id=BLOG_USER_ID, entity_agent=entity_agent,
            session_uuid=session_uuid, workflow_id=workflow_id,
            companion_id=BLOG_COMPANION_ID, companion_name="user_admin",
            companion_title="admin"),
        **json_from_string(entity_agent.get("workflow_variable") or "{}"),
    }
    ai_workflow_variables_defaults_apply(variables, workflow_data["variables"])

    async with mysql_get_db_async() as db:
        await db.execute("SELECT name, path FROM tool WHERE id > 0")
        raw_tools = await db.fetchall()
    tools = {t["name"].strip(): t["path"].strip()
             for t in raw_tools if t.get("name") and t.get("path")}

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    framework_model = await agent_manager.framework_model_create({
        "entity_agent": entity_agent,
        "entities_llm": await ai_llm_node_get(entity_agent.get("node_id")),
        "workflow_steps": workflow_data["steps"],
        "workflow_variables": variables,
        "prompt_user": message,
        "user_id": BLOG_USER_ID,
        "companion_id": BLOG_COMPANION_ID,
        "session_uuid": session_uuid,
        "tools": tools,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        return await asyncio.wait_for(future, timeout=BLOG_AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                            detail="агент разметки не ответил вовремя")

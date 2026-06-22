import asyncio
import json
import os
import traceback
import uuid

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from fastapi import UploadFile, File

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflowl import ai_workflow_variables_default_get
from src.faster_whisper.faster_whisper_model import faster_whisper_create_model
from src.mysql_.repository.agent_repository import AgentRepository
from src.mysql_.repository.llm_repository import LlmRepository
from src.mysql_.repository.user_repository import UserRepository

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
async def ask_ai(request: Request, json_request: ChatAskJsonRequest, db=Depends(mysql_get_db_async)):
    logger_info('Чат запрос: ' + str(json_request))

    session_uuid = json_request.session_uuid or str(uuid.uuid4())

    repo_user = UserRepository()
    entity_user = await repo_user.find_one_by({'id': json_request.user_id})
    if not entity_user:
        raise HTTPException(status_code=404, detail="User not found by ID: %s" % json_request.user_id)

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'id': json_request.agent_id})
    if not entity_agent:
        raise HTTPException(status_code=404, detail="Agent not found by ID: %s" % json_request.agent_id)

    workflow_id = entity_agent.get('workflow_id')
    if not workflow_id:
        raise HTTPException(status_code=401, detail="Agent '%s' not have workflow" % entity_agent.get('name'))

    repo_llm = LlmRepository()
    entity_llm = await repo_llm.find_one_by({'name': json_request.llm})
    if not entity_llm:
        raise HTTPException(status_code=404, detail="LLM not found by name: %s" % json_request.llm)

    async with db:
        # 1. Запрашиваем шаги воркфлоу, строго сортируя их по позиции
        sql_steps = """
            SELECT ws.*, wst.name as step_type_name 
            FROM workflow_step ws 
            LEFT JOIN workflow_step_type wst ON ws.type_id = wst.id 
            WHERE ws.workflow_id = %s 
            ORDER BY ws.position ASC
        """
        await db.execute(sql_steps, workflow_id)
        raw_workflow_steps = await db.fetchall()

        # 2. Запрашиваем динамические переменные воркфлоу
        sql_vars = "SELECT name, `default` FROM workflow_variable WHERE workflow_id = %s"
        await db.execute(sql_vars, workflow_id)
        raw_workflow_variables = await db.fetchall()

    # Парсим метаданные и очищаем строки от пробелов CHAR-типа
    workflow_steps = []
    for step in raw_workflow_steps:
        step_type = step.get('step_type_name', '').strip()
        step_title = step.get('title', '').strip()

        # Парсим JSON-строку из longtext metadata
        step_metadata = {}
        if step.get('metadata'):
            try:
                step_metadata = (json.loads(step['metadata'], strict=False)) \
                    if isinstance(step['metadata'], str) else step['metadata']
            except Exception as e:
                backtrace = traceback.format_exc()
                logger_info(
                    f"❌ Не удалось распарсить workflow step metadata: {e}. Metadata: {step.get('metadata')}"
                    f"Полный стек вызовов:\n{backtrace}"
                )
                step_metadata = {}

        workflow_steps.append({
            "id": step.get('id'),
            "step_type_name": step_type,
            "title": step_title,
            "metadata": step_metadata
        })

    # Собираем переменные: базовые + динамические из БД
    workflow_variables = {
        'prompt_user': json_request.question.strip(),
        'user_id': json_request.user_id,
        'agent_id': json_request.agent_id,
        'session_uuid': session_uuid,
        'agent_greeting': entity_agent.get('greeting'),
    }
    for v in raw_workflow_variables:
        v_name = v.get('name', '').strip()
        if v_name and v_name not in workflow_variables:
            workflow_variables[v_name] = v.get('default', None)

    for i in ai_workflow_variables_default_get():
        if i not in workflow_variables:
            raise HTTPException(status_code=401, detail=f"Переменная '{i}' отсутсвует в списке переменных по умолчанию.")

    tools = {}
    async with db:
        # 1. Запрашиваем шаги воркфлоу, строго сортируя их по позиции
        sql_tools = """
            SELECT name, path 
            FROM tool 
            WHERE id > 0
        """
        await db.execute(sql_tools)
        raw_tools = await db.fetchall()
        tools = {t['name'].strip(): t['path'].strip() for t in raw_tools if t.get('name') and t.get('path')}

    # Инициализируем механизм синхронизации потоков через Future
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    # Вызываем создание модели и запуск бизнес-логики в менеджере
    agent_manager = request.app.state.agent_manager
    framework_model = await agent_manager.framework_model_create({
        "entity_agent": entity_agent,
        "entity_llm": entity_llm,
        "workflow_steps": workflow_steps,
        "workflow_variables": workflow_variables,
        "prompt_user": json_request.question,
        "user_id": entity_user.get('id'),
        "session_uuid": session_uuid,
        "tools": tools,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    timeout = 60.0
    try:
        result_text = await asyncio.wait_for(future, timeout=timeout)
        return {"result": result_text}
    except asyncio.TimeoutError:
        # Пытаемся отменить future, чтобы не висела в памяти
        future.cancel()
        raise HTTPException(status_code=504, detail=f"Превышено время ожидания ответа от ИИ ({timeout} сек.)")
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

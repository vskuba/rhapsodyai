import asyncio
import os
import traceback
import uuid

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from fastapi import UploadFile, File

from src.mysql_.repository.companion_repository import CompanionRepository
from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflowl import ai_workflow_variables_default_get
from src.auth.auth import AuthChecker
from src.auth.auth_session import AuthSession
from src.faster_whisper.faster_whisper_model import faster_whisper_create_model
from src.mysql_.repository.agent_repository import AgentRepository
from src.mysql_.repository.user_repository import UserRepository

router = APIRouter()


class ChatAskJsonRequest(BaseModel):
    question: str
    agent_id: int
    companion_id: int
    session_uuid: str | None = None
    variables: dict = {}


class ChatMessagesJsonRequest(BaseModel):
    session_uuid: str
    limit: int = 10


@router.post("/chat/ask")
async def ask_ai(
        request: Request,
        json_request: ChatAskJsonRequest,
        db=Depends(mysql_get_db_async),
        user: AuthSession = Depends(AuthChecker([]))
) -> dict:
    logger_info('Чат запрос: ' + str(json_request))

    session_uuid = json_request.session_uuid or str(uuid.uuid4())

    repo_user = UserRepository()
    entity_user = await repo_user.find_one_by({'id': user.user_id})
    if not entity_user:
        raise HTTPException(status_code=404, detail="User not found by ID: %s" % user.user_id)

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'id': json_request.agent_id})
    if not entity_agent:
        raise HTTPException(status_code=404, detail="Agent not found by ID: %s" % json_request.agent_id)

    workflow_id = entity_agent.get('workflow_id')
    if not workflow_id:
        raise HTTPException(status_code=401, detail="Agent '%s' not have workflow" % entity_agent.get('name'))

    repo_companion = CompanionRepository()
    entity_companion = await repo_companion.find_one_by({'id': json_request.companion_id})
    if not entity_companion:
        raise HTTPException(status_code=401, detail="Companion not found by ID: %s" % json_request.companion_id)

    # Получаем все связанные с пользователем LLM
    entities_llm = []
    async with db:
        await db.execute(
            """
            SELECT l.* 
            FROM `llm` l
            JOIN `user_llm` ul ON l.id = ul.llm_id
            WHERE ul.user_id = %s
            ORDER BY ul.rate_limit_at ASC, ul.position ASC
            """,
            (user.user_id,)
        )
        entities_llm = await db.fetchall()

    if not entities_llm:
        raise HTTPException(status_code=404, detail="LLM models not found for user ID: %s" % user.user_id)

    async with db:
        # 1. Запрашиваем шаги воркфлоу, строго сортируя их по позиции
        sql_steps = """
            SELECT ws.*, wst.name as step_type_name 
            FROM agent_workflow_step ws 
            LEFT JOIN agent_workflow_step_type wst ON ws.type_id = wst.id 
            WHERE ws.workflow_id = %s 
            ORDER BY ws.position ASC
        """
        await db.execute(sql_steps, workflow_id)
        raw_workflow_steps = await db.fetchall()

        # 2. Запрашиваем динамические переменные воркфлоу
        sql_vars = """
            SELECT v.name, v.`default`
            FROM agent_workflow_variable v
            JOIN agent_workflow_variable_workflow vw ON v.id = vw.variable_id
            WHERE vw.workflow_id = %s
        """
        await db.execute(sql_vars, workflow_id)
        raw_workflow_variables = await db.fetchall()

    # Парсим метаданные и очищаем строки от пробелов CHAR-типа
    workflow_steps = []
    for step in raw_workflow_steps:
        step_type = step.get('step_type_name', '').strip()
        step_title = step.get('title', '').strip()

        workflow_steps.append({
            "id": step.get('id'),
            "step_type_name": step_type,
            "title": step_title,
            "metadata": json_from_string(step.get('metadata', {}))
        })

    # Собираем переменные: базовые + динамические из БД
    workflow_variables = {
        'prompt_user': json_request.question.strip(),
        'user_id': user.user_id,
        'user_username': entity_user.get('username'),
        'companion_id': json_request.companion_id,
        'companion_title': entity_companion.get('title'),
        'agent_id': json_request.agent_id,
        'agent_title': entity_agent.get('title'),
        'agent_greeting': entity_agent.get('greeting'),
        'session_uuid': session_uuid,
        'workflow_id': workflow_id,
        'node_id': entity_agent.get('node_id'),
        **json_from_string(entity_agent.get('workflow_variable', {})),
        **json_request.variables
    }

    for v in raw_workflow_variables:
        v_name = v.get('name', '').strip()
        if v_name and v_name not in workflow_variables:
            workflow_variables[v_name] = v.get('default', None)

    for i in await ai_workflow_variables_default_get():
        if i not in workflow_variables:
            raise HTTPException(
                status_code=401,
                detail=f"Переменная '{i}' системная, но отсутствует в маппинге."
            )

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
        "entities_llm": entities_llm,
        "workflow_steps": workflow_steps,
        "workflow_variables": workflow_variables,
        "prompt_user": json_request.question,
        "user_id": user.user_id,
        "companion_id": json_request.companion_id,
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
        raise e


@router.post("/chat/messages", include_in_schema=False)
async def chat_messages(request: Request, json_request: ChatMessagesJsonRequest, db=Depends(mysql_get_db_async)):
    async with db:
        sql = '''
            SELECT s.role, s.content, s.created_at, s.id
            FROM agent_session s
            JOIN (
                -- Находим максимальный ID для каждой комбинации request_uuid и kind_type.
                -- Для user-prompt это будет его единственный ID, 
                -- а для response-final — ID самого последнего ответа.
                SELECT MAX(id) as max_id
                FROM agent_session
                WHERE session_uuid = %s 
                  AND kind_type IN ('user-prompt', 'response-final')
                GROUP BY request_uuid, kind_type
            ) t ON s.id = t.max_id
            -- Сортируем полученные уникальные сообщения по убыванию времени и ID
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT %s
        '''
        await db.execute(sql, (json_request.session_uuid, json_request.limit))
        rows = await db.fetchall()

        return {"result": list(reversed(rows))}


@router.post("/chat/voice", include_in_schema=False)
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

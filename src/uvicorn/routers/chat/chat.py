import asyncio
import os
import traceback
import uuid

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from fastapi import UploadFile, File

from ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load
from src.ai.ai_workflow import ai_workflow_variables_render
from src.ai.ai_workflow import ai_workflow_variables_input_get
from src.ai.ai_workflow import ai_workflow_variables_public_get
from src.ai.ai_workflow import ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.mysql_.repository.companion_repository import CompanionRepository
from setting_.setting_ import setting_get
from src.tool.setting.setting_ import setting_value_get
from i18n_.i18n_ import i18n_text_resolve, i18n_languages_parse
from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_variables_global_get
from src.auth.auth import AuthChecker
from src.auth.auth_session import AuthSession
from src.faster_whisper.faster_whisper_model import faster_whisper_transcribe
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

    # LLM ноды агента (список настраивается на ноду, не на пользователя)
    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))

    if not entities_llm:
        raise HTTPException(status_code=404, detail="LLM models not found for agent '%s'" % entity_agent.get('name'))

    # Загружаем шаги (нормализованные) и переменные workflow
    workflow_data = await ai_workflow_load(workflow_id)
    workflow_steps = workflow_data['steps']
    raw_workflow_variables = workflow_data['variables']

    # Собираем переменные: базовые (единый сборщик) + из агента + из запроса пользователя
    workflow_variables_all = {
        **ai_workflow_variables_base(
            prompt_user=json_request.question.strip(),
            user_id=user.user_id,
            user_username=entity_user.get('username'),
            user_email=entity_user.get('email'),
            companion_id=json_request.companion_id,
            companion_name=entity_companion.get('name'),
            companion_title=entity_companion.get('title'),
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
        ),
        **json_from_string(entity_agent.get('workflow_variable', {})),
        **json_request.variables
    }

    # node_languages — список языков, которые поддерживает нода (настройка 'languages':
    # 'ru' | 'ru,en'; нодовая перекрывает общую). Только справочный список для UI/промптов.
    node_id = entity_agent.get('node_id')
    node_languages = i18n_languages_parse(
        (await setting_value_get('languages', node_id or 0, 'ru'))['value']
    )
    workflow_variables_all.setdefault('node_languages', ','.join(node_languages))

    # user_language — активный язык workflow: всегда выбор пользователя из личного кабинета,
    # а не настройка ноды. Нода лишь публикует СПИСОК поддерживаемых языков (node_languages) —
    # решение, укладывается ли в него выбор пользователя, если нужно, принимает сам workflow.
    # setdefault — явный workflow_variable агента/запроса все еще может переопределить язык
    user_language = str(await setting_get('language', '', user_id=user.user_id) or '').strip().lower()
    workflow_variables_all.setdefault('user_language', user_language or node_languages[0])
    language_active = str(workflow_variables_all.get('user_language') or 'ru')

    # Поля агента уходят в движок напрямую (prompt_system_create читает entity_agent,
    # минуя workflow-переменные) — резолвим их мультиязычные значения здесь же
    entity_agent['prompt_system'] = i18n_text_resolve(entity_agent.get('prompt_system'), language_active)
    entity_agent['greeting'] = i18n_text_resolve(entity_agent.get('greeting'), language_active)
    workflow_variables_all['agent_greeting'] = entity_agent['greeting']

    # Получаем переменные ноды воркфлоу и рендерим их с учетом уже собранных переменных
    if node_id:
        for x in await ai_workflow_variables_public_get(node_id):
            # Рендерим переменные ноды по очереди с учетом сортировки по позиции, чтобы переменные могли ссылаться друг на друга
            workflow_variable_node = ai_workflow_variables_render(
                {x.get('name'): x.get('default', None)},
                workflow_variables_all
            )
            # Резолвим i18n сразу, а не одним проходом в конце: следующие по позиции
            # public-переменные подставляют %эту_переменную% и должны видеть уже
            # готовый текст, а не сырой JSON-словарь переводов (иначе он подмешивается
            # как текст внутрь следующей переменной и ломает ее JSON при финальном резолве)
            for v_name, v_value in workflow_variable_node.items():
                workflow_variable_node[v_name] = i18n_text_resolve(v_value, language_active)
            workflow_variables_all.update(workflow_variable_node)

    # получаем переменные из БД для воркфлоу и добавляем их в workflow_variables_all
    ai_workflow_variables_defaults_apply(workflow_variables_all, raw_workflow_variables)

    # Мультиязычные значения ({"ru": "...", "en": "..."} — переменные, default'ы)
    # приводим к активному языку
    for v_name, v_value in workflow_variables_all.items():
        workflow_variables_all[v_name] = i18n_text_resolve(v_value, language_active)

    # Проверяем, что все глобальные переменные присутствуют в workflow_variables_all
    for i in [x.get('name') for x in await ai_workflow_variables_global_get()]:
        if i not in workflow_variables_all:
            raise HTTPException(
                status_code=400,
                detail=f"Переменная '{i}' глобальная, но отсутствует в маппинге."
            )

    # Проверяем, что все входящие переменные workflow присутствуют в workflow_variables_all
    for i in [x.get('name') for x in await ai_workflow_variables_input_get(workflow_id)]:
        if i not in workflow_variables_all:
            raise HTTPException(
                status_code=400,
                detail=f"Переменная '{i}' обязательная для workflow, но отсутствует в маппинге."
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
        "workflow_variables": workflow_variables_all,
        "prompt_user": json_request.question,
        "user_id": user.user_id,
        "companion_id": json_request.companion_id,
        "session_uuid": session_uuid,
        "tools": tools,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    # Долгие workflow (например, тестовые прогоны в цикле) поднимают таймаут
    # переменной chat_timeout; обычные — 60 секунд
    try:
        timeout = float(workflow_variables_all.get('chat_timeout') or 60.0)
    except (TypeError, ValueError):
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

    text = await faster_whisper_transcribe(temp_file)

    os.remove(temp_file)

    return {"result": text}

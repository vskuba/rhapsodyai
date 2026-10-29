import asyncio
import os
import traceback
import uuid

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from fastapi import UploadFile, File

from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load
from src.ai.ai_workflow import ai_workflow_variables_render
from src.ai.ai_workflow import ai_workflow_variables_input_get
from src.ai.ai_workflow import ai_workflow_variables_node_get
from src.ai.ai_workflow import ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.ai_workflow import ai_workflow_text_render
from setting_.setting_ import setting_get
from src.tool.setting.setting_ import setting_value_get
from i18n_.i18n_ import i18n_text_resolve, i18n_languages_parse
from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_variables_global_get
from src.ai.ai_workflow_trace import ai_workflow_trace_run_contract
from src.auth.auth import AuthChecker
from src.auth.auth_session import AuthSession
from src.faster_whisper.faster_whisper_model import faster_whisper_model_transcribe
from src.mysql_.repository.agent_repository import AgentRepository
from src.mysql_.repository.user_repository import UserRepository

router = APIRouter()


class ChatAskJsonRequest(BaseModel):
    question: str
    agent_id: int
    session_uuid: str | None = None
    variables: dict = {}


class ChatMessagesJsonRequest(BaseModel):
    session_uuid: str
    limit: int = 10


class ChatMessageDeliveredRequest(BaseModel):
    message_id: int


class ChatMessageIncomingRequest(BaseModel):
    owner_unique_id: str
    companion_unique_id: str
    text: str
    kind: str = 'chat'
    # Ключ реплики у источника. Не обязателен, но без него повтор вызова
    # положит вторую строку: защита стоит именно на нём.
    source_uid: str = ''
    # Когда он это написал, `ГГГГ-ММ-ДД ЧЧ:ММ:СС` в UTC. Пусто — сейчас.
    said_at: str = ''


@router.post("/chat/ask")
async def chat_ask_ai(
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

    # LLM ноды агента (список настраивается на ноду, не на пользователя)
    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))

    if not entities_llm:
        raise HTTPException(status_code=404, detail="LLM models not found for agent '%s'" % entity_agent.get('name'))

    # Загружаем шаги (нормализованные) и переменные workflow
    workflow_data = await ai_workflow_load(workflow_id)
    workflow_steps = workflow_data['steps']
    raw_workflow_variables = workflow_data['variables']

    # ⚠⚠⚠ **Присланное проверяется ДО того, как попадёт в сборку.**
    #
    # Ниже переменные запроса подмешиваются последними и перекрывают всё. Это и
    # была дыра: вызывающий переопределял **любую** внутреннюю переменную
    # workflow, а не только предназначенную ему.
    #
    # Проверено живьём — в запрос клалось `fact_collection_girl_name:
    # 'ЧУЖАЯ_КОЛЛЕКЦИЯ'`, и прогон шёл с ним: поиск и запись фактов уводились в
    # чужое хранилище одним полем запроса. Так же уводились `prompt_user`,
    # `girl_id`, имя агента.
    #
    # ⚠ Проверка стоит **до** сборки, а не после: иначе отвергнутое значение
    # успело бы попасть в `workflow_variables_all`, и вопрос «чем закончилось»
    # решался бы порядком строк.
    await _variables_allowed(workflow_id, json_request.variables)

    # Собираем переменные: базовые (единый сборщик) + из агента + из запроса пользователя
    workflow_variables_all = {
        **ai_workflow_variables_base(
            prompt_user=json_request.question.strip(),
            user_id=user.user_id,
            user_username=entity_user.get('username'),
            user_email=entity_user.get('email'),
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

    # Приветствие — такой же шаблон, как системный промпт: у универсального агента
    # в нём стоит `%girl_name%`. Раскрываем здесь, а не в движке: дальше по коду
    # переменные ноды подставляют `%agent_greeting%` и должны увидеть готовый текст.
    # Промпт раскрывает движок — ему видны ещё и переменные ноды.
    entity_agent['greeting'] = ai_workflow_text_render(entity_agent['greeting'], workflow_variables_all)
    workflow_variables_all['agent_greeting'] = entity_agent['greeting']

    # Получаем переменные ноды воркфлоу и рендерим их с учетом уже собранных переменных
    if node_id:
        for x in await ai_workflow_variables_node_get(node_id):
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
        "session_uuid": session_uuid,
        "tools": tools,
    })

    # ⚠⚠ Контракт вызова — в журнал прогона, рядом с ним самим. ЗАПРОС и ОТВЕТ
    # на странице трассы это `prompt_user` и `result`, то есть вход и выход
    # **workflow**; чем позвали по HTTP — вопрос соседний и по прогону не
    # восстановимый: `variables` запроса растворяются в снапшоте старта
    # вперемешку с переменными агента, ноды и реестра.
    #
    # ⚠ Кладём ДО запуска: движок перенесёт это в строку журнала при её
    # заведении, и контракт будет виден у идущего прогона — там, где он нужнее
    # всего. После ответа писать поздно: у зависшего ответа не будет никогда.
    framework_model.contract_request = json_request.model_dump()
    agent_manager.framework_workflow_run(framework_model, future, loop)

    # Долгие workflow (например, тестовые прогоны в цикле) поднимают таймаут
    # переменной chat_timeout; обычные — 60 секунд
    try:
        timeout = float(workflow_variables_all.get('chat_timeout') or 60.0)
    except (TypeError, ValueError):
        timeout = 60.0

    try:
        result_text = await asyncio.wait_for(future, timeout=timeout)

        # ⚠⚠ Номер обмена разговора — тому, кто будет отправлять реплику.
        # `workflow_variables` движок мутирует на месте, поэтому после прогона в
        # нём лежат финальные значения, в том числе положенные шагом записи.
        #
        # ⚠ Ноль — законный исход, а не отказ: агент промолчал, прогон ушёл в
        # «Тишину», и доставлять нечего.
        message_id = framework_model.companion_session_message_id

        # ⚠⚠ Намерения прогона — тем же полем модели, что номер обмена, и по
        # тем же причинам (движок копит их по ответу `chat_intention_add`).
        #
        # ⚠ Ключ отдаётся ВСЕГДА, пустым объектом в том числе. Принимающая
        # сторона обычно сворачивает «пусто» и «ключа нет» в одно, и пропажа
        # стала бы неотличима от штатной тишины — ровно так поломка номера
        # обмена прожила шесть дней незамеченной.
        #
        # ⚠⚠ **Форма — объект `{намерение: контекст}`, а не список меток.**
        # Метка отвечает «что решили», контекст — «с чем это делать»: письму
        # нужен текст, звонку время, покупке список. Прежняя форма (список
        # строк) места под это не имела вовсе.
        #
        # ⚠ Контекст бывает пустым: намерение помечено, а собрать контекст было
        # нечем или незачем. Это законный исход, а не полуготовность.
        intentions = framework_model.chat_intentions

        response = {"result": result_text, "message_id": message_id,
                    "intentions": intentions}

        # ⚠ Вторая половина контракта: что ушло зовущему. Пишется тем же, чем
        # отвечаем, — одним объектом, чтобы в журнале лежало ровно отданное,
        # а не его пересказ.
        await ai_workflow_trace_run_contract(framework_model.trace_run_id, response=response)

        return response
    except asyncio.TimeoutError:
        # Пытаемся отменить future, чтобы не висела в памяти
        future.cancel()
        # ⚠⚠ Отказ — тоже ответ контракта, и в журнале он нужнее удачного:
        # «почему зовущий не дождался» разбирают именно по нему. Без этой
        # записи у прогона, оборванного таймаутом, ответа нет вовсе — и
        # отличить его от оборванного «Стопом» нечем.
        await ai_workflow_trace_run_contract(
            framework_model.trace_run_id,
            response={"status": 504,
                      "detail": f"Превышено время ожидания ответа от ИИ ({timeout} сек.)"})
        raise HTTPException(status_code=504, detail=f"Превышено время ожидания ответа от ИИ ({timeout} сек.)")
    except Exception as e:
        backtrace = traceback.format_exc()
        logger_info(
            f"❌ Ошибка при ответе web чата: {e}."
            f"Полный стек вызовов:\n{backtrace}"
        )
        await ai_workflow_trace_run_contract(
            framework_model.trace_run_id,
            response={"status": 500, "detail": str(e)})
        raise e


@router.post("/chat/message/delivered")
async def chat_message_delivered(
        json_request: ChatMessageDeliveredRequest,
        user: AuthSession = Depends(AuthChecker([]))
) -> dict:
    """Отметить обмен разговора доставленным.

    Зовёт DatingAi в момент, когда реплика реально ушла собеседнику. До этого
    строка в `companion_session` лежит без отметки и в ленту для агента не идёт:
    сочинённое — ещё не сказанное.

    ⚠ Идемпотентна: повтор отвечает `marked: 0` и времени не двигает.
    """
    from src.tool.companion.companion_session import companion_session_delivered

    return {"result": await companion_session_delivered(json_request.message_id)}


@router.post("/chat/message/incoming")
async def chat_message_incoming(
        json_request: ChatMessageIncomingRequest,
        user: AuthSession = Depends(AuthChecker([]))
) -> dict:
    """Записать реплику собеседника — сразу, не дожидаясь нашего ответа.

    Зовёт DatingAi в момент приёма сообщения. Вторая дорога в
    `companion_session` помимо прогона workflow, и заведена она потому, что
    первая проходима **только при ответе**: `/chat/ask` запускают, когда
    решили отвечать, а реплика, оставшаяся без ответа, не попадала к нам
    ничем — ни ошибкой, ни следом. Двенадцать таких за восемь дней, замерено
    на проде 02.10.2026.

    ⚠ Идемпотентна по `source_uid`: повтор отвечает `saved: 0` и номер уже
    записанной строки. Без ключа защиты нет — повтор положит вторую строку.

    ⚠ Ответ агента, пришедший следом, эту строку **поглотит**: шаг workflow
    пишет обмен целиком, а висящая реплика убирается (`_pending_absorb`).
    Поэтому звать приём на каждое входящее безопасно и правильно — даже на
    то, на которое собираемся ответить.
    """
    from src.tool.companion.companion_session import companion_session_incoming

    return {"result": await companion_session_incoming(
        json_request.owner_unique_id, json_request.companion_unique_id,
        json_request.text, kind=json_request.kind,
        source_uid=json_request.source_uid, said_at=json_request.said_at)}


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
async def chat_voice_to_text(file: UploadFile = File(...)):
    temp_file = f"temp_{file.filename}.wav"

    # Асинхронно читаем и записываем
    content = await file.read()
    with open(temp_file, "wb") as buffer:
        buffer.write(content)

    text = await faster_whisper_model_transcribe(temp_file)

    os.remove(temp_file)

    return {"result": text}


async def _variables_allowed(workflow_id: int, sent: dict) -> None:
    """Пускает в сборку только объявленные переменные. Иначе — 400.

    Args:
        workflow_id: чей вызов проверяем.
        sent: то, что прислал вызывающий (`json_request.variables`).

    Raises:
        HTTPException: 400 — прислано имя, не объявленное входящим у этого
            workflow. В сообщении — имя и что с ним делать.

    ## ⚠⚠ Пускаем `input` и `global`, а `workflow` — нет

    `input` — то, что вызывающий обязан прислать: это его часть договора.
    `global` — переменные запроса, приносимые каждым сообщением заново; у них в
    движке своя роль (снимок сессии их намеренно не хранит).

    А `workflow` — **внутреннее устройство**: имена коллекций фактов, пределы,
    флаги ветвления. Право их переопределять снаружи и было дырой.

    ⚠ Молча отбрасывать нельзя: вызывающий, приславший `girl_i` вместо
    `girl_id`, получил бы зелёный ответ и молчащую ветку. Отказ с именем читается
    сразу.
    """
    if not sent:
        return

    allowed = {x.get('name') for x
               in await ai_workflow_variables_input_get(workflow_id)}
    allowed |= {x.get('name') for x in await ai_workflow_variables_global_get()}

    extra = sorted(set(sent) - allowed)
    if not extra:
        return

    raise HTTPException(
        status_code=400,
        detail=(f"Переменные {', '.join(extra)} не объявлены входящими у этого "
                f"workflow. Объявите их (`agent_workflow_variable.type = "
                f"'input'` у этого workflow) либо уберите из запроса: "
                f"переопределять внутренние переменные workflow снаружи нельзя.")
    )

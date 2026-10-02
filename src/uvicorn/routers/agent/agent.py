import httpx
from fastapi import APIRouter, Request, Depends, Body, HTTPException
from pydantic import BaseModel, Field, ConfigDict
import json

from config.config import config_get
from mysql_.mysql_ import mysql_get_db_async
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository
from src.mysql_.repository.user_repository import UserRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import auth_role_is_full

router = APIRouter()

# Свой же сервер: workflow гоняем через `/chat/ask`, а не мимо него — у точки своя
# проверка прав, свой журнал и своя сборка переменных, и вторая дорога к движку
# разошлась бы с первой на первой же правке.
#
# **Петля, а не имя сервиса.** Запрос идёт в тот же процесс, и `127.0.0.1` — самый
# короткий и самый надёжный путь до него. Имя контейнера здесь было ловушкой:
# Blue-Green переключает активный слот между `uvicorn` и `uvicorn_green`, а
# умолчание указывало на `uvicorn` — и на проде с активным green заведение агента
# падало с «Temporary failure in name resolution». Настройка `UVICORN_URL`
# остаётся: ею можно увести вызов на другой адрес, если понадобится.
AGENT_CREATE_CHAT_URL = config_get('UVICORN_URL', 'http://127.0.0.1:8000') + '/chat/ask'

# Прогон с LLM идёт минуты, а не секунды.
AGENT_CREATE_TIMEOUT = 300.0

# Сколько `/chat/ask` ждёт движок. Его умолчание — 60 секунд, и создание девушки
# в них не укладывается: один шаг разбирает биографию на три десятка фактов.
# Перед экраном здесь никто не сидит, поэтому ждём столько, сколько работа занимает.
AGENT_CREATE_CHAT_TIMEOUT = 240

# Инструмент, по которому узнаём: workflow сам заводит агента или нет.
AGENT_CREATE_TOOL = 'agent_create_or_update'

# All agent routes require AGENT_VIEW permission
agent_auth = AuthChecker([AuthPermission.AGENT_VIEW])


class AgentJsonRequest(BaseModel):
    find_by: dict


class AgentResponse(BaseModel):
    id: int = Field(..., description="Уникальный идентификатор агента", examples=[1])
    name: str = Field(..., description="Системное имя агента", examples=["support_agent"])
    title: str = Field(..., description="Отображаемое название агента", examples=["Служба поддержки"])


class AgentListResponse(BaseModel):
    result: list[AgentResponse] = Field(..., description="Список найденных агентов")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "result": [
                    {
                        "id": 1,
                        "name": "support_agent",
                        "title": "Служба поддержки"
                    }
                ]
            }
        }
    )


@router.get("/agent/list", include_in_schema=False)
async def agent_list_get(
        request: Request,
        data: AgentJsonRequest = Body(None),
        user=Depends(AuthChecker([AuthPermission.AGENT_VIEW]))
):
    repo = AgentRepository()

    find_by = {}
    if data and data.find_by is not None:
        find_by = data.find_by.copy()
    else:
        find_by_query = request.query_params.get("find_by")
        if find_by_query:
            try:
                find_by = json.loads(find_by_query)
            except Exception:
                pass
        else:
            # Fallback to direct user_id query parameter
            user_id_query = request.query_params.get("user_id")
            if user_id_query:
                find_by = {"user_id": int(user_id_query)}

    requested_user_id = find_by.pop("user_id", None)
    if requested_user_id is not None:
        try:
            requested_user_id = int(requested_user_id)
        except ValueError:
            requested_user_id = None

    # Роль сверяем по объёму прав, а не по имени `admin`: служебная роль `qa` тоже
    # полноправная, и по имени она проваливалась в ветку «свои агенты» — список
    # приходил пустым, а фильтр `user_id` молча игнорировался.
    if not auth_role_is_full(user.role.lower()):
        return {"result": await _agent_list_for_user(repo, user.user_id, find_by)}

    # Полноправная роль без явного user_id видит всех агентов; с user_id — превью списка "как видит этот пользователь"
    if requested_user_id is not None:
        return {"result": await _agent_list_for_user(repo, requested_user_id, find_by)}

    return {"result": await repo.find_by(find_by, order_by='position ASC')}


@router.post(
    "/agent/list",
    response_model=AgentListResponse,
    summary="Получить список агентов по токену доступа",
    description="Возвращает список агентов владельца токена доступа, отфильтрованных по переданным критериям.",
    response_description="Успешный ответ со списком агентов"
)
async def agent_list(
        request: Request,
        data: AgentJsonRequest,
        user=Depends(AuthChecker([]))
):
    repo = AgentRepository()
    return {"result": await _agent_list_for_user(repo, user.user_id, data.find_by or {})}


class AgentCreateRequest(BaseModel):
    """Заведение агента по именам, а не по номерам.

    Номера узла и workflow — внутреннее дело установки: они разные на стенде и на
    проде, и клиенту их взять неоткуда. Имена одинаковы везде и видны в админке.
    """

    node: str = Field(..., min_length=1, max_length=50,
                      description="Имя узла (`node.name`), например `Dating`")
    name: str = Field(..., min_length=1, max_length=50,
                      description="Системное имя агента; должно быть уникальным")
    workflow: str = Field(..., min_length=1, max_length=50,
                          description="Имя workflow (`agent_workflow.name`)")
    site: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-z0-9]+$',
                      description="Сайт-владелец агента: строчная латиница и цифры, "
                                  "без пробелов и спецсимволов (`^[a-z0-9]+$`); "
                                  "не соответствует — `422`")
    group_name: str | None = Field(None, max_length=50,
                                   description="Папка группировки агента в меню "
                                               "(`agent.group_name`); не передан — без группы")
    title: str = Field('', max_length=150, description="Отображаемое имя; пусто — возьмётся `name`")
    description: str = Field('', max_length=250, description="Для чего агент")
    greeting: str = Field('', description="Первая реплика агента в диалоге")
    prompt_system: str = Field('', description="Системная инструкция агента")
    variables: dict = Field(
        default_factory=dict,
        description="Значения обязательных полей workflow (`input`-переменные). "
                    "Каких именно — смотрите в отказе `422`: он их перечисляет")
    agent_variable: dict = Field(
        default_factory=dict,
        description="Переменные агента (`agent.agent_variable`): значения, которые "
                    "подставляются в `%плейсхолдеры%` системного промпта и "
                    "приветствия — например `{\"girl_name\": \"Natalia\"}`. "
                    "Это умолчания записи; конкретный разговор может прислать "
                    "своё значение в `variables` запроса `POST /chat/ask`")

    model_config = ConfigDict(json_schema_extra={
        "example": {"node": "Dating", "name": "support_agent", "workflow": "dating_talk",
                    "site": "support", "group_name": "Service",
                    "title": "Служба поддержки",
                    "agent_variable": {"girl_name": "Natalia"}}})


class AgentCreatedResponse(BaseModel):
    """Что получилось: номера проставлены сервером по переданным именам."""

    id: int = Field(..., description="Идентификатор заведённого агента", examples=[42])
    name: str = Field(..., description="Системное имя", examples=["support_agent"])
    title: str = Field(..., description="Отображаемое имя", examples=["Служба поддержки"])
    node_id: int = Field(..., description="Найденный узел", examples=[2])
    workflow_id: int = Field(..., description="Найденный workflow", examples=[7])
    site: str = Field(..., description="Записанный сайт агента", examples=["support"])


class AgentCreatedResult(BaseModel):
    result: AgentCreatedResponse


@router.post(
    "/agent/create",
    response_model=AgentCreatedResult,
    status_code=201,
    summary="Создать агента по именам узла и workflow",
    description="Заводит агента, находя узел и workflow **по имени**. Нужен заголовок "
                "`Authorization: Bearer <access-token>` пользователя с правом `AGENT_CREATE` "
                "(вместо него принимается и `X-API-KEY`). Имя агента глобально уникально: "
                "занятое имя даёт `409`, неизвестный узел или workflow — `422`. "
                "Обязателен сайт (`site`, строчная латиница и цифры) — "
                "не подходит под формат, `422`.",
    response_description="Агент заведён",
)
async def agent_create_by_name(
        request: Request,
        data: AgentCreateRequest,
        user=Depends(AuthChecker([AuthPermission.AGENT_CREATE]))
):
    repo = AgentRepository()
    await _agent_name_unique_check(repo, data.name)

    node_id = await _entity_id_by_name('node', data.node)
    workflow_id = await _entity_id_by_name('agent_workflow', data.workflow)

    # Workflow, который умеет заводить агента сам, и заводит его сам: у него для
    # этого есть шаги — промпт из шаблона узла, факты из биографии. Дублировать
    # это записью в таблицу значило бы завести вторую, расходящуюся дорогу.
    if await _workflow_creates_agent(workflow_id):
        # Обязательные поля проверяем здесь, а не выше: они нужны **работе**
        # workflow. У обычного агента те же переменные задаются в
        # `workflow_variable` и требуются в первом разговоре, а не при заведении.
        await _workflow_inputs_check(workflow_id, data.variables)

        return await _agent_create_by_workflow(request, data, node_id, workflow_id, user)

    agent_id = await repo.add({
        "name": data.name.strip(),
        "title": (data.title or data.name).strip(),
        "greeting": data.greeting,
        "node_id": node_id,
        "prompt_system": data.prompt_system,
        "workflow_id": workflow_id,
        "description": data.description,
        "site": data.site.strip(),
        "group_name": (data.group_name or '').strip() or None,
        "workflow_variable": None,
        "agent_variable": _agent_variable_json(data.agent_variable),
    })

    return {"result": {"id": agent_id, "name": data.name.strip(),
                       "title": (data.title or data.name).strip(),
                       "node_id": node_id, "workflow_id": workflow_id,
                       "site": data.site.strip()}}


@router.get(
    "/agent/name/{name}",
    summary="Найти агента по системному имени",
    description="Отдаёт номер, имя и заголовок агента по его системному имени (`name`). "
                "Нужен заголовок `Authorization: Bearer <access-token>` пользователя с правом "
                "`AGENT_VIEW` (принимается и `X-API-KEY`). Нет такого агента — `404`.",
    response_description="Агент найден",
)
async def agent_get_by_name(name: str, user=Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
    """Агент по имени — точечный поиск вместо просмотра списка.

    Списком это не сделать: `/agent/list` для неполноправной роли отдаёт только
    агентов, доступных её узлам, и служебной учётке приходит пустой массив. Ей и
    не нужен весь список — нужен один агент, про которого она знает имя.

    Так работает DatingAi: имя агента анкеты он собирает сам
    (`natalia_1430119`), а номер спрашивает здесь. Проверка «есть ли агент» идёт
    по имени, потому что агента могли удалить или переименовать в админке, и
    хранимая ссылка соврала бы.
    """
    agent = await AgentRepository().find_one_by({'name': str(name).strip()})
    if not agent:
        raise HTTPException(status_code=404, detail=f'агента «{name}» нет')

    return {"result": {"id": int(agent['id']), "name": agent['name'],
                       "title": agent.get('title') or '',
                       "node_id": agent.get('node_id'),
                       "workflow_id": agent.get('workflow_id')}}


@router.get("/agent/{agent_id}", include_in_schema=False)
async def agent_get(request: Request, agent_id: int, user=Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
    repo = AgentRepository()
    entity_agent = await repo.find(agent_id)
    if entity_agent:
        entity_agent["role_ids"] = await _agent_role_ids_get(agent_id)
    return {"result": entity_agent}


@router.get("/agent/{agent_id}/prompt_system/{collection_name}", include_in_schema=False)
async def agent_get_prompt_system(
        request: Request,
        agent_id: int,
        collection_name: str,
        user=Depends(AuthChecker([AuthPermission.AGENT_VIEW]))):
    repo = AgentRepository()
    entity = await repo.find(agent_id)

    manager = AiFrameworkAgentManager()
    prompt_system = await manager.prompt_system_create({
        "entity_agent": entity,
        "collection_name": collection_name
    })

    return {"result": prompt_system}


@router.post("/agent", include_in_schema=False)
async def agent_create(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.AGENT_CREATE]))):
    repo = AgentRepository()

    await _agent_name_unique_check(repo, data.get('name'))

    agent_id = await repo.add({
        "name": data.get('name'),
        "title": data.get('title'),
        "greeting": data.get('greeting', ''),
        "node_id": data.get('node_id', None),
        "prompt_system": data.get('prompt_system', ''),
        "workflow_id": data.get('workflow_id', None),
        "llm_id": data.get('llm_id', None),
        "description": data.get('description', ''),
        "group_name": data.get('group_name') or None,
        "workflow_variable": _agent_variable_json(data.get('workflow_variable')),
        "agent_variable": _agent_variable_json(data.get('agent_variable')),
    })

    await _agent_role_ids_set(agent_id, data.get('role_ids') or [])

    # Return the full created agent object
    entity_agent = await repo.find(agent_id)
    entity_agent["role_ids"] = await _agent_role_ids_get(agent_id)
    return {"result": entity_agent}


@router.put("/agent/{agent_id}", include_in_schema=False)
async def agent_update(
        request: Request,
        agent_id: int,
        data: dict, db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.AGENT_UPDATE]))):
    # First get the current agent to preserve fields not in the request
    repo = AgentRepository()
    current_agent = await repo.find(agent_id)
    if not current_agent:
        return {"status": "error", "message": "Агент не найден"}

    if 'name' in data and data.get('name') != current_agent.get('name'):
        await _agent_name_unique_check(repo, data.get('name'), exclude_id=agent_id)

    # Merge current data with updates (only update provided fields)
    # For fields not in request, keep current values
    merged_data = {
        "name": data.get('name', current_agent.get('name')),
        "node_id": data.get('node_id', current_agent.get('node_id')),
        "title": data.get('title', current_agent.get('title')),
        "group_name": data.get('group_name', current_agent.get('group_name')) or None,
        "workflow_id": data.get('workflow_id', current_agent.get('workflow_id')),
        "llm_id": data.get('llm_id', current_agent.get('llm_id')),
        "workflow_variable": data.get('workflow_variable', current_agent.get('workflow_variable')),
        "agent_variable": data.get('agent_variable', current_agent.get('agent_variable')),
        "prompt_system": data.get('prompt_system', current_agent.get('prompt_system')),
        "greeting": data.get('greeting', current_agent.get('greeting')),
        "description": data.get('description', current_agent.get('description')),
    }

    async with db:
        sql = """
            UPDATE agent
            SET
                name = %s,
                node_id = %s,
                title = %s,
                group_name = %s,
                workflow_id = %s,
                llm_id = %s,
                workflow_variable = %s,
                agent_variable = %s,
                prompt_system = %s,
                greeting = %s,
                description = %s
            WHERE id = %s
        """

        values = (
            merged_data['name'],
            merged_data['node_id'],
            merged_data['title'],
            merged_data['group_name'],
            merged_data['workflow_id'],
            merged_data['llm_id'],
            _agent_variable_json(merged_data['workflow_variable']),
            _agent_variable_json(merged_data['agent_variable']),
            merged_data['prompt_system'],
            merged_data['greeting'],
            merged_data['description'],
            agent_id
        )

        await db.execute(sql, values)
        await db.connection.commit()

    # Синхронизируем роли, только если поле передано в запросе
    if 'role_ids' in data:
        await _agent_role_ids_set(agent_id, data.get('role_ids') or [], replace=True)

    return {"status": "success", "result": "Данные обновлены"}


@router.get("/agent/{agent_id}/user/{user_id}/session_last_entry", include_in_schema=False)
async def agent_session_active_get(
        request: Request,
        agent_id: int,
        user_id: int,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.AGENT_VIEW, AuthPermission.SESSION_VIEW]))):
    async with db:
        await db.execute(
            "SELECT session_uuid "
            "FROM agent_session "
            "WHERE agent_id = %s AND user_id = %s "
            "ORDER BY created_at DESC LIMIT 1", (agent_id, user_id)
        )
        return {"result": await db.fetchone()}


@router.delete("/agent/{agent_id}", include_in_schema=False)
async def agent_delete(request: Request, agent_id: int, user=Depends(AuthChecker([AuthPermission.AGENT_DELETE]))):
    repo = AgentRepository()
    deleted = await repo.delete(agent_id)
    if not deleted:
        return {"status": "error", "message": "Агент не найден"}
    return {"status": "success", "result": "Агент удален"}


def _agent_variable_json(value) -> str | None:
    """Приводит словарь переменных к тому, что лежит в колонке, — JSON-строке.

    Строка проходит как есть: админка присылает уже сериализованный JSON, а
    внешний клиент — словарь. Пустое значение записываем `NULL`, а не `'{}'`:
    «переменных нет» и «переменные есть, но пустые» в чтении неразличимы, а
    NULL короче и честнее.
    """
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False) if value else None

    return value or None


async def _agent_role_ids_get(agent_id: int) -> list[int]:
    """Возвращает список role_id агента из таблицы agent_role."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT role_id FROM agent_role WHERE agent_id = %s ORDER BY role_id", (agent_id,))
        rows = await db.fetchall()
        return [row["role_id"] for row in rows]


async def _agent_role_ids_set(agent_id: int, role_ids: list, replace: bool = False):
    """Записывает роли агента в таблицу agent_role."""
    async with mysql_get_db_async() as db:
        if replace:
            await db.execute("DELETE FROM agent_role WHERE agent_id = %s", (agent_id,))
        for role_id in role_ids:
            await db.execute("INSERT INTO agent_role (agent_id, role_id) VALUES (%s, %s)", (agent_id, role_id))


async def _workflow_inputs_check(workflow_id: int, variables: dict) -> None:
    """Проверяет обязательные поля workflow. Не хватает — 422 с перечнем.

    Проверяем только `input`-переменные. Как раскрыть шаблоны промпта — забота
    самого workflow: он их и рендерит, а вызывающему знать про `%wildcards%`
    незачем.
    """
    from src.ai.ai_workflow import ai_workflow_variables_input_get

    missing = []
    for row in await ai_workflow_variables_input_get(workflow_id):
        name = str(row.get('name') or '')
        if name and not str(variables.get(name) or '').strip():
            missing.append(f"{name} — {row.get('description') or 'обязательное поле'}")

    if missing:
        raise HTTPException(status_code=422,
                            detail='не заполнены обязательные поля workflow: ' + '; '.join(missing))


async def _workflow_creates_agent(workflow_id: int) -> bool:
    """Есть ли у workflow шаг, который заводит агента."""
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT COUNT(*) AS n FROM agent_workflow_step '
            ' WHERE workflow_id = %s AND metadata LIKE %s',
            (int(workflow_id), f'%{AGENT_CREATE_TOOL}%'))
        row = await db.fetchone()

    return bool(row and row['n'])


async def _agent_create_by_workflow(request: Request, data: AgentCreateRequest,
                                    node_id: int, workflow_id: int, user) -> dict:
    """Заводит агента прогоном workflow и отдаёт его итог.

    Имя девушки уходит в `question`, а не в переменные: у узла Dating есть своя
    переменная `girl_title` типа `proxy` со значением `%prompt_user%`, и она
    перекрывает одноимённую из запроса. Идти против этого значило бы чинить узел
    ради одного вызова.
    """
    # Агент-исполнитель: тот, кто умеет гонять этот workflow. Заводим временного,
    # потому что `/chat/ask` работает от агента, а нашего ещё нет — его и создаст
    # прогон.
    runner_name = f'{data.workflow}_runner'
    runner = await AgentRepository().find_one_by({'name': runner_name})
    if not runner:
        runner_id = await AgentRepository().add({
            'name': runner_name, 'title': f'Мастер: {data.workflow}',
            'greeting': '', 'node_id': node_id, 'prompt_system': '',
            'workflow_id': workflow_id, 'description': f'Служебный агент для {data.workflow}',
            'group_name': None, 'workflow_variable': None})
    else:
        runner_id = int(runner['id'])

    # `agent_name` кладём сами: workflow обязан создать агента под тем именем,
    # которое просил вызывающий, а не выводить своё. Иначе точка отвечает 201 на
    # повторный запрос — имя-то свободно, занято другое.
    variables = dict(data.variables or {})
    variables['agent_name'] = data.name
    variables.setdefault('chat_timeout', AGENT_CREATE_CHAT_TIMEOUT)

    payload = {'question': (data.title or data.name).strip(),
               'agent_id': runner_id,
               'variables': variables}

    headers = {}
    for header in ('authorization', 'x-api-key', 'cookie'):
        value = request.headers.get(header)
        if value:
            headers[header] = value

    async with httpx.AsyncClient(timeout=AGENT_CREATE_TIMEOUT) as client:
        response = await client.post(AGENT_CREATE_CHAT_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=502,
                            detail=f'workflow «{data.workflow}» не отработал: {response.text[:300]}')

    answer = str((response.json() or {}).get('result') or '').strip()
    created = await AgentRepository().find_one_by({'name': data.name})

    # Сайт, группу и переменные агента пишет точка создания, а не прогон:
    # вызывающий их просил, а у прогона своя забота. Группа и переменные —
    # COALESCE: не переданы, оставляем то, что в строке (workflow мог их задать
    # сам — `agent_create_or_update` умеет писать переменные).
    if created:
        async with mysql_get_db_async() as db:
            await db.execute(
                'UPDATE agent SET site = %s, group_name = COALESCE(%s, group_name), '
                '       agent_variable = COALESCE(%s, agent_variable) '
                ' WHERE id = %s',
                (data.site.strip(), (data.group_name or '').strip() or None,
                 _agent_variable_json(data.agent_variable), int(created['id'])))
            await db.connection.commit()

    return {'result': {'id': int(created['id']) if created else 0,
                       'name': data.name, 'title': data.title or data.name,
                       'node_id': node_id, 'workflow_id': workflow_id,
                       'site': data.site.strip(),
                       'workflow_answer': answer}}


async def _entity_id_by_name(table: str, name: str) -> int:
    """Номер записи по её имени. Нет такой — 422 с перечнем того, что есть.

    Список в ответе не роскошь: клиент задал имя, которого нет, и без подсказки
    ему остаётся гадать. Отдаём немного — ровно чтобы узнать своё.
    """
    async with mysql_get_db_async() as db:
        await db.execute(f"SELECT id FROM `{table}` WHERE name = %s", (name.strip(),))
        row = await db.fetchone()
        if row:
            return int(row['id'])

        await db.execute(f"SELECT name FROM `{table}` ORDER BY name LIMIT 20")
        known = [str(r['name']) for r in (await db.fetchall() or [])]

    raise HTTPException(
        status_code=422,
        detail=f"{table}: имя «{name}» не найдено. Известные: {', '.join(known) or '—'}")


async def _agent_name_unique_check(repo: AgentRepository, name: str | None, exclude_id: int | None = None):
    """Имя агента — системный идентификатор (document_id в Qdrant, заголовок фактов),
    поэтому оно должно быть глобально уникальным. Отображаемое имя — поле title."""
    name = (name or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="Имя агента (name) не может быть пустым")

    existing = await repo.find_one_by({"name": name})
    if existing and existing.get('id') != exclude_id:
        raise HTTPException(
            status_code=409,
            detail=f"Имя агента '{name}' уже занято. Системное имя должно быть уникальным — "
                   f"используйте другое name (отображаемое имя задается в поле title)."
        )


async def _agent_list_for_user(repo: AgentRepository, user_id: int, find_by: dict) -> list:
    """Возвращает агентов, доступных пользователю user_id, с учетом его роли и нод."""
    user_repo = UserRepository()
    target_user = await user_repo.find(user_id)

    if not target_user or not target_user.get('role_id'):
        return []

    role_id = target_user['role_id']

    # ⚠⚠ Репозиторий зовётся ЗА пределами блока `async with`, а не внутри.
    #
    # `repo.find_by` берёт из пула СВОЁ соединение. Позови его внутри блока,
    # который своё соединение уже держит, — и обработчик занимает два. Пока
    # запросы идут по одному, это лишь расточительно; но стоит десяти прийти
    # разом, и каждый держит одно соединение, ожидая второго, которого в пуле
    # больше нет. Все ждут друг друга навсегда, и ни одной ошибки при этом не
    # возникает: исчерпанный пул не роняет запрос, а ждёт.
    #
    # Ровно так 2026-09-29 встал прод из-за `/llm/status` — там внутри блока
    # крутился цикл с `setting_get`. Подробности в комментарии той ручки.
    async with mysql_get_db_async() as db:
        # Определяем имя роли: админ видит всех агентов без фильтрации по нодам
        await db.execute("SELECT name FROM `role` WHERE id = %s", (role_id,))
        role_row = await db.fetchone()
        role_name = role_row['name'] if role_row else None

        if auth_role_is_full(role_name or ''):
            # Своё соединение больше не нужно: остальное сделает репозиторий.
            full_access = True
        else:
            full_access = False

            # Получаем node_ids пользователя из промежуточной таблицы
            await db.execute("SELECT node_id FROM user_node WHERE user_id = %s", (user_id,))
            rows = await db.fetchall()
            user_node_ids = [row["node_id"] for row in rows]

            # Агенты, у которых среди ролей есть роль пользователя
            await db.execute("SELECT agent_id FROM agent_role WHERE role_id = %s", (role_id,))
            role_rows = await db.fetchall()
            role_agent_ids = {row["agent_id"] for row in role_rows}

    # Соединение блока уже отпущено — репозиторий берёт своё, а не второе.
    all_agents = await repo.find_by(find_by, order_by='position ASC')

    if full_access:
        return all_agents

    # Фильтруем агентов:
    # - должен относиться к одной из нод пользователя (agent['node_id'] in user_node_ids)
    # - роль пользователя должна быть среди ролей агента (agent_role)
    return [
        agent for agent in all_agents
        if agent.get("node_id") in user_node_ids and agent.get("id") in role_agent_ids
    ]

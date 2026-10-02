"""Ручки журнала вызовов LLM: страница «Сессии», вкладка «Агенты».

Строка `agent_session` — это один вызов модели или его часть: промпт, ответ,
обращение к инструменту, потраченные токены. Переписка «кто с кем и о чём»
живёт в соседней таблице и читается соседней ручкой
(`session_companion.py`) — предметы разные, поля разные, отборы разные.

## ⚠⚠ Отбора по собеседнику здесь нет и быть не может

Столбец `agent_session.companion_id` снят миграцией
`20260924320000_agent_session_companion_drop`: у таблицы одно занятие — журнал
вызова, а «кто с кем разговаривает» она отвечала плохо. Фильтр «Собеседник»
на странице переживал столбец на несколько месяцев и всё это время не
фильтровал ничего: тело запроса поля не знает, а выдача его не возвращает.
Собеседник теперь на вкладке «Чат».
"""

from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import auth_role_is_full

router = APIRouter()

# Какие `kind_type` считаются диалоговыми — остальное служебные записи вокруг
# них (`llm-request` и прочее).
#
# ⚠ Пара нужна в двух местах сразу: ею режется предел в `/session/messages` и
# ею же считается `dialog_count` в выдаче списка. Разойдись эти два понимания —
# и «сообщений 12» в списке означало бы не то, что показывает выбранная сессия.
SESSION_KIND_DIALOG = ('user-prompt', 'response-final')

# Та же пара списком для SQL. Значения свои, не из запроса, — подстановка в
# текст запроса здесь ничем не грозит.
_SESSION_KIND_DIALOG_SQL = ', '.join(f"'{kind}'" for kind in SESSION_KIND_DIALOG)

# Выборка «строка на сессию»: сгруппированный журнал.
#
# ⚠⚠ `MAX(role)` и `MAX(kind_type)` — **не последнее значение**, а
# лексикографический максимум по строкам группы. Реконструировать по ним ход
# диалога нельзя; остаются они потому, что их читают снаружи (tests, соседи).
# Что происходило в сессии, спрашивают у `/session/messages`.
#
# ⚠ `msg_count` считает строки журнала целиком, `dialog_count` — только
# реплики. Разница на живых данных десятикратная (служебных записей больше
# всего), и показывать человеку первое как «сообщений в переписке» — врать.
_SESSION_GROUPED_SELECT = f"""
    SELECT
        session_uuid,
        MAX(role) as role,
        MAX(kind_type) as kind_type,
        MAX(agent_id) as agent_id,
        MAX(user_id) as user_id,
        MAX(created_at) as last_message_at,
        COUNT(*) as msg_count,
        SUM(kind_type IN ({_SESSION_KIND_DIALOG_SQL})) as dialog_count
    FROM agent_session
    WHERE 1=1
"""


class SessionJsonRequest(BaseModel):
    agent_id: int | None = None
    user_id: int | None = None


class SessionMessagesJsonRequest(BaseModel):
    session_uuid: str
    # Максимум диалоговых сообщений (user-prompt + response-final) в выдаче
    limit: int = 25


@router.post("/session/list")
async def session_list(
        request: Request,
        json_request: SessionJsonRequest,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """Сессии по фильтрам, свежие сверху. Строка на `session_uuid`.

    Returns:
        dict: `result` — строки с `session_uuid`, `agent_id`, `user_id`,
        временем последней записи, числом строк журнала (`msg_count`) и числом
        реплик (`dialog_count`).
    """
    condition, params = _session_filters(json_request, user)
    sql = (_SESSION_GROUPED_SELECT + condition
           + " GROUP BY session_uuid ORDER BY last_message_at DESC")

    async with db:
        await db.execute(sql, tuple(params))
        return {"result": await db.fetchall()}


@router.get("/session/kind_type/list")
async def session_kind_types_list(
        request: Request,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    sql = "SELECT DISTINCT kind_type FROM agent_session"
    params = []
    if not auth_role_is_full(user.role):
        sql += f" WHERE {_agent_role_condition()}"
        params.append(user.role)
    sql += " ORDER BY kind_type ASC"

    async with db:
        await db.execute(sql, params)
        rows = await db.fetchall()
        return {"result": [row["kind_type"] for row in rows]}


@router.post("/session/last")
async def session_last(
        request: Request,
        json_request: SessionJsonRequest,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """Та же выборка, что у `/session/list`, но одна — последняя."""
    condition, params = _session_filters(json_request, user)
    sql = (_SESSION_GROUPED_SELECT + condition
           + " GROUP BY session_uuid ORDER BY last_message_at DESC LIMIT 1")

    async with db:
        await db.execute(sql, tuple(params))
        return {"result": await db.fetchone()}


@router.post("/session/last/uuid")
async def session_last_uuid(
        request: Request,
        json_request: SessionJsonRequest,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """Только `session_uuid` последней сессии — или `null`, если её нет."""
    condition, params = _session_filters(json_request, user)
    sql = ("SELECT session_uuid FROM agent_session WHERE 1=1" + condition
           + " ORDER BY created_at DESC LIMIT 1")

    async with db:
        await db.execute(sql, tuple(params))
        row = await db.fetchone()

        session_uuid = row["session_uuid"] if row else None
        return {"result": session_uuid}


@router.post("/session/messages")
async def session_messages(
        request: Request,
        json_request: SessionMessagesJsonRequest,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    async with db:
        # Выбираем сообщения в обратном порядке (DESC), чтобы отсчитать последние диалоговые сообщения
        sql = """
            SELECT s.*, l.name as llm_name
            FROM agent_session s
            LEFT JOIN llm l ON s.llm_id = l.id
            WHERE s.session_uuid = %s
        """
        params = [json_request.session_uuid]

        if not auth_role_is_full(user.role):
            sql += f" AND {_agent_role_condition('s')}"
            params.append(user.role)

        sql += " ORDER BY s.id DESC"

        await db.execute(sql, params)
        rows = await db.fetchall()

    limit = min(max(json_request.limit, 1), 200)
    selected_messages = []
    dialog_count = 0
    for m in rows:
        kind = m.get("kind_type", "").strip().lower()
        is_dialog = kind in SESSION_KIND_DIALOG

        # Лимит считаем по диалоговым сообщениям; служебные записи (llm-request и пр.)
        # включаются, пока принадлежат выбранным запросам
        if is_dialog and dialog_count >= limit:
            break

        selected_messages.append(m)
        if is_dialog:
            dialog_count += 1

    # Возвращаем сообщения в правильном хронологическом порядке (ASC)
    return {"result": list(reversed(selected_messages))}


@router.delete("/session/{session_uuid}")
async def session_delete(
        request: Request,
        session_uuid: str,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_DELETE]))
):
    """Удаляет всю переписку сессии (все сообщения agent_session с этим session_uuid)."""
    async with db:
        sql = "DELETE FROM agent_session WHERE session_uuid = %s"
        params = [session_uuid]

        if not auth_role_is_full(user.role):
            sql += f" AND {_agent_role_condition()}"
            params.append(user.role)

        await db.execute(sql, params)
        deleted = db.rowcount
        await db.connection.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    return {"result": deleted}


def _session_filters(json_request: SessionJsonRequest, user) -> tuple[str, list]:
    """Отбор строк журнала куском `WHERE` и его значениями.

    Один сборщик на три ручки (`list`, `last`, `last/uuid`): отбор у них
    одинаковый по смыслу, и три копии расходились бы на первой же правке —
    например, когда у выдачи появился `user_id`, а у фильтров нет.

    ⚠ Видимость не-админа подставляется здесь же, последним условием: забыть
    её в одной из трёх ручек значило бы открыть чужие сессии именно той, про
    которую забыли.
    """
    condition = ''
    params = []

    if json_request.agent_id:
        condition += " AND agent_id = %s"
        params.append(json_request.agent_id)

    if json_request.user_id:
        condition += " AND user_id = %s"
        params.append(json_request.user_id)

    if not auth_role_is_full(user.role):
        condition += f" AND {_agent_role_condition()}"
        params.append(user.role)

    return condition, params


def _agent_role_condition(alias: str = '') -> str:
    """Видимость сессий для не-админов: только сессии агентов, роли которых
    совпадают с ролью пользователя (agent_id -> agent_role -> role.name)."""
    prefix = f"{alias}." if alias else ""
    return (
        f"{prefix}`agent_id` IN ("
        "SELECT ar.`agent_id` FROM `agent_role` ar "
        "JOIN `role` r ON r.`id` = ar.`role_id` "
        "WHERE r.`name` = %s)"
    )

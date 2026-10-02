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

# Размер страницы списка сессий и потолок поверх запрошенного.
#
# ⚠⚠ Предел стоит **по умолчанию**, а не по желанию вызывающего. Без него
# ручка отдавала 5,25 МБ на 27 792 сессии прода — строка на сессию, все разом,
# и браузер потом строил из них 27 792 `<option>`. Это не теория: страница
# открывалась семь секунд, из которых почти четыре уходили на перевоз и
# отрисовку списка, который человек всё равно читает сверху.
SESSION_PAGE = 50
SESSION_PAGE_MAX = 500

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
    # Страница списка и её размер. Касаются только `/session/list`: у `last` и
    # `last/uuid` ответ и так один.
    page: int = 1
    per_page: int = SESSION_PAGE


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
    """Страница сессий по фильтрам, свежие сверху. Строка на `session_uuid`.

    Returns:
        dict: `result` — строки страницы (`session_uuid`, `agent_id`,
        `user_id`, время последней записи, `msg_count` — строк журнала,
        `dialog_count` — реплик); рядом `total`, `page`, `pages`, `per_page`.

    ## ⚠ Выдача ограничена по умолчанию, и это слом совместимости

    Прежде ручка отдавала **все** сессии. Вызывающий, который про страницы не
    знает, теперь получит первые `SESSION_PAGE` — то есть самые свежие.
    Сделано нарочно: на проде «все» это 5,25 МБ и четыре секунды, и такой
    ответ нельзя оставлять умолчанием. Нужен прежний объём — спросите
    `per_page` явно (потолок `SESSION_PAGE_MAX`).

    ## ⚠ `total` считается отдельным запросом, и он дёшев

    `COUNT(DISTINCT session_uuid)` идёт по `idx_session` разреженным сканом
    (`Using index for group-by`) — 0,23 с против трёх у самой выборки. Брать
    его из длины полного списка значило бы вернуть ровно то, от чего ушли.

    ⚠ Порядок — `last_message_at DESC`: свежие сверху, первая страница это
    «что происходит сейчас». Так же устроен и список разговоров на соседней
    вкладке.

    ## ⚠⚠⚠ Вторым ключом `session_uuid`, иначе страницы пересекаются

    Время последней записи **не уникально**: сессии, заведённые в одну
    миллисекунду, равны для сортировки, и порядок между ними MySQL выбирает на
    своё усмотрение — для каждого `LIMIT/OFFSET` заново. Одна и та же сессия
    тогда попадает и на первую страницу, и на вторую, а чья-то не попадает
    никуда.

    Поймано тестом `test_session_list_pages_do_not_overlap`: при `per_page = 5`
    пересеклась одна сессия из пяти. На проде это видно как «строка
    продублировалась при перелистывании».

    ⚠ `session_uuid` годится в тай-брейкер именно здесь: по нему идёт
    `GROUP BY`, значит в выдаче он уникален по построению.
    """
    condition, params = _session_filters(json_request, user)
    per_page = max(1, min(int(json_request.per_page or 0) or SESSION_PAGE,
                          SESSION_PAGE_MAX))
    page = max(1, int(json_request.page or 1))

    sql = (_SESSION_GROUPED_SELECT + condition
           + " GROUP BY session_uuid"
             " ORDER BY last_message_at DESC, session_uuid DESC"
             " LIMIT %s OFFSET %s")

    async with db:
        await db.execute(
            "SELECT COUNT(DISTINCT session_uuid) as total FROM agent_session"
            " WHERE 1=1" + condition, tuple(params))
        total = int(((await db.fetchone()) or {}).get("total") or 0)

        await db.execute(sql, tuple(params) + (per_page, (page - 1) * per_page))
        rows = await db.fetchall()

    return {"result": rows, "total": total, "page": page,
            "per_page": per_page,
            "pages": max(1, -(-total // per_page))}


@router.get("/session/agent/list")
async def session_agent_list(
        request: Request,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """По каким парам «агент + пользователь» есть сессии и сколько.

    Returns:
        dict: `result` — `[{agent_id, user_id, sessions}]`, пар два десятка;
        `total` — сессий всего под правами вызывающего.

    ## ⚠⚠ Заведена потому, что список сессий стал страничным

    Отборы на странице строились из **полной** выдачи `/session/list`: оттуда
    брались и список агентов, и счётчики, и сужение пользователей выбранным
    агентом. Со страницей в полсотни строк такой источник показывал бы только
    тех, кто попал в первую страницу, — то есть отбор молча терял бы агентов,
    у которых давно не было разговоров.

    Здесь спрашивается ровно то, что нужно отбору: пары и счёт. Строк два
    десятка против двадцати восьми тысяч.

    ⚠ Считаются **сессии**, а не строки журнала: в отборе стоит «сколько
    разговоров у этого агента», а строк на разговор приходится в среднем
    шестнадцать.

    ## ⚠ `total` спрашивается отдельно, и не из лени

    Сложить `sessions` по парам нельзя: сессия, у которой строки лежат под
    разными парами, попала бы в сумму дважды. На проде таких одна из 27 792,
    на разработке тринадцать из 4 018 — мало, но «всего сессий» обязано
    совпадать с тем, что отдаёт список, иначе числа в интерфейсе спорят.
    Отдельный `COUNT(DISTINCT)` идёт разреженным сканом и стоит доли секунды.
    """
    condition = ''
    params = []

    if not auth_role_is_full(user.role):
        condition = f" AND {_agent_role_condition()}"
        params.append(user.role)

    async with db:
        await db.execute(
            "SELECT agent_id, user_id, COUNT(DISTINCT session_uuid) as sessions"
            " FROM agent_session WHERE 1=1" + condition
            + " GROUP BY agent_id, user_id", tuple(params))
        pairs = await db.fetchall()

        await db.execute(
            "SELECT COUNT(DISTINCT session_uuid) as total FROM agent_session"
            " WHERE 1=1" + condition, tuple(params))
        total = int(((await db.fetchone()) or {}).get("total") or 0)

    return {"result": pairs, "total": total}


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

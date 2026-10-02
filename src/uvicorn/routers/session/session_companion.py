"""Ручки разговоров пары: страница «Сессии», вкладка «Чат».

Предмет у вкладки свой, поэтому и ручки свои. `agent_session` — журнал вызова
LLM: строка на промпт, на ответ, на вызов инструмента, с токенами и `llm_id`.
`companion_session` — разговор двух сторон: строка на **обмен**, «он спросил —
мы ответили», с временем каждой половины и отметкой доставки. Полей общих
почти нет, отборы разные, и одна ручка «дай сессии» утопила бы один предмет в
другом — тот же довод, что у подвкладок журнала
(`src/uvicorn/routers/journal/journal_mysql.py`).

Запись сюда делает инструмент `src/tool/companion/companion_session.py`; этот
роутер разговор только читает.

## ⚠⚠ Вкладка «Чат» не сужается по роли, и сузить её нечем

У `agent_session` есть `agent_id`, и соседняя ручка прячет от не-админа чужих
агентов через `agent_role` (session.md §2). У `companion_session` агента нет
вовсе: столбец `request_uuid` заведён «мостом в `agent_session`», но его никто
не заполняет — на установке он пуст во всех строках. Значит отбор по роли не
то чтобы не сделан, а **не из чего сделать**: право `session:view` открывает
все разговоры всем, кто его имеет (не-админские роли получают его набором по
умолчанию, `auth_role.py`). Появится заполненный `request_uuid` — отбор можно
будет построить по нему; до тех пор это известная дырка, а не недосмотр.

## ⚠ Удаления здесь нет намеренно

У вкладки «Агенты» кнопка удаления есть: журнал вызовов можно чистить, он
только журнал. Разговор — **память агента**: `companion_session_history`
собирает из него ленту для промпта. Удалив переписку, агент начинает говорить с
человеком как с незнакомым — ровно та беда, от которой таблицу и заводили.
Понадобится — завести отдельным правом и с предупреждением в интерфейсе.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.tool.companion.companion_session import COMPANION_SESSION_KINDS

router = APIRouter()

# Сколько обменов отдавать странице, если предел не задали, и потолок поверх
# запрошенного.
#
# ⚠ Пределы свои, не те, что у `companion_session` в инструменте: там лента едет
# в промпт и стоит токенов на каждом ответе, здесь её читает человек глазами.
SESSION_COMPANION_LIMIT = 50
SESSION_COMPANION_LIMIT_MAX = 500


class SessionCompanionListRequest(BaseModel):
    owner_id: int | None = None
    companion_id: int | None = None
    # Канал разговора: `chat` или `mail`. Пусто — оба.
    kind: str = ''
    # Доставка нашего ответа: `yes`, `no`, пусто — любая.
    delivered: str = ''


class SessionCompanionMessagesRequest(BaseModel):
    owner_id: int
    companion_id: int
    kind: str = ''
    delivered: str = ''
    # Максимум обменов в выдаче, по последним.
    limit: int = SESSION_COMPANION_LIMIT


@router.post('/session/companion/list')
async def session_companion_list(
        request: Request,
        json_request: SessionCompanionListRequest,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """Разговоры: строка на пару и канал, свежие сверху.

    Returns:
        dict: `result` — список строк с ключами обеих сторон, каналом,
        счётчиками обменов (`exchange_count`, `question_count`,
        `answer_count`, `undelivered_count`) и временем последней реплики
        (`last_at`).

    ## ⚠ Разговор — это тройка, а не пара

    Группировка идёт по `owner_id`, `companion_id` **и** `kind`: чат и почта
    одной пары — разные разговоры (разной длины, разного тона, часто разных
    дней). Слей их в одну строку, и выбор в списке перестал бы отвечать на
    вопрос «какую переписку открыть».

    ## ⚠ Ключи сторон в `GROUP BY`, а не в `MAX()`

    Они однозначны по номеру записи, и база это иногда выводит сама — но
    только иногда: под `ONLY_FULL_GROUP_BY` (на установке режим выключен, на
    соседней может быть включён) запрос с ними «в воздухе» отвергается целиком.
    `MAX()` же повторил бы грабли соседней ручки, где `MAX(role)` выглядит
    «последней ролью», ею не являясь (session.md, грабли №1).
    """
    sql = """
        SELECT s.`owner_id`,
               o.`unique_id` AS owner_unique_id,
               o.`title`     AS owner_title,
               s.`companion_id`,
               c.`unique_id` AS companion_unique_id,
               c.`title`     AS companion_title,
               s.`kind`,
               COUNT(*) AS exchange_count,
               SUM(s.`question` <> '') AS question_count,
               SUM(s.`answer` <> '') AS answer_count,
               SUM(s.`answer` <> '' AND s.`delivered_at` IS NULL)
                   AS undelivered_count,
               MAX(COALESCE(s.`question_at`, s.`answer_at`, s.`created_at`))
                   AS last_at
          FROM `companion_session` s
          JOIN `companion` o ON o.`id` = s.`owner_id`
          JOIN `companion` c ON c.`id` = s.`companion_id`
         WHERE 1=1
    """
    params = []

    if json_request.owner_id:
        sql += ' AND s.`owner_id` = %s'
        params.append(json_request.owner_id)

    if json_request.companion_id:
        sql += ' AND s.`companion_id` = %s'
        params.append(json_request.companion_id)

    kind = _kind_of(json_request.kind)

    if kind:
        sql += ' AND s.`kind` = %s'
        params.append(kind)

    sql += _delivered_condition(json_request.delivered)
    sql += """
         GROUP BY s.`owner_id`, o.`unique_id`, o.`title`,
                  s.`companion_id`, c.`unique_id`, c.`title`, s.`kind`
         ORDER BY last_at DESC
    """

    async with db:
        await db.execute(sql, tuple(params))

        return {'result': await db.fetchall()}


@router.get('/session/companion/kind/list')
async def session_companion_kind_list(
        request: Request,
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """Каналы разговора — чем заполнять отбор на странице.

    Returns:
        dict: `result` — `['chat', 'mail']`.

    ⚠ Ручка, а не два `<option>` в шаблоне: значения — `enum`-столбец `kind`, и
    единственный их хозяин — инструмент, который в таблицу пишет
    (`COMPANION_SESSION_KINDS`). Повтори их страница — появился бы третий
    канал, и разговоры этого канала просто не нашлись бы отбором.

    ⚠ Отдаём список каналов, а не те, что встретились в данных: пустой канал
    должен быть выбираемым — «почему здесь ничего нет» это тоже ответ.
    """
    return {'result': list(COMPANION_SESSION_KINDS)}


@router.post('/session/companion/messages')
async def session_companion_messages(
        request: Request,
        json_request: SessionCompanionMessagesRequest,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """Последние обмены разговора, старое сверху.

    Returns:
        dict: `result` — строки `companion_session` как есть: обе половины с
        их временем, `delivered_at`, `source_uid`, `request_uuid`, `id`.

    ## ⚠⚠ Неподтверждённый ответ показывается — в отличие от ленты агента

    `companion_session_rows` прячет ответ без `delivered_at`: агенту нельзя
    продолжать несказанное. Здесь наоборот — «что сочинили, но не отправили»
    и есть главный вопрос, с которым на эту страницу приходят. Поэтому отбор
    по доставке тут **выбор человека** (`delivered`), а не правило выдачи.

    ## ⚠ Берём последние, отдаём по возрастанию

    `ORDER BY … DESC LIMIT` забирает хвост разговора, `reversed` возвращает
    ему естественный порядок. Без первого взяли бы начало переписки вместо
    конца, без второго человек читал бы диалог снизу вверх.

    ## ⚠ Время, а не `id`

    Перенесённые обмены ложатся в базу позже, чем стоят в разговоре: тот же
    довод, что у индекса таблицы и у `companion_session_rows`.
    """
    sql = """
        SELECT s.`id`,
               s.`kind`,
               s.`question`,
               s.`question_at`,
               s.`answer`,
               s.`answer_at`,
               s.`delivered_at`,
               s.`source_uid`,
               s.`request_uuid`,
               s.`created_at`
          FROM `companion_session` s
         WHERE s.`owner_id` = %s AND s.`companion_id` = %s
    """
    params = [json_request.owner_id, json_request.companion_id]

    kind = _kind_of(json_request.kind)

    if kind:
        sql += ' AND s.`kind` = %s'
        params.append(kind)

    sql += _delivered_condition(json_request.delivered)
    sql += """
         ORDER BY COALESCE(s.`question_at`, s.`answer_at`, s.`created_at`) DESC,
                  s.`id` DESC
         LIMIT %s
    """
    params.append(max(1, min(int(json_request.limit or 0)
                             or SESSION_COMPANION_LIMIT,
                             SESSION_COMPANION_LIMIT_MAX)))

    async with db:
        await db.execute(sql, tuple(params))
        rows = await db.fetchall()

    return {'result': list(reversed(rows or []))}


def _kind_of(kind: str) -> str:
    """Канал из запроса или пустая строка, если фильтра нет.

    ⚠ Неизвестное значение считается «любой канал», а не ошибкой: отбор —
    удобство чтения, и 422 вместо списка разговоров тут несоразмерен.

    ⚠ Список каналов берётся у инструмента, который в таблицу пишет
    (`COMPANION_SESSION_KINDS`), а не повторяется здесь: разойдись они — и
    страница молча теряла бы новый канал.
    """
    channel = str(kind or '').strip().lower()

    return channel if channel in COMPANION_SESSION_KINDS else ''


def _delivered_condition(delivered: str) -> str:
    """Условие отбора по доставке — куском `WHERE` без параметров.

    `yes` — отметка стоит; `no` — **ответ сочинён, но отметки нет**; пусто или
    незнакомое — без отбора.

    ⚠ `no` смотрит и на `answer`: строка без нашего ответа (он написал дважды
    подряд) отметки не имеет и иметь не может, а в «не доставлено» она читалась
    бы как потерянная реплика.
    """
    choice = str(delivered or '').strip().lower()

    if choice == 'yes':
        return ' AND s.`delivered_at` IS NOT NULL'

    if choice == 'no':
        return " AND s.`answer` <> '' AND s.`delivered_at` IS NULL"

    return ''

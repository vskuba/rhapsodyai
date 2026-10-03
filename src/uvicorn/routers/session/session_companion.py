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

## ⚠⚠ Удаляется НАШ ОТВЕТ, а не строка и не разговор

Разговор целиком отсюда снести нельзя, и это не недоделка: разговор — **память
агента**, `companion_session_history` собирает из него ленту для промпта, и без
неё агент заговорит с человеком как с незнакомым — ровно та беда, от которой
таблицу и заводили.

Но и строку целиком не сносят. Строка — это **обмен**: его реплика и наш ответ
лежат в колонках одной записи. Ошибочно доставленным бывает наш ответ, а его
слова настоящие — снеси запись, и вместе с нашей ошибкой пропало бы то, что он
правда написал. Поэтому `DELETE /session/companion/{exchange_id}/answer`
помечает только нашу половину, и обмен читается как «он написал, мы смолчали»
— случай, который лента рисует прочерком.

## ⚠⚠ И даже половина не стирается: ставится отметка

`answer_deleted_at` (миграция `20261003212000`), сам текст остаётся в базе.
Решение «ответ лишний» принимает человек и может ошибиться, а разбирать потом
«что же там было написано» будет не по чему. Видимости это не меняет: ни один
читатель помеченное не берёт —

    companion_session_rows        лента в промпт агента (и `..._history` над ней)
    session_companion_messages    лента вкладки «Чат»
    session_companion_list        список разговоров и его счётчики

⚠ Условие у всех одно: `answer_deleted_at IS NULL`. Забыть его в одном месте —
это «на странице ответа нет, а модель его помнит», то есть ровно та беда, от
которой отметку и заводили.

Зачем вообще: ответ, доставленный по ошибке, ленту **портит**. Он уезжает в
промпт наравне с настоящими, и чем дальше, тем больше ответов модели опирается
на него.

Отсюда и устройство: право своё (`session_companion:delete`, не
`session:delete` — тем чистят журнал вызовов, а это память), поштучно, и в
интерфейсе спрашивается модальным окном, показывающим обе половины целиком.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
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

# Какие строки странице вообще видны.
#
# ⚠⚠ Обмен, у которого убрали наш ответ, а его реплики не было вовсе (инвайт,
# письмо, наша инициатива — две трети строк установки), показывать нечем: в нём
# не осталось ни одной видимой половины. Такие строки прячутся **до**
# группировки и до `LIMIT` — иначе счётчик разговора считал бы невидимое, а
# «показано 9 из 10» расходилось бы с лентой без всякой причины на экране.
#
# ⚠ Условие одно на список и на ленту: разойдись они, «в разговоре 3 обмена» и
# «в ленте пусто» означали бы разные отборы. Тот же довод, что у
# `_delivered_condition`.
SESSION_COMPANION_VISIBLE = (
    "(s.`question` <> '' OR s.`answer_deleted_at` IS NULL)")


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
    sql = f"""
        SELECT s.`owner_id`,
               o.`unique_id` AS owner_unique_id,
               o.`title`     AS owner_title,
               s.`companion_id`,
               c.`unique_id` AS companion_unique_id,
               c.`title`     AS companion_title,
               s.`kind`,
               COUNT(*) AS exchange_count,
               SUM(s.`question` <> '') AS question_count,
               -- ⚠ Убранный ответ не считается ни ответом, ни недоставленным:
               -- на странице его нет, и счётчик, который его помнит, читался бы
               -- как «ответов 9» над лентой с восемью.
               SUM(s.`answer` <> '' AND s.`answer_deleted_at` IS NULL)
                   AS answer_count,
               SUM(s.`answer` <> '' AND s.`answer_deleted_at` IS NULL
                   AND s.`delivered_at` IS NULL) AS undelivered_count,
               MAX(COALESCE(s.`question_at`, s.`answer_at`, s.`created_at`))
                   AS last_at
          FROM `companion_session` s
          JOIN `companion` o ON o.`id` = s.`owner_id`
          JOIN `companion` c ON c.`id` = s.`companion_id`
         WHERE {SESSION_COMPANION_VISIBLE}
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
    sql = f"""
        SELECT s.`id`,
               s.`kind`,
               s.`question`,
               s.`question_at`,
               -- ⚠⚠ Убранный ответ не уезжает со страницы ВООБЩЕ: ни текстом,
               -- ни временем, ни отметкой доставки. Текст остаётся в базе — на
               -- случай «а что там было» и разбора задним числом, — но страница
               -- его не показывает, иначе отметка не значила бы ничего.
               IF(s.`answer_deleted_at` IS NULL, s.`answer`, '') AS `answer`,
               IF(s.`answer_deleted_at` IS NULL, s.`answer_at`, NULL) AS `answer_at`,
               IF(s.`answer_deleted_at` IS NULL, s.`delivered_at`, NULL)
                   AS `delivered_at`,
               s.`source_uid`,
               s.`request_uuid`,
               s.`created_at`
          FROM `companion_session` s
         WHERE s.`owner_id` = %s AND s.`companion_id` = %s
           AND {SESSION_COMPANION_VISIBLE}
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


@router.delete('/session/companion/{exchange_id}/answer')
async def session_companion_answer_delete(
        request: Request,
        exchange_id: int,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_COMPANION_DELETE]))
):
    """Убирает из обмена НАШ ответ. Реплика собеседника остаётся.

    Returns:
        dict: `result` с `id` обмена, временем отметки (`answer_deleted_at`) и
        `row_hidden` — пропадёт ли со страницы вся строка (его реплики в обмене
        не было, и показывать больше нечего).

    ## ⚠⚠ Убирается половина, а не строка

    В таблице строка — это ОБМЕН: его реплика и наш ответ лежат в колонках
    одной записи (`question` против `answer`). Снести запись значило бы стереть
    заодно его слова, а они настоящие: ошибочно доставленным бывает **наш**
    ответ. Обмен после отметки читается как «он написал, мы смолчали» — лента
    такой случай знает и показывает прочерком.

    ## ⚠⚠ Текст остаётся в базе — стирается только видимость

    Ставится `answer_deleted_at`, сам `answer` не трогается. Решение «ответ
    лишний» принимает человек и может ошибиться, а разбирать потом «что же там
    было написано» будет не по чему. Поэтому читатели (`companion_session_rows`
    — лента в промпт, `session_companion_messages` и `session_companion_list` —
    страница) просто не берут помеченное: модель его не видит, человек на
    странице тоже, а в базе оно цело.

    Отсюда и `UPDATE` вместо `DELETE` даже в случае, когда его реплики в обмене
    не было (инвайт, письмо, наша инициатива — две трети строк установки).
    Такая строка со страницы исчезает целиком (`row_hidden`), но в таблице
    остаётся.

    ⚠ Нечего убирать — `404`: строки нет вовсе, нашего ответа в ней нет (он
    написал дважды подряд, агент смолчал) либо его уже убрали. «Убрали ноль, и
    всё хорошо» означало бы, что повторное нажатие выглядит как новая работа.

    ## ⚠ Сужения по роли нет — его не из чего сделать

    У `companion_session` агента нет (шапка модуля), поэтому ограничить правку
    «своими» агентами нечем: право `session_companion:delete` открывает все
    разговоры установки. В наборе по умолчанию его нет — не-админские роли
    получают только `session:view`.
    """
    async with db:
        await db.execute(
            'SELECT `question`, `answer`, `answer_deleted_at`'
            ' FROM `companion_session` WHERE `id` = %s', (exchange_id,))
        row = await db.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail='Обмен не найден')

        if str(row['answer'] or '') == '':
            raise HTTPException(status_code=404,
                                detail='В этом обмене нашего ответа нет')

        if row['answer_deleted_at'] is not None:
            raise HTTPException(status_code=404,
                                detail='Этот ответ уже убран')

        # Время ставит база, а не Python: у соседних отметок строки
        # (`delivered_at`, `created_at`) источник времени тот же, и два разных
        # разъехались бы на величину, которую потом не объяснить.
        await db.execute(
            'UPDATE `companion_session` SET `answer_deleted_at` = UTC_TIMESTAMP()'
            ' WHERE `id` = %s AND `answer_deleted_at` IS NULL', (exchange_id,))

        await db.execute(
            'SELECT `answer_deleted_at` FROM `companion_session` WHERE `id` = %s',
            (exchange_id,))
        stamped = await db.fetchone()

        await db.connection.commit()

    return {'result': {
        'id': exchange_id,
        'answer_deleted_at': stamped['answer_deleted_at'],
        # Со страницы такая строка пропадёт целиком: видимых половин в ней не
        # осталось. В базе она на месте — отсюда `hidden`, а не `removed`.
        'row_hidden': str(row['question'] or '') == '',
    }}


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

    ⚠⚠ Убранный ответ не попадает **ни в один** из двух отборов: его на странице
    нет вовсе. Иначе «доставленные» показывали бы обмены с прочерком вместо
    ответа — то есть отбор по доставке отвечал бы про текст, которого не видно.
    """
    choice = str(delivered or '').strip().lower()

    if choice == 'yes':
        return (' AND s.`delivered_at` IS NOT NULL'
                ' AND s.`answer_deleted_at` IS NULL')

    if choice == 'no':
        return (" AND s.`answer` <> '' AND s.`delivered_at` IS NULL"
                ' AND s.`answer_deleted_at` IS NULL')

    return ''

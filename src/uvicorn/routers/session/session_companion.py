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
`session:delete` — тем чистят журнал вызовов, а это память), и в интерфейсе
спрашивается модальным окном, показывающим обе половины целиком.

⚠ Ручек две, и правка у них одна и та же: поштучная
(`DELETE /session/companion/{id}/answer`) и пачкой по списку номеров
(`POST /session/companion/answer/delete`) — «убрать все ответы, которые видно
в разговоре», чтобы не щёлкать полсотни чипов подряд. Пачка не новый вид
правки: тот же `answer_deleted_at`, те же условия, тот же текст в базе.
Разговор ею тоже не сносится — реплики собеседника остаются все до одной.
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

# ⚠ Строк, скрытых от страницы целиком, здесь нет и не должно появиться.
#
# Был соблазн прятать обмен, у которого убрали наш ответ, а его реплики не было
# вовсе (инвайт, письмо — две трети строк установки): показывать в нём было
# нечего. Но страница рисует на месте убранного ответа «было удалено», то есть
# показывать есть что — и исчезай такие строки, человек видел бы одну свою
# правку пометкой, а другую пропажей строки, без всякой причины на экране.
#
# Прячет убранный ответ только **лента агента** (`companion_session_rows`): там
# скрывать надо, иначе модель продолжает разговор от сказанного по ошибке.
#
# ⚠⚠ Правило уже нарушали, и нарушил его ОТБОР, а не выдача: в
# `_delivered_condition` стояло `answer_deleted_at IS NULL`, и под «Доставлен»
# обмен с убранным ответом пропадал строкой — вместе с настоящим вопросом
# собеседника. Дописывая условие в отбор, помни: условие про НАШУ половину,
# применённое к строке, выкидывает и его половину тоже.


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


class SessionCompanionAnswerDeleteManyRequest(BaseModel):
    # Номера обменов — ровно те, что человек видел на экране.
    #
    # ⚠⚠ Пачка задаётся СПИСКОМ, а не тройкой разговора с отбором. Повтори
    # здесь условия выдачи — и «убрать всё показанное» означало бы «убрать всё,
    # что найдётся по тем же условиям СЕЙЧАС»: между открытием ленты и нажатием
    # в разговор успевает лечь новый обмен (их пишет инструмент, без участия
    # страницы), и он попал бы под правку, которой человек не видел.
    ids: list[int]


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
        `answer_count`, `undelivered_count`, `deleted_count`) и временем
        последней реплики (`last_at`).

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
               -- в ленте на его месте стоит пометка «было удалено», а не
               -- реплика, и счётчик, который его помнит, читался бы как
               -- «ответов 9» над лентой с восемью.
               --
               -- ⚠ `exchange_count` его при этом считает: строка из ленты не
               -- пропадает, и «показано 9 из 10» разошлось бы с экраном.
               SUM(s.`answer` <> '' AND s.`answer_deleted_at` IS NULL)
                   AS answer_count,
               SUM(s.`answer` <> '' AND s.`answer_deleted_at` IS NULL
                   AND s.`delivered_at` IS NULL) AS undelivered_count,
               -- Сколько наших ответов в разговоре убрано. Считается ПОД тем же
               -- отбором, что и остальные счётчики: под «Доставлен» это и есть
               -- ответ на «сколько доставленного мы убрали» — вопрос, с которым
               -- на отметку и смотрят.
               --
               -- ⚠ Условие тут одно (`IS NOT NULL`), без оглядки на `answer`:
               -- отметку ставят только там, где ответ был (`DELETE` отвечает
               -- `404` на пустой), и второе условие было бы ложным уточнением.
               SUM(s.`answer_deleted_at` IS NOT NULL) AS deleted_count,
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
        dict: `result` — строки `companion_session`: обе половины с их временем,
        `delivered_at`, `source_uid`, `request_uuid`, `id`. У убранного ответа
        вместо текста приходят `answer_deleted_at` и `answer_deleted_text`, а
        `delivered_at` остаётся настоящим.

    ## ⚠⚠ Убранный ответ приходит ОТДЕЛЬНЫМ полем, а не в `answer`

    Страница рисует на его месте «было удалено», а сам текст показывает
    подсказкой: решение «ответ лишний» принимает человек и имеет право
    посмотреть, что именно убрал. Но в `answer` этот текст класть нельзя —
    по нему страница считает «ответ есть», и убранный снова выглядел бы
    сказанным: вернулись бы и чип доставки, и чип удаления, и счётчик ответов.

    ⚠⚠ Ленту агента это **не** касается: `companion_session_rows` убранное не
    отдаёт вовсе и о подсказках не знает. Разница намеренная — человек
    разбирается в своей же правке, модель продолжает разговор.

    ## ⚠⚠ Обмен с убранным ответом из выдачи НЕ ВЫПАДАЕТ — ни под каким отбором

    Строка здесь — обмен, и реплика собеседника лежит в той же записи. Спрячь
    строку по нашей правке, и вместе с ней пропадёт его вопрос — настоящий,
    доставленный, к правке не относящийся (поймано на обмене #5018 под отбором
    «Доставлен»). Поэтому `answer_deleted_at` на отбор не влияет вовсе: разбор
    — у `_delivered_condition`.

    ⚠ Обмен, у которого убранный ответ был единственной половиной (инвайт,
    письмо — две трети строк установки), тоже приходит: его половина пуста, на
    нашей стоит «было удалено». Так видно, сколько доставленного мы убрали;
    пропади такие строки — это осталось бы не видно ничем.

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
               -- ⚠⚠ Убранный ответ уезжает отдельными полями, а не в `answer`.
               -- Страница рисует «было удалено» и кладёт текст в подсказку, но
               -- всё, что считается по `answer` (чип доставки, чип удаления,
               -- счётчик ответов), обязано видеть пусто: иначе убранный ответ
               -- снова выглядит сказанным.
               IF(s.`answer_deleted_at` IS NULL, s.`answer`, '') AS `answer`,
               IF(s.`answer_deleted_at` IS NULL, s.`answer_at`, NULL) AS `answer_at`,
               -- ⚠⚠ `delivered_at` у убранного ответа приходит КАК ЕСТЬ, в
               -- отличие от текста и времени сочинения. Отметка о доставке —
               -- запись о случившемся: собеседник ответ получил и прочёл, и
               -- наша правка убрала его из памяти агента, а не с его экрана.
               -- Обнули её здесь — и обмен, найденный отбором «Доставлен»,
               -- приходил бы без единого следа доставки, то есть страница не
               -- могла бы объяснить, почему эта строка в выдаче.
               --
               -- ⚠ Чипа «✓ доставлено» это не возвращает: он считается по
               -- `answer`, а тот пуст. Видно только время в левом столбце —
               -- «когда это увидел собеседник», ровно то, на что столбец и
               -- отвечает у обеих половин.
               s.`delivered_at`,
               s.`answer_deleted_at`,
               IF(s.`answer_deleted_at` IS NULL, '', s.`answer`)
                   AS `answer_deleted_text`,
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


@router.delete('/session/companion/{exchange_id}/answer')
async def session_companion_answer_delete(
        request: Request,
        exchange_id: int,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_COMPANION_DELETE]))
):
    """Убирает из обмена НАШ ответ. Реплика собеседника остаётся.

    Returns:
        dict: `result` с `id` обмена и временем отметки (`answer_deleted_at`).

    ## ⚠⚠ Убирается половина, а не строка

    В таблице строка — это ОБМЕН: его реплика и наш ответ лежат в колонках
    одной записи (`question` против `answer`). Снести запись значило бы стереть
    заодно его слова, а они настоящие: ошибочно доставленным бывает **наш**
    ответ.

    ## ⚠⚠ Текст остаётся в базе — убирается только участие в разговоре

    Ставится `answer_deleted_at`, сам `answer` не трогается, и читатели
    расходятся:

        companion_session_rows        НЕ отдаёт убранное вовсе — модель
                                      продолжала бы разговор от сказанного по
                                      ошибке, ради этого отметку и завели
        session_companion_messages    отдаёт отдельными полями: страница рисует
                                      «было удалено», текст кладёт в подсказку
        session_companion_list        не считает убранное ответом

    Расхождение намеренное: человек разбирается в своей же правке и имеет право
    посмотреть, что убрал; модели этого знать не нужно.

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
    }}


@router.post('/session/companion/answer/delete')
async def session_companion_answer_delete_many(
        request: Request,
        json_request: SessionCompanionAnswerDeleteManyRequest,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_COMPANION_DELETE]))
):
    """Убирает НАШИ ответы сразу у пачки обменов. Реплики собеседника остаются.

    Args:
        json_request: `ids` — номера обменов, ровно те, что показаны человеку.

    Returns:
        dict: `result` с `deleted` (сколько отметок легло) и `skipped`
        (сколько номеров отметки не получили — ответа в них нет либо он уже
        убран).

    ## ⚠⚠ Это та же правка, что поштучная, а не «очистить переписку»

    Разговор остаётся: его реплики не трогаются, строки не сносятся, тексты
    наших ответов лежат в базе под отметкой. Разница с чипом в строке —
    только в числе обменов за одно нажатие. Довод, по которому разговор
    целиком снести нельзя, — в шапке модуля, и он в силе.

    ⚠⚠ Для памяти агента пачка тем не менее тяжелее поштучного: ушедшие
    ответы пропадают из `companion_session_rows`, и лента в промпте становится
    «он говорил — мы молчали». Поэтому страница спрашивает окном, где
    перечислено каждое, что уйдёт, и названо число.

    ## ⚠ Список, а не отбор

    Ручка берёт номера, а не тройку разговора с условиями: между тем, как
    человек посмотрел ленту, и нажатием в разговор успевает лечь новый обмен
    (их пишет инструмент, страницу не спрашивая). Повтори здесь условия
    выдачи — и под правку попало бы то, чего на экране не было.

    ## ⚠ Чего убрать не вышло — не ошибка, а число

    В отличие от поштучной ручки (та отвечает `404` на «уже убрано»: повторное
    нажатие не должно выглядеть новой работой), здесь пропуски обычны —
    обмен без нашего ответа, уже убранный ответ, строка, которую успели
    удалить. Отказывать всей пачке из-за одного такого значило бы требовать от
    страницы повторять отбор сервера.

    ⚠ Одним `UPDATE`, а не циклом по номерам: условия те же, что у поштучной
    (`answer <> ''`, `answer_deleted_at IS NULL`), и отметка у всей пачки
    обязана быть одним временем — иначе «убрано тогда-то» у соседних строк
    разъедется на доли секунды без всякой причины.
    """
    ids = sorted({int(one) for one in json_request.ids if int(one) > 0})

    if not ids:
        raise HTTPException(status_code=400, detail='Список обменов пуст')

    # Потолок тот же, что у выдачи: пачка приходит из показанного, а показать
    # больше нельзя. Защищает не базу, а от «прилетел чужой список на полтаблицы».
    if len(ids) > SESSION_COMPANION_LIMIT_MAX:
        raise HTTPException(
            status_code=400,
            detail=f'За раз можно убрать не больше'
                   f' {SESSION_COMPANION_LIMIT_MAX} ответов')

    async with db:
        await db.execute(
            'UPDATE `companion_session`'
            ' SET `answer_deleted_at` = UTC_TIMESTAMP()'
            f' WHERE `id` IN ({", ".join(["%s"] * len(ids))})'
            " AND `answer` <> '' AND `answer_deleted_at` IS NULL",
            tuple(ids))
        deleted = int(db.rowcount or 0)

        await db.connection.commit()

    return {'result': {'deleted': deleted, 'skipped': len(ids) - deleted}}


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

    ## ⚠⚠ Про убранный ответ отбор НЕ СПРАШИВАЕТ — и спрашивать не должен

    Сперва здесь стояло `AND s.answer_deleted_at IS NULL` в обеих ветках, по
    доводу «убранного на странице нет, незачем его и отбирать». Довод оказался
    неверен дважды.

    Во-первых, отметка ничего не отменяет в прошлом: ответ **был доставлен**,
    собеседник его прочёл, и `delivered_at` — запись о случившемся. Убрали мы
    его из памяти агента, а не с его экрана. Отбор «Доставлен», прячущий
    доставленное, отвечает не на свой вопрос.

    Во-вторых — и это хуже — условие прячет **строку**, а строка это обмен.
    Воспроизведено: у обмена #5018 убрали наш ответ, и под «Доставлен» вместе с
    ним пропал вопрос собеседника «which city do you live in?» — реплика
    настоящая, доставленная, к нашей правке не относящаяся. Ровно то, что
    шапка этого модуля запрещает: строк, скрытых от страницы целиком, здесь
    нет.

    ⚠ Поэтому убранный ответ попадает в тот отбор, которому отвечает его
    `delivered_at`: доставленный — в «Доставлен», сочинённый и не отправленный
    — в «Не доставлен». На странице он при этом остаётся пометкой «было
    удалено» (текст и оба времени — подсказкой), так что «сколько доставленного
    мы убрали» считается глазами по ленте, а не догадкой.
    """
    choice = str(delivered or '').strip().lower()

    if choice == 'yes':
        return ' AND s.`delivered_at` IS NOT NULL'

    if choice == 'no':
        return " AND s.`answer` <> '' AND s.`delivered_at` IS NULL"

    return ''

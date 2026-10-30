"""Ручки намерений пары: страница «Сессии», вкладка «Намерения».

Намерение — то, что агент пообещал или заметил за собеседником, одним словом:
`she_promised_send_photo`. Кладёт их инструмент
`src/tool/companion/companion_intention.py`, этот роутер только читает.

## ⚠⚠ Зачем вкладка, если намерение видно в трассе прогона

Трасса отвечает на вопрос «что сделал **этот** прогон», а намерение живёт
дольше прогона: по нему следующий ответ отличит новое обещание от уже
найденного. Вопросы к нему другие — «какие обещания за парой накопились»,
«когда это началось», «не застряло ли одно и то же». В трассе на такой вопрос
отвечать пришлось бы, открывая прогоны по одному.

## ⚠⚠ Отметка времени — не украшение ленты, а рабочее значение

`companion_intention_at_get` режет ею историю разговора надвое: модель ищет
новое намерение только в свежей половине. Поэтому в ленте время стоит у каждой
записи, а не сворачивается в «сегодня» — человек, пришедший разбираться, почему
обещание приехало дважды, смотрит именно на него.

## ⚠ Отбор по роли здесь тот же, что у «Чата», — то есть никакой

У `companion_intention` агента нет, как и у `companion_session`: сузить выдачу
не по чему. Право `session:view` открывает все намерения всем, кто его имеет.
Разбор целиком — `session_companion.py`, шапка.
"""

from fastapi import APIRouter, Depends, Request
from mysql_.mysql_ import mysql_get_db_async
from pydantic import BaseModel, Field

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# Сколько записей отдаём лентой за раз. ⚠ Потолок есть и у довода, и здесь:
# довод приходит со страницы, а страницу открывает кто угодно с правом.
SESSION_INTENTION_LIMIT_DEFAULT = 200
SESSION_INTENTION_LIMIT_MAX = 1000


class SessionIntentionListRequest(BaseModel):
    """Отбор пар. Пусто в поле — «любой»."""

    owner_unique_id: str = Field('', max_length=190)
    companion_unique_id: str = Field('', max_length=190)
    intention: str = Field('', max_length=100)


class SessionIntentionRowsRequest(BaseModel):
    """Отбор ленты. ⚠ Пара обязательна: лента принадлежит паре."""

    owner_unique_id: str = Field(..., min_length=1, max_length=190)
    companion_unique_id: str = Field(..., min_length=1, max_length=190)
    intention: str = Field('', max_length=100)
    limit: int = Field(SESSION_INTENTION_LIMIT_DEFAULT, ge=1,
                       le=SESSION_INTENTION_LIMIT_MAX)


@router.post('/session/intention/list')
async def session_intention_list(
        request: Request,
        json_request: SessionIntentionListRequest,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """Пары, за которыми есть намерения: строка на пару, свежие сверху.

    Returns:
        dict: `result` — список строк с ключами и подписями обеих сторон,
        числом намерений (`intention_count`), числом **разных** намерений
        (`intention_kinds`) и временем последнего (`last_at`).

    ## ⚠ Пара, а не тройка с каналом

    У разговоров группировка идёт по тройке «мы, он, канал» — чат и почта одной
    пары ведутся врозь. У намерений канала нет и быть не должно: обещание
    прислать фото, данное письмом, остаётся тем же обещанием в чате. Раздели мы
    их, одно намерение двоилось бы по каналам и дедупликация следующего прогона
    читала бы половину своей истории.

    ## ⚠ Ключи и подписи сторон в `GROUP BY`, а не в `MAX()`

    Тот же довод, что у соседней ручки: под `ONLY_FULL_GROUP_BY` (на установке
    выключен, на соседней может быть включён) запрос с ними «в воздухе»
    отвергается целиком, а `MAX()` выглядел бы «последним значением», им не
    являясь.
    """
    where = ['1 = 1']
    params = []

    if json_request.owner_unique_id:
        where.append('o.`unique_id` = %s')
        params.append(json_request.owner_unique_id)

    if json_request.companion_unique_id:
        where.append('c.`unique_id` = %s')
        params.append(json_request.companion_unique_id)

    if json_request.intention:
        where.append('i.`intention` = %s')
        params.append(json_request.intention)

    async with db:
        await db.execute(
            'SELECT o.`unique_id` AS owner_unique_id, o.`title` AS owner_title,'
            '       c.`unique_id` AS companion_unique_id,'
            '       c.`title` AS companion_title,'
            '       COUNT(*) AS intention_count,'
            '       COUNT(DISTINCT i.`intention`) AS intention_kinds,'
            '       MAX(i.`created_at`) AS last_at'
            '  FROM `companion_intention` i'
            '  JOIN `companion` o ON o.`id` = i.`owner_id`'
            '  JOIN `companion` c ON c.`id` = i.`companion_id`'
            f' WHERE {" AND ".join(where)}'
            ' GROUP BY o.`unique_id`, o.`title`, c.`unique_id`, c.`title`'
            ' ORDER BY last_at DESC', params)

        return {'result': [_row_said(row) for row in await db.fetchall() or []]}


@router.post('/session/intention/rows')
async def session_intention_rows(
        request: Request,
        json_request: SessionIntentionRowsRequest,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """Лента намерений пары: строка на запись, свежие сверху.

    Returns:
        dict: `result` — список записей (`id`, `intention`, `created_at`) и
        `kinds` — сводка по видам намерений этой пары: `intention`, `count`,
        `first_at`, `last_at`.

    ## ⚠⚠ Сводка по видам считается ОТДЕЛЬНЫМ запросом, а не из ленты

    Лента обрезана `limit`, сводка — нет. Посчитай мы виды по отданным строкам,
    число «за парой 28 обещаний» молча означало бы «28 из показанных двухсот»,
    и на длинной истории сводка врала бы тем сильнее, чем интереснее случай.

    ⚠ Сводка не зависит и от отбора по виду: она отвечает на вопрос «что вообще
    за этой парой», а сузив её тем же `intention`, мы получили бы строку,
    повторяющую отбор.
    """
    where = ['o.`unique_id` = %s', 'c.`unique_id` = %s']
    params = [json_request.owner_unique_id, json_request.companion_unique_id]

    if json_request.intention:
        where.append('i.`intention` = %s')
        params.append(json_request.intention)

    async with db:
        await db.execute(
            'SELECT i.`id`, i.`intention`, i.`created_at`'
            '  FROM `companion_intention` i'
            '  JOIN `companion` o ON o.`id` = i.`owner_id`'
            '  JOIN `companion` c ON c.`id` = i.`companion_id`'
            f' WHERE {" AND ".join(where)}'
            ' ORDER BY i.`created_at` DESC, i.`id` DESC'
            ' LIMIT %s', [*params, json_request.limit])

        rows = [{'id': int(row['id']), 'intention': str(row['intention'] or ''),
                 'created_at': _stamp(row.get('created_at'))}
                for row in await db.fetchall() or []]

        await db.execute(
            'SELECT i.`intention`, COUNT(*) AS `count`,'
            '       MIN(i.`created_at`) AS first_at,'
            '       MAX(i.`created_at`) AS last_at'
            '  FROM `companion_intention` i'
            '  JOIN `companion` o ON o.`id` = i.`owner_id`'
            '  JOIN `companion` c ON c.`id` = i.`companion_id`'
            ' WHERE o.`unique_id` = %s AND c.`unique_id` = %s'
            ' GROUP BY i.`intention` ORDER BY `count` DESC, last_at DESC',
            [json_request.owner_unique_id, json_request.companion_unique_id])

        kinds = [{'intention': str(row['intention'] or ''),
                  'count': int(row['count'] or 0),
                  'first_at': _stamp(row.get('first_at')),
                  'last_at': _stamp(row.get('last_at'))}
                 for row in await db.fetchall() or []]

    return {'result': {'rows': rows, 'kinds': kinds}}


@router.get('/session/intention/kind/list')
async def session_intention_kind_list(
        request: Request,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.SESSION_VIEW]))
):
    """Виды намерений, встречающиеся в базе, — для отбора на странице.

    Returns:
        dict: `result` — список `{intention, count}`, частые сверху.

    ⚠ Отдельная ручка, а не разбор `list`: отбор по виду не должен зависеть от
    того, что сейчас выбрано в соседних отборах, иначе выбранный вид исчезал бы
    из списка, стоило сузить пару.
    """
    async with db:
        await db.execute(
            'SELECT `intention`, COUNT(*) AS `count`'
            '  FROM `companion_intention`'
            ' GROUP BY `intention` ORDER BY `count` DESC, `intention`')

        return {'result': [{'intention': str(row['intention'] or ''),
                            'count': int(row['count'] or 0)}
                           for row in await db.fetchall() or []]}


# ── Приватное ────────────────────────────────────────────────────────────────

def _row_said(row) -> dict:
    """Строка списка пар наружу: числа числами, время строкой."""
    return {
        'owner_unique_id': str(row['owner_unique_id'] or ''),
        'owner_title': str(row['owner_title'] or ''),
        'companion_unique_id': str(row['companion_unique_id'] or ''),
        'companion_title': str(row['companion_title'] or ''),
        'intention_count': int(row['intention_count'] or 0),
        'intention_kinds': int(row['intention_kinds'] or 0),
        'last_at': _stamp(row.get('last_at')),
    }


def _stamp(value) -> str:
    """Время в ISO для страницы; пусто — пустая строка.

    ⚠ Отдаём как есть, без пояса: в поясе настройки его покажет `fmtTz` на
    странице, и перевод здесь был бы вторым местом, знающим про `timezone`
    (`datetime_rules.md`).
    """
    return value.isoformat(sep=' ') if value else ''

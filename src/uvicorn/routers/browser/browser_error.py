"""Журнал ошибок браузера: что сломалось, где и при каких обстоятельствах.

Ошибку живого окна видит только тот, кто в этот момент смотрит в строку
состояния: сокет показал её и забыл. Разбираться потом было не с чем —
приходилось воспроизводить наугад. Здесь ошибки остаются с контекстом: адрес
страницы, сессия, действие, селектор, номер шага.

Пишет `uvicorn`, а не контейнер: базы у контейнера нет и не будет. Ошибки живого
окна ловит прокси вебсокета по дороге к клиенту (`browser_proxy`), сбои обращений
к контейнеру — `browser_upstream`, а `POST /api/browser/error` открыт странице:
её собственный сбой (не разобрался JSON, отвалился запрос) видно только ей.

Чистка ручная (`DELETE /api/browser/error`), TTL нет: журнал маленький, а
«само удалилось перед тем, как я посмотрел» — худшее свойство для отладки.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.uvicorn.routers.browser.browser_error_tag import (BROWSER_ERROR_TAG_RULES,
                                                           browser_error_tags,
                                                           browser_error_tags_list)

router = APIRouter(prefix='/api/browser/error', tags=['browser'])

# Сколько ошибок отдаём страницей. Больше сотни за раз никто не читает, а вкладка
# на них заметно тяжелеет.
BROWSER_ERROR_PAGE = 100

# Текст ошибки бывает со стеком на сотню строк: в списке он всё равно не читается,
# а место занимает. Полное сообщение остаётся в логах контейнера.
BROWSER_ERROR_MESSAGE_MAX = 2000
BROWSER_ERROR_URL_MAX = 1000
BROWSER_ERROR_SOURCE_MAX = 50


class BrowserErrorSave(BaseModel):
    """Тело записи ошибки. Страница шлёт своё, сервер — своё, форма одна."""

    source: str = Field('page', max_length=BROWSER_ERROR_SOURCE_MAX,
                        description='Откуда: view, scenario, workflow, proxy, page')
    message: str = Field(..., min_length=1, max_length=BROWSER_ERROR_MESSAGE_MAX)
    session_id: str = Field('', max_length=32)
    site_id: int | None = Field(None, description='Сайт из browser_site, если известен')
    url: str = Field('', max_length=BROWSER_ERROR_URL_MAX)
    context: dict = Field(default_factory=dict, description='Что делали: действие, селектор, шаг')


class BrowserErrorResponse(BaseModel):
    """Строка журнала."""

    id: int = Field(..., description='Идентификатор записи', examples=[12])
    source: str = Field(..., description='Откуда пришла ошибка', examples=['view'])
    message: str = Field(..., description='Текст ошибки',
                         examples=["float() argument must be a string or a real number, not 'NoneType'"])
    session_id: str = Field('', description='Сессия контейнера, если ошибка из живого окна')
    site_id: int | None = Field(None, description='Сайт, на котором случилась ошибка')
    site_name: str = Field('', description='Имя сайта из справочника; пусто — сайт удалён или неизвестен')
    tags: list[str] = Field(default_factory=list, description='Род ошибки: auth, timeout, network…')
    url: str = Field('', description='Адрес страницы на момент ошибки')
    context: dict = Field(default_factory=dict, description='Обстоятельства: действие, селектор, шаг')
    created_at: datetime | None = Field(None, description='Когда записана')


class BrowserErrorListResponse(BaseModel):
    result: list[BrowserErrorResponse] = Field(..., description='Ошибки, свежие сверху')

    model_config = ConfigDict(
        json_schema_extra={
            'example': {
                'result': [
                    {
                        'id': 12,
                        'source': 'view',
                        'message': "float() argument must be a string or a real number, not 'NoneType'",
                        'session_id': 'd1978340390a',
                        'url': 'https://example.com/',
                        'context': {'action': 'wheel', 'dx': None},
                        'created_at': '2026-08-15T20:31:04',
                    }
                ]
            }
        }
    )


@router.get(
    '',
    response_model=BrowserErrorListResponse,
    summary='Получить журнал ошибок браузера',
    description='Ошибки живого окна, сценариев и обращений к контейнеру-браузеру, свежие '
                'сверху. Нужна сессия админки или заголовок `X-API-KEY` с токеном доступа '
                'пользователя, имеющего право `BROWSER_VIEW`.',
    response_description='Успешный ответ со списком ошибок',
)
async def browser_error_list(limit: int = BROWSER_ERROR_PAGE, source: str = '',
                             site_id: int = 0, tag: str = '',
                             user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """
    Журнал, свежие сверху.

    Сужается тремя признаками, и они про разное: `source` — кто прислал, `site_id` — где
    случилось, `tag` — что за род сбоя. Пустые не сужают.

    Имя сайта тянем из справочника соединением, а не вторым запросом на строку: журнал
    отдаётся сотней записей, и сотня запросов ради подписи — это сотня лишних походов в
    базу. `LEFT JOIN`, потому что сайт мог быть удалён, а ошибка на нём осталась: строка
    от этого не исчезает, просто имя пустое.
    """
    limit = max(1, min(int(limit or BROWSER_ERROR_PAGE), BROWSER_ERROR_PAGE))
    where, params = [], []
    if source.strip():
        where.append('e.source = %s')
        params.append(source.strip()[:BROWSER_ERROR_SOURCE_MAX])
    if int(site_id or 0):
        where.append('e.site_id = %s')
        params.append(int(site_id))
    if tag.strip():
        # Тег сверяем со списком разметчика, а не берём как есть. Список закрытый
        # (`BROWSER_ERROR_TAG_RULES`), чипсы на странице шлют только его значения, а
        # `%` и `_` в шаблоне `LIKE` значат «что угодно»: запрос `?tag=%` отдавал весь
        # журнал вместо пустого ответа. Неизвестный тег даёт пустую выборку, а не тихо
        # снятый фильтр: человек просил сузить, и показать ему всё было бы враньём.
        #
        # Обрамляющие запятые — часть формата хранения: без них `,net,` нашёлся бы
        # внутри `,network,` и фильтр показывал бы чужой род ошибок.
        if tag.strip() in BROWSER_ERROR_TAG_RULES:
            where.append('e.tags LIKE %s')
            params.append(f'%,{tag.strip()},%')
        else:
            where.append('1 = 0')

    sql = ('SELECT e.id, e.source, e.message, e.session_id, e.site_id, e.url, e.context, '
           '       e.tags, e.created_at, COALESCE(s.name, \'\') AS site_name '
           '  FROM browser_error e '
           '  LEFT JOIN browser_site s ON s.id = e.site_id')
    if where:
        sql += ' WHERE ' + ' AND '.join(where)

    async with mysql_get_db_async() as db:
        await db.execute(f'{sql} ORDER BY e.id DESC LIMIT {limit}', tuple(params))
        rows = await db.fetchall()

    for row in rows or []:
        row['context'] = _context_load(row.get('context'))
        row['tags'] = browser_error_tags_list(row.get('tags'))

    return {'result': rows}


@router.post('', status_code=201, include_in_schema=False)
async def browser_error_create(data: BrowserErrorSave,
                               user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Записывает ошибку. Открыт странице админки и клиентам — соседним проектам.

    Право на запись то же, что на чтение (`BROWSER_VIEW`): это журнал для отладки,
    а не действие над данными, и тот, кто видит ошибку, должен уметь её сохранить.

    **Кто сообщил — пишем сами, а не берём из тела.** Учётка приходит из сессии, и
    подделать её в запросе нельзя. Без неё журнал клиентских ошибок отвечал на
    «что сломалось», но не на «у кого»: `source` клиент ставит себе сам, и два проекта
    вполне могут прислать одно и то же слово. Разбор чужого сбоя начинается с вопроса,
    чей он.
    """
    context = dict(data.context or {})
    context['reported_by'] = getattr(user, 'username', '') or ''

    await browser_error_write(data.source, data.message, data.session_id, data.url, context,
                              site_id=data.site_id)

    return {'status': 'success'}


@router.delete('', include_in_schema=False)
async def browser_error_clear(user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Чистит журнал целиком — разобрались и убрали."""
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM browser_error')
        await db.connection.commit()

    return {'status': 'success'}


async def browser_error_write(source: str, message: str, session_id: str = '',
                              url: str = '', context: dict | None = None,
                              site_id: int | None = None) -> None:
    """Кладёт ошибку в журнал. Не бросает: сбой журнала не должен ронять работу.

    Это правило общее для всей журналистики проекта (`observability_rules.md`):
    упавшая запись в журнал превращает одну понятную ошибку в две непонятных.

    Сайт берём из довода, а если его не дали — из `context.site_id`: так его слали
    клиенты, пока колонки не было, и терять уже налаженное незачем.

    Теги ставим сами по тексту (`browser_error_tags`). Просить клиента размечать свои
    ошибки бесполезно: соседний проект шлёт то, что у него упало, и лишнего поля не
    заполнит — а без разметки журнал в тысячи строк читается только подряд.
    """
    context = context or {}
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'INSERT INTO browser_error '
                '       (source, message, session_id, site_id, url, context, tags) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (str(source or 'page')[:BROWSER_ERROR_SOURCE_MAX],
                 str(message or '')[:BROWSER_ERROR_MESSAGE_MAX],
                 str(session_id or '')[:32],
                 _site_id_of(site_id, context),
                 str(url or '')[:BROWSER_ERROR_URL_MAX],
                 json.dumps(context, ensure_ascii=False, default=str),
                 browser_error_tags(message, source)))
            await db.connection.commit()
    except Exception as e:
        logger_info(f'[browser] ошибка не записалась в журнал: {e}')


def _site_id_of(site_id, context: dict):
    """
    Номер сайта: из довода, иначе из `context.site_id`. Нет или не число — `None`.

    Терпимо к типу: клиенты кладут в контекст что придётся, и строка «19» значит то же
    самое, что число. А `main` — уже не номер, и в колонку `INT` он молча превратился бы
    в ноль, то есть в несуществующий сайт.
    """
    for value in (site_id, (context or {}).get('site_id')):
        text = str(value if value is not None else '').strip()
        if text.isdigit() and int(text):
            return int(text)

    return None


def _context_load(value):
    """JSON-столбец приезжает то структурой, то строкой — зависит от драйвера."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}

    return value if isinstance(value, dict) else {}

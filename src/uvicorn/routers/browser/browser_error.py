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
    url: str = Field('', max_length=BROWSER_ERROR_URL_MAX)
    context: dict = Field(default_factory=dict, description='Что делали: действие, селектор, шаг')


class BrowserErrorResponse(BaseModel):
    """Строка журнала."""

    id: int = Field(..., description='Идентификатор записи', examples=[12])
    source: str = Field(..., description='Откуда пришла ошибка', examples=['view'])
    message: str = Field(..., description='Текст ошибки',
                         examples=["float() argument must be a string or a real number, not 'NoneType'"])
    session_id: str = Field('', description='Сессия контейнера, если ошибка из живого окна')
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
                             user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Журнал, свежие сверху. `source` сужает выборку до одного происхождения."""
    limit = max(1, min(int(limit or BROWSER_ERROR_PAGE), BROWSER_ERROR_PAGE))
    where, params = '', []
    if source.strip():
        where = ' WHERE source = %s'
        params.append(source.strip()[:BROWSER_ERROR_SOURCE_MAX])

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, source, message, session_id, url, context, created_at '
            f'FROM browser_error{where} ORDER BY id DESC LIMIT {limit}', tuple(params))
        rows = await db.fetchall()

    for row in rows or []:
        row['context'] = _context_load(row.get('context'))

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

    await browser_error_write(data.source, data.message, data.session_id, data.url, context)

    return {'status': 'success'}


@router.delete('', include_in_schema=False)
async def browser_error_clear(user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Чистит журнал целиком — разобрались и убрали."""
    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM browser_error')
        await db.connection.commit()

    return {'status': 'success'}


async def browser_error_write(source: str, message: str, session_id: str = '',
                              url: str = '', context: dict | None = None) -> None:
    """Кладёт ошибку в журнал. Не бросает: сбой журнала не должен ронять работу.

    Это правило общее для всей журналистики проекта (`observability_rules.md`):
    упавшая запись в журнал превращает одну понятную ошибку в две непонятных.
    """
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'INSERT INTO browser_error (source, message, session_id, url, context) '
                'VALUES (%s, %s, %s, %s, %s)',
                (str(source or 'page')[:BROWSER_ERROR_SOURCE_MAX],
                 str(message or '')[:BROWSER_ERROR_MESSAGE_MAX],
                 str(session_id or '')[:32],
                 str(url or '')[:BROWSER_ERROR_URL_MAX],
                 json.dumps(context or {}, ensure_ascii=False, default=str)))
            await db.connection.commit()
    except Exception as e:
        logger_info(f'[browser] ошибка не записалась в журнал: {e}')


def _context_load(value):
    """JSON-столбец приезжает то структурой, то строкой — зависит от драйвера."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}

    return value if isinstance(value, dict) else {}

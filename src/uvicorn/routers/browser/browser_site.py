"""Сайты — закладки контейнера-браузера: имя и адрес.

Список того, с чем работают: личный кабинет, чужая админка, стенд. Карточка
сайта на `/admin/browser` заводит сессию прямо на его адрес — до этого адрес
приходилось помнить или искать в истории живого окна.

Хранится в `uvicorn`, а не в контейнере: у контейнера базы нет и не будет, а
закладка обязана пережить и его рестарт, и падение. Вход в сайт (cookie,
`storage_state`) здесь не лежит — это состояние сессии со своим сроком жизни.

Адрес требуется со схемой, как и у REST-создания сессии: угаданный `https://`
скрыл бы опечатку программы, а закладку заводят один раз и открывают потом сотни.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mysql_.mysql_ import mysql_get_db_async

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.browser.site_repository import BrowserSiteRepository

router = APIRouter(prefix='/api/browser/site', tags=['browser'])

# Схемы, которые умеет открыть Chromium сессии. `file://` и `data:` не берём:
# первая ведёт в файловую систему контейнера, вторая даёт opaque-origin страницу,
# на которой обработчики ведут себя не так, как на настоящем сайте.
BROWSER_SITE_SCHEMES = ('http://', 'https://')


class BrowserSiteSave(BaseModel):
    """Тело создания и правки карточки сайта."""

    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=500)

    @field_validator('name', 'url')
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()

    @field_validator('url')
    @classmethod
    def _scheme(cls, value: str) -> str:
        if not value.startswith(BROWSER_SITE_SCHEMES):
            raise ValueError('адрес должен начинаться с http:// или https://')

        return value


class BrowserSiteResponse(BaseModel):
    """Карточка сайта в списке."""

    id: int = Field(..., description='Идентификатор сайта', examples=[19])
    name: str = Field(..., description='Название закладки', examples=['Goldenbride'])
    url: str = Field(..., description='Полный адрес со схемой', examples=['https://goldenbride.net/'])
    position: int = Field(..., description='Порядок в раскладке карточек; список отсортирован по нему',
                          examples=[1])
    created_at: datetime | None = Field(None, description='Когда заведена')
    updated_at: datetime | None = Field(None, description='Когда правилась последний раз')


class BrowserSiteListResponse(BaseModel):
    result: list[BrowserSiteResponse] = Field(..., description='Сайты в порядке раскладки')

    model_config = ConfigDict(
        json_schema_extra={
            'example': {
                'result': [
                    {
                        'id': 19,
                        'name': 'Goldenbride',
                        'url': 'https://goldenbride.net/',
                        'position': 1,
                        'created_at': '2026-08-15T13:10:26',
                        'updated_at': '2026-08-15T13:11:46',
                    }
                ]
            }
        }
    )


class BrowserSiteOrder(BaseModel):
    """Новый порядок карточек: id сверху вниз."""

    ids: list[int] = Field(..., min_length=1)


@router.get(
    '',
    response_model=BrowserSiteListResponse,
    summary='Получить список сайтов контейнера-браузера',
    description='Возвращает закладки — имя и адрес того, с чем работает браузер, — '
                'в порядке раскладки карточек на `/admin/browser`. '
                'Нужна сессия админки или заголовок `X-API-KEY` с токеном доступа '
                'пользователя, имеющего право `BROWSER_VIEW`.',
    response_description='Успешный ответ со списком сайтов',
)
async def browser_site_list(user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Все сайты в порядке раскладки — карточки и селекты идут тем же порядком.

    Сортировка по `position`, а `id` — только чтобы порядок был определён у
    карточек с одинаковой позицией (так лягут все, если раскладку ещё не трогали).
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, name, url, position, created_at, updated_at '
            'FROM browser_site ORDER BY position, id'
        )
        rows = await db.fetchall()

    return {'result': rows}


@router.get('/{site_id}', include_in_schema=False)
async def browser_site_get(site_id: int,
                           user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Карточка сайта целиком, вместе с настройкой присутствия (`presence`).

    Отдельно от списка, потому что `presence` — это простыня: адреса ручек сайта,
    заготовки GWT-запросов, имена сценариев по ролям. В списке, который рисует
    селекты и карточки, она была бы мёртвым грузом на каждой строке.

    Наружу нужна тем, кто работает с сайтом, а карточками не управляет: DatingAi
    берёт отсюда, чем опрашивать присутствие анкеты и каким кадром слать сообщение.
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, name, url, presence, position, created_at, updated_at '
                         '  FROM browser_site WHERE id = %s', (int(site_id),))
        row = await db.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f'сайта #{site_id} нет')

    return {'result': row}


@router.post('', status_code=201, include_in_schema=False)
async def browser_site_create(data: BrowserSiteSave,
                              user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Заводит карточку сайта. Занятое имя — 409, а не молчаливый второй такой же.

    Новая карточка встаёт в конец: первым идёт то, что человек туда положил, и
    заведение сайта не должно менять его выбор в селектах соседних вкладок.
    """
    try:
        site_id = await BrowserSiteRepository().add({
            'name': data.name, 'url': data.url, 'position': await _position_next()})
    except Exception as e:
        raise HTTPException(status_code=409, detail=_save_error(e, data.name))

    return {'result': site_id}


@router.post('/order', include_in_schema=False)
async def browser_site_order(data: BrowserSiteOrder,
                             user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Раскладка карточек мышью: список id в новом порядке.

    Позиции переписываются целиком по присланному списку, а не сдвигаются по
    одной: страница и так знает весь порядок, а частичные сдвиги оставляли бы
    дыры и совпадения при каждом втором перетаскивании.

    Чужие и уже удалённые id просто не найдутся и ничего не сдвинут — 404 здесь
    ни к чему: соседняя вкладка могла удалить сайт, пока карточку тащили.
    """
    async with mysql_get_db_async() as db:
        for position, site_id in enumerate(data.ids, start=1):
            await db.execute('UPDATE browser_site SET position = %s WHERE id = %s',
                             (position, int(site_id)))
        await db.connection.commit()

    return {'status': 'success'}


@router.put('/{site_id}', include_in_schema=False)
async def browser_site_update(site_id: int, data: BrowserSiteSave,
                              user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Переписывает имя и адрес карточки."""
    await _site_row(site_id)

    try:
        await BrowserSiteRepository().update(site_id, {'name': data.name, 'url': data.url})
    except Exception as e:
        raise HTTPException(status_code=409, detail=_save_error(e, data.name))

    return {'status': 'success'}


@router.delete('/{site_id}', include_in_schema=False)
async def browser_site_delete(site_id: int,
                              user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Удаляет карточку. Живые сессии этого сайта не трогает — они сами по себе."""
    await _site_row(site_id)
    await BrowserSiteRepository().delete(site_id)

    return {'status': 'success'}


async def _position_next() -> int:
    """Позиция в конце списка."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT COALESCE(MAX(position), 0) + 1 AS next FROM browser_site')
        row = await db.fetchone()

    return int((row or {}).get('next') or 1)


def _save_error(error: Exception, name: str) -> str:
    """Человеческая причина отказа вместо текста драйвера.

    Единственное ограничение таблицы — уникальное имя, и `(1062, "Duplicate entry
    …for key 'uk_browser_site_name'")` в окне правки не говорит человеку ничего.
    Остальные сбои редки и остаются как есть: скрыв их текст, чинить нечего.
    """
    text = str(error)
    if '1062' in text or 'Duplicate entry' in text:
        return f'сайт с названием «{name}» уже есть'

    return f'не удалось сохранить сайт: {text}'


async def _site_row(site_id: int) -> dict:
    """Сайт из базы или 404 — иначе правка несуществующего молча ничего не делает."""
    row = await BrowserSiteRepository().find(site_id)
    if not row:
        raise HTTPException(status_code=404, detail='сайт не найден')

    return row

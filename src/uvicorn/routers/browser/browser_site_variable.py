"""Переменные сайта: `{{login}}`, `{{password}}`, адрес кабинета.

Сценарии ссылаются на переменные по имени, а значения до сих пор жили в самом
сценарии либо приходили на прогон снаружи. У сайта сценариев несколько, и одно и то же
значение переписывалось в каждом. Здесь оно заводится один раз на сайт.

**Секретные значения в базе зашифрованы** (`browser_secret`), ключ — в окружении. В
списке они не отдаются вовсе: чтобы получить сырое, нужно спросить одну переменную
отдельно и иметь право `browser:secret`. Разделение не формальность —
`browser:view` есть у служебной учётки соседнего проекта, и пароли от чужих кабинетов
ей ни к чему.

Открытые переменные показываются всем, у кого есть `browser:view`: адрес стенда и
номер тарифа прятать не от кого, а список, где каждое второе значение скрыто, читать
невозможно.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mysql_.mysql_ import mysql_get_db_async

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.browser.browser_secret import (browser_secret_decrypt, browser_secret_encrypt,
                                        browser_secret_ready)
from src.mysql_.repository.browser.site_variable_repository import BrowserSiteVariableRepository

# Префикс не вложен в `/api/browser/site` намеренно, хотя переменные и принадлежат
# сайту. У соседнего роутера есть `GET /{site_id}`, и он перехватывал бы `/site/variable`
# целиком: FastAPI разбирает пути по порядку регистрации, и список переменных приходил
# бы как «сайт с номером `variable`» — 422 про непарсящееся число. Полагаться на порядок
# роутеров нельзя, он меняется при первой перестановке импортов.
router = APIRouter(prefix='/api/browser/variable', tags=['browser'])

# Чем закрыто секретное значение в общем списке. Не пустая строка: пустое поле
# читается как «переменная не заполнена», и человек завёл бы её заново поверх целой.
BROWSER_SITE_VARIABLE_MASK = '••••••••'

# Имя переменной — то, что стоит внутри `{{…}}`. Буквы, цифры, подчёркивание и дефис:
# ровно то, что разбирает подстановка сценария (`browser_scenario`). Пробел или скобка
# в имени дали бы переменную, на которую невозможно сослаться.
BROWSER_SITE_VARIABLE_NAME_RE = r'^[A-Za-z0-9_-]+$'


class BrowserSiteVariableIn(BaseModel):
    """Тело создания и правки. `value` пустой при правке означает «не менять»."""

    model_config = ConfigDict(extra='forbid')

    site_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100, pattern=BROWSER_SITE_VARIABLE_NAME_RE)
    value: str = Field(default='', max_length=4000)
    is_secret: bool = False
    description: str = Field(default='', max_length=255)

    @field_validator('name')
    @classmethod
    def _name_clean(cls, value: str) -> str:
        """Скобки снимаем, если человек скопировал имя прямо из шага сценария."""
        return value.strip().strip('{}').strip()


@router.get('')
async def browser_site_variable_list(
        site_id: int = Query(gt=0),
        user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """
    Переменные сайта. Секретные значения закрыты маской — всегда, для всех.

    Маска стоит и для полноправного человека: список рисуется на каждой смене сайта, и
    отдавать пароли пачкой в ответ, который осядет в журнале прокси и в истории
    браузера, незачем. Сырое значение выдаётся поштучно и по отдельному праву
    (`/reveal`), то есть на явное действие человека.

    `secret_ready` — есть ли рабочий ключ. Без него страница не даст завести секрет:
    иначе человек пометил бы значение секретным, получил бы отказ на сохранении и не
    понял, при чём тут вообще ключ.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, site_id, name, value, is_secret, description, position, updated_at '
            '  FROM browser_site_variable WHERE site_id = %s ORDER BY position, id',
            (int(site_id),))
        rows = await db.fetchall() or []

    items = []
    for row in rows:
        row = dict(row)
        row['is_secret'] = bool(row.get('is_secret'))
        row['value'] = (BROWSER_SITE_VARIABLE_MASK if row['is_secret']
                        else browser_secret_decrypt(row.get('value')))
        items.append(row)

    return {'items': items, 'secret_ready': browser_secret_ready()}


@router.get('/{variable_id}/reveal')
async def browser_site_variable_reveal(
        variable_id: int,
        user=Depends(AuthChecker([AuthPermission.BROWSER_SECRET_VIEW]))):
    """
    Сырое значение одной переменной — по нажатию «показать».

    Отдельной ручкой, а не полем списка: так доступ к паролю виден в журнале запросов
    как отдельное событие с именем переменной, а не растворяется в обычном показе
    страницы. По той же причине право своё, отличное от `browser:view`.
    """
    row = await BrowserSiteVariableRepository().find_one_by({'id': int(variable_id)})
    if not row:
        raise HTTPException(status_code=404, detail='variable not found')

    return {'id': int(row['id']), 'name': row['name'],
            'value': browser_secret_decrypt(row.get('value'))}


@router.post('')
async def browser_site_variable_create(
        data: BrowserSiteVariableIn,
        user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Завести переменную. Имя уникально внутри сайта — двойник получает 409."""
    await _site_require(data.site_id)
    await _name_free(data.site_id, data.name)

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT COALESCE(MAX(position), -1) + 1 AS next FROM browser_site_variable '
            ' WHERE site_id = %s', (data.site_id,))
        position = int((await db.fetchone() or {}).get('next') or 0)

    variable_id = await BrowserSiteVariableRepository().add({
        'site_id': data.site_id,
        'name': data.name,
        'value': _value_store(data.value, data.is_secret),
        'is_secret': int(data.is_secret),
        'description': data.description,
        'position': position,
    })

    return {'id': variable_id}


@router.put('/{variable_id}')
async def browser_site_variable_update(
        variable_id: int, data: BrowserSiteVariableIn,
        user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """
    Правка переменной.

    Пустой `value` означает «значение не трогать»: в форме секретное поле показано
    маской, и отправь мы его как есть, паролем стала бы строка из точек. Чтобы
    очистить значение по-настоящему, переменную удаляют — пустой пароль в подстановке
    всё равно ничего не даст.

    Смена `is_secret` переписывает значение целиком: открытое, ставшее секретным,
    шифруется, а секретное, ставшее открытым, ложится сырым. Иначе в базе осталась бы
    строка, чей вид не соответствует пометке, и решать «шифровать ли» пришлось бы
    гаданием по содержимому.
    """
    repository = BrowserSiteVariableRepository()
    row = await repository.find_one_by({'id': int(variable_id)})
    if not row:
        raise HTTPException(status_code=404, detail='variable not found')

    await _site_require(data.site_id)
    await _name_free(data.site_id, data.name, skip_id=int(variable_id))

    was_secret = bool(row.get('is_secret'))
    if data.value:
        value = _value_store(data.value, data.is_secret)
    elif data.is_secret == was_secret:
        value = row.get('value') or ''
    else:
        # Пометка сменилась, а нового значения не прислали — перекладываем прежнее:
        # расшифровываем и, если надо, шифруем обратно.
        value = _value_store(browser_secret_decrypt(row.get('value')), data.is_secret)

    await repository.update(int(variable_id), {
        'site_id': data.site_id,
        'name': data.name,
        'value': value,
        'is_secret': int(data.is_secret),
        'description': data.description,
    })

    return {'ok': True}


@router.delete('/{variable_id}')
async def browser_site_variable_delete(
        variable_id: int,
        user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Удалить переменную. Несуществующая — тоже успех: результат тот же."""
    await BrowserSiteVariableRepository().delete(int(variable_id))

    return {'ok': True}


async def browser_site_variable_values(site_id: int) -> tuple[dict, dict]:
    """
    Переменные сайта для прогона: `(обычные, секретные)` — обе расшифрованы.

    Разделение то же, что у сценария (`browser_scenario_run`): обычные попадают в
    журнал, секретные замазываются в нём и в тексте ошибок. Поэтому две сумки, а не
    одна с флажком: потребителю нельзя дать возможность залогировать всё скопом.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT name, value, is_secret FROM browser_site_variable '
            ' WHERE site_id = %s ORDER BY position, id', (int(site_id),))
        rows = await db.fetchall() or []

    plain, secret = {}, {}
    for row in rows:
        target = secret if row.get('is_secret') else plain
        target[row['name']] = browser_secret_decrypt(row.get('value'))

    return plain, secret


def _value_store(value: str, is_secret: bool) -> str:
    """
    Значение в том виде, в каком оно ложится в базу.

    Отказ ключа поднимается как 400, а не 500: это не поломка сервера, а незаконченная
    настройка установки, и человеку нужно сказать, чего именно не хватает.
    """
    if not is_secret:
        return str(value or '')

    try:
        return browser_secret_encrypt(value)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))


async def _site_require(site_id: int) -> None:
    """Сайт существует. Иначе переменная повисла бы на несуществующем номере."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id FROM browser_site WHERE id = %s', (int(site_id),))
        if not await db.fetchone():
            raise HTTPException(status_code=404, detail='site not found')


async def _name_free(site_id: int, name: str, skip_id: int = 0) -> None:
    """
    Имя свободно внутри сайта.

    Проверяем до записи, чтобы вернуть понятный 409 вместо 500 от нарушения
    UNIQUE-ключа. Сам ключ при этом остаётся: между проверкой и вставкой успевает
    чужой запрос, и последнее слово должно быть за базой.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id FROM browser_site_variable WHERE site_id = %s AND name = %s '
            '   AND id <> %s', (int(site_id), str(name), int(skip_id)))
        if await db.fetchone():
            raise HTTPException(status_code=409, detail=f'переменная «{name}» у сайта уже есть')

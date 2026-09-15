"""Реестр прокси: какие выходы наружу есть и какие из них живые.

⚠ **Не путать с `browser_proxy.py` рядом.** Тот — прокси вебсокета: труба от
админки к живому окну Chromium. Здесь — сетевые прокси, то есть **с какого IP нас
видит чужой сайт**. Слово одно, предметы разные, и файлы поэтому разные.

## Что здесь есть и чего здесь нет

Реестр отвечает на один вопрос: **какие выходы заведены и какие из них
работают**. Всё.

⚠ **Кому какой выход достанется — решает не он.** Сутки реестр умел раздавать
места: хранил, кто на каком выходе сидит, и знал предел «сколько анкет допустимо
на адрес». Это было ошибкой границы: здесь не знают, что такое анкета, и знать не
должны, — а таблица мест хранила чужие ключи вида `dating:profile:41`.

Теперь так: реестр отдаёт список вместе с **увиденным адресом** (`check_ip`), а
потребитель считает своих по этому адресу сам. У него для этого есть всё, чего
нет здесь: он знает, сколько у него потребителей, и знает предел — а предел
зависит от сайта знакомств, про который тут не слыхали.

## Проверка отвечает «каким адресом нас видят»

Не «жив ли прокси». Разница существенная: два разных прокси нередко выходят одним
и тем же IP — так устроены пулы у провайдеров, — и потребитель, считающий по
строке подключения, поделил бы чужой лимит, ничего об этом не зная. Поэтому
`check_ip` не украшение отчёта, а то, ради чего проверка и нужна.

Прокси без удачной проверки потребителю не годится: куда его считать, неизвестно.

## Права

| Что | Право | Кто |
|-----|-------|-----|
| смотреть список | `browser:view` | человек и сосед |
| заводить, править, удалять, проверять | `browser:create` | человек |
| получить адреса с паролями | `browser:proxy` | сосед |

Пароль уходит наружу **одной ручкой** — `GET /address`, — и только по
`browser:proxy`. Везде остальное показывается `•••`.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from http_.http_proxy import (http_proxy_check, http_proxy_direct_ip, http_proxy_hide,
                              http_proxy_parse, http_proxy_url)
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.browser.proxy_repository import BrowserProxyRepository

router = APIRouter(prefix='/api/browser/proxy', tags=['browser'])

# Сколько проверок идёт разом при «Проверить все». Прокси отвечают секундами, и
# по одной за раз два десятка строк заняли бы минуту; больше пяти — и медленный
# провайдер начинает отвечать отказами на собственный перегруз.
BROWSER_PROXY_CHECK_PARALLEL = 5


class BrowserProxySave(BaseModel):
    """Тело заведения и правки выхода.

    ⚠ **Адрес — одной строкой, а не пятью полями.** Каналы покупают пачками, и
    провайдер присылает список: по строке на выход. Пять полей на строку — это
    пять мест, где можно ошибиться, помноженные на два десятка каналов. Форматы
    разбирает общий слой (`http_proxy_parse`), он же экранирует пароль при сборке.
    """

    address: str = Field(..., min_length=1, max_length=500,
                         description='socks5://user:pass@host:1080 либо host:1080:user:pass')
    name: str = Field('', max_length=100,
                      description='Как звать этот выход; пусто — возьмём хост')
    note: str = Field('', max_length=255)
    is_enabled: bool = True

    @field_validator('name', 'note')
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()

    def parts(self) -> dict:
        """Части адреса плюс имя: то, что ложится в строку таблицы.

        Имя пустое — берём хост: у двадцати каналов одного провайдера имена
        всё равно придумывают по хосту, а строка без имени в списке безымянна.

        Raises:
            ValueError: строку не разобрать. ⚠ Ловит её **обработчик**, а не
                валидатор pydantic: отказ валидатора приезжает списком объектов
                (`[{"type": "value_error", "loc": […]}]`), и страница показывает
                его как JSON. Человек вставлял строку — ему нужна фраза.
        """
        got = http_proxy_parse(self.address)

        return {**got, 'name': self.name or f'{got["host"]}:{got["port"]}',
                'note': self.note, 'is_enabled': int(bool(self.is_enabled))}


@router.get('', include_in_schema=False)
async def browser_proxy_list(user=Depends(AuthChecker([AuthPermission.BROWSER_VIEW]))):
    """Выходы реестра. Пароль скрыт: в строке `url` на его месте `•••`.

    Кому нужен настоящий адрес — `GET /address`, и там своё право.
    """
    async with mysql_get_db_async() as db:
        rows = await _rows(db)

    # ⚠ **Свой адрес рядом со списком, а не отдельным запросом.** Он нужен ровно
    # для сравнения: выход, у которого увиденный IP совпал с нашим, не скрывает
    # ничего — запрос идёт мимо него либо он прозрачный. Ответ кэширован на
    # полчаса (`http_proxy_direct_ip`), так что показ страницы наружу не ходит.
    direct = await http_proxy_direct_ip()
    for row in rows:
        row['is_direct'] = bool(row['check_ip']) and row['check_ip'] == direct.get('ip')

    return {'result': rows, 'direct': direct}


@router.get('/address', include_in_schema=False)
async def browser_proxy_address(ready: bool = True,
                                user=Depends(AuthChecker([AuthPermission.BROWSER_PROXY_USE]))):
    """Выходы **с адресами и паролями** — тому, кто через них пойдёт.

    Args:
        ready: отдавать только проверенные и включённые. Так спрашивает
            потребитель: непроверенный выход ему не годится — неизвестно, каким
            адресом его видят, а считать своих он будет именно по адресу.

    Returns:
        dict: `result` — список `{id, name, url, check_ip, check_ok, …}`, где
        `url` **с паролем**.

    ⚠ **Единственная ручка, отдающая пароль канала**, и отдельное право у неё
    поэтому. `browser:view` показывает тот же список с `•••`: знать, что выход
    есть, и знать, чем к нему подключиться, — разные вещи.

    ⚠ **Мест и занятости здесь нет.** Реестр не считает потребителей: он не знает,
    кто они. Считает их тот, кто знает, — по `check_ip`, который едет в каждой
    строке.
    """
    async with mysql_get_db_async() as db:
        rows = await _rows(db, with_password=True)

    if ready:
        rows = [row for row in rows if row['check_ok'] and row['is_enabled'] and row['check_ip']]

    return {'result': rows}


@router.post('', status_code=201, include_in_schema=False)
async def browser_proxy_create(data: BrowserProxySave,
                               user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Заводит выход. Проверку **не** гонит — это отдельное действие.

    Разделено намеренно: заводят обычно пачкой, из письма провайдера, а проверка
    идёт секунды на строку. Непроверенный выход при этом потребителю не достанется,
    и забыть проверку молча нельзя — на странице он виден серым.
    """
    try:
        fields = data.parts()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        proxy_id = await BrowserProxyRepository().add(fields)
    except Exception as e:
        raise HTTPException(status_code=409, detail=f'не завёлся: {e}')

    logger_info(f'[proxy] заведён выход #{proxy_id} «{fields["name"]}»')

    return {'result': {'id': proxy_id}}


@router.put('/{proxy_id}', include_in_schema=False)
async def browser_proxy_update(proxy_id: int, data: BrowserProxySave,
                               user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Правит выход.

    ⚠ **Правка адреса сбрасывает итог проверки.** Иначе строка осталась бы с
    прежним `check_ip` — то есть считалась бы годной и попадала к потребителю,
    ведя при этом в другое место.

    ⚠ **Адрес без пароля прежний пароль не затирает.** Страница показать его не
    может и на правку подставляет строку без него; «нет пароля» здесь значит «не
    трогал». Сменить — вписать новый прямо в адрес.
    """
    try:
        fields = data.parts()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    async with mysql_get_db_async() as db:
        await db.execute('SELECT scheme, host, port, username, password '
                         '  FROM browser_proxy WHERE id = %s', (int(proxy_id),))
        was = await db.fetchone()

    if not was:
        raise HTTPException(status_code=404, detail=f'выхода #{proxy_id} нет')

    if not fields['password']:
        fields['password'] = was['password']

    moved = any(str(fields[key]) != str(was[key])
                for key in ('scheme', 'host', 'port', 'username'))
    if moved:
        fields.update({'check_ok': 0, 'check_ip': '', 'check_country': '', 'check_ms': 0,
                       'check_error': 'адрес правили — нужна проверка', 'checked_at': None})

    await BrowserProxyRepository().update(int(proxy_id), fields)

    return {'result': {'id': int(proxy_id), 'recheck': moved}}


@router.delete('/{proxy_id}', include_in_schema=False)
async def browser_proxy_delete(proxy_id: int,
                               user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Удаляет выход.

    ⚠ **Реестр не знает, пользуется ли кто-то этим выходом прямо сейчас**, и
    спросить ему некого: потребители ему не докладываются. Поэтому удаление
    молчаливое — предупредить о последствиях может лишь тот, кто ведёт своих
    потребителей, и он же увидит пропажу: выход исчезнет из `GET /address`.
    """
    if not await BrowserProxyRepository().delete(int(proxy_id)):
        raise HTTPException(status_code=404, detail=f'выхода #{proxy_id} нет')

    logger_info(f'[proxy] выход #{proxy_id} удалён')

    return {'result': {'deleted': True}}


@router.post('/check', include_in_schema=False)
async def browser_proxy_check_all(user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Проверяет все включённые выходы разом и возвращает итоги.

    ⚠ Объявлено выше `/{proxy_id}/check`: пути разбираются по порядку, и слово
    «check» при обратном порядке однажды прочиталось бы как номер.
    """
    return {'result': await browser_proxy_net_check_all()}


@router.post('/{proxy_id}/check', include_in_schema=False)
async def browser_proxy_check_one(proxy_id: int,
                                  user=Depends(AuthChecker([AuthPermission.BROWSER_CREATE]))):
    """Идёт через выход наружу и запоминает, каким адресом нас увидели.

    Отказ — это **результат проверки**, а не ошибка запроса: отвечаем 200 с
    `ok: false` и причиной словами. Иначе страница не смогла бы отличить «прокси
    мёртв» от «ручка сломалась», а это разные разговоры.
    """
    return {'result': await _check(int(proxy_id))}


async def browser_proxy_net_check_all() -> list[dict]:
    """Проверяет все включённые выходы и запоминает итоги. Отдаёт их списком.

    ⚠ **Функция, а не только ручка.** Её же зовёт сторож
    (`src/cronjob/browser_proxy_watch.py`): кнопку «Проверить все» жмут руками и
    редко, а прокси умирают сами и молча. Вторая копия этого кода разошлась бы с
    первой — и человек с кнопкой видел бы одно, а потребитель получал другое.

    Идут пачками по `BROWSER_PROXY_CHECK_PARALLEL`: по одной за раз два десятка
    строк заняли бы минуту, а залпом медленный провайдер начинает отвечать
    отказами на собственный перегруз.
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id FROM browser_proxy WHERE is_enabled = 1 ORDER BY id')
        ids = [int(row['id']) for row in await db.fetchall() or []]

    gate = asyncio.Semaphore(BROWSER_PROXY_CHECK_PARALLEL)

    async def _one(proxy_id: int) -> dict:
        async with gate:
            return await _check(proxy_id)

    return await asyncio.gather(*[_one(proxy_id) for proxy_id in ids])


async def browser_proxy_net_url(proxy_id: int) -> str:
    """Адрес выхода по его номеру — для тех, кто открывает через него сессию.

    ⚠ **Не ручка, а функция**: адрес с паролем не должен ездить по сети ради
    того, что установка и так знает. Её зовут создание сессии и прогон сценария
    (`browser_proxy.py`, `browser_scenario.py`), получая от соседа лишь номер.

    Нет такого номера — 404 прямо отсюда. Молчаливый прямой выход был бы худшим
    исходом: вкладка пошла бы на сайт с общего адреса сервера, и узнали бы мы об
    этом из блокировки учётки, а не из ответа ручки.
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT scheme, host, port, username, password, is_enabled '
                         '  FROM browser_proxy WHERE id = %s', (int(proxy_id),))
        row = await db.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f'выхода #{proxy_id} нет в реестре')
    if not int(row['is_enabled']):
        raise HTTPException(status_code=409, detail=f'выход #{proxy_id} выключен')

    return http_proxy_url(row['scheme'], row['host'], int(row['port']),
                          row['username'] or '', row['password'] or '')


# ── Приватное ────────────────────────────────────────────────────────────────

async def _rows(db, with_password: bool = False) -> list[dict]:
    """Выходы реестра: **живые сверху и по пингу**, мёртвые вниз.

    ⚠ **Порядок задаёт сервер, а не страница.** Реестр читают, чтобы понять, чем
    сейчас можно работать, и решают по скорости: 200 мс против 15 секунд — это
    разница между «страница открылась» и «сценарий отвалился по таймауту».

    ⚠ Непроверенный пинг (`0`) уходит в конец живых, а не в начало: ноль здесь
    значит «не мерили», и ставить такую строку впереди самой быстрой было бы
    враньём.

    «Живой» — проверенный, включённый и с увиденным адресом: без адреса выход не
    годится, даже если пинг прошёл (считать его не с чем).
    """
    await db.execute('SELECT * FROM browser_proxy ORDER BY name, id')
    rows = [_proxy_out(row, with_password) for row in await db.fetchall() or []]
    rows.sort(key=lambda row: (
        not (row['check_ok'] and row['is_enabled'] and row['check_ip']),
        row['check_ms'] or 10 ** 9,
        row['id']))

    return rows


def _proxy_out(row: dict, with_password: bool) -> dict:
    """Строка наружу: адрес собран, пароль показан только по требованию.

    ⚠ **Собирает адрес сервер, а не потребитель.** Экранирование логина и пароля
    — место, где ошибаются молча (`@` в пароле уводит хост), и делать это в двух
    проектах по-разному мы не будем.
    """
    url = http_proxy_url(row['scheme'], row['host'], int(row['port']),
                         row.get('username') or '', row.get('password') or '')

    return {
        'id': int(row['id']), 'name': row['name'], 'scheme': row['scheme'],
        'host': row['host'], 'port': int(row['port']),
        'username': row.get('username') or '',
        'has_password': bool(row.get('password')),
        'note': row.get('note') or '',
        'is_enabled': bool(int(row.get('is_enabled') or 0)),
        'checked_at': row.get('checked_at'),
        'check_ok': bool(int(row.get('check_ok') or 0)),
        # ⚠ Увиденный адрес — **главное поле строки для потребителя**: по нему он
        # считает своих. Два выхода с одним `check_ip` делят чужой лимит, и
        # узнать об этом можно только отсюда.
        'check_ip': row.get('check_ip') or '',
        # Страна выхода по ISO-3166 alpha-2. Едет тем же запросом, что и адрес:
        # сайты сверяют геолокацию входа с анкетой, и канал не из той страны —
        # повод к вопросам у них. Пусто значит «не знаем», а не «нет страны».
        'check_country': row.get('check_country') or '',
        'check_ms': int(row.get('check_ms') or 0),
        'check_error': row.get('check_error') or '',
        'url': url if with_password else http_proxy_hide(url),
    }


async def _check(proxy_id: int) -> dict:
    """Проверяет один выход и запоминает итог в его строке."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT * FROM browser_proxy WHERE id = %s', (int(proxy_id),))
        row = await db.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f'выхода #{proxy_id} нет')

    url = http_proxy_url(row['scheme'], row['host'], int(row['port']),
                         row.get('username') or '', row.get('password') or '')
    got = await http_proxy_check(url)

    async with mysql_get_db_async() as db:
        await db.execute(
            'UPDATE browser_proxy SET checked_at = NOW(), check_ok = %s, check_ip = %s, '
            '       check_country = %s, check_ms = %s, check_error = %s WHERE id = %s',
            (int(bool(got['ok'])), got['ip'], got.get('country') or '',
             int(got['ms']), got['error'][:255], int(proxy_id)))
        await db.connection.commit()

    return {'id': int(proxy_id), 'name': row['name'], **got}

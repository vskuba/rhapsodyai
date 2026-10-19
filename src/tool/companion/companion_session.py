"""Разговор пары: записать обмен и прочитать последние.

Единственный дом переписки. До него её не хранили нигде разборно: DatingAi
собирал ленту на каждый вызов из пяти своих таблиц и присылал готовым текстом, а
у нас она оседала слепками — в `agent_workflow_trace.variables_start` и внутри
собранных промптов в `agent_session`. Разговор был, но выбрать его по паре,
времени или каналу было нельзя.

## ⚠⚠ Ключи приходят готовыми, и это то же решение, что у `companion_create`

Склеить `{номер}_{имя}` мог бы и инструмент. Но тогда правило «из чего состоит
ключ» лежало бы в коде, а читают workflow — в редакторе: шаг «Ключи» показывает
`%companion_id%_%companion_name%` прямо в списке.

## ⚠ Обе половины обмена умеют пустовать

    вопроса нет   заговорили мы: инвайт, рассылка, письмо избранному
    ответа нет    не ответили: он написал дважды подряд, или агент смолчал

Пустые обе — единственный отказ: такая строка не говорит ничего.
"""
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from datetime_.datetime_ import datetime_utc_now
from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.companion_repository import CompanionRepository
from src.mysql_.repository.companion_session_repository import (
    CompanionSessionRepository)

# Каналы разговора — они же значения столбца `kind`.
#
# ⚠ Чат и почта держатся врозь намеренно: это разные разговоры — разной длины,
# разного тона, часто разных дней. Слитые в одну ленту, письма вытолкнул бы чат
# на первом же пределе выборки, а отвечать на письмо агент стал бы в регистре
# мессенджера.
COMPANION_SESSION_KINDS = ('chat', 'mail')

# Сколько последних обменов отдавать, если предел не задали.
COMPANION_SESSION_LIMIT = 20

# Потолок поверх запрошенного: длинная история стоит токенов на каждом ответе, а
# промпт из сотни реплик модель читает как простыню и отвечает первым, что
# увидит.
COMPANION_SESSION_LIMIT_MAX = 100

# Обрезка текста реплики в ленте, знаков. У письма свой предел: три абзаца, и
# тысяча знаков отрезала бы у него конец.
COMPANION_SESSION_TEXT_MAX = {'chat': 1000, 'mail': 2000}

# Сколько времени висящая реплика считается относящейся к новому ответу.
#
# ⚠ Сутки, а не вечность: собеседник написал вчера, агент отвечает сегодня на
# сегодняшнее — вчерашняя строка к этому ответу не относится и остаётся в
# ленте своей репликой. Подробности — в `_pending_absorb`.
COMPANION_SESSION_PENDING_SEC = 86400

# Выше этой похожести две реплики считаются одной и той же.
#
# ⚠ Число не выведено, а подобрано на живых ответах, и взято то же, что стояло у
# прежней проверки по сессии: ниже начинают слипаться разные реплики с общим
# хвостом («…расскажи подробнее»), выше перестаёт ловиться перефразировка.
COMPANION_SESSION_REPEAT_RATIO = 0.85

# Сколько последних обменов пары сравнивать, если предел не задали.
#
# ⚠ Пять, а не двадцать: повтор ловится у свежего хвоста разговора, а на длинном
# окне растёт цена ложного срабатывания — вопрос, заданный месяц назад,
# законно задают снова.
COMPANION_SESSION_REPEAT_LIMIT = 5


async def companion_session_add(owner_unique_id: str, companion_unique_id: str,
                                question: str = '', answer: str = '',
                                kind: str = 'chat',
                                source_uid: str = '') -> dict:
    """Записать один обмен разговора: что спросил он, что ответили мы.

    Args:
        owner_unique_id: ключ нашей стороны (`companion.unique_id`).
        companion_unique_id: ключ той стороны.
        question: что написал он. Пусто — заговорили мы.
        answer: что ответили мы. Пусто — не ответили.
        kind: `chat` или `mail`.
        source_uid: номер реплики у источника, если он есть. Ловит повтор.

    Returns:
        dict: `id` — номер строки (0, если не записали), `saved` — записали ли,
        `why` — причина отказа словами.

    ## ⚠ Записи заводятся, если их нет

    Обе стороны обязаны лежать в `companion`: строка разговора ведёт на них
    внешним ключом. Обычно записи уже есть — их заводит шаг `companion_create`, —
    но полагаться на порядок шагов значило бы терять разговор всякий раз, когда
    шаг переставят.
    """
    owner_key = str(owner_unique_id or '').strip()
    companion_key = str(companion_unique_id or '').strip()
    question_text = str(question or '').strip()
    answer_text = str(answer or '').strip()
    channel = str(kind or '').strip().lower()

    if not owner_key or not companion_key:
        # ⚠ Пустой ключ — не «запиши куда-нибудь», а «части не доехали». Запиши
        # мы обмен под чужой записью, разговор двух людей слился бы в один.
        return {'id': 0, 'saved': 0, 'why': 'нет ключа стороны'}

    if channel not in COMPANION_SESSION_KINDS:
        return {'id': 0, 'saved': 0, 'why': f'неизвестный канал: {channel}'}

    if not question_text and not answer_text:
        return {'id': 0, 'saved': 0, 'why': 'обе половины пусты'}

    owner_id = await _companion_id(owner_key)
    companion_id = await _companion_id(companion_key)

    if not owner_id or not companion_id:
        return {'id': 0, 'saved': 0, 'why': 'не завелась запись стороны'}

    now = datetime_utc_now()
    # ⚠ Время у половины ставится, **только если половина есть**: пустой
    # половине время незачем, а ноль встал бы в ленту раньше всего сказанного.
    row = {'owner_id': owner_id, 'companion_id': companion_id, 'kind': channel,
           'question': question_text,
           'question_at': now if question_text else None,
           'answer': answer_text,
           'answer_at': now if answer_text else None,
           'source_uid': str(source_uid or '').strip() or None}

    # ⚠⚠ Реплики, записанные приёмом (`companion_session_incoming`), вошли в
    # этот же вопрос — их строки надо закрыть, иначе лента покажет вопрос
    # дважды: один раз висящим, второй в составе обмена. Подробности и границы
    # — в `_pending_absorb`.
    if question_text:
        await _pending_absorb(owner_id, companion_id, channel, question_text)

    made = await CompanionSessionRepository().add(row)

    return {'id': int(made or 0), 'saved': 1, 'why': ''}


async def companion_session_incoming(owner_unique_id: str,
                                     companion_unique_id: str,
                                     text: str, kind: str = 'chat',
                                     source_uid: str = '',
                                     said_at: str = '') -> dict:
    """Записать реплику собеседника сразу, не дожидаясь нашего ответа.

    Args:
        owner_unique_id: ключ нашей стороны (`companion.unique_id`).
        companion_unique_id: ключ той стороны.
        text: что он написал.
        kind: `chat` или `mail`.
        source_uid: ключ реплики у источника. **Нужен**: им ловится повтор.
        said_at: когда он это написал, `ГГГГ-ММ-ДД ЧЧ:ММ:СС` в UTC. Пусто —
            сейчас.

    Returns:
        dict: `id` — номер строки (0, если не записали), `saved` — записали ли,
        `why` — причина отказа словами.

    ## ⚠⚠ ЗАЧЕМ ОТДЕЛЬНАЯ ДОРОГА

    Единственный путь в `companion_session` шёл через прогон workflow, а его
    запускает `/chat/ask` — то есть **решение ответить**. Реплика, на которую
    не ответили, не попадала к нам ничем: ни ошибки, ни следа.

    Замерено на проде 02.10.2026: двенадцать таких за восемь дней. У всех у
    соседа `is_answered = 0` и попытки не было вовсе — агента на них не звали.
    Среди потерянного «how did you sleep???» и «sent you photo».

    ## ⚠ Повтор не задваивает, и ключ тут обязателен

    Приём зовут на каждое входящее, а доставка до нас не гарантирована:
    сосед повторит вызов. Без `source_uid` каждый повтор клал бы новую строку.
    Проверка идёт по тройке `(owner, kind, source_uid)` — ровно тот уникальный
    ключ, что стоит у таблицы.

    ⚠ Пустой `source_uid` не запрещён (у реплики со страницы своего номера
    нет), но тогда и защиты от повтора нет: `NULL` в уникальном ключе MySQL
    сам с собой не сталкивается.
    """
    owner_key = str(owner_unique_id or '').strip()
    companion_key = str(companion_unique_id or '').strip()
    said = str(text or '').strip()
    channel = str(kind or '').strip().lower()
    source = str(source_uid or '').strip()

    if not owner_key or not companion_key:
        return {'id': 0, 'saved': 0, 'why': 'нет ключа стороны'}

    if channel not in COMPANION_SESSION_KINDS:
        return {'id': 0, 'saved': 0, 'why': f'неизвестный канал: {channel}'}

    if not said:
        return {'id': 0, 'saved': 0, 'why': 'пустая реплика'}

    owner_id = await _companion_id(owner_key)
    companion_id = await _companion_id(companion_key)

    if not owner_id or not companion_id:
        return {'id': 0, 'saved': 0, 'why': 'не завелась запись стороны'}

    if source:
        found = await _by_source(owner_id, channel, source)

        if found:
            return {'id': found, 'saved': 0, 'why': 'уже записано'}

    when = _moment(said_at)
    # ⚠ Ответа нет и времени ответа нет: его ещё не сочинили. `delivered_at`
    # тоже пуст — отметка про НАШУ реплику, а её тут нет.
    row = {'owner_id': owner_id, 'companion_id': companion_id, 'kind': channel,
           'question': said, 'question_at': when,
           'answer': '', 'answer_at': None,
           'source_uid': source or None}

    made = await CompanionSessionRepository().add(row)

    return {'id': int(made or 0), 'saved': 1, 'why': ''}


async def companion_session_delivered(message_id: int) -> dict:
    """Отметить обмен доставленным: наш ответ дошёл до собеседника.

    Args:
        message_id: номер строки `companion_session` — его отдаёт
            `companion_session_add` и возвращает `/chat/ask` полем `message_id`.

    Returns:
        dict: `marked` — 1, если отметка легла, 0 иначе; `why` — почему не легла.

    ## ⚠⚠ Повтор времени не двигает

    Условие `delivered_at IS NULL`. Без него повторная отправка сдвигала бы
    отметку вперёд, и «когда это дошло» перестало бы отвечать на свой вопрос.

    ## ⚠ Неизвестный номер — не отказ

    Строки нет — отвечаем `marked: 0` и причиной. Исключение здесь заставило бы
    панель повторять вызов, которому повторяться незачем: строка не появится.
    """
    number = int(message_id or 0)

    if number <= 0:
        return {'marked': 0, 'why': 'номер обмена не задан'}

    async with mysql_get_db_async() as db:
        await db.execute(
            'UPDATE `companion_session` SET `delivered_at` = %s'
            ' WHERE `id` = %s AND `delivered_at` IS NULL',
            # ⚠ UTC, как и `question_at`/`answer_at` у записи обмена: столбцы
            # одной строки обязаны мериться одними часами. Разойдись они — и
            # «доставлено раньше, чем сказано» выглядело бы поломкой кода.
            (datetime_utc_now(), number))
        marked = int(db.rowcount or 0)
        await db.connection.commit()

    if marked:
        return {'marked': 1, 'why': ''}

    return {'marked': 0, 'why': f'обмен {number} не найден либо уже отмечен'}


async def companion_session_history(owner_unique_id: str,
                                    companion_unique_id: str,
                                    kind: str = 'chat',
                                    limit: int = 0,
                                    companion_message_at_least: int = 1,
                                    since: str = '',
                                    until: str = '') -> str:
    """Последние обмены пары строками промпта. Пусто — разговора не было.

    Args:
        owner_unique_id: ключ нашей стороны.
        companion_unique_id: ключ той стороны.
        kind: `chat` или `mail` — каналы не смешиваются.
        limit: сколько последних обменов взять. Ноль — умолчание канала.
        companion_message_at_least: сколько реплик **собеседника** должно быть в
            ленте, чтобы её вообще отдавать. Меньше — пустая строка. Ноль или
            отрицательное — порога нет, отдаём что есть.
        since: брать только то, что **позже** этой отметки (`ГГГГ-ММ-ДД ЧЧ:ММ:СС`,
            UTC). Пусто — без нижней границы.
        until: брать только то, что **не позже** этой отметки. Пусто — без
            верхней границы.

    Returns:
        str: строки «[дд.мм чч:мм] она|он: текст», старое сверху.

    ## ⚠⚠ Зачем границы: лента, разрезанная надвое

    Намерение разговора («она обещала фото») ищется по тексту истории, а история
    накапливается — та же реплика поднимает ту же тему на каждом ответе. Отличает
    новое обещание от старого только **время**: оно сказано позже прошлого
    намерения.

    Поэтому промпт получает **обе** половины: «до намерений» (`until=отметка`) и
    «свежую» (`since=отметка`). Модель видит разговор целиком — без этого
    короткое «а можешь ещё раз?» непонятно вовсе, — но ищет новое только во
    второй половине.

    ⚠ Границы **не пересекаются**: `since` строго больше, `until` включительно.
    Одна и та же строка в обе половины не попадёт, иначе модель приняла бы её за
    повтор.

    ⚠ Отметка сверяется с тем же временем, по которому лента упорядочена
    (`question_at`, у нашей реплики — `answer_at`). Сортируй мы по одному, а режь
    по другому — половины разошлись бы с порядком строк.

    ⚠⚠ Граница стоит **до предела** (`LIMIT`), а не после: отсеки мы после
    выборки, «последние двадцать» считались бы до среза, и свежая половина
    выходила бы тем короче, чем длиннее разговор.

    ## Что видит агент

        [16.09 21:04] он: Спорим, ты сейчас улыбнулся?
        [17.09 08:12] она: Улыбнулся. Как тебя зовут?

    ## ⚠⚠ Монолог — это не история, и отдавать его нельзя

    Порог считает реплики **собеседника**, а не строки ленты. Разговор, где
    говорили только мы (инвайт, рассылка, письмо без ответа), даёт ленту из
    одних своих слов — и агент, получив её, продолжает несуществующий диалог:
    ссылается на «как я говорила вчера» там, где человек не сказал ещё ничего.
    Пустая лента в этом случае честнее: агент заговорит как при первом
    знакомстве, то есть как оно и есть.

    Отсюда и умолчание `1`: хотя бы одна его реплика. Нужна лента с первого
    слова, без порога — передать `0`.

    ⚠ Считается в **той самой ленте, что вернётся**, а не во всём разговоре.
    `limit` отрезает хвост переписки, и спроси мы про весь разговор, порог
    пропускал бы окно, в котором его реплик нет ни одной, — то есть отвечал бы
    не про то, что увидит модель.

    ⚠ Реплика считается по тексту, а не по строке базы: у обмена две половины, и
    пустая половина собеседника — обычное дело (две трети строк установки это
    наши инвайты и письма).

    ⚠ Порог **не досматривает глубже предела**. Лента в 20 обменов без его слов
    и лента в 200 без его слов — для агента одно и то же: продолжать нечего.

    ⚠ **Время в строке обязательно.** Без него агент не отличит «ответил через
    минуту» от «ответил через неделю», а это разные разговоры: во втором случае
    продолжать с полуслова значит выдать робота.

    ⚠ **«Она» и «он», а не имена.** Имя девушки у агента есть переменной, а имя
    собеседника приходит не всегда — у трети людей в ленте оно нелатинское или
    пустое. Роль же не пустеет никогда.

    ⚠ **Старое сверху.** Так читают диалог глаза и так понимает его модель: в
    обратном порядке она отвечает на верхнюю строку, то есть на последнюю по
    времени.

    ⚠ **Не бросает.** Ответ без истории хуже, чем с историей, но лучше, чем
    молчание: сбой чтения отдаёт пустую строку, и агент отвечает как прежде — по
    одной реплике.
    """
    channel = str(kind or '').strip().lower()

    if channel not in COMPANION_SESSION_KINDS:
        channel = COMPANION_SESSION_KINDS[0]

    rows = await companion_session_rows(owner_unique_id, companion_unique_id,
                                        channel, limit, since=since, until=until)

    # ⚠ Порог приходит из workflow-переменной, то есть строкой: «3», а бывает и
    # пустая строка. Движок приводит по аннотации, но инструмент зовут и из кода
    # — своя проверка дешевле разбирательства «почему порог не сработал».
    try:
        at_least = int(companion_message_at_least or 0)
    except (TypeError, ValueError):
        at_least = 0

    if at_least > 0:
        said = sum(1 for row in rows if str(row.get('question') or '').strip())

        if said < at_least:
            return ''

    text_max = COMPANION_SESSION_TEXT_MAX[channel]
    lines = []

    for row in rows:
        lines.extend(_lines_of(row, text_max))

    return '\n'.join(lines)


async def companion_session_rows(owner_unique_id: str,
                                 companion_unique_id: str,
                                 kind: str = 'chat',
                                 limit: int = 0,
                                 since: str = '',
                                 until: str = '') -> list[dict]:
    """Те же обмены, но строками базы — для страниц и проверок.

    Отдельно от текста, потому что вопросы разные: промпту нужна одна строка, а
    тому, кто считает или показывает, — поля.

    Args:
        since: брать только позже этой отметки (строго); пусто — без границы.
        until: брать только не позже этой отметки; пусто — без границы.

    ⚠ Границы сверяются с тем же временем, по которому идёт сортировка
    (`COALESCE(question_at, answer_at)`): режь мы по одному полю, а упорядочивай
    по другому — половины разговора разошлись бы с его порядком. Зачем половины
    — `companion_session_history`.

    ⚠ **Берём последние, а отдаём по возрастанию.** `ORDER BY … DESC LIMIT`
    отбирает хвост разговора, `reversed` возвращает ему естественный порядок. Без
    первого мы взяли бы начало переписки вместо конца, без второго — модель
    отвечала бы на самую свежую строку как на самую важную.

    ## ⚠⚠ Неподтверждённый ответ не показывается

    `delivered_at IS NULL` значит «мы это сочинили, но собеседник не получил»:
    обмен пишется внутри прогона, а отправляет его DatingAi после. Показать
    такое агенту — заставить его продолжать несказанное.
    """
    owner_key = str(owner_unique_id or '').strip()
    companion_key = str(companion_unique_id or '').strip()

    if not owner_key or not companion_key:
        return []

    channel = str(kind or '').strip().lower()

    if channel not in COMPANION_SESSION_KINDS:
        channel = COMPANION_SESSION_KINDS[0]

    take = int(limit or 0) or COMPANION_SESSION_LIMIT
    take = max(1, min(take, COMPANION_SESSION_LIMIT_MAX))

    # ⚠ Границы собираются в условие ДО `LIMIT` — иначе предел отсчитывался бы
    # от всего разговора, и срезанная половина выходила бы короче заказанного.
    #
    # ⚠⚠ `since` строго больше, `until` включительно: так строка на самой
    # отметке достаётся ровно одной половине. Будь обе включительными, обмен, на
    # котором нашли прошлое намерение, попал бы и в «свежее» — и модель сочла бы
    # его новым обещанием.
    edges, args_edges = '', []

    if str(since or '').strip():
        edges += ' AND COALESCE(s.`question_at`, s.`answer_at`) > %s'
        args_edges.append(str(since).strip())

    if str(until or '').strip():
        edges += ' AND COALESCE(s.`question_at`, s.`answer_at`) <= %s'
        args_edges.append(str(until).strip())

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT s.`question`, s.`question_at`,'
                # ⚠⚠ **Отбор половиной, а не строкой.** Доставка бывает только у
                # нашей реплики: его слова доставлены самим фактом прихода.
                # Отбери мы строку целиком — вместе с неподтверждённым ответом
                # пропали бы и его слова, в том числе у «тишины», где нашего
                # ответа нет вовсе.
                #
                # ⚠⚠ `answer_deleted_at` — ответ, убранный человеком со страницы
                # «Сессии». Текст остаётся в базе (решение «лишний» принимает
                # человек и может ошибиться), но модели он не достаётся: ради
                # этого отметку и завели. Условие тут же, рядом с доставкой, —
                # обе про одно и то же: «эту половину агенту показывать нельзя».
                "       IF(s.`delivered_at` IS NULL"
                "          OR s.`answer_deleted_at` IS NOT NULL, '', s.`answer`)"
                '           AS `answer`,'
                '       s.`answer_at`'
                '  FROM `companion_session` s'
                '  JOIN `companion` o ON o.`id` = s.`owner_id`'
                '  JOIN `companion` c ON c.`id` = s.`companion_id`'
                ' WHERE o.`unique_id` = %s AND c.`unique_id` = %s'
                '   AND s.`kind` = %s'
                # ⚠⚠ **Строка, которой нечего показать, отсекается здесь — до
                # `LIMIT`.** Отсеки её после выборки, и «последние двадцать»
                # считали бы двадцать строк, из которых видимых три: лента
                # выходила бы короче предела тем сильнее, чем хуже доходили
                # ответы, — то есть ровно тогда, когда история нужнее всего.
                #
                # ⚠ Убранный ответ делает строку пустой ровно так же, как
                # недоставленный: если его реплики в обмене не было (инвайт,
                # письмо, наша инициатива), показывать больше нечего.
                "   AND (s.`question` <> ''"
                '        OR (s.`delivered_at` IS NOT NULL'
                '            AND s.`answer_deleted_at` IS NULL))'
                + edges +
                # ⚠ По времени, а не по `id`: перенесённые обмены ложатся в базу
                # позже, чем стоят в разговоре.
                ' ORDER BY COALESCE(s.`question_at`, s.`answer_at`) DESC,'
                '          s.`id` DESC'
                ' LIMIT %s',
                (owner_key, companion_key, channel, *args_edges, take))
            rows = await db.fetchall()
    except Exception:
        return []

    return list(reversed(rows or []))


async def companion_session_repeat_check(owner_unique_id: str,
                                         companion_unique_id: str,
                                         response: str,
                                         question: str = '',
                                         kind: str = 'chat',
                                         limit: int = 0) -> dict:
    """Не повторяет ли черновик того, что мы уже писали этому человеку.

    Анти-луп: «сплю уже» на каждое «ок». Повтор — когда выполнены **оба**
    условия: наш черновик повторяет один из последних ответов этой паре И его
    сообщение повторяет одно из прошлых. Один и тот же ответ на РАЗНЫЕ вопросы
    законен («да», «нет»), поэтому новое входящее снимает подозрение.

    Args:
        owner_unique_id: ключ нашей стороны (`companion.unique_id`).
        companion_unique_id: ключ той стороны.
        response: черновик ответа — до отправки и до записи обмена.
        question: что написал он сейчас. Пусто — заговорили мы сами.
        kind: `chat` или `mail` — каналы не смешиваются.
        limit: сколько последних обменов сравнивать. Ноль — умолчание.

    Returns:
        A dictionary with the check result.
        repeat (int): 1 — зацикливание, отвечать не надо; 0 — отвечать можно.
        why (str): чем кончилась проверка, словами — для трассы.

    ## ⚠⚠ Почему не по сессии

    Прежняя проверка (`session_response_repeat_check`) искала прошлые ответы в
    `agent_session` по `session_uuid`. Соседу этот ключ передавать нечем, и
    движок заводит новый на каждый запрос: 1062 прогона `dating_talk` — 1062
    разных сессии, 818 вызовов проверки и `repeat = 0` во всех 818. Сравнивать
    там было не с чем никогда.

    Разговор пары живёт не в сессии, а в `companion_session`, и адресуется он
    парой ключей. Отсюда и аргументы: те же, что у `companion_session_history`.

    ## ⚠⚠ Берём всё сказанное, а не видимое агенту

    `companion_session_rows` прячет недоставленное и убранное человеком — она
    собирает ленту для промпта, и показывать там несказанное нельзя. Здесь
    вопрос другой: **не сочиняли ли мы это уже**. Недоставленный ответ лежит в
    очереди и может уйти следом, убранный со страницы — мог уйти до того, как
    его убрали. Оба случая делают второй такой же ответ повтором, поэтому
    проверка смотрит строки как есть, своим запросом.

    ⚠ Цена различия измерена: у писем прода 462 ответа из 718 помечены убранными
    одним днём, 168 не подтверждены доставкой. Сравнивай проверка видимую ленту
    — она не нашла бы и четверти того, что мы писали.

    ## ⚠ Текущее сообщение в ленте уже может лежать

    Приём (`companion_session_incoming`) пишет реплику собеседника сразу, не
    дожидаясь ответа, — и тогда сравнение нашло бы её само в себе. Поэтому самое
    свежее его сообщение, если оно и есть переданное, из сравнения выпадает.

    ⚠ **Не бросает.** Сбой чтения даёт `repeat = 0`: промолчать по ошибке хуже,
    чем ответить дважды, — второе человек простит, первое выглядит как обрыв.
    """
    draft = _text_flat(response)

    if not draft:
        # Пустой черновик гасит не эта проверка, а шаги до неё: ей сравнивать
        # нечего, и «повтором» пустота не является.
        return {'repeat': 0, 'why': 'черновик пуст, сравнивать нечего'}

    channel = str(kind or '').strip().lower()

    if channel not in COMPANION_SESSION_KINDS:
        channel = COMPANION_SESSION_KINDS[0]

    # ⚠ Предел приходит из workflow-переменной, то есть строкой, и бывает
    # пустой. Движок приводит по аннотации, но инструмент зовут и из кода.
    try:
        take = int(limit or 0)
    except (TypeError, ValueError):
        take = 0

    take = take or COMPANION_SESSION_REPEAT_LIMIT
    take = max(1, min(take, COMPANION_SESSION_LIMIT_MAX))

    rows = await _said_rows(owner_unique_id, companion_unique_id, channel, take)

    if not rows:
        return {'repeat': 0, 'why': 'этому человеку мы в этом канале ещё не писали'}

    if not _said_among(draft, [row.get('answer') for row in rows]):
        return {'repeat': 0, 'why': 'такого мы ещё не писали'}

    incoming = _text_flat(question)

    if not incoming:
        # Заговорили мы сами — письмо избранному, инициатива, рассылка. Второго
        # условия у такого хода нет вовсе: сравнивать не с чем, и единственный
        # признак зацикливания — что этими же словами мы уже заговаривали.
        return {'repeat': 1, 'why': 'заговорили мы сами, и этими словами уже заговаривали'}

    if not _said_among(incoming, _asked_before(rows, incoming)):
        return {'repeat': 0, 'why': 'ответ повторяется, но спросил он о новом'}

    return {'repeat': 1, 'why': 'и ответ, и его сообщение повторяют сказанное раньше'}


async def _by_source(owner_id: int, kind: str, source_uid: str) -> int:
    """Номер уже записанного обмена с этим ключом источника; нет — ноль."""
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT `id` FROM `companion_session`'
                ' WHERE `owner_id` = %s AND `kind` = %s AND `source_uid` = %s'
                ' LIMIT 1', (int(owner_id), kind, source_uid))
            row = await db.fetchone()
    except Exception:
        return 0

    return int((row or {}).get('id') or 0)


async def _pending_absorb(owner_id: int, companion_id: int, kind: str,
                          question: str) -> int:
    """Убрать висящие реплики пары, уже вошедшие в этот вопрос.

    Returns:
        int: сколько строк убрано.

    ## ⚠⚠ ЗАЧЕМ

    Приём (`companion_session_incoming`) пишет реплику собеседника сразу, а
    через минуту агент отвечает — и шаг workflow кладёт обмен, где та же
    реплика стоит вопросом (автоответчик соседа склеивает хвост в
    `prompt_user`). Без уборки лента показала бы её дважды: висящей строкой и
    в составе обмена.

    ## ⚠⚠⚠ Границы узкие нарочно — это единственное место, где инструмент УДАЛЯЕТ

    Убирается строка, у которой сошлось **всё**:

        та же пара и тот же канал       чужой разговор не трогаем
        ответ пуст и доставки нет       наша половина не написана
        текст вопроса ВХОДИТ в новый    это ровно та реплика, что склеили
        не старше суток                 вчерашнее к сегодняшнему ответу не относится

    Любое из условий не сошлось — строка остаётся. Лишняя строка в ленте
    хуже, чем её отсутствие, но куда лучше, чем стёртая чужая реплика.

    ⚠ Сравнение по сжатым пробелам: склейка идёт через пустую строку, а внутри
    реплики переводы строк бывают свои — побайтово такое не совпадёт.

    ⚠ Своей ошибкой не роняем запись обмена: не вышло убрать — обмен всё равно
    пишется, в ленте будет повтор. Потерять ответ дороже.
    """
    text = ' '.join(str(question or '').split())

    if not text:
        return 0

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT `id`, `question` FROM `companion_session`'
                ' WHERE `owner_id` = %s AND `companion_id` = %s AND `kind` = %s'
                "   AND `answer` = '' AND `delivered_at` IS NULL"
                "   AND `question` <> ''"
                '   AND `created_at` >= %s',
                (int(owner_id), int(companion_id), kind,
                 datetime_utc_now() - timedelta(seconds=COMPANION_SESSION_PENDING_SEC)))
            rows = await db.fetchall()

            gone = [int(r['id']) for r in (rows or [])
                    if ' '.join(str(r['question'] or '').split()) in text]

            if not gone:
                return 0

            await db.execute(
                'DELETE FROM `companion_session` WHERE `id` IN ('
                + ', '.join(['%s'] * len(gone)) + ')', tuple(gone))
            await db.connection.commit()
    except Exception:
        return 0

    return len(gone)


def _moment(said_at: str):
    """Время реплики из строки запроса; не разобралось — сейчас.

    ⚠ UTC, как и всё остальное в таблице: `question_at` этой строки и
    `answer_at` соседней обязаны мериться одними часами.
    """
    text = str(said_at or '').strip()

    if not text:
        return datetime_utc_now()

    for shape in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(text[:19], shape)
        except ValueError:
            continue

    return datetime_utc_now()


async def _companion_id(unique_id: str) -> int:
    """Номер записи стороны; нет её — завести."""
    from src.tool.companion.companion import companion_create

    repo = CompanionRepository()
    found = await repo.find_one_by({'unique_id': unique_id})

    if found:
        return int(found.get('id') or 0)

    return int((await companion_create(unique_id)).get('id') or 0)


async def _said_rows(owner_unique_id: str, companion_unique_id: str,
                     kind: str, take: int) -> list[dict]:
    """Последние обмены пары как есть — вместе с недоставленным и убранным.

    Свежие сверху: сравнению порядок безразличен, а отбросить самую свежую его
    реплику (см. `_asked_before`) так дешевле.

    ⚠ Отдельный запрос, а не `companion_session_rows`: та показывает ленту
    агенту и потому прячет половины, которых он не говорил вслух. Проверке
    повтора нужны все — причина в докстринге `companion_session_repeat_check`.
    """
    owner_key = str(owner_unique_id or '').strip()
    companion_key = str(companion_unique_id or '').strip()

    if not owner_key or not companion_key:
        return []

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT s.`question`, s.`answer`'
                '  FROM `companion_session` s'
                '  JOIN `companion` o ON o.`id` = s.`owner_id`'
                '  JOIN `companion` c ON c.`id` = s.`companion_id`'
                ' WHERE o.`unique_id` = %s AND c.`unique_id` = %s'
                '   AND s.`kind` = %s'
                # ⚠ По времени, а не по `id`: перенесённые обмены ложатся в базу
                # позже, чем стоят в разговоре.
                ' ORDER BY COALESCE(s.`question_at`, s.`answer_at`) DESC,'
                '          s.`id` DESC'
                ' LIMIT %s',
                (owner_key, companion_key, kind, int(take)))
            rows = await db.fetchall()
    except Exception:
        return []

    return list(rows or [])


def _asked_before(rows: list[dict], incoming: str) -> list[str]:
    """Его прошлые реплики — без той, что он прислал прямо сейчас.

    ⚠⚠ «Прямо сейчас» — это **висящая** реплика: самая свежая строка, где его
    слова есть, а нашего ответа ещё нет. Такую пишет приём
    (`companion_session_incoming`), не дожидаясь ответа, и не выброси мы её —
    сообщение совпало бы само с собой, второе условие выполнялось бы всегда, и
    проверка гасила бы ответ на каждое новое сообщение.

    ⚠ По «первому совпадению» так не отличить: скажи он то же самое вчера, у той
    строки есть наш ответ — она прошлое, и прятать её нельзя, иначе настоящее
    зацикливание («ок» → «сплю уже» → «ок») осталось бы незамеченным.
    """
    rest = rows
    newest = rows[0] if rows else {}

    if (not str(newest.get('answer') or '').strip()
            and _text_flat(newest.get('question')) == incoming):
        rest = rows[1:]

    asked = [_text_flat(row.get('question')) for row in rest]

    return [said for said in asked if said]


def _said_among(text: str, said: list) -> bool:
    """Есть ли среди сказанного то же самое — точно или с точностью до слов."""
    for one in said:
        previous = _text_flat(one)

        if not previous:
            continue

        if previous == text:
            return True

        if SequenceMatcher(None, text, previous).ratio() >= COMPANION_SESSION_REPEAT_RATIO:
            return True

    return False


def _text_flat(text) -> str:
    """Реплика в виде, пригодном для сравнения.

    Нижний регистр, только буквы и цифры, пробелы схлопнуты: скобки, эмодзи и
    точки у повтора меняются, а слова — нет.
    """
    flat = re.sub(r'[^\w\s]+', '', str(text or '').lower(), flags=re.UNICODE)

    return re.sub(r'\s+', ' ', flat).strip()


def _lines_of(row: dict, text_max: int) -> list[str]:
    """Обмен строками ленты: вопрос и ответ идут порознь, как их и говорили."""
    made = []

    for half, who in (('question', 'он'), ('answer', 'она')):
        text = ' '.join(str(row.get(half) or '').split())[:text_max]

        if not text:
            continue

        when = row.get(f'{half}_at')
        stamp = f'[{when:%d.%m %H:%M}] ' if when else ''
        made.append(f'{stamp}{who}: {text}')

    return made

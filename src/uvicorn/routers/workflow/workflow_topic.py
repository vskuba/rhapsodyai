"""
Группы тем и темы внутри них: реестр, из которого читает шаг `topic_action`.

Группа — свод тем одного рода. Тема — запись внутри неё: метки-иглы, два порога,
вопросы и один текст инструкции.

⚠ Правила отбора темы живут не здесь, а в `src/ai/ai_workflow_topic_action.py`:
тут только хранение и контракт HTTP. Своя копия арифметики на странице или в
ручке разошлась бы с движком на первой же правке.

⚠ Модуль звался `workflow_branch`, ручки — `/workflow_branch/*`, права —
`workflow_branch:*`. Переименованы вместе со сносом старого рода шага: держать
имя «ветка» у того, что хранит темы, значило бы заставлять читающего держать в
голове словарь перевода.

⚠⚠ Миграции переименование НЕ потребовало, хотя выглядит так, будто должно.
Права живут в коде (`auth_role.py`, словарь `AUTH_ROLE_PERMISSIONS`), у таблицы
`role` только `id` и `name` — строки прав в данных не лежат нигде. Проверено
обходом всех текстовых колонок базы: совпадения нашлись лишь в журналах и в
истории миграций.

## ⚠⚠ Подпотока у ветки НЕТ — его выбирает шаг

Прежде ветка хранила `workflow_id`, и настройка вызова была разорвана пополам:
карты (`inputs_map`, `outputs_map`) человек правит на шаге, а кого они вызывают —
выбирал здесь, на другой вкладке. Карты принадлежат паре «шаг + подпоток»: имена
в них — переменные конкретного подпотока, и смена дороги из другого места
оставляла карты от прежней молча, без единой ошибки.

Поэтому отсюда ушли три вещи: приём `workflow_id` (его нет в `GROUP_COLUMNS`),
сверка контрактов при подмене и ручка «завести ветке скелет подпотока». Порядок
теперь прямой: человек заводит подпоток сам, на странице Workflow, и выбирает его
в шаге — там же, где настраивает карты.

⚠ Колонка `agent_workflow_topic_group.workflow_id` снесена миграцией
`20261010180756_branch_drop.sql` вместе с остальным мёртвым.
"""

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request

from i18n_.i18n_ import i18n_translit_cyr
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow_import import (AiWorkflowImportConflictError,
                                       AiWorkflowImportFailedError,
                                       AiWorkflowImportRejectedError)
from src.ai.ai_workflow_topic_export import (
    AiWorkflowTopicExportNodeMissingError, ai_workflow_topic_export_payload)
from src.ai.ai_workflow_topic_import import ai_workflow_topic_import_apply
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# Колонки, которые принимаются снаружи.
#
# ⚠ Белым списком, а не `**body`: `id`, `node_id` и отметки времени правит сервер,
# и присланное поле не должно их достать.
#
# ⚠⚠ `name` здесь НЕТ намеренно: код ветки правке не подлежит. В рантайме его не
# читает никто — ветку выбирают номером, — а живёт он в двух местах, где важна
# неизменность: имя скелета подпотока (`branch_deal`) и поиск ветки в
# миграциях-сидах (`WHERE name = 'deal'`). Переименуй его руками, и сид заведёт
# рядом вторую ветку вместо того, чтобы найти свою.
#
# ⚠⚠ `workflow_id` здесь НЕТ: подпоток выбирается на шаге (шапка модуля). Пока
# колонка жива, присланное поле не должно её достать — иначе у вопроса «куда
# ведёт ветка» снова стало бы два ответа.
# ⚠ `match_min` больше не принимается: порог уехал к теме, по одному на каждую.
# Пока словарь меток был один на ветку и выбирался ОДИН победитель, общий порог
# был осмыслен; теперь у темы свои метки и свои вопросы, и судится она
# независимо от соседей. Колонка доживает до сноса второй выкладкой.
GROUP_COLUMNS = ('title', 'description', 'is_enabled', 'position')

# ⚠ Набор полей темы одинаков во всех ветках. Дать ветке объявлять свои поля
# значило бы превратить вкладку в конструктор форм.
#
# ⚠⚠ Текст инструкции ОДИН. Прежде их было три — `acceptance` / `direction` /
# `restriction`, — и деление оказалось вымышленным: человек пишет инструкцию
# целиком, а раскладывать её по трём коробкам может только гадая, в какую ляжет
# «соглашайся, но не обещай часа». Старые колонки ещё стоят в схеме (снос —
# второй выкладкой), но сюда не принимаются: иначе у темы снова стало бы два
# места с инструкциями, и промпт читал бы одно, а человек правил другое.
TOPIC_COLUMNS = ('name', 'title', 'tags', 'tags_qty_accept',
                 'questions_qty_yes_accept', 'instructions', 'is_enabled', 'position')


@router.get("/workflow_topic/export")
async def workflow_topic_export(
        node_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_VIEW]))
):
    """Темы ноды одним файлом: группы, темы, вопросы.

    ⚠ Здесь только права и статус ошибки; формат файла и что в него едет — в
    `src/ai/ai_workflow_topic_export.py`, там и правят.
    """
    try:
        payload = await ai_workflow_topic_export_payload(node_id)
    except AiWorkflowTopicExportNodeMissingError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return {"result": payload}


@router.post("/workflow_topic/import")
async def workflow_topic_import(
        data: dict,
        node_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_CREATE,
                                  AuthPermission.WORKFLOW_TOPIC_UPDATE]))
):
    """Влить темы файла в ноду `node_id`, сливая по коду группы и темы.

    ⚠⚠ Нода — **довод запроса**, а не имя из файла: полезное действие здесь
    «перенести темы отсюда туда», в том числе между нодами одной установки.
    Имя ноды из файла не выбрасывается — расхождение приезжает в `notes`.

    ⚠ Права — create и update, без delete: импорт тем ничего не удаляет
    (`ai_workflow_topic_import.py`, шапка). Исключение — вопросы пришедших тем,
    они переписываются целиком, ровно как при правке темы с формы.
    """
    actor = getattr(user, 'username', None) or getattr(user, 'id', None)
    try:
        result = await ai_workflow_topic_import_apply(data, node_id, actor)
    except AiWorkflowImportRejectedError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except AiWorkflowImportConflictError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except AiWorkflowImportFailedError as error:
        raise HTTPException(status_code=500, detail=str(error))
    return {"status": "success", "result": result}


@router.get("/workflow_topic/topic/list")
async def workflow_topic_list_by_node(
        node_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_VIEW]))
):
    """Все темы ноды — одним списком, с именем ветки у каждой."""
    sql = """
        SELECT t.*, b.`name` AS `branch_name`, b.`title` AS `branch_title`
          FROM `agent_workflow_topic` t
          JOIN `agent_workflow_topic_group` b ON b.`id` = t.`topic_group_id`
         WHERE b.`node_id` = %s
         ORDER BY b.`position` ASC, t.`position` ASC
    """
    # ⚠⚠ Вопросы едут вместе со списком, а не только в карточке темы. Дерево
    # вкладки грузится этой ручкой, и форма рисует тему из её данных: оставь
    # вопросы одному `_topic_row` — и карточка откроется пустым списком, затерев
    # заведённое первым же сохранением. Поймано кадром, а не рассуждением.
    #
    # ⚠ Одним запросом на всю ноду, а не по теме в цикле: тем в ноде десятки.
    sql_questions = """
        SELECT q.`id`, q.`topic_id`, q.`question`, q.`is_enabled`, q.`position`
          FROM `agent_workflow_topic_question` q
          JOIN `agent_workflow_topic` t ON t.`id` = q.`topic_id`
          JOIN `agent_workflow_topic_group` b ON b.`id` = t.`topic_group_id`
         WHERE b.`node_id` = %s
         ORDER BY q.`position` ASC, q.`id` ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        rows = [dict(row) for row in await db.fetchall() or []]
        await db.execute(sql_questions, (node_id,))
        asked: dict = {}
        for item in await db.fetchall() or []:
            asked.setdefault(item['topic_id'], []).append(item)

    for row in rows:
        row['questions'] = asked.get(row['id'], [])
    return {"result": rows}


@router.get("/workflow_topic/{branch_id}/topic/list")
async def workflow_topic_of_group_list(
        branch_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_VIEW]))
):
    """Темы одной группы. ⚠ Без вопросов: их отдаёт список по ноде и карточка."""
    await _group_row(branch_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            """SELECT * FROM `agent_workflow_topic`
                WHERE `topic_group_id` = %s ORDER BY `position` ASC, `title` ASC""",
            (branch_id,)
        )
        rows = list(await db.fetchall() or [])
    return {"result": rows}


@router.post("/workflow_topic/{branch_id}/topic")
async def workflow_topic_create(
        branch_id: int,
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_CREATE]))
):
    """Завести тему в группе.

    Принимает, помимо имени и меток, два порога и список вопросов.

    ⚠ Пороги прижимаются к единице: ноль означал бы «подходит всегда», а это не
    порог. Клиент может прислать что угодно — решает здесь сервер.

    ⚠ `questions` необязателен: тема без вопросов законна и поднимается одними
    метками. Разбор списка — `_topic_questions_save`.
    """
    branch = await _group_row(branch_id)
    body = await request.json()

    name = str(body.get('name') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Нужен код темы')
    await _topic_name_free(branch['node_id'], name)

    async with mysql_get_db_async() as db:
        await db.execute(
            """INSERT INTO `agent_workflow_topic`
                      (`topic_group_id`, `name`, `title`, `tags`,
                       `tags_qty_accept`, `questions_qty_yes_accept`,
                       `instructions`, `is_enabled`, `position`)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (branch_id, name, str(body.get('title') or name),
             str(body.get('tags') or ''),
             max(1, int(body.get('tags_qty_accept') or 1)),
             max(1, int(body.get('questions_qty_yes_accept') or 1)),
             body.get('instructions') or None,
             int(body.get('is_enabled', 1)),
             int(body.get('position') or 0))
        )
        topic_id = db.lastrowid

    if 'questions' in body:
        await _topic_questions_save(topic_id, body.get('questions'))

    return {"result": await _topic_row(topic_id)}


@router.put("/workflow_topic/topic/reorder")
async def workflow_topic_reorder(
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_UPDATE]))
):
    """Разложить темы по группам и порядку — как их перетащили на вкладке.

    Тело: `{"positions": [{"id": 7, "topic_group_id": 3, "position": 1}, …]}`.
    Приезжают **все темы затронутых групп**, а не одна переехавшая: порядок —
    свойство списка, и прислать его можно только списком.

    ⚠⚠ Объявлена **выше** `PUT /workflow_topic/topic/{topic_id}`: FastAPI
    разбирает пути в порядке объявления, и ниже слово `reorder` попало бы в
    `topic_id` — ответом был бы 422 на исправный запрос.

    ⚠⚠ Порядок внутри группы — **не украшение**: в нём шаг темы отдаёт
    инструкции накопителю (`ai_workflow_topic_action_topics_raised`). Поэтому
    перестановка это правка содержимого, а не вида.

    ⚠ Все группы — одной ноды, и той же, что у самих тем. Код темы уникален в
    пределах ноды (`_topic_name_free`), и переезд в чужую ноду молча завёл бы
    там второй `photo_send`.
    """
    body = await request.json()
    rows = _reorder_rows_read(body.get('positions'))
    if not rows:
        return {"result": {"moved": 0}}

    await _reorder_one_node_check(rows)

    async with mysql_get_db_async() as db:
        for row in rows:
            await db.execute(
                "UPDATE `agent_workflow_topic` SET `topic_group_id` = %s, `position` = %s "
                "WHERE `id` = %s",
                (row['topic_group_id'], row['position'], row['id'])
            )

    return {"result": {"moved": len(rows)}}


@router.put("/workflow_topic/topic/{topic_id}")
async def workflow_topic_update(
        topic_id: int,
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_UPDATE]))
):
    """Править тему: любые поля из `TOPIC_COLUMNS` и список вопросов.

    ⚠⚠ Вопросы идут **мимо** `TOPIC_COLUMNS`: это не колонка темы, а своя
    таблица. Ключ `questions` есть — список переписывается целиком (пустой
    чистит), ключа нет — вопросы не трогаются вовсе: форма могла прислать одни
    пороги.
    """
    topic = await _topic_row(topic_id)
    branch = await _group_row(topic['topic_group_id'])
    body = await request.json()

    # ⚠ Вопросы идут мимо `TOPIC_COLUMNS`: это не колонка темы, а своя таблица.
    # Ключ есть — переписываем целиком (пустой список чистит), ключа нет — не
    # трогаем вовсе: форма могла прислать одни пороги.
    if 'questions' in body:
        await _topic_questions_save(topic_id, body.get('questions'))

    fields = {key: body[key] for key in TOPIC_COLUMNS if key in body}
    if not fields:
        return {"result": await _topic_row(topic_id)}

    if 'name' in fields:
        name = str(fields['name'] or '').strip()
        if not name:
            raise HTTPException(status_code=400, detail='Код темы не может быть пустым')
        await _topic_name_free(branch['node_id'], name, topic_id)
        fields['name'] = name

    # ⚠ Имена колонок уходят в SQL текстом — только из `TOPIC_COLUMNS`.
    sets = ', '.join(f"`{key}` = %s" for key in fields)
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE `agent_workflow_topic` SET {sets} WHERE `id` = %s",
            (*fields.values(), topic_id)
        )

    return {"result": await _topic_row(topic_id)}


@router.delete("/workflow_topic/topic/{topic_id}")
async def workflow_topic_delete(
        topic_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_DELETE]))
):
    await _topic_row(topic_id)
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM `agent_workflow_topic` WHERE `id` = %s", (topic_id,))
    return {"result": {"deleted": topic_id}}


@router.get("/workflow_topic/list")
async def workflow_topic_group_list(
        node_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_VIEW]))
):
    sql = """
        SELECT b.*,
               (SELECT COUNT(*) FROM `agent_workflow_topic` t
                 WHERE t.`topic_group_id` = b.`id`) AS `topic_count`
          FROM `agent_workflow_topic_group` b
         WHERE b.`node_id` = %s
         ORDER BY b.`position` ASC, b.`title` ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        rows = list(await db.fetchall() or [])
    return {"result": rows}


@router.get("/workflow_topic/road/list")
async def workflow_topic_road_list(
        node_id: int | None = None,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_VIEW]))
):
    """Подпотоки, которые кто-то из шагов `branch` зовёт своей дорогой.

    Args:
        node_id: ограничить ответ одной нодой; без него — вся установка.

    Returns:
        dict: `result` — номера workflow строками, без повторов.

    ## ⚠⚠ Без `node_id` — не «на всякий случай», а потому что вопрос не про ноду

    Спрашивающий держит список **всех** workflow сразу: левая колонка страницы
    Workflow листается каруселью нод, и дорога соседней ноды нужна ей ровно так
    же, как дорога открытой. Пока ручку звали по ноде, реестр на странице
    перетирался при каждом открытии workflow — и подпоток чужой ноды оставался
    без ответа, то есть с красным «!» на живых `topic_action_*`.

    ## ⚠⚠ Зачем ручка, если дорога лежит в метаданных шага

    Спрашивающий знает НЕ ТО. Вопрос у него обратный: «открытый workflow — он
    чья-то дорога?» Ответ на него — в чужих шагах, в других workflow той же
    ноды, и страница их не грузит. Прежде ответ давал реестр веток одним
    запросом (`branch.workflow_id`); теперь дорога на шаге, и собрать её может
    только сервер.

    Спрашивают двое, и оба про одно: список переменных — показывать ли группу
    «🌿 Branch переменные», и сторож «Undefined» — снимать ли с `topic_*` красный.
    Ошибись здесь, и `%topic_instructions%` в промпте дороги горел бы «нигде не
    заведена», человек завёл бы её руками — и заведённая пустой **перекрыла** бы
    приехавшую от шага.

    ⚠ Разбор JSON в Python, а не `JSON_EXTRACT` в SQL: на единственной битой
    строке метаданных запрос упал бы целиком, унеся ответ про все остальные.
    Шагов `branch` на установке единицы — цена разбора здесь никакая.
    """
    sql = """
        SELECT s.`metadata`
          FROM `agent_workflow_step` s
          JOIN `agent_workflow` w ON w.`id` = s.`workflow_id`
          JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id`
         WHERE t.`name` IN ('branch', 'topic_action')
    """
    params = ()
    if node_id is not None:
        sql += " AND w.`node_id` = %s"
        params = (node_id,)

    async with mysql_get_db_async() as db:
        await db.execute(sql, params)
        rows = list(await db.fetchall() or [])

    roads = []
    for row in rows:
        try:
            meta = json.loads(row.get('metadata') or '{}')
        except (TypeError, ValueError):
            continue

        # ⚠⚠ Оба рода шага сразу. Пока спрашивался один `branch`, подпоток
        # переведённого шага выпадал из реестра дорог — а на нём держится
        # группа «Topic & Action переменные» в редакторе: восемь приезжающих
        # имён горели «не объявлена», и человек завёл бы их руками. Заведённая
        # пустой перекрыла бы приехавшую (`workflow_topic.md`).
        road = ((meta.get('topic_action') or meta.get('branch') or {})
                .get('workflow_id'))
        if road and str(road) not in roads:
            roads.append(str(road))

    return {"result": roads}


@router.post("/workflow_topic")
async def workflow_topic_group_create(
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_CREATE]))
):
    """Завести группу тем в ноде.

    ⚠ Порога у группы больше нет: он уехал к теме, по два на каждую. Пока
    колонка `match_min` жива, присланное поле её не достаёт — см. `GROUP_COLUMNS`.
    """
    body = await request.json()
    node_id = int(body.get('node_id') or 0)
    title = str(body.get('title') or '').strip()
    if not node_id or not title:
        raise HTTPException(status_code=400, detail='Нужны node_id и title')

    # Код задаётся явно только сидами и импортом; со страницы его не присылают —
    # там человек вводит одно название
    name = str(body.get('name') or '').strip() or await _branch_code_make(node_id, title)

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT `id` FROM `agent_workflow_topic_group` WHERE `node_id` = %s AND `name` = %s",
            (node_id, name)
        )
        if await db.fetchone():
            raise HTTPException(status_code=400, detail='Ветка с таким именем в ноде уже есть')

        await db.execute(
            """INSERT INTO `agent_workflow_topic_group`
                      (`node_id`, `name`, `title`, `description`,
                       `is_enabled`, `position`)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (node_id, name, title,
             body.get('description') or None,
             int(body.get('is_enabled', 1)),
             int(body.get('position') or 0))
        )
        branch_id = db.lastrowid

    return {"result": await _group_row(branch_id)}


@router.put("/workflow_topic/{branch_id}")
async def workflow_topic_group_update(
        branch_id: int,
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_UPDATE]))
):
    body = await request.json()
    branch = await _group_row(branch_id)

    fields = {key: body[key] for key in GROUP_COLUMNS if key in body}
    if not fields:
        return {"result": branch}

    if 'title' in fields and not str(fields['title'] or '').strip():
        raise HTTPException(status_code=400, detail='Название ветки не может быть пустым')

    # ⚠ Имена колонок уходят в SQL текстом — потому и берутся только из
    # `GROUP_COLUMNS`, а не из тела запроса.
    sets = ', '.join(f"`{key}` = %s" for key in fields)
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE `agent_workflow_topic_group` SET {sets} WHERE `id` = %s",
            (*fields.values(), branch_id)
        )

    return {"result": await _group_row(branch_id)}


@router.delete("/workflow_topic/{branch_id}")
async def workflow_topic_group_delete(
        branch_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TOPIC_DELETE]))
):
    await _group_row(branch_id)
    async with mysql_get_db_async() as db:
        # ⚠ Темы уносит каскад внешнего ключа — отдельного DELETE не нужно.
        await db.execute("DELETE FROM `agent_workflow_topic_group` WHERE `id` = %s", (branch_id,))
    return {"result": {"deleted": branch_id}}


async def _branch_code_make(node_id: int, title: str) -> str:
    """Код ветки из её названия: «Договориться» → `dogovoritsya`.

    ⚠ Транслит берётся общей `i18n_translit_cyr` — она заведена ровно для
    устойчивых идентификаторов и меняться не должна: по её выводу заводят
    записи, которые потом ищут по имени.

    ⚠ Занятый код получает номер (`dogovoritsya_2`), а не отказ: человек назвал
    ветку как хотел, и спорить с ним из-за служебного поля не о чем.
    """
    base = re.sub(r'[^a-z0-9]+', '_', i18n_translit_cyr(title).lower()).strip('_')[:40]
    base = base or 'branch'

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT `name` FROM `agent_workflow_topic_group` WHERE `node_id` = %s", (node_id,))
        taken = {row['name'] for row in await db.fetchall() or []}

    code, number = base, 2
    while code in taken:
        code = f'{base}_{number}'
        number += 1
    return code


async def _group_row(branch_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT * FROM `agent_workflow_topic_group` WHERE `id` = %s", (branch_id,))
        row = await db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Ветка не найдена')
    return row


async def _topic_row(topic_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT * FROM `agent_workflow_topic` WHERE `id` = %s", (topic_id,))
        row = await db.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Тема не найдена')
        # ⚠ Вопросы едут вместе с темой, а не отдельной ручкой: форма правит их
        # в одной карточке с метками и порогами, и второй поход за ними означал
        # бы показ темы без вопросов на время загрузки.
        await db.execute(
            """SELECT `id`, `question`, `is_enabled`, `position`
                 FROM `agent_workflow_topic_question`
                WHERE `topic_id` = %s ORDER BY `position` ASC, `id` ASC""",
            (topic_id,)
        )
        row = dict(row)
        row['questions'] = list(await db.fetchall() or [])
    return row


async def _topic_questions_save(topic_id: int, questions) -> None:
    """Переписать вопросы темы целиком списком, пришедшим с формы.

    ⚠⚠ Полная замена, а не правка по одному. Форма показывает список целиком и
    отдаёт его целиком; разбор «что добавили, что удалили, что переехало» на
    стороне сервера требовал бы от неё слать id каждой строки и порядок — то
    есть вести учёт, который ей вести незачем.

    ⚠ Пустой список — законное состояние, а не «ничего не прислали»: тема без
    вопросов поднимается одними метками. Отличает их вызывающий: ключа нет в
    теле — не трогаем, ключ есть и пуст — чистим.
    """
    rows = []
    for position, item in enumerate(questions or [], 1):
        text = str((item or {}).get('question') or '').strip()
        if not text:
            continue
        rows.append((topic_id, text, int((item or {}).get('is_enabled', 1)), position))

    async with mysql_get_db_async() as db:
        await db.execute(
            "DELETE FROM `agent_workflow_topic_question` WHERE `topic_id` = %s",
            (topic_id,))
        for row in rows:
            await db.execute(
                """INSERT INTO `agent_workflow_topic_question`
                          (`topic_id`, `question`, `is_enabled`, `position`)
                   VALUES (%s, %s, %s, %s)""",
                row
            )


def _reorder_rows_read(positions) -> list:
    """Разобрать присланную раскладку: номер темы, номер группы, место в ней.

    ⚠ Строка без номера темы или группы молча пропускается, а не роняет запрос:
    список собирает страница обходом DOM, и одна недоразобранная строка не
    повод отменять перестановку остальных. Непохожее на число — отказ: это уже
    не «чего-то не хватило», а чужой запрос.
    """
    rows, seen = [], set()
    for item in positions or []:
        if not isinstance(item, dict):
            continue
        if item.get('id') is None or item.get('topic_group_id') is None:
            continue
        try:
            topic_id = int(item['id'])
            group_id = int(item['topic_group_id'])
            position = int(item.get('position') or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400,
                                detail='Раскладка тем: id, topic_group_id и position — числа')
        if topic_id in seen:
            raise HTTPException(status_code=400,
                                detail=f'Тема {topic_id} в раскладке дважды')
        seen.add(topic_id)
        rows.append({'id': topic_id, 'topic_group_id': group_id, 'position': position})
    return rows


async def _reorder_one_node_check(rows: list) -> None:
    """Темы и группы раскладки — одной ноды; иначе отказ до первой записи.

    ⚠⚠ Проверка не формальная. Перетащить тему в группу чужой ноды со страницы
    нельзя — там одна нода на экране, — но ручка открыта, а код темы уникален в
    пределах **ноды**. Переезд через границу завёл бы в чужой ноде второй
    `photo_send` в обход `_topic_name_free`, и узналось бы это из журнала
    прогона, где две темы под одним кодом.
    """
    topic_ids = [row['id'] for row in rows]
    group_ids = {row['topic_group_id'] for row in rows}

    async with mysql_get_db_async() as db:
        placeholders = ','.join(['%s'] * len(topic_ids))
        await db.execute(
            f"""SELECT t.`id`, g.`node_id`
                  FROM `agent_workflow_topic` t
                  JOIN `agent_workflow_topic_group` g ON g.`id` = t.`topic_group_id`
                 WHERE t.`id` IN ({placeholders})""",
            tuple(topic_ids)
        )
        found = {row['id']: row['node_id'] for row in await db.fetchall() or []}

        placeholders = ','.join(['%s'] * len(group_ids))
        await db.execute(
            f"SELECT `id`, `node_id` FROM `agent_workflow_topic_group` "
            f"WHERE `id` IN ({placeholders})",
            tuple(group_ids)
        )
        groups = {row['id']: row['node_id'] for row in await db.fetchall() or []}

    missing = [topic_id for topic_id in topic_ids if topic_id not in found]
    if missing:
        raise HTTPException(status_code=404,
                            detail=f'Тем нет: {", ".join(str(one) for one in missing)}')

    lost = [group_id for group_id in group_ids if group_id not in groups]
    if lost:
        raise HTTPException(status_code=404,
                            detail=f'Групп тем нет: {", ".join(str(one) for one in lost)}')

    nodes = set(found.values()) | set(groups.values())
    if len(nodes) > 1:
        raise HTTPException(
            status_code=400,
            detail='Темы и группы раскладки из разных нод — перестановка отменена')


async def _topic_name_free(node_id: int, name: str, topic_id: int = 0) -> None:
    """Код темы уникален в пределах НОДЫ, а не только ветки.

    ⚠ Ключ в базе держит пару «ветка + имя»: по коду тема называется в промптах и
    в журнале прогона, и два `money` в разных ветках сделали бы журнал
    нечитаемым. Поэтому вторая проверка — здесь, запросом по ветвям ноды.
    """
    sql = """
        SELECT t.`id` FROM `agent_workflow_topic` t
          JOIN `agent_workflow_topic_group` b ON b.`id` = t.`topic_group_id`
         WHERE b.`node_id` = %s AND t.`name` = %s AND t.`id` <> %s
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id, name, topic_id))
        if await db.fetchone():
            raise HTTPException(status_code=400, detail='Тема с таким кодом в ноде уже есть')

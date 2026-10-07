"""
Ветки разговора и темы внутри них: реестр, из которого читает шаг `branch`.

Ветка — род разговора: имя, порог совпадений и темы. Тема — запись внутри ветки:
метки и три текста (разрешено / желательно / запрещено).

⚠ Правила выбора темы живут не здесь, а в `src/ai/ai_workflow_branch.py`: тут
только хранение и контракт HTTP. Своя копия арифметики на странице или в ручке
разошлась бы с движком на первой же правке.

## ⚠⚠ Подпотока у ветки НЕТ — его выбирает шаг

Прежде ветка хранила `workflow_id`, и настройка вызова была разорвана пополам:
карты (`inputs_map`, `outputs_map`) человек правит на шаге, а кого они вызывают —
выбирал здесь, на другой вкладке. Карты принадлежат паре «шаг + подпоток»: имена
в них — переменные конкретного подпотока, и смена дороги из другого места
оставляла карты от прежней молча, без единой ошибки.

Поэтому отсюда ушли три вещи: приём `workflow_id` (его нет в `BRANCH_COLUMNS`),
сверка контрактов при подмене и ручка «завести ветке скелет подпотока». Порядок
теперь прямой: человек заводит подпоток сам, на странице Workflow, и выбирает его
в шаге — там же, где настраивает карты.

⚠ Колонка `agent_workflow_branch.workflow_id` пока жива: снос едет второй
выкладкой (`deploy.md`). Читателей у неё не осталось.
"""

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request

from i18n_.i18n_ import i18n_translit_cyr
from mysql_.mysql_ import mysql_get_db_async
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
BRANCH_COLUMNS = ('title', 'description', 'match_min', 'is_enabled', 'position')

# ⚠ Набор полей темы одинаков во всех ветках. Дать ветке объявлять свои поля
# значило бы превратить вкладку в конструктор форм, а смысл слоя — ровно в трёх
# текстах: разрешено, желательно, запрещено.
TOPIC_COLUMNS = ('name', 'title', 'tags', 'acceptance', 'direction', 'restriction',
                 'is_enabled', 'position')


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
            "SELECT `name` FROM `agent_workflow_branch` WHERE `node_id` = %s", (node_id,))
        taken = {row['name'] for row in await db.fetchall() or []}

    code, number = base, 2
    while code in taken:
        code = f'{base}_{number}'
        number += 1
    return code


async def _branch_row(branch_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT * FROM `agent_workflow_branch` WHERE `id` = %s", (branch_id,))
        row = await db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Ветка не найдена')
    return row


async def _topic_row(topic_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT * FROM `agent_workflow_branch_topic` WHERE `id` = %s", (topic_id,))
        row = await db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Тема не найдена')
    return row


async def _topic_name_free(node_id: int, name: str, topic_id: int = 0) -> None:
    """Код темы уникален в пределах НОДЫ, а не только ветки.

    ⚠ Ключ в базе держит пару «ветка + имя»: по коду тема называется в промптах и
    в журнале прогона, и два `money` в разных ветках сделали бы журнал
    нечитаемым. Поэтому вторая проверка — здесь, запросом по ветвям ноды.
    """
    sql = """
        SELECT t.`id` FROM `agent_workflow_branch_topic` t
          JOIN `agent_workflow_branch` b ON b.`id` = t.`branch_id`
         WHERE b.`node_id` = %s AND t.`name` = %s AND t.`id` <> %s
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id, name, topic_id))
        if await db.fetchone():
            raise HTTPException(status_code=400, detail='Тема с таким кодом в ноде уже есть')


@router.get("/workflow_branch/topic/list")
async def workflow_branch_topic_list_by_node(
        node_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_VIEW]))
):
    """Все темы ноды — одним списком, с именем ветки у каждой."""
    sql = """
        SELECT t.*, b.`name` AS `branch_name`, b.`title` AS `branch_title`,
               b.`match_min`
          FROM `agent_workflow_branch_topic` t
          JOIN `agent_workflow_branch` b ON b.`id` = t.`branch_id`
         WHERE b.`node_id` = %s
         ORDER BY b.`position` ASC, t.`position` ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        rows = list(await db.fetchall() or [])
    return {"result": rows}


@router.get("/workflow_branch/{branch_id}/topic/list")
async def workflow_branch_topic_list(
        branch_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_VIEW]))
):
    await _branch_row(branch_id)
    async with mysql_get_db_async() as db:
        await db.execute(
            """SELECT * FROM `agent_workflow_branch_topic`
                WHERE `branch_id` = %s ORDER BY `position` ASC, `title` ASC""",
            (branch_id,)
        )
        rows = list(await db.fetchall() or [])
    return {"result": rows}


@router.post("/workflow_branch/{branch_id}/topic")
async def workflow_branch_topic_create(
        branch_id: int,
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_CREATE]))
):
    branch = await _branch_row(branch_id)
    body = await request.json()

    name = str(body.get('name') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Нужен код темы')
    await _topic_name_free(branch['node_id'], name)

    async with mysql_get_db_async() as db:
        await db.execute(
            """INSERT INTO `agent_workflow_branch_topic`
                      (`branch_id`, `name`, `title`, `tags`, `acceptance`,
                       `direction`, `restriction`, `is_enabled`, `position`)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (branch_id, name, str(body.get('title') or name),
             str(body.get('tags') or ''),
             body.get('acceptance') or None,
             body.get('direction') or None,
             body.get('restriction') or None,
             int(body.get('is_enabled', 1)),
             int(body.get('position') or 0))
        )
        topic_id = db.lastrowid

    return {"result": await _topic_row(topic_id)}


@router.put("/workflow_branch/topic/{topic_id}")
async def workflow_branch_topic_update(
        topic_id: int,
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_UPDATE]))
):
    topic = await _topic_row(topic_id)
    branch = await _branch_row(topic['branch_id'])
    body = await request.json()

    fields = {key: body[key] for key in TOPIC_COLUMNS if key in body}
    if not fields:
        return {"result": topic}

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
            f"UPDATE `agent_workflow_branch_topic` SET {sets} WHERE `id` = %s",
            (*fields.values(), topic_id)
        )

    return {"result": await _topic_row(topic_id)}


@router.delete("/workflow_branch/topic/{topic_id}")
async def workflow_branch_topic_delete(
        topic_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_DELETE]))
):
    await _topic_row(topic_id)
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM `agent_workflow_branch_topic` WHERE `id` = %s", (topic_id,))
    return {"result": {"deleted": topic_id}}


@router.get("/workflow_branch/list")
async def workflow_branch_list(
        node_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_VIEW]))
):
    sql = """
        SELECT b.*,
               (SELECT COUNT(*) FROM `agent_workflow_branch_topic` t
                 WHERE t.`branch_id` = b.`id`) AS `topic_count`
          FROM `agent_workflow_branch` b
         WHERE b.`node_id` = %s
         ORDER BY b.`position` ASC, b.`title` ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        rows = list(await db.fetchall() or [])
    return {"result": rows}


@router.get("/workflow_branch/road/list")
async def workflow_branch_road_list(
        node_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_VIEW]))
):
    """Подпотоки, которые кто-то из шагов `branch` этой ноды зовёт своей дорогой.

    Returns:
        dict: `result` — номера workflow строками, без повторов.

    ## ⚠⚠ Зачем ручка, если дорога лежит в метаданных шага

    Спрашивающий знает НЕ ТО. Вопрос у него обратный: «открытый workflow — он
    чья-то дорога?» Ответ на него — в чужих шагах, в других workflow той же
    ноды, и страница их не грузит. Прежде ответ давал реестр веток одним
    запросом (`branch.workflow_id`); теперь дорога на шаге, и собрать её может
    только сервер.

    Спрашивают двое, и оба про одно: список переменных — показывать ли группу
    «🌿 Branch переменные», и сторож «Undefined» — снимать ли с `topic_*` красный.
    Ошибись здесь, и `%topic_accept%` в промпте дороги горел бы «нигде не
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
         WHERE w.`node_id` = %s AND t.`name` = 'branch'
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        rows = list(await db.fetchall() or [])

    roads = []
    for row in rows:
        try:
            meta = json.loads(row.get('metadata') or '{}')
        except (TypeError, ValueError):
            continue

        road = (meta.get('branch') or {}).get('workflow_id')
        if road and str(road) not in roads:
            roads.append(str(road))

    return {"result": roads}


@router.post("/workflow_branch")
async def workflow_branch_create(
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_CREATE]))
):
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
            "SELECT `id` FROM `agent_workflow_branch` WHERE `node_id` = %s AND `name` = %s",
            (node_id, name)
        )
        if await db.fetchone():
            raise HTTPException(status_code=400, detail='Ветка с таким именем в ноде уже есть')

        await db.execute(
            """INSERT INTO `agent_workflow_branch`
                      (`node_id`, `name`, `title`, `description`,
                       `match_min`, `is_enabled`, `position`)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (node_id, name, title,
             body.get('description') or None,
             int(body.get('match_min') or 1),
             int(body.get('is_enabled', 1)),
             int(body.get('position') or 0))
        )
        branch_id = db.lastrowid

    return {"result": await _branch_row(branch_id)}


@router.put("/workflow_branch/{branch_id}")
async def workflow_branch_update(
        branch_id: int,
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_UPDATE]))
):
    body = await request.json()
    branch = await _branch_row(branch_id)

    fields = {key: body[key] for key in BRANCH_COLUMNS if key in body}
    if not fields:
        return {"result": branch}

    if 'title' in fields and not str(fields['title'] or '').strip():
        raise HTTPException(status_code=400, detail='Название ветки не может быть пустым')

    # ⚠ Имена колонок уходят в SQL текстом — потому и берутся только из
    # `BRANCH_COLUMNS`, а не из тела запроса.
    sets = ', '.join(f"`{key}` = %s" for key in fields)
    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE `agent_workflow_branch` SET {sets} WHERE `id` = %s",
            (*fields.values(), branch_id)
        )

    return {"result": await _branch_row(branch_id)}


@router.delete("/workflow_branch/{branch_id}")
async def workflow_branch_delete(
        branch_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_DELETE]))
):
    await _branch_row(branch_id)
    async with mysql_get_db_async() as db:
        # ⚠ Темы уносит каскад внешнего ключа — отдельного DELETE не нужно.
        await db.execute("DELETE FROM `agent_workflow_branch` WHERE `id` = %s", (branch_id,))
    return {"result": {"deleted": branch_id}}

"""
Ветки разговора и темы внутри них: реестр, из которого читает шаг `branch`.

Ветка — род разговора со своим контрактом и необязательным subflow. Тема —
запись внутри ветки: метки и три текста (разрешено / желательно / запрещено).

⚠ Правила выбора темы живут не здесь, а в `src/ai/ai_workflow_branch.py`: тут
только хранение и контракт HTTP. Своя копия арифметики на странице или в ручке
разошлась бы с движком на первой же правке.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# Колонки, которые принимаются снаружи.
#
# ⚠ Белым списком, а не `**body`: `id`, `node_id` и отметки времени правит сервер,
# и присланное поле не должно их достать.
BRANCH_COLUMNS = ('name', 'title', 'description', 'workflow_id', 'match_min',
                  'is_enabled', 'position')

# ⚠ Набор полей темы одинаков во всех ветках. Дать ветке объявлять свои поля
# значило бы превратить вкладку в конструктор форм, а смысл слоя — ровно в трёх
# текстах: разрешено, желательно, запрещено.
TOPIC_COLUMNS = ('name', 'title', 'tags', 'acceptance', 'direction', 'restriction',
                 'is_enabled', 'position')


async def _branch_row(branch_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT * FROM `agent_workflow_branch` WHERE `id` = %s", (branch_id,))
        row = await db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Ветка не найдена')
    return row


async def _branch_contract_check(branch_id: int, workflow_id: int) -> None:
    """Совпадает ли контракт subflow с контрактом ветки.

    ⚠ Заглушка до задачи 7: проверка появится вместе с кнопкой «Создать subflow».
    Пока привязка принимается как есть.
    """
    return None


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
               b.`match_min`, b.`workflow_id`
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


@router.post("/workflow_branch")
async def workflow_branch_create(
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_CREATE]))
):
    body = await request.json()
    node_id = int(body.get('node_id') or 0)
    name = str(body.get('name') or '').strip()
    if not node_id or not name:
        raise HTTPException(status_code=400, detail='Нужны node_id и name')

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT `id` FROM `agent_workflow_branch` WHERE `node_id` = %s AND `name` = %s",
            (node_id, name)
        )
        if await db.fetchone():
            raise HTTPException(status_code=400, detail='Ветка с таким именем в ноде уже есть')

        await db.execute(
            """INSERT INTO `agent_workflow_branch`
                      (`node_id`, `name`, `title`, `description`, `workflow_id`,
                       `match_min`, `is_enabled`, `position`)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (node_id, name, str(body.get('title') or name),
             body.get('description') or None,
             body.get('workflow_id') or None,
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

    if 'name' in fields:
        name = str(fields['name'] or '').strip()
        if not name:
            raise HTTPException(status_code=400, detail='Имя ветки не может быть пустым')
        async with mysql_get_db_async() as db:
            await db.execute(
                """SELECT `id` FROM `agent_workflow_branch`
                    WHERE `node_id` = %s AND `name` = %s AND `id` <> %s""",
                (branch['node_id'], name, branch_id)
            )
            if await db.fetchone():
                raise HTTPException(status_code=400, detail='Ветка с таким именем в ноде уже есть')
        fields['name'] = name

    if fields.get('workflow_id'):
        await _branch_contract_check(branch_id, int(fields['workflow_id']))

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

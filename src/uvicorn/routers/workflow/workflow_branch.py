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

"""
Ветки разговора и темы внутри них: реестр, из которого читает шаг `branch`.

Ветка — род разговора со своим контрактом и необязательным subflow. Тема —
запись внутри ветки: метки и три текста (разрешено / желательно / запрещено).

⚠ Правила выбора темы живут не здесь, а в `src/ai/ai_workflow_branch.py`: тут
только хранение и контракт HTTP. Своя копия арифметики на странице или в ручке
разошлась бы с движком на первой же правке.
"""

import json

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

STEP_TYPE_LLM_TO_JSON = 2
STEP_TYPE_RETURN_TEXT = 4

# Начальный контракт ветки: что передаёт вызывающий и что он забирает обратно.
#
# ⚠ Семи `topic_*` здесь нет намеренно — их шаг `branch` протаскивает сам,
# сквозными значениями, и объявлять их ребёнку не требуется: тем же приёмом
# движок протаскивает `user_language`.
BRANCH_SKELETON_INPUTS = ('prompt_user', 'talk_history', 'companion_title',
                          'girl_name', 'user_language')
BRANCH_SKELETON_OUTPUTS = ('branch_response', 'branch_result')

BRANCH_SKELETON_PROMPT = (
    '=== %companion_title% пишет ===\n%prompt_user%\n\n'
    '%if talk_history%=== Разговор с этим человеком ===\n%talk_history%\n\n%endif%'
    '=== Что нужно ===\n'
    '%if topic_accept%%topic_accept%\n\n%endif%'
    '%if topic_direction%Куда вести разговор: %topic_direction%\n\n%endif%'
    '%if topic_restrict%⚠ Нельзя: %topic_restrict%\n\n%endif%'
    'Отвечай строго на языке: %user_language%.\n\n'
    '=== Important information about final response ===\n'
    'Please return your response in JSON format. The JSON response must contain '
    'follow keys: \n'
    '- "branch_response": твой ответ\n'
    '- "branch_result": чем кончилось, одним словом\n\n'
    'Example of JSON response:\n'
    '{\n  "branch_response": "of course, send them",\n  "branch_result": "agreed"\n}'
)


async def _branch_row(branch_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT * FROM `agent_workflow_branch` WHERE `id` = %s", (branch_id,))
        row = await db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Ветка не найдена')
    return row


async def _workflow_contract(workflow_id: int) -> dict:
    """Объявленный контракт workflow: имена входов и выходов."""
    async with mysql_get_db_async() as db:
        await db.execute(
            """SELECT `name`, `type` FROM `agent_workflow_variable`
                WHERE `workflow_id` = %s AND `type` IN ('input', 'output')""",
            (workflow_id,)
        )
        rows = await db.fetchall() or []
    return {
        'input': sorted(row['name'] for row in rows if row['type'] == 'input'),
        'output': sorted(row['name'] for row in rows if row['type'] == 'output'),
    }


async def _branch_contract_check(branch_id: int, workflow_id: int) -> None:
    """Совпадает ли контракт нового subflow с тем, что у ветки уже был.

    ⚠⚠ Отдельного хранилища контракта у ветки нет — он и есть `input`/`output`
    переменные её subflow. Поэтому первый привязанный subflow контракт
    **задаёт**, а подмена требует совпадения: шаги `branch` в workflow уже несут
    карты, собранные под прежние имена, и молча разошлись бы с новым ребёнком.
    Движок узнал бы об этом только в проде, отказом на непереданном входе.
    """
    branch = await _branch_row(branch_id)
    current = branch.get('workflow_id')
    if not current or int(current) == int(workflow_id):
        return

    was = await _workflow_contract(int(current))
    now = await _workflow_contract(int(workflow_id))
    if was == now:
        return

    raise HTTPException(
        status_code=400,
        detail=('Контракт subflow не совпадает с контрактом ветки: '
                f"было входы {was['input']}, выходы {was['output']}; "
                f"стало входы {now['input']}, выходы {now['output']}")
    )


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


@router.post("/workflow_branch/{branch_id}/subflow")
async def workflow_branch_subflow_create(
        branch_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_BRANCH_CREATE]))
):
    """Завести ветке её дорогу: subflow со скелетом и привязать.

    ⚠⚠ Шагов в скелете ДВА, и второй обязателен. Движок отдаёт результат
    родителю только на `return_response_text` / `return_response_llm`; дойдя до
    конца списка без них, `_workflow_steps_run` возвращает `None`, родитель
    кладёт в результат пустую строку — и **без ошибки**. Скелет из одного
    `llm_to_json` молча возвращал бы пустоту.
    """
    branch = await _branch_row(branch_id)
    if branch.get('workflow_id'):
        raise HTTPException(status_code=400, detail='У ветки уже есть subflow')

    name = f"branch_{branch['name']}"[:50]
    async with mysql_get_db_async() as db:
        await db.execute("SELECT `id` FROM `agent_workflow` WHERE `name` = %s", (name,))
        if await db.fetchone():
            # ⚠ `agent_workflow.name` уникален по всей базе, не по ноде
            name = f"branch_{branch_id}_{branch['name']}"[:50]

        await db.execute(
            """INSERT INTO `agent_workflow`
                      (`node_id`, `name`, `title`, `description`, `position`,
                       `subflow`, `group_name`)
               SELECT %s, %s, %s, %s,
                      (SELECT COALESCE(MAX(w.`position`), 0) + 1
                         FROM (SELECT `position` FROM `agent_workflow`) w),
                      1, %s""",
            (branch['node_id'], name, str(branch['title'])[:50],
             f"Ветка разговора: {branch['title']}"[:200], 'branch')
        )
        workflow_id = db.lastrowid

        for variable in BRANCH_SKELETON_INPUTS:
            await db.execute(
                """INSERT INTO `agent_workflow_variable`
                          (`workflow_id`, `name`, `type`, `default`, `description`)
                   VALUES (%s, %s, 'input', '', %s)""",
                (workflow_id, variable, 'Вход ветки, передаётся шагом branch')
            )
        for variable in BRANCH_SKELETON_OUTPUTS:
            await db.execute(
                """INSERT INTO `agent_workflow_variable`
                          (`workflow_id`, `name`, `type`, `default`, `description`)
                   VALUES (%s, %s, 'output', '', %s)""",
                (workflow_id, variable, 'Выход ветки, забирается outputs_map')
            )

        await db.execute(
            """INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`,
                                                  `position`, `metadata`)
               VALUES (%s, %s, %s, %s, %s)""",
            (workflow_id, STEP_TYPE_LLM_TO_JSON, 'Ответ по теме', 0,
             json.dumps({
                 'prompt_user': BRANCH_SKELETON_PROMPT,
                 'transitions_after': [],
                 'transitions_before': [],
                 'llm_to_json_variable': [
                     {'variable': 'branch_response', 'text': 'ответ собеседнику'},
                     {'variable': 'branch_result', 'text': 'чем кончилось, одним словом'},
                 ],
             }, ensure_ascii=False))
        )
        await db.execute(
            """INSERT INTO `agent_workflow_step` (`workflow_id`, `type_id`, `title`,
                                                  `position`, `metadata`)
               VALUES (%s, %s, %s, %s, %s)""",
            (workflow_id, STEP_TYPE_RETURN_TEXT, 'Ответ', 1,
             json.dumps({
                 'prompt_user': '%branch_response%',
                 'continue_workflow': False,
                 'transitions_after': [],
                 'transitions_before': [],
             }, ensure_ascii=False))
        )

        await db.execute(
            "UPDATE `agent_workflow_branch` SET `workflow_id` = %s WHERE `id` = %s",
            (workflow_id, branch_id)
        )

    return {"result": {"workflow_id": workflow_id, "branch": await _branch_row(branch_id)}}


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

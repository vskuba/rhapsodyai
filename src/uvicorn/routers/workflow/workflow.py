import re

from fastapi import APIRouter, Request, Depends, HTTPException

from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_variables_node_get
from src.mysql_.repository.agent_workflow_repository import AgentWorkflowRepository
from src.mysql_.repository.agent_workflow_step_repository import AgentWorkflowStepRepository
from src.mysql_.repository.agent_workflow_step_type_repository import AgentWorkflowStepTypeRepository
from src.mysql_.repository.agent_workflow_variable_repository import AgentWorkflowVariableRepository
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()


@router.get("/workflow/list")
async def workflow_list(request: Request, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.find_by({}, 'title ASC')}


@router.post("/workflow")
async def workflow_create(
        request: Request,
        data: dict,
        db=Depends(mysql_get_db_async),
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_CREATE]))
):
    async with db:
        sql = """
            INSERT INTO agent_workflow (name, title, node_id, description, position, group_name, subflow)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            data.get('name'),
            data.get('title'),
            data.get('node_id') or None,
            data.get('description', ''),
            int(data.get('position', 0)),
            data.get('group_name') or None,
            int(data.get('subflow', 0))
        )
        await db.execute(sql, values)
        await db.connection.commit()

        # Получаем ID только что созданной строки в MySQL
        new_id = db.lastrowid

        return {"status": "success", "result": {"id": new_id}}


@router.post("/workflow/{workflow_id}/duplicate")
async def workflow_duplicate(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_CREATE]))
):
    """Полный дубликат workflow: строка agent_workflow (title + ' copy', уникальный name),
    все шаги и связи переменных. Внутри metadata шагов ремапятся id: переходы
    (step_id) и переменные результатов (tool_{id}_result_*) указывают на новые шаги."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM agent_workflow WHERE id = %s", (workflow_id,))
        source = await db.fetchone()
        if not source:
            raise HTTPException(status_code=404, detail="Workflow не найден")

        # Уникальное имя (u_w_workflow_name, CHAR(50)): name_copy, name_copy2, ...
        new_name = None
        for i in range(1, 100):
            suffix = '_copy' if i == 1 else f'_copy{i}'
            candidate = source['name'][:50 - len(suffix)] + suffix
            await db.execute("SELECT id FROM agent_workflow WHERE name = %s", (candidate,))
            if not await db.fetchone():
                new_name = candidate
                break
        if not new_name:
            raise HTTPException(status_code=400, detail="Не удалось подобрать уникальное имя дубликата")

        new_title = (source['title'] + ' copy')[:50]

        await db.execute(
            """
            INSERT INTO agent_workflow (node_id, name, title, description, position, subflow)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (source['node_id'], new_name, new_title, source['description'],
             source['position'], source['subflow'])
        )
        new_workflow_id = db.lastrowid

        # Шаги: первый проход — вставка копий, собираем соответствие old id -> new id
        await db.execute(
            "SELECT * FROM agent_workflow_step WHERE workflow_id = %s ORDER BY position ASC",
            (workflow_id,)
        )
        steps = await db.fetchall()

        id_map = {}
        metadata_by_new_id = {}
        for step in steps:
            await db.execute(
                """
                INSERT INTO agent_workflow_step (workflow_id, type_id, title, position, metadata)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (new_workflow_id, step['type_id'], step['title'], step['position'], step['metadata'])
            )
            id_map[step['id']] = db.lastrowid
            metadata_by_new_id[db.lastrowid] = step['metadata'] or ''

        # Второй проход — ремап id шагов в metadata. Новые id (AUTO_INCREMENT) всегда
        # больше всех старых, поэтому последовательные замены не пересекаются
        for new_step_id, metadata in metadata_by_new_id.items():
            updated = metadata
            for old_id, new_id in id_map.items():
                # Переходы: "step_id": "66" (строкой) и "step_id": 66 (числом)
                updated = re.sub(rf'("step_id"\s*:\s*"){old_id}(")', rf'\g<1>{new_id}\g<2>', updated)
                updated = re.sub(rf'("step_id"\s*:\s*){old_id}(\s*[,}}\]])', rf'\g<1>{new_id}\g<2>', updated)
                # Переменные результатов шагов: tool_66_result_* -> tool_<new>_result_*
                updated = updated.replace(f'_{old_id}_result', f'_{new_id}_result')
            if updated != metadata:
                await db.execute(
                    "UPDATE agent_workflow_step SET metadata = %s WHERE id = %s",
                    (updated, new_step_id)
                )

        # Связи переменных: обычные и публичные (сами переменные общие, копируем только связи)
        await db.execute(
            """
            INSERT INTO agent_workflow_variable_workflow (variable_id, workflow_id)
            SELECT variable_id, %s FROM agent_workflow_variable_workflow WHERE workflow_id = %s
            """,
            (new_workflow_id, workflow_id)
        )
        await db.execute(
            """
            INSERT INTO node_variable_workflow (node_variable_id, workflow_id)
            SELECT node_variable_id, %s FROM node_variable_workflow WHERE workflow_id = %s
            """,
            (new_workflow_id, workflow_id)
        )

        await db.connection.commit()

        return {"status": "success", "result": {"id": new_workflow_id, "title": new_title, "name": new_name}}


@router.get("/workflow/{node_id}/list")
async def workflow_list(request: Request, node_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.find_by({"node_id": node_id}, 'title ASC')}


@router.get("/workflow/{workflow_id}")
async def workflow_get(request: Request, workflow_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    repo = AgentWorkflowRepository()
    return {"result": await repo.find(workflow_id)}


@router.put("/workflow/{workflow_id}")
async def workflow_update(
        request: Request,
        workflow_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    repo = AgentWorkflowRepository()
    return {"result": await repo.update(workflow_id, data)}


@router.delete("/workflow/{workflow_id}")
async def workflow_delete(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))
):
    """Удаляет workflow вместе с его шагами. Связи переменных чистит FK CASCADE;
    у агентов и журнала запусков workflow_id обнуляется (FK SET NULL).
    Шаги удаляем явно: их FK — ON DELETE SET NULL, иначе остались бы сироты."""
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM agent_workflow_step WHERE workflow_id = %s", (workflow_id,))
        await db.execute("DELETE FROM agent_workflow WHERE id = %s", (workflow_id,))
        deleted = db.rowcount
        await db.connection.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow не найден")

    return {"status": "success", "result": deleted}


@router.get("/workflow/{workflow_id}/steps")
async def workflow_steps(request: Request, workflow_id: int, user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))):
    """
    Получает все шаги задачи вместе с их иконками и описаниями типов.
    """
    sql = f"""
            SELECT
                ts.*,
                tst.icon,
                tst.description as description
            FROM `agent_workflow_step` ts
            LEFT JOIN `agent_workflow_step_type` tst ON ts.type_id = tst.id
            WHERE ts.workflow_id = %s
            ORDER BY ts.position ASC
        """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        return {"result": await db.fetchall()}


@router.get("/workflow/{workflow_id}/variables")
async def workflow_variables(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))
):
    # Получает все переменные, связанные с конкретным workflow (включая глобальные и публичные переменные ноды)
    #
    # ⚠⚠ **Переменные ноды спрашиваем у движка, а не ищем своим запросом.**
    # Правило «что за переменные у этой ноды» принадлежит
    # `ai_workflow_variables_node_get`, и второго знатока у него быть не должно:
    # ровно на этом страница и разошлась с работой. Она искала переменные через
    # связку `node_variable_workflow`, движок — по `node_id`, и у workflow, не
    # попавшего в связку, колонка показывала ноль. У `dating_favorite_mail_write`
    # связок нет вовсе, а в его прогонах лежат и `girl_prompt_system`, и
    # `girl_bio_example`: человек видел пустую колонку и не мог сослаться на то,
    # что ему доступно.
    #
    # Ценой второго запроса, и она того стоит: свой SQL повторял бы чужое правило
    # и разошёлся бы с ним снова — при первой же правке у движка.
    #
    # ⚠ Связка при этом жива и наполняется редактором переменной — вот только на
    # работу движка она не влияет **никак**. Это отдельный разговор: либо она
    # должна начать ограничивать выдачу, либо её стоит убрать.
    sql = """
        (SELECT v.id, v.name, v.`type`, v.`default`, v.description, NULL as node_id
         FROM `agent_workflow_variable` v
         JOIN `agent_workflow_variable_workflow` vw ON v.id = vw.variable_id
         WHERE vw.workflow_id = %s)
        UNION
        (SELECT v.id, v.name, v.`type`, v.`default`, v.description, NULL as node_id
         FROM `agent_workflow_variable` v
         WHERE v.type = 'global')
        ORDER BY name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        rows = list(await db.fetchall())

        await db.execute("SELECT node_id FROM agent_workflow WHERE id = %s", (workflow_id,))
        found = await db.fetchone()

    rows.extend(await _node_variables_public(int((found or {}).get('node_id') or 0)))
    # ⚠ Без учёта регистра — как сортировал `ORDER BY name` до переноса: сличение
    # у колонки `utf8mb4_0900_ai_ci`, а сортировка Python идёт по байтам, и
    # `Girl_title` уехал бы к началу списка. Сегодня имён с заглавными нет ни
    # одного, поэтому разницы не видно, — но она и не должна появиться молча.
    rows.sort(key=lambda one: str(one.get('name') or '').lower())

    return {"result": rows}


@router.post("/workflow/{workflow_id}/step")
async def workflow_step_add(
        request: Request,
        workflow_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    repo_workflow_step = AgentWorkflowStepRepository()
    repo_workflow_step_type = AgentWorkflowStepTypeRepository()

    # 1. Получаем текущие шаги, чтобы вычислить следующую позицию
    current_steps = await repo_workflow_step.find_by({"workflow_id": workflow_id})
    next_position = len(current_steps)

    type_id = data.get("type_id", 0)
    workflow_step_type = await repo_workflow_step_type.find(type_id)

    # 2. Подготавливаем данные для вставки
    # Извлекаем title из данных или ставим дефолт, если в схеме NOT NULL
    new_step_data = {
        "workflow_id": workflow_id,
        "type_id": type_id,
        "title": workflow_step_type.get('description', f"Шаг {next_position}"),
        "position": next_position,
        "metadata": data.get("metadata", "{}")  # Инициализируем пустым JSON
    }

    new_id = await repo_workflow_step.add(new_step_data)

    return {"result": new_id}


@router.post("/workflow/{workflow_id}/variable")
async def workflow_variable_add(
        request: Request,
        workflow_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    async with mysql_get_db_async() as db:
        # Check if relation already exists
        sql_check = """
            SELECT v.id 
            FROM agent_workflow_variable v
            JOIN agent_workflow_variable_workflow vw ON v.id = vw.variable_id
            WHERE vw.workflow_id = %s AND v.name = %s
        """
        await db.execute(sql_check, (workflow_id, data.get("name")))
        variable = await db.fetchone()
        if variable:
            return {"result": variable.get("id")}

        variable_type = data.get("type", "workflow")

        # Check if variable with same name and type already exists
        await db.execute(
            "SELECT id FROM agent_workflow_variable WHERE name = %s AND `type` = %s",
            (data.get("name"), variable_type)
        )
        existing_var = await db.fetchone()

        if existing_var:
            variable_id = existing_var.get("id")
        else:
            # Create new variable
            sql_insert_var = """
                INSERT INTO agent_workflow_variable (name, `default`, `type`)
                VALUES (%s, %s, %s)
            """
            await db.execute(sql_insert_var, (data.get("name"), data.get("default"), variable_type))
            variable_id = db.lastrowid

        # Insert relationship
        sql_insert_link = """
            INSERT INTO agent_workflow_variable_workflow (variable_id, workflow_id)
            VALUES (%s, %s)
        """
        await db.execute(sql_insert_link, (variable_id, workflow_id))

        return {"result": variable_id}


@router.put("/workflow/{workflow_id}/steps/reorder")
async def workflow_steps_reorder(
        request: Request,
        workflow_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    repo = AgentWorkflowStepRepository()
    positions = data.get("positions", [])

    for item in positions:
        step_id = item.get("id")
        new_position = item.get("position")

        if step_id is not None:
            await repo.update(int(step_id), {"position": int(new_position)})

    return {"result": "success"}


@router.put("/workflow/{workflow_id}/step/{workflow_step_id}")
async def workflow_step_update(
        request: Request,
        workflow_step_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    repo = AgentWorkflowStepRepository()
    return {"result": await repo.update(workflow_step_id, data)}


@router.delete("/workflow/{workflow_id}/step/{workflow_step_id}")
async def workflow_step_delete(
        request: Request,
        workflow_step_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))
):
    repo = AgentWorkflowStepRepository()
    return {"result": await repo.delete(workflow_step_id)}


@router.get("/workflow/{workflow_id}/parents")
async def workflow_parents(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))
):
    """Кто зовёт этот подпоток шагом `workflow_invoke`.

    ## ⚠⚠ Номер бывает и числом, и строкой — искать надо оба

    Четыре шаблона `LIKE` искали только **число** (`"workflow_id":36,`), а в базе
    встречается и строка (`"workflow_id": "36"`). Страница подпотока честно отвечала
    «не используется ни одним workflow» про тот, который вызывается прямо сейчас, —
    и проверить это было нечем, кроме как открыть родителя глазами.

    ⚠ Движку разницы нет: он приводит значение к `int` при вызове
    (`ai_framework_manager`). Поэтому беда и жила — ломался только показ.

    ⚠⚠ Строку пишет не редактор: его виджет кладёт `parseInt(...)`. Строки приходят
    из миграций и из переносов между базами, где значение однажды прошло через
    `str()`. Значит «починить того, кто пишет» — не решение: писавших много, и
    новый появится завтра. Читаем оба вида.

    ## ⚠ Почему `REGEXP` по тексту, а не `JSON_EXTRACT`

    В таблице есть строки с **невалидным JSON** (пять на сегодня: `response_soko`,
    `response_cashier`, `test`). `JSON_EXTRACT` в `WHERE` упал бы на них целиком —
    и ответ стал бы отказом вместо списка. Текстовый поиск их просто не находит.

    ⚠ Хвост `"?[[:space:]]*[,}]` обязателен: без него номер `74` нашёлся бы внутри
    `740`, и подпоток показал бы чужих родителей.
    """
    pattern = (r'"workflow_id"[[:space:]]*:[[:space:]]*"?'
               + str(int(workflow_id)) + r'"?[[:space:]]*[,}]')

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT DISTINCT w.id, w.name, w.title "
            "FROM agent_workflow_step s "
            "JOIN agent_workflow w ON w.id = s.workflow_id "
            "WHERE s.metadata LIKE '%%workflow_invoke%%' "
            "  AND s.metadata REGEXP %s",
            (pattern,)
        )
        rows = await db.fetchall()

    return {"result": [dict(r) for r in rows]}


@router.get("/workflow/{workflow_id}/agents")
async def workflow_agents(
        request: Request,
        workflow_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))
):
    """Agents that use this workflow."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, name, title FROM agent WHERE workflow_id = %s ORDER BY title",
            (workflow_id,)
        )
        rows = await db.fetchall()
    return {"result": [dict(r) for r in rows]}


@router.put("/workflow/{workflow_id}/variable/{workflow_variable_id}")
async def workflow_variable_update(
        request: Request,
        workflow_id: int,
        workflow_variable_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_UPDATE]))
):
    """Правит переменную workflow: имя, умолчание, описание.

    ⚠⚠ **Этой ручки не было вовсе**, а страница в неё стучалась — по адресу
    `/agent_workflow_variable/{id}`, которого тоже нет. То есть правка имени и
    умолчания во входящих переменных **молча не работала**: `404` уходил в
    консоль браузера, форма показывала новое значение, база хранила старое.

    Нашлось при заведении описания: проба PUT ответила `404`, и описание
    сохранялось бы ровно так же — никак.

    ⚠ Правим **только присланные поля**: страница шлёт одно описание, и
    затирать им имя с умолчанием нельзя.

    Raises:
        HTTPException: 400 — нечего править либо имя не годится в идентификатор.
    """
    fields, values = [], []

    if 'name' in data:
        name = str(data.get('name') or '').strip()
        # ⚠ Имя уходит в промпт меткой `%имя%`, и разборщик ждёт идентификатор:
        # пробел или дефис превратят метку в текст, который модель прочтёт как
        # часть задания.
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise HTTPException(
                status_code=400,
                detail=f"Имя '{name}' не годится: буквы, цифры и подчёркивание, "
                       f"и не с цифры.")
        fields.append('`name` = %s')
        values.append(name)

    if 'default' in data:
        fields.append('`default` = %s')
        values.append(data.get('default'))

    if 'description' in data:
        # ⚠ Пустое описание — `NULL`, а не пустая строка: «не описали» и
        # «описали пустотой» это одно состояние, и двух его видов быть не должно.
        note = str(data.get('description') or '').strip()
        fields.append('`description` = %s')
        values.append(note or None)

    if not fields:
        raise HTTPException(status_code=400,
                            detail='Нечего править: ни имени, ни умолчания, '
                                   'ни описания в запросе.')

    values.append(workflow_variable_id)

    async with mysql_get_db_async() as db:
        await db.execute(
            f"UPDATE `agent_workflow_variable` SET {', '.join(fields)} "
            f"WHERE `id` = %s", tuple(values))
        await db.connection.commit()

    return {'result': {'id': workflow_variable_id}}


@router.delete("/workflow/{workflow_id}/variable/{workflow_variable_id}")
async def workflow_variable_delete(
        request: Request,
        workflow_variable_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_DELETE]))
):
    repo = AgentWorkflowVariableRepository()
    return {"result": await repo.delete(workflow_variable_id)}


# Тип переменной ноды, который человек настраивает сам. Второй — `proxy`,
# служебный псевдоним: его значение подставляет другую переменную
# (`girl_title` = `%prompt_user%`), и предлагать его в списке «на что сослаться и
# что настроить» незачем. Подробности — `workflow.md` §3.0a.
WORKFLOW_VARIABLE_NODE_PUBLIC = 'public'


async def _node_variables_public(node_id: int) -> list:
    """Публичные переменные ноды в том виде, в каком их ждёт страница.

    Args:
        node_id: нода workflow. Ноль — у workflow нет ноды, и список пуст.

    Returns:
        list: записи с теми же ключами, что у остальных переменных выдачи.

    ⚠ **Список берём у движка** (`ai_workflow_variables_node_get`), а не своим
    запросом: правило «что за переменные у ноды» принадлежит ему. Здесь остаётся
    только то, что вправду наше, — какие из них показывать человеку и в каком
    виде.

    ⚠ `type` подменяем на `'node'`: страница делит переменные на группы по этому
    полю, и `public`/`proxy` для неё не роль, а подробность устройства ноды.
    """
    if not node_id:
        return []

    return [{'id': one.get('id'), 'name': one.get('name'), 'type': 'node',
             'default': one.get('default'), 'description': one.get('description'),
             'node_id': one.get('node_id')}
            for one in await ai_workflow_variables_node_get(node_id)
            if one.get('type') == WORKFLOW_VARIABLE_NODE_PUBLIC]

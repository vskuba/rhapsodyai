from fastapi import APIRouter, Request, Depends

from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow_undefined import ai_workflow_undefined_index
from src.auth.auth import AuthChecker
from src.auth.auth_field_policy import ALL_FIELDS, auth_field_policy_fields_filter_for_update, auth_field_policy_fields_allowed
from src.auth.auth_permission import AuthPermission
from src.auth.auth_role import auth_role_is_full

router = APIRouter()


@router.get("/workflow_variable/public/list")
async def workflow_variable_list(
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_VIEW]))
):
    sql = """
        SELECT v.*,
               GROUP_CONCAT(DISTINCT r.name) as role_names,
               GROUP_CONCAT(DISTINCT r.id) as role_ids,
               GROUP_CONCAT(DISTINCT vw.workflow_id) as workflow_ids
        FROM node_variable v
        LEFT JOIN node_variable_role vr ON v.id = vr.node_variable_id
        LEFT JOIN role r ON vr.role_id = r.id
        LEFT JOIN node_variable_workflow vw ON v.id = vw.node_variable_id
        WHERE v.node_id IS NOT NULL
    """
    params = []

    if not auth_role_is_full(user.role):
        # Только переменные в нодах текущего пользователя
        sql += " AND v.node_id IN (SELECT node_id FROM user_node WHERE user_id = %s)"
        params.append(user.user_id)
        # Переменные без ролей — всем; с ролями — только при совпадении роли пользователя
        sql += """
            AND (
                NOT EXISTS (SELECT 1 FROM node_variable_role vr2 WHERE vr2.node_variable_id = v.id)
                OR EXISTS (
                    SELECT 1 FROM node_variable_role vr3
                    JOIN role r3 ON r3.id = vr3.role_id
                    WHERE vr3.node_variable_id = v.id AND r3.name = %s
                )
            )
        """
        params.append(user.role)

    sql += " GROUP BY v.id ORDER BY v.name ASC"

    async with mysql_get_db_async() as db:
        await db.execute(sql, params or None)
        results = await db.fetchall()
        # Преобразуем role_ids и workflow_ids в списки чисел
        for row in results:
            if row['role_ids']:
                row['role_ids'] = [int(r) for r in row['role_ids'].split(',')]
            else:
                row['role_ids'] = []
            if row.get('workflow_ids'):
                row['workflow_ids'] = [int(w) for w in row['workflow_ids'].split(',')]
            else:
                row['workflow_ids'] = []

        # Отдаём только поля, разрешённые роли пользователя на чтение
        allowed = auth_field_policy_fields_allowed('node_variable', 'read', user.role)
        if allowed != ALL_FIELDS:
            results = [{k: v for k, v in row.items() if k in allowed} for row in results]

        return {"result": results}


@router.get("/workflow_variable/undefined_index")
async def workflow_variable_undefined_index(
        request: Request,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_VIEW]))
):
    """Сырьё для индекса «Undefined переменные» — разом для всех workflow.

    ⚠⚠ **Здесь только HTTP.** Что считать обеспеченным именем и откуда его
    брать — `src/ai/ai_workflow_undefined.py`, там и правят. Само правило
    «эта переменная неопределённая» не здесь и не там, а на фронте
    (`variable-group.js`): бэкенд складывает сырьё, считает и красит клиент.
    """
    return {"result": {"workflows": await ai_workflow_undefined_index()}}


@router.get("/workflow_variable/public/{variable_id}/hints")
async def workflow_variable_hints(
        request: Request,
        variable_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_VIEW]))
):
    async with mysql_get_db_async() as db:
        await db.execute("SELECT node_id FROM node_variable WHERE id=%s", (variable_id,))
        variable = await db.fetchone()

        if not variable:
            return {"result": []}

        # Подсказки — proxy-переменные той же ноды (кроме самой редактируемой)
        await db.execute(
            """
            SELECT name, description
            FROM node_variable
            WHERE node_id <=> %s AND `type` = 'proxy' AND id != %s
            ORDER BY position ASC
            """,
            (variable['node_id'], variable_id)
        )
        results = await db.fetchall()

        return {"result": results}


@router.post("/node/workflow_variable")
async def workflow_variable_create(
        request: Request,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_CREATE]))
):
    async with mysql_get_db_async() as db:
        # Позиция по умолчанию — в конец списка своей ноды
        position = data.get('position')
        if position is None:
            await db.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS position FROM node_variable WHERE node_id <=> %s",
                (data.get('node_id'),))
            position = (await db.fetchone())['position']

        sql = """
            INSERT INTO node_variable (name, `title`, description, `default`, node_id, position, `type`)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        # Заголовок не задан — по умолчанию совпадает с системным именем
        await db.execute(sql, (data.get('name'), data.get('title') or data.get('name'),
                               data.get('description'), data.get('default'),
                               data.get('node_id'), position,
                               data.get('type', 'public')))
        variable_id = db.lastrowid

        # Сохранение ролей
        role_ids = data.get('role_ids', [])
        for role_id in role_ids:
            await db.execute("INSERT INTO node_variable_role (node_variable_id, role_id) VALUES (%s, %s)",
                             (variable_id, role_id))

        # Привязка к workflow: переменная видна только в выбранных workflow ноды
        workflow_ids = data.get('workflow_ids') or []
        for workflow_id in workflow_ids:
            if workflow_id:
                await db.execute(
                    "INSERT INTO node_variable_workflow (node_variable_id, workflow_id) VALUES (%s, %s)",
                    (variable_id, workflow_id))

        return {"result": {"id": variable_id}}


@router.put("/workflow_variable/public/{variable_id}")
async def workflow_variable_update(
        request: Request,
        variable_id: int,
        data: dict,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_UPDATE]))
):
    # Оставляем только поля, разрешённые роли пользователя (admin — все)
    fields, data = auth_field_policy_fields_filter_for_update('node_variable', 'write', user.role, data)

    async with mysql_get_db_async() as db:
        if fields:
            # Исключаем реляционные и нетабличные поля из UPDATE-запроса
            db_fields = [f for f in fields if f not in ('role_ids', 'workflow_ids')]
            if db_fields:
                set_clause = ', '.join(f"`{f}`=%s" for f in db_fields)
                values = [data[f] for f in db_fields] + [variable_id]
                await db.execute(f"UPDATE node_variable SET {set_clause} WHERE id=%s", values)

        # Обновление ролей — только если поле role_ids разрешено политикой
        if 'role_ids' in data:
            await db.execute("DELETE FROM node_variable_role WHERE node_variable_id=%s", (variable_id,))
            for role_id in data.get('role_ids') or []:
                await db.execute("INSERT INTO node_variable_role (node_variable_id, role_id) VALUES (%s, %s)",
                                 (variable_id, role_id))

        # Обновление привязок к workflow — только если поле workflow_ids разрешено политикой
        if 'workflow_ids' in data:
            await db.execute("DELETE FROM node_variable_workflow WHERE node_variable_id=%s", (variable_id,))
            for workflow_id in data.get('workflow_ids') or []:
                if workflow_id:
                    await db.execute(
                        "INSERT INTO node_variable_workflow (node_variable_id, workflow_id) VALUES (%s, %s)",
                        (variable_id, workflow_id))

        return {"result": "success"}


@router.delete("/workflow_variable/public/{variable_id}")
async def workflow_variable_delete(
        request: Request,
        variable_id: int,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VARIABLE_DELETE]))
):
    async with mysql_get_db_async() as db:
        # Связи с ролями удалятся каскадно (FK ON DELETE CASCADE)
        await db.execute("DELETE FROM node_variable WHERE id=%s", (variable_id,))
    return {"result": "success"}

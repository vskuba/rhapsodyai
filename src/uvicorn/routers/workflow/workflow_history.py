"""Ручка вкладки «History»: правки workflow страницами.

Запись живёт в `src/ai/ai_workflow_history.py` — её зовут ручки правки. Здесь
только чтение.

⚠ Отбор и страницы считает **сервер**. Отдай ручка всё и листай страница сама —
«все правки этого шага» означало бы «те, что попали на открытую страницу», а
список молча обрывался бы на пределе: эту грабли уже проходили и диалоги, и
журнал доставки в DatingAi.
"""

import json

from fastapi import APIRouter, Depends, Request

from mysql_.mysql_ import mysql_get_db_async

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# Сколько правок на странице по умолчанию и максимум.
#
# ⚠ Тридцать — как у журнала прогонов (`workflow_trace`): страницы стоят рядом,
# листаются одним пейджером, и разные размеры читались бы как разница по
# существу, которой нет.
HISTORY_PER_DEFAULT = 30
HISTORY_PER_MAX = 100


@router.get("/workflow/{workflow_id}/history")
async def workflow_history_list(
        request: Request,
        workflow_id: int,
        object: str | None = None,
        object_id: int | None = None,
        author: str | None = None,
        page: int = 1,
        limit: int = HISTORY_PER_DEFAULT,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_VIEW]))
):
    """Правки этого workflow — свежие сверху.

    Args:
        object: сузить до рода предмета — `workflow`, `step`, `variable`.
        object_id: сузить до одного шага или переменной. ⚠ Без `object` не
            работает: номера шагов и переменных независимы, и `object_id=786`
            без рода означал бы два разных предмета.
        author: `human`, `agent` или `import`. ⚠ Правки агента лежат **в той же
            ленте** (решение человека): отбор нужен затем, чтобы человеческие не
            терялись среди машинных, а не затем, чтобы их разделить.
        page: страница с единицы. `limit` — сколько на ней.

    Returns:
        dict: `result` — строки, плюс `total`, `page`, `pages` для пейджера.

    ⚠ Права — `WORKFLOW_VIEW`: кто видит workflow, видит и его историю. Отдельного
    права не заводим — скрывать «кто правил» от того, кто правит рядом, незачем.
    """
    where = ['`workflow_id` = %s']
    params: list = [int(workflow_id)]

    if object in ('workflow', 'step', 'variable'):
        where.append('`object` = %s')
        params.append(object)

        # ⚠ Внутри рода, а не вместо него: см. довод у довода `object_id`.
        if object_id:
            where.append('`object_id` = %s')
            params.append(int(object_id))

    if author in ('human', 'agent', 'import'):
        where.append('`author` = %s')
        params.append(author)

    where_sql = ' AND '.join(where)
    limit = max(1, min(int(limit), HISTORY_PER_MAX))
    page = max(1, int(page))

    async with mysql_get_db_async() as db:
        await db.execute(
            f'SELECT COUNT(*) AS total FROM `agent_workflow_history`'
            f' WHERE {where_sql}', tuple(params))
        total = int(dict((await db.fetchone()) or {}).get('total') or 0)

        pages = max(1, (total + limit - 1) // limit)
        # ⚠ Страницу поправляем, если она уехала за конец: лента растёт на каждой
        # правке, и номер, открытый минуту назад, мог стать несуществующим.
        page = min(page, pages)

        await db.execute(
            f'SELECT `id`, `workflow_id`, `object`, `object_id`, `object_name`,'
            f' `action`, `changes`, `user_id`, `username`, `author`, `created_at`'
            f'  FROM `agent_workflow_history`'
            f' WHERE {where_sql}'
            # ⚠ `id` вторым: правки одной миллисекунды бывают (автосохранение),
            # и без него порядок между ними не определён — лента перетасуется
            # между отрисовками.
            f' ORDER BY `created_at` DESC, `id` DESC'
            f' LIMIT %s OFFSET %s',
            tuple(params) + (limit, (page - 1) * limit))
        rows = await db.fetchall()

    return {'result': [_answer(row) for row in rows or []],
            'total': total, 'page': page, 'pages': pages}


# ── Приватное ────────────────────────────────────────────────────────────────

def _answer(row) -> dict:
    """Строка для страницы. `changes` — разобранным, а не строкой JSON.

    ⚠ Разбираем здесь, а не на странице: столбец `JSON`, и драйвер отдаёт его
    то строкой, то уже разобранным — в зависимости от версии. Страница не должна
    знать, какая у нас.
    """
    row = dict(row or {})
    changes = row.get('changes')

    if isinstance(changes, str):
        try:
            changes = json.loads(changes or '[]')
        except (ValueError, TypeError):
            # ⚠ Не падаем: правка уже записана, и показать её без диффа лучше,
            # чем не показать вовсе.
            changes = []

    return {**row, 'changes': changes or []}

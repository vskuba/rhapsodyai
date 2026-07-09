from typing import Any

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async


async def ai_workflow_load(workflow_id: int) -> dict:
    """Загружает workflow для выполнения: сущность workflow, нормализованные шаги
    (metadata распарсен, строки очищены от пробелов CHAR-типа) и переменные
    с default-значениями.
    Используется точкой входа chat.py и шагом workflow_invoke (sub-workflow)."""
    sql_workflow = "SELECT * FROM agent_workflow WHERE id = %s"
    sql_steps = """
        SELECT ws.*, wst.name as step_type_name
        FROM agent_workflow_step ws
        LEFT JOIN agent_workflow_step_type wst ON ws.type_id = wst.id
        WHERE ws.workflow_id = %s
        ORDER BY ws.position ASC
    """
    sql_vars = """
        SELECT v.name, v.`default`
        FROM agent_workflow_variable v
        JOIN agent_workflow_variable_workflow vw ON v.id = vw.variable_id
        WHERE vw.workflow_id = %s
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql_workflow, (workflow_id,))
        workflow_row = await db.fetchone()

        await db.execute(sql_steps, (workflow_id,))
        raw_steps = await db.fetchall()

        await db.execute(sql_vars, (workflow_id,))
        raw_variables = await db.fetchall()

    steps = []
    for step in raw_steps:
        steps.append({
            "id": step.get('id'),
            "step_type_name": step.get('step_type_name', '').strip(),
            "title": step.get('title', '').strip(),
            "metadata": json_from_string(step.get('metadata', {}))
        })

    return {"workflow": workflow_row or {}, "steps": steps, "variables": list(raw_variables)}


async def ai_workflow_variables_global_get() -> list[dict]:
    sql = """
        SELECT v.*
        FROM agent_workflow_variable v
        WHERE v.type = 'global'
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql)
        return await db.fetchall()


async def ai_workflow_variables_public_get(node_id: int) -> list[dict]:
    # Публичные переменные ноды (включая proxy) — порядок по position важен:
    # переменные ниже по списку могут ссылаться на %переменные% выше
    sql = """
        SELECT v.*
        FROM agent_workflow_variable_public v
        WHERE v.node_id = %s
        ORDER BY v.position ASC, v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        return await db.fetchall()


async def ai_workflow_variables_input_get(workflow_id: int) -> list[dict]:
    sql = """
        SELECT v.*
        FROM agent_workflow_variable v
        LEFT JOIN agent_workflow_variable_workflow vw ON v.id = vw.variable_id
        WHERE v.type = 'input' AND vw.workflow_id = %s
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        return await db.fetchall()


def ai_workflow_variables_render(source: Any, variables: dict) -> Any:
    """ Рекурсивно подставляет значения %переменных% во все строки метаданных """
    if isinstance(source, str):
        # Быстрая проверка: если в строке нет знака %, пропускаем циклы
        if "%" not in source:
            return source

        rendered_str = source
        for key, val in variables.items():
            placeholder = f"%{key}%"

            # Умная замена типов: если строка состоит ТОЛЬКО из плейсхолдера (н-р, "%id%")
            # возвращаем исходный тип значения (int, bool, list и т.д.), а не строку
            if rendered_str == placeholder:
                return val

            if placeholder in rendered_str:
                rendered_str = rendered_str.replace(placeholder, str(val))
        return rendered_str

    elif isinstance(source, dict):
        # Теперь рекурсивный вызов работает правильно
        return {k: ai_workflow_variables_render(v, variables) for k, v in source.items()}

    elif isinstance(source, list):
        # Теперь рекурсивный вызов работает правильно
        return [ai_workflow_variables_render(item, variables) for item in source]

    return source

"""Сырьё для индекса «Undefined переменные»: кто чем обеспечен в каждом workflow.

⚠⚠ **Правила здесь нет.** «Что считать неопределённой переменной» знает фронт —
`variable-group.js`, функция `undefinedVariables`, и второго знатока ей не нужно.
Здесь собирают только то, чего фронту не взять из чужих карточек: метаданные
шагов, имена реестра и имена, которые движок подмешивает в scope молча.
"""

import json

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import (WORKFLOW_SUBFLOW_STEP_TYPES, WORKFLOW_VARIABLE_NODE_PUBLIC,
                               ai_workflow_variables_node_get)

# Сколько последних прогонов workflow спросить про имена, которые запускающий
# положил в scope при старте. Один был бы беден: часть имён условная (`subtask_*`
# приходят, только когда подзадача есть), и по единственному прогону они выглядели
# бы неопределёнными. Пятёрка закрывает условные ветки и стоит пяти строк на
# workflow: тяжёлый `variables_start` читается **после** отбора по id.
AI_WORKFLOW_UNDEFINED_RUNS_LIMIT = 5


async def ai_workflow_undefined_index() -> dict:
    """Чем обеспечено имя в каждом workflow — разом по всей установке.

    Returns:
        dict: `{id_строкой: {steps, registryNames, hiddenNames}}`, где `steps` —
        `[{id, metadata}]` в порядке `position` (метаданные сырой строкой, их
        разбирает фронт), `registryNames` — имена, видимые в списке переменных
        редактора (реестр workflow + глобальные + публичные ноды),
        `hiddenNames` — имена легальные, но в списках не показуемые.

    ## ⚠⚠ Четыре источника `hiddenNames`, и три из них — про запускающего

    Реестр отвечает только за то, что человек завёл руками. Значение переменной
    приходит ещё с трёх сторон, и ни одной из них в реестре нет:

    * `agent_variable` агента — словарь на карточке;
    * `proxy`-переменные ноды — псевдонимы, которые движок раскрывает молча;
    * **словарь запускающего**: `task_id`, `subtask_branch`, `planning_phase_name`
      кладёт питон при старте (`src/project/task/task_agent_*.py`), и в базе их
      нет нигде, кроме `variables_start` уже случившихся прогонов;
    * **`inputs_map` родителя**: у подпрогона входящие даёт шаг `workflow_invoke`
      того workflow, что его зовёт, — ключи карты это и есть имена внутри ребёнка.

    ⚠ Без двух последних правило кричало на 38 имён из 74 на этой установке —
    все живые. Мера простая: «не знаю, откуда придёт» — не повод звать дыркой.

    ⚠⚠ Переменные ноды спрашиваются **после** выхода из блока соединения: взять
    второе соединение внутри первого — тупик пула, а не трата (`database_rules.md`).
    """
    async with mysql_get_db_async() as db:
        await db.execute("SELECT id, node_id FROM agent_workflow")
        workflow_rows = await db.fetchall()

        await db.execute("""
            SELECT id, workflow_id, metadata
            FROM agent_workflow_step
            WHERE workflow_id IS NOT NULL
            ORDER BY workflow_id ASC, position ASC
        """)
        step_rows = await db.fetchall()

        await db.execute("SELECT workflow_id, name, `type` FROM agent_workflow_variable")
        variable_rows = await db.fetchall()

        await db.execute("SELECT workflow_id, agent_variable FROM agent WHERE workflow_id IS NOT NULL")
        agent_rows = await db.fetchall()

        # ⚠ Ключи, а не значения: `JSON_KEYS` считает их в базе, и longtext со
        # всеми промптами прогона по сети не едет. Отбор по id идёт по индексу на
        # `workflow_id` (в него же входит `id`), тяжёлая колонка читается только у
        # отобранных строк — иначе оконная функция тащила бы всю таблицу трасс.
        await db.execute("""
            SELECT t.workflow_id, JSON_KEYS(t.variables_start) AS variable_keys
            FROM agent_workflow_trace t
            JOIN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                               PARTITION BY workflow_id ORDER BY id DESC) AS rn
                    FROM agent_workflow_trace
                    WHERE workflow_id IS NOT NULL
                ) ranked
                WHERE ranked.rn <= %s
            ) recent ON recent.id = t.id
            WHERE JSON_VALID(t.variables_start)
        """, (AI_WORKFLOW_UNDEFINED_RUNS_LIMIT,))
        run_rows = await db.fetchall()

    steps_by_workflow = _steps_by_workflow(step_rows)
    registry_by_workflow, global_names = _registry_by_workflow(variable_rows)
    hidden_by_workflow = _hidden_by_workflow(agent_rows, run_rows, step_rows)

    # Переменные ноды — у движка, одним обращением на ноду (кэш по node_id)
    node_names_by_node = {}
    workflows = {}
    for one in workflow_rows:
        workflow_id = one['id']
        node_id = one.get('node_id')

        registry_names = list(registry_by_workflow.get(workflow_id) or []) + global_names
        hidden_names = list(hidden_by_workflow.get(workflow_id) or [])

        if node_id and node_id not in node_names_by_node:
            node_names_by_node[node_id] = await _node_names(node_id)

        if node_id:
            registry_names += list(node_names_by_node[node_id][0])
            hidden_names += list(node_names_by_node[node_id][1])

        workflows[str(workflow_id)] = {
            'steps': steps_by_workflow.get(workflow_id) or [],
            'registryNames': sorted(set(filter(None, registry_names))),
            'hiddenNames': sorted(set(filter(None, hidden_names))),
        }

    return workflows


# ── детали реализации ──────────────────────────────────────────────────────────

def _steps_by_workflow(step_rows: list) -> dict:
    """Шаги по workflow одним проходом; метаданные — сырыми строками для фронта."""
    found = {}
    for one in step_rows:
        found.setdefault(one['workflow_id'], []).append(
            {'id': one['id'], 'metadata': one['metadata']})

    return found


def _registry_by_workflow(variable_rows: list) -> tuple:
    """Имена реестра: строка с `workflow_id` — своя, глобальная — всех сразу."""
    registry = {}
    globals_ = []
    for one in variable_rows:
        if one.get('type') == 'global':
            globals_.append(one.get('name'))
        elif one.get('workflow_id') is not None:
            registry.setdefault(one['workflow_id'], []).append(one.get('name'))

    return registry, globals_


def _hidden_by_workflow(agent_rows: list, run_rows: list, step_rows: list) -> dict:
    """Имена, которые движок кладёт в scope молча: агент, запускающий, родитель."""
    hidden = {}

    # Переменные агента: ключи словаря на карточке, как их читает движок
    for one in agent_rows:
        hidden.setdefault(one['workflow_id'], []).extend(
            str(name) for name in json_from_string(one.get('agent_variable') or {}))

    # Словарь запускающего: имена из последних прогонов.
    # ⚠ `JSON_KEYS` отдаёт **массив**, а `json_from_string` по своему докстрингу
    # годится только под объект и на массиве молча вернёт `{}`. Потому здесь
    # `json.loads`: тип другой, не разбор другой.
    for one in run_rows:
        try:
            keys = json.loads(one.get('variable_keys') or '[]')
        except (TypeError, ValueError):
            continue
        if isinstance(keys, list):
            hidden.setdefault(one['workflow_id'], []).extend(str(name) for name in keys)

    # Входящие подпрогона: их даёт `inputs_map` родительского шага-вызова.
    # ⚠ Ключи карты — имена **внутри ребёнка**, значения — имена у родителя
    # (`{"w_project_id": "planning_project_id"}`), и путать их нельзя: у родителя
    # эти же значения читаются шагом и в его собственном правиле уже учтены.
    #
    # ⚠⚠ Родов вызова два (`WORKFLOW_SUBFLOW_STEP_TYPES`), и читать надо оба:
    # подпоток темы получает карту от шага `topic_action`. Знай мы только
    # `workflow_invoke`, его входящие считались бы ничем не заданными — и
    # страница светила бы красным те самые имена, которые приезжают всегда.
    for one in step_rows:
        metadata = json_from_string(one.get('metadata') or {})
        for kind in WORKFLOW_SUBFLOW_STEP_TYPES:
            invoke = metadata.get(kind) or {}
            inputs_map = invoke.get('inputs_map') if isinstance(invoke, dict) else None
            if not isinstance(inputs_map, dict):
                continue
            try:
                # ⚠ В метаданных id ребёнка бывает строкой — ключи словаря здесь
                # целые, как их отдаёт база, и '5' с 5 не сойдутся.
                child_id = int(invoke.get('workflow_id'))
            except (TypeError, ValueError):
                continue
            hidden.setdefault(child_id, []).extend(str(name) for name in inputs_map)

    return hidden


async def _node_names(node_id: int) -> tuple:
    """Имена переменных ноды: показуемые (`public`) и молчаливые (`proxy`)."""
    registry, hidden = [], []
    for one in await ai_workflow_variables_node_get(node_id):
        (registry if one.get('type') == WORKFLOW_VARIABLE_NODE_PUBLIC
         else hidden).append(one['name'])

    return sorted(set(registry)), sorted(set(hidden))

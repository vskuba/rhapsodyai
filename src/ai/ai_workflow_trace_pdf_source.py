"""Чем прогон был настроен: агент, входящие переменные workflow, шаги жребия.

Трасса пишет, **что случилось**; эти три справочника отвечают на соседний
вопрос — **чем это было задано**. Системный промпт агента, объявленные входящие
переменные ветки и описания жребия в трассе не лежат: они живут в настройке и к
моменту чтения могли смениться. Поэтому документ берёт их отдельно и говорит
прямо, что показывает настройку **на сейчас**, а не снимок на момент прогона.

⚠⚠ Единственное место этого файла, где есть база. Сборка документа
(`..._pdf`, `..._pdf_step`, `..._pdf_dice`) чистая: ей отдают готовый словарь.
Так разметку проверяют тестом без базы, а запросы — отдельно и один раз на
документ, а не на каждую строку.

⚠ Запросы идут по ключам (`id IN (…)`), без поиска по тексту: таблица шагов на
проде 1.3 ГБ, и подстрочный поиск по ней — полный проход.
"""
import json

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Имена инструмента жребия. ⚠ Два, а не одно: `dice_batch` — тот же жребий,
# бросающий серию на пачку, и описание у них одинаковое. Список обязан совпадать
# с `DICE_TOOL_NAMES` в `js/workflow/dice-widget.js` — там он у редактора.
AI_WORKFLOW_TRACE_PDF_SOURCE_DICE = ('dice', 'dice_batch')


async def ai_workflow_trace_pdf_source(run: dict) -> dict:
    """
    Собрать настройку, которой был задан прогон: агенты, входящие, жребии.

    Args:
        run: дерево прогона из `GET /workflow_trace/run/{run_uuid}`.

    Returns:
        dict: `{'agents': [...], 'inputs': {workflow_id: [...]},
        'dice': {workflow_id: [...]}}`. Чего нет (агент удалён, прав не
        хватило) — пустой список: документ обязан собраться и без справочника.

    ⚠ Сбой здесь не роняет выгрузку: справочники — украшение документа, а не
    его суть, и прогон, чей агент удалён, читать всё равно надо.
    """
    agent_ids, workflow_ids = _ids(run)
    try:
        async with mysql_get_db_async() as db:
            agents = await _agents(db, agent_ids)
            inputs = await _inputs(db, workflow_ids)
            dice = await _dice(db, workflow_ids)
    except Exception as e:
        logger_info(f'[workflow_trace] настройку прогона собрать не вышло: {e}')
        return {'agents': [], 'inputs': {}, 'dice': {}}
    return {'agents': agents, 'inputs': inputs, 'dice': dice}


# ── детали сборки ──────────────────────────────────────────────────────────

def _ids(run: dict) -> tuple:
    """Номера агентов и workflow по всему дереву: у подпотока они свои."""
    agent_ids, workflow_ids = set(), set()

    def walk(node):
        if node.get('agent_id'):
            agent_ids.add(node['agent_id'])
        if node.get('workflow_id'):
            workflow_ids.add(node['workflow_id'])
        for child in node.get('children') or []:
            walk(child)

    walk(run)
    return agent_ids, workflow_ids


async def _agents(db, agent_ids: set) -> list:
    """Агенты прогона: системный промпт и переменные агента."""
    if not agent_ids:
        return []
    marks = ', '.join(['%s'] * len(agent_ids))
    await db.execute(
        f"""
        SELECT a.id, a.name, a.title, a.prompt_system, a.agent_variable,
               a.workflow_variable, n.name AS node_name
        FROM agent a
        LEFT JOIN node n ON n.id = a.node_id
        WHERE a.id IN ({marks})
        ORDER BY a.id
        """,
        list(agent_ids))
    return list(await db.fetchall())


async def _inputs(db, workflow_ids: set) -> dict:
    """Объявленные **входящие** переменные каждой ветки — контракт её вызова.

    ⚠ Только `type = 'input'`: остальные объявленные (`workflow`, `global`)
    описывают внутреннюю кухню ветки, а не то, с чем её позвали. Ровно так же
    отбирает экранная страница, и расходиться им нельзя.
    """
    if not workflow_ids:
        return {}
    marks = ', '.join(['%s'] * len(workflow_ids))
    # ⚠⚠ Ветка у переменной — **колонка `workflow_id`**, а не связка
    # `agent_workflow_variable_workflow`: связки на проде нет вовсе, хотя она и
    # стоит в замороженной начальной схеме. Поймано пробой — запрос через
    # связку падал «Table … doesn't exist». Форма та же, что у ручки
    # `GET /workflow/{id}/variables`, и расходиться им нельзя.
    #
    # ⚠ `default` — зарезервированное слово MySQL: без обратных кавычек запрос
    # падает синтаксической ошибкой.
    await db.execute(
        f"""
        SELECT v.workflow_id, v.name, v.`default`, v.description
        FROM agent_workflow_variable v
        WHERE v.workflow_id IN ({marks}) AND v.`type` = 'input'
        ORDER BY v.workflow_id, v.name
        """,
        list(workflow_ids))
    out: dict = {}
    for row in await db.fetchall():
        out.setdefault(row['workflow_id'], []).append(row)
    return out


async def _dice(db, workflow_ids: set) -> dict:
    """Шаги жребия каждой ветки — включая те, до которых прогон не дошёл.

    ⚠⚠ Берутся из **определения** workflow, а не из трассы: жребий, который в
    этот раз не бросали, на прогон всё равно влияет — он описывает, каким тот
    мог быть. В трассе же его нет вовсе, и по ней такой шаг невидим.
    """
    if not workflow_ids:
        return {}
    marks = ', '.join(['%s'] * len(workflow_ids))
    await db.execute(
        f"""
        SELECT s.id, s.workflow_id, s.title, s.metadata
        FROM agent_workflow_step s
        WHERE s.workflow_id IN ({marks})
        ORDER BY s.workflow_id, s.position, s.id
        """,
        list(workflow_ids))

    out: dict = {}
    for row in await db.fetchall():
        try:
            invoke = (json.loads(row['metadata'] or '{}') or {}).get('tool_invoke') or {}
        except (ValueError, TypeError):
            continue
        if invoke.get('tool_name') not in AI_WORKFLOW_TRACE_PDF_SOURCE_DICE:
            continue
        out.setdefault(row['workflow_id'], []).append({
            'step_id': row['id'],
            'title': row['title'],
            'tool_name': invoke.get('tool_name'),
            # ⚠ Здесь лежит ИМЯ переменной, а не само описание: его значение
            # собирается в заходе, и достать его можно только из прогона.
            'spec_ref': (invoke.get('inputs_map') or {}).get('spec'),
            'outputs_map': invoke.get('outputs_map') or {},
        })
    return out

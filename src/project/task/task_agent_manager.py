"""
Manager конвейера задач: читает описание и пишет по нему план, подзадачи и цели.

Работает через обычный агентный движок — агент `task_plan_manager`, workflow
которого прогоняет план и цели через шаги-судьи с возвратом на доработку
(план → судья → цели → судья → результат). Вызывается из тика оркестратора,
то есть из отдельного процесса: очередь и поток движка поднимает
`task_orchestrator.py`, здесь только запуск workflow и разбор ответа.

Ошибки наружу отдаются исключением — `task_pipeline` ловит его и уводит задачу
в `failed`, тик от этого не падает.
"""
import asyncio
import uuid

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository
from src.project.task.task_plan import task_plan_goals_normalize

TASK_MANAGER_AGENT_NAME = 'task_plan_manager'

# С судьями это до восьми обращений к LLM за прогон (план и цели, каждый с
# доработками), поэтому таймаут больше прежних 480s. Верхняя граница не круглая,
# а привязана к `task_claim.LOCK_TIMEOUT_SEC` (900s): прогон обязан сорваться
# раньше, чем блокировку задачи сочтут протухшей и её подберёт второй воркер.
MANAGER_TIMEOUT = 720.0
MANAGER_USER_ID = 1  # только для атрибуции session/log


async def task_agent_manager_plan(task: dict) -> dict:
    """
    Разложить глобальную задачу на план, подзадачи и цели.

    Returns:
        plan_text: человекочитаемый план для утверждения человеком.
        subtasks: список {'title': str, 'description': str} в порядке выполнения.
        goals: список {'text': str, 'done': False} — проверяемые цели по плану.
    """
    entity_agent = await _agent_get()
    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        raise RuntimeError(f'у ноды агента {TASK_MANAGER_AGENT_NAME!r} нет LLM-моделей')

    workflow_id   = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)
    session_uuid  = str(uuid.uuid4())

    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=str(task.get('description') or ''),
            user_id=MANAGER_USER_ID,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
        ),
        'task_title':       str(task.get('title') or ''),
        'task_description': str(task.get('description') or ''),
        'task_goals':       _goals_text(task.get('goals')),
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    loop   = asyncio.get_running_loop()
    future = loop.create_future()

    agent_manager   = AiFrameworkAgentManager()
    framework_model = await agent_manager.framework_model_create({
        'entity_agent':       entity_agent,
        'entities_llm':       entities_llm,
        'workflow_steps':     workflow_data['steps'],
        'workflow_variables': wf_vars,
        'prompt_user':        str(task.get('description') or ''),
        'user_id':            MANAGER_USER_ID,
        'companion_id':       None,
        'session_uuid':       session_uuid,
        'tools':              await _tools_load(),
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=MANAGER_TIMEOUT)
    except asyncio.TimeoutError:
        future.cancel()
        raise RuntimeError(f'менеджер не уложился в {MANAGER_TIMEOUT:.0f}s')

    return _plan_parse(result_text)


async def _agent_get() -> dict:
    entity_agent = await AgentRepository().find_one_by({'name': TASK_MANAGER_AGENT_NAME})
    if not entity_agent:
        raise RuntimeError(f'агент {TASK_MANAGER_AGENT_NAME!r} не найден')
    if not entity_agent.get('workflow_id'):
        raise RuntimeError(f'у агента {TASK_MANAGER_AGENT_NAME!r} не задан workflow')
    return entity_agent


async def _tools_load() -> dict:
    """
    Карта `имя -> путь` для шагов `tool_invoke`.

    Без неё workflow падает на шаге `counter_increment` — счётчик итераций
    судейских циклов вызывается как обычный инструмент, а движок берёт список
    из метаданных модели, а не из БД.
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, path FROM tool WHERE id > 0')
        rows = await db.fetchall()
    return {r['name'].strip(): r['path'].strip() for r in (rows or []) if r.get('name') and r.get('path')}


def _goals_text(goals_raw) -> str:
    """Цели лежат в task.goals как JSON [{text, done}] — LLM нужен плоский список."""
    goals = json_from_string(goals_raw or '') or []
    if not isinstance(goals, list):
        return ''
    lines = []
    for g in goals:
        text = str(g.get('text') if isinstance(g, dict) else g or '').strip()
        if text:
            lines.append(f'- {text}')
    return '\n'.join(lines)


def _plan_parse(result_text) -> dict:
    """
    Ответ шага return_response_text приходит с префиксом `json:`.

    Форма ответа — `{"plan": {plan_text, subtasks}, "goals": [...]}`: план и цели
    собираются разными шагами workflow и склеиваются шаблоном последнего шага.
    Плоскую форму (`plan_text` и `subtasks` в корне) тоже разбираем — так
    отвечал workflow до появления шагов-судей.

    Пустой `subtasks` не чиним и не додумываем: `task_pipeline` считает такой
    план провалом и уводит задачу в `failed`, а не в бесконечное планирование.
    """
    raw    = str(result_text or '').removeprefix('json:').strip()
    parsed = json_from_string(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f'менеджер вернул не JSON: {raw[:200]}')

    plan = parsed.get('plan')
    if not isinstance(plan, dict):
        plan = parsed

    subtasks = []
    for item in (plan.get('subtasks') or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        if title:
            subtasks.append({'title': title, 'description': str(item.get('description') or '').strip()})

    return {
        'plan_text': str(plan.get('plan_text') or '').strip(),
        'subtasks':  subtasks,
        'goals':     task_plan_goals_normalize(parsed.get('goals')),
    }

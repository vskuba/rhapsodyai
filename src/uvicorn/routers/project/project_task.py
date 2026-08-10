import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.agent_repository import AgentRepository
from src.project.task.task_plan import (
    task_plan_goals_get,
    task_plan_goals_normalize,
    task_plan_parse,
    task_plan_serialize,
)
from src.project.task.task_revision import task_revision_add
from src.project.task.task_tree import task_tree_parent_check, task_tree_position_next

_TASK_AI_AGENT_NAME = 'task_ai_generator'
_TASK_AI_TIMEOUT    = 60.0

router = APIRouter()


@router.get('/tasks')
async def project_tasks_all(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM project_task ORDER BY position, id")
        rows = await db.fetchall()
    return {'tasks': [dict(r) for r in rows]}


@router.get('/tasks/{project_id}')
async def project_tasks_list(project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    # project_id = 0 — это «Без проекта» в селекте. Колонка допускает и NULL, и 0
    # (0 приходит из формы, NULL остаётся у задач, заведённых мимо неё), поэтому
    # без второго условия часть задач просто не показалась бы ни под одним пунктом.
    where = "project_id = 0 OR project_id IS NULL" if project_id == 0 else "project_id = %s"
    params = () if project_id == 0 else (project_id,)

    async with mysql_get_db_async() as db:
        await db.execute(f"SELECT * FROM project_task WHERE {where} ORDER BY position, id", params)
        rows = await db.fetchall()
    return {'tasks': [dict(r) for r in rows]}


@router.post('/tasks/{project_id}')
async def project_task_create(project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    title = str(data.get('title') or '').strip()
    if not title:
        raise HTTPException(status_code=400, detail='title required')

    async with mysql_get_db_async() as db:
        try:
            parent_id = await task_tree_parent_check(db, None, data.get('parent_id'))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        next_pos = await task_tree_position_next(db, project_id, parent_id)

        task_type_id = data.get('task_type_id')
        await db.execute(
            "INSERT INTO project_task (project_id, parent_id, title, description, goals, status, report, position, task_type_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (project_id, parent_id, title, str(data.get('description') or ''), str(data.get('goals') or ''),
             str(data.get('status') or 'pending'), str(data.get('report') or ''), next_pos, task_type_id)
        )
        await db.connection.commit()
        task_id = db.lastrowid

        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()

    return {'task': dict(task)}


@router.put('/task/{task_id}')
async def project_task_update(task_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    allowed = {'title', 'description', 'goals', 'status', 'report', 'task_type_id'}
    updates = {k: v for k, v in data.items() if k in allowed}

    async with mysql_get_db_async() as db:
        # Перенос по дереву: FK ловит только несуществующего родителя, а цикл и
        # переезд задачи внутрь собственной ветки — нет, это на нас.
        if 'parent_id' in data:
            try:
                updates['parent_id'] = await task_tree_parent_check(db, task_id, data.get('parent_id'))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        # План правится как текст, а в колонке лежит JSON {plan_text, subtasks, goals} —
        # подзадачи и цели менеджера сохраняем, иначе ручная правка их снесёт.
        revision: dict | None = None
        if 'plan_text' in data:
            await db.execute("SELECT pipeline_plan, goals FROM project_task WHERE id = %s", (task_id,))
            row = await db.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail='task not found')
            _, subtasks = task_plan_parse(row['pipeline_plan'] or '')
            goals_plan  = task_plan_goals_get(row['pipeline_plan'] or '')
            plan_text   = str(data.get('plan_text') or '').strip()
            updates['pipeline_plan'] = task_plan_serialize(plan_text, subtasks, goals_plan) if plan_text else ''
            # В ревизию идут живые цели задачи, а не копия из плана: чипс ревизии
            # подменяет на странице именно тот список с чекбоксами, который человек
            # видит и правит.
            revision = {
                'plan_text': plan_text,
                'goals':     task_plan_goals_normalize(updates.get('goals', row['goals'])),
                'subtasks':  subtasks,
            }

        if not updates:
            raise HTTPException(status_code=400, detail='nothing to update')

        set_clause = ', '.join(f'`{k}` = %s' for k in updates)
        values = list(updates.values()) + [task_id]

        await db.execute(f"UPDATE project_task SET {set_clause} WHERE id = %s", values)
        await db.connection.commit()
        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()

    if not task:
        raise HTTPException(status_code=404, detail='task not found')

    # Ревизия — снимок плана, поэтому правка одних целей её не создаёт. Дублей не
    # будет и здесь: страница шлёт `plan_text` при каждом «Сохранить», но
    # `task_revision_add` отбрасывает запись, совпавшую с последней.
    if revision:
        await task_revision_add(task_id, revision['plan_text'], revision['goals'], revision['subtasks'],
                                author_kind='user', author_id=user.user_id, author_name=user.username)

    return {'task': dict(task)}


@router.delete('/task/{task_id}')
async def project_task_delete(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM project_task WHERE id = %s", (task_id,))
        await db.connection.commit()
    return {'ok': True}


@router.post('/task/{task_id}/move')
async def project_task_move(task_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """Поменять местами задачу с соседом по уровню (up / down)."""
    direction = str(data.get('direction') or '').strip()
    if direction not in ('up', 'down'):
        raise HTTPException(status_code=400, detail='direction must be up or down')

    async with mysql_get_db_async() as db:
        # Текущая задача: parent_id и position
        await db.execute("SELECT parent_id, position FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail='task not found')

        parent_clause = "parent_id IS NULL" if task['parent_id'] is None else f"parent_id = {task['parent_id']}"
        if direction == 'up':
            # Найти соседа слева: та же parent_id, position меньше, самый большой position
            await db.execute(
                f"SELECT id, position FROM project_task WHERE {parent_clause} AND position < %s "
                f"ORDER BY position DESC LIMIT 1", (task['position'],))
        else:
            # Найти соседа справа: та же parent_id, position больше, самый маленький position
            await db.execute(
                f"SELECT id, position FROM project_task WHERE {parent_clause} AND position > %s "
                f"ORDER BY position ASC LIMIT 1", (task['position'],))

        sibling = await db.fetchone()
        if not sibling:
            return {'ok': True, 'moved': False, 'reason': f'cannot move {direction}'}

        # Меняем positions местами
        await db.execute(
            "UPDATE project_task SET position = %s WHERE id = %s",
            (sibling['position'], task_id))
        await db.execute(
            "UPDATE project_task SET position = %s WHERE id = %s",
            (task['position'], sibling['id']))
        await db.connection.commit()

    return {'ok': True, 'moved': True}


@router.post('/task/ai-generate')
async def project_task_ai_generate(request: Request, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    description = str(data.get('description') or '').strip()
    if not description:
        raise HTTPException(status_code=400, detail='description required')

    repo_agent = AgentRepository()
    entity_agent = await repo_agent.find_one_by({'name': _TASK_AI_AGENT_NAME})
    if not entity_agent:
        raise HTTPException(status_code=404, detail='AI агент не найден')

    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        raise HTTPException(status_code=503, detail='LLM не настроены')

    workflow_data = await ai_workflow_load(entity_agent['workflow_id'])
    session_uuid = str(uuid.uuid4())
    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=description,
            user_id=user.user_id,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=entity_agent['workflow_id'],
        ),
        'task_description': description,
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    agent_manager = request.app.state.agent_manager
    framework_model = await agent_manager.framework_model_create({
        'entity_agent':      entity_agent,
        'entities_llm':      entities_llm,
        'workflow_steps':    workflow_data['steps'],
        'workflow_variables': wf_vars,
        'prompt_user':       description,
        'user_id':           user.user_id,
        'companion_id':      None,
        'session_uuid':      session_uuid,
        'tools':             {},
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    try:
        result_text = await asyncio.wait_for(future, timeout=_TASK_AI_TIMEOUT)
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=504, detail='Превышено время ожидания AI')

    raw = str(result_text).removeprefix('json:').strip()
    parsed = json_from_string(raw)
    if not parsed or not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail='AI вернул некорректный ответ')

    title       = str(parsed.get('title') or '').strip()
    description = str(parsed.get('description') or '').strip()
    goals_raw   = parsed.get('goals') or []
    if isinstance(goals_raw, list):
        goals = [{'text': str(g), 'done': False} for g in goals_raw if g]
    else:
        goals = []

    return {'title': title, 'description': description, 'goals': goals}

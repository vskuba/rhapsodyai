import asyncio
import uuid

from fastapi import APIRouter, Request, Depends, HTTPException

from src.ai.ai_llm import ai_llm_node_get
from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_load
from src.ai.framework.agent.ai_framework_manager import workflow_runs_active
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.agent_repository import AgentRepository

router = APIRouter()


@router.get("/workflow_trace/run/list")
async def workflow_trace_run_list(
        request: Request,
        workflow_id: int | None = None,
        agent_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 30,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TRACE_VIEW]))
):
    """Список запусков workflow (только верхний уровень, depth=0) с пагинацией."""
    where = ["r.depth = 0"]
    params: list = []

    if workflow_id:
        where.append("r.workflow_id = %s")
        params.append(workflow_id)
    if agent_id:
        where.append("r.agent_id = %s")
        params.append(agent_id)
    if status in ('running', 'success', 'error', 'stopped'):
        where.append("r.status = %s")
        params.append(status)

    where_sql = " AND ".join(where)
    limit = max(1, min(int(limit), 100))
    page = max(1, int(page))
    offset = (page - 1) * limit

    async with mysql_get_db_async() as db:
        await db.execute(
            "DELETE FROM agent_workflow_trace WHERE depth = 0 AND finished_at < NOW() - INTERVAL 7 DAY"
        )
        if db.rowcount:
            await db.connection.commit()

        await db.execute(f"SELECT COUNT(*) as qty FROM agent_workflow_trace r WHERE {where_sql}", params)
        total = (await db.fetchone())['qty']

        await db.execute(
            f"""
            SELECT r.id, r.run_uuid, r.workflow_id, r.agent_id, r.user_id, r.status,
                   r.prompt_user, r.result, r.error, r.started_at, r.duration_ms,
                   w.title AS workflow_title,
                   a.title AS agent_title,
                   (SELECT COUNT(*) FROM agent_workflow_trace_step s WHERE s.run_id = r.id) AS steps_qty,
                   (SELECT COUNT(*) FROM agent_workflow_trace c WHERE c.parent_run_id = r.id) AS children_qty
            FROM agent_workflow_trace r
            LEFT JOIN agent_workflow w ON w.id = r.workflow_id
            LEFT JOIN agent a ON a.id = r.agent_id
            WHERE {where_sql}
            ORDER BY r.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset]
        )
        rows = await db.fetchall()

    return {
        "result": rows,
        "pagination": {
            "current_page": page,
            "total_pages": max(1, (total + limit - 1) // limit),
            "total_records": total,
        },
    }


@router.get("/workflow_trace/run/{run_uuid}")
async def workflow_trace_run_detail(
        request: Request,
        run_uuid: str,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TRACE_VIEW]))
):
    """Запуск с шагами и деревом дочерних запусков (sub-workflow)."""
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT r.*, w.title AS workflow_title, w.name AS workflow_name, a.title AS agent_title
            FROM agent_workflow_trace r
            LEFT JOIN agent_workflow w ON w.id = r.workflow_id
            LEFT JOIN agent a ON a.id = r.agent_id
            WHERE r.run_uuid = %s
            """,
            (run_uuid,)
        )
        root = await db.fetchone()
        if not root:
            raise HTTPException(status_code=404, detail="Запуск не найден")

        # Собираем всех потомков по уровням (BFS по parent_run_id)
        runs = {root['id']: root}
        layer = [root['id']]
        while layer:
            placeholders = ', '.join(['%s'] * len(layer))
            await db.execute(
                f"""
                SELECT r.*, w.title AS workflow_title, w.name AS workflow_name, a.title AS agent_title
                FROM agent_workflow_trace r
                LEFT JOIN agent_workflow w ON w.id = r.workflow_id
                LEFT JOIN agent a ON a.id = r.agent_id
                WHERE r.parent_run_id IN ({placeholders})
                """,
                layer
            )
            children = await db.fetchall()
            layer = [c['id'] for c in children]
            for c in children:
                runs[c['id']] = c

        # Все шаги всех запусков одним запросом (с JOIN на LLM)
        run_ids = list(runs.keys())
        placeholders = ', '.join(['%s'] * len(run_ids))
        await db.execute(
            f"""
            SELECT s.*, l.name AS llm_name
            FROM agent_workflow_trace_step s
            LEFT JOIN llm l ON l.id = s.llm_id
            WHERE s.run_id IN ({placeholders})
            ORDER BY s.run_id, s.exec_index, s.id
            """,
            run_ids
        )
        all_steps = await db.fetchall()

    # Сборка дерева: у каждого запуска — шаги и дочерние запуски
    for run in runs.values():
        run['steps'] = []
        run['children'] = []
    for step in all_steps:
        runs[step['run_id']]['steps'].append(step)
    for run in runs.values():
        parent_id = run.get('parent_run_id')
        if parent_id and parent_id in runs:
            runs[parent_id]['children'].append(run)

    # Для running-запусков вычисляем текущий (ещё не завершённый) шаг из определения workflow
    for run in runs.values():
        if run.get('status') != 'running':
            continue
        wf_id = run.get('workflow_id')
        if not wf_id:
            continue
        try:
            wf_data = await ai_workflow_load(wf_id)
            wf_steps = wf_data.get('steps') or []
            completed_steps = run['steps']

            if not wf_steps:
                continue

            # Строим карту step_id -> позиция
            step_pos = {s['id']: i for i, s in enumerate(wf_steps)}

            if not completed_steps:
                # Ещё ни один шаг не завершён → первый шаг
                candidate = wf_steps[0]
            else:
                # Последний завершённый шаг
                last = max(completed_steps, key=lambda s: s.get('exec_index', 0))
                last_step_id = last.get('step_id')
                transition_raw = last.get('transition')

                next_step = None
                if transition_raw:
                    import json as _json
                    t = transition_raw if isinstance(transition_raw, dict) else _json.loads(transition_raw or '{}')
                    to_id = t.get('to_step_id')
                    if to_id:
                        next_step = next((s for s in wf_steps if s['id'] == to_id), None)

                if next_step is None and last_step_id in step_pos:
                    pos = step_pos[last_step_id]
                    if pos + 1 < len(wf_steps):
                        next_step = wf_steps[pos + 1]

                candidate = next_step

            if candidate:
                run['current_step'] = {
                    'step_id': candidate['id'],
                    'step_title': candidate.get('title', ''),
                    'step_type': candidate.get('step_type_name', ''),
                }
        except Exception:
            pass

    return {"result": root}


@router.post("/workflow_trace/run/{run_uuid}/replay")
async def workflow_trace_run_replay(
        request: Request,
        run_uuid: str,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TRACE_REPLAY]))
):
    """Повторяет запуск workflow с сохраненным снапшотом переменных (variables_start).

    Шаги берутся из ТЕКУЩЕГО определения workflow — replay нужен, чтобы проверить
    правки сценария на реальных входных данных. История и continue_workflow-индекс
    пишутся в НОВУЮ сессию, чтобы не засорять оригинальную переписку; сам снапшот
    переменных (включая старый session_uuid как значение) не изменяется."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT * FROM agent_workflow_trace WHERE run_uuid = %s AND depth = 0",
            (run_uuid,)
        )
        run = await db.fetchone()

    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден (replay доступен только для верхнего уровня)")
    if not run.get('workflow_id'):
        raise HTTPException(status_code=400, detail="Workflow этого запуска удален — повторить невозможно")

    variables = json_from_string(run.get('variables_start') or '{}')
    if not isinstance(variables, dict) or not variables:
        raise HTTPException(status_code=400, detail="У запуска нет снапшота переменных (variables_start)")
    variables.setdefault('prompt_user', run.get('prompt_user') or '')

    entity_agent = {}
    if run.get('agent_id'):
        entity_agent = await AgentRepository().find_one_by({'id': run['agent_id']}) or {}
    if not entity_agent:
        raise HTTPException(status_code=400, detail="Агент этого запуска удален — повторить невозможно")

    workflow_data = await ai_workflow_load(run['workflow_id'])
    if not workflow_data['steps']:
        raise HTTPException(status_code=400, detail="Workflow не содержит шагов")

    # LLM ноды агента этого запуска (не пользователя — список настраивается на ноду)
    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        raise HTTPException(status_code=404, detail="Не найдены LLM для ноды этого агента")

    async with mysql_get_db_async() as db:
        await db.execute("SELECT name, path FROM tool WHERE id > 0")
        raw_tools = await db.fetchall()
    tools = {t['name'].strip(): t['path'].strip() for t in raw_tools if t.get('name') and t.get('path')}

    # Новая сессия: история и continue_workflow-индекс replay-запуска не трогают оригинал
    replay_session_uuid = str(uuid.uuid4())

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    agent_manager = request.app.state.agent_manager
    framework_model = await agent_manager.framework_model_create({
        "entity_agent": entity_agent,
        "entities_llm": entities_llm,
        "workflow_steps": workflow_data['steps'],
        "workflow_variables": variables,
        "prompt_user": variables.get('prompt_user', ''),
        "user_id": run.get('user_id') or user.user_id,
        "companion_id": variables.get('companion_id', 0),
        "session_uuid": replay_session_uuid,
        "tools": tools,
    })
    agent_manager.framework_workflow_run(framework_model, future, loop)

    timeout = 60.0
    try:
        result_text = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        future.cancel()
        raise HTTPException(status_code=504, detail=f"Превышено время ожидания ответа ({timeout} сек.)")

    return {"result": result_text, "session_uuid": replay_session_uuid}


@router.post("/workflow_trace/run/{run_uuid}/stop")
async def workflow_trace_run_stop(
        request: Request,
        run_uuid: str,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TRACE_STOP]))
):
    """Останавливает выполняющийся workflow: отменяет asyncio-задачу запуска
    (журнал закроет статусом 'stopped' обработчик отмены в менеджере).

    Если живой задачи нет (сервер перезапускался и 'running'-лог завис) — запуск
    помечается остановленным напрямую. Дочерние 'running'-запуски (sub-workflow)
    в обоих случаях закрываются здесь: их trace-финализация при отмене не вызывается."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, status FROM agent_workflow_trace WHERE run_uuid = %s AND depth = 0",
            (run_uuid,)
        )
        run = await db.fetchone()

    if not run:
        raise HTTPException(status_code=404, detail="Запуск не найден (стоп доступен только для верхнего уровня)")
    if run['status'] != 'running':
        raise HTTPException(status_code=400, detail=f"Запуск уже завершен (статус: {run['status']})")

    task = workflow_runs_active.get(run_uuid)
    task_alive = bool(task and not task.done())
    if task_alive:
        task.cancel()

    async with mysql_get_db_async() as db:
        # Задачи в процессе нет (зависший лог после рестарта) — закрываем запись сами
        if not task_alive:
            await db.execute(
                "UPDATE agent_workflow_trace SET status = 'stopped', error = 'Остановлен пользователем', "
                "finished_at = NOW(3) WHERE id = %s AND status = 'running'",
                (run['id'],)
            )

        # Дочерние запуски уровень за уровнем (глубина ограничена MAX_WORKFLOW_DEPTH)
        run_ids = [run['id']]
        while run_ids:
            placeholders = ', '.join(['%s'] * len(run_ids))
            await db.execute(
                f"SELECT id FROM agent_workflow_trace "
                f"WHERE parent_run_id IN ({placeholders}) AND status = 'running'",
                run_ids
            )
            run_ids = [r['id'] for r in await db.fetchall()]
            if run_ids:
                placeholders = ', '.join(['%s'] * len(run_ids))
                await db.execute(
                    f"UPDATE agent_workflow_trace SET status = 'stopped', "
                    f"error = 'Остановлен пользователем', finished_at = NOW(3) "
                    f"WHERE id IN ({placeholders})",
                    run_ids
                )

    return {"result": "stopped", "task_cancelled": task_alive}


@router.delete("/workflow_trace/run/{run_uuid}")
async def workflow_trace_run_delete(
        request: Request,
        run_uuid: str,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TRACE_DELETE]))
):
    """Удаляет запуск: шаги и дочерние запуски удаляются каскадно (FK)."""
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM agent_workflow_trace WHERE run_uuid = %s", (run_uuid,))
    return {"result": "success"}

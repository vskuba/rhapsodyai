import asyncio
import time
import uuid

from fastapi import APIRouter, Request, Depends, HTTPException

from src.ai.ai_llm import ai_llm_node_get
from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_load
from src.ai.framework.agent.ai_framework_manager import workflow_runs_active
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from src.mysql_.repository.agent_repository import AgentRepository

router = APIRouter()

# ── Поиск по содержимому прогонов ───────────────────────────────────────────
#
# ⚠ Короче трёх знаков не ищем: отсеивать нечем, а проход был бы полный.
TRACE_SEARCH_MIN = 3

# ⚠⚠ Потолок времени одного поиска. Не уложился — база обрывает сама, ручка
# отвечает 504 и просит сузить отбор. Без потолка дорогой запрос держал бы
# соединение пула, а их шесть на весь процесс.
TRACE_SEARCH_TIMEOUT_MS = 8000

# Колонки, по которым идёт поиск. ⚠ Условие и его доводы собираются **из этих
# же списков** (`_trace_search_where` и `_trace_search_params`) — порядок `%s` и
# порядок значений иначе разошлись бы молча, и драйвер упал бы на ровном месте.
TRACE_SEARCH_RUN_COLUMNS = ('r.prompt_user', 'r.result', 'r.error',
                            'r.request_json', 'r.response_json')
TRACE_SEARCH_STEP_COLUMNS = ('s.step_title', 's.metadata_rendered',
                             's.variables_changed', 's.output', 's.error')

# ⚠⚠⚠ Окно поиска ПО ШАГАМ — сколько последних строк трассы просматривать.
#
# Замерено на проде 13.10.2026, и замер перевернул оценку: таблица шагов там
# **1311 МБ** (242 611 строк) против 147 МБ у самой трассы — я ожидал 174 МБ на
# обе. Полный сбор совпадений по шагам стоит **7.6 с**, то есть упирается в
# потолок и обрывается: без этого окна поиск на проде не работал вовсе, всегда
# отвечая 504.
#
# | окно | совпадений | время |
# |------|-----------|-------|
# | вся таблица | 25 483 | 7625 мс |
# | max-10000 | 8 824 | 3739 мс |
# | max-3000 | 2 583 | 654 мс |
# | max-1000 | 897 | 213 мс |
#
# ⚠ Поля самого прогона (`TRACE_SEARCH_RUN_COLUMNS`) окном НЕ ограничены: проход
# по ним стоит 4 мс на тех же 29 тысячах прогонов. Асимметрия не прихоть — она
# ровно по тому, что дорого: запрос, ответ и контракт ищутся по всей истории,
# шаги — в недавнем.
#
# ⚠ Окно считается в строках трассы, а не в прогонах верхнего уровня: номера
# дочерних прогонов лежат вперемешку с родительскими, и `id >= max - N` — то
# единственное, что база берёт индексом. Сколько это прогонов, ручка считает и
# говорит человеку (`steps_window`): на проде 5000 строк ≈ 600 прогонов.
TRACE_SEARCH_STEP_WINDOW = 5000


@router.get("/workflow_trace/run/list")
async def workflow_trace_run_list(
        request: Request,
        workflow_id: int | None = None,
        agent_id: int | None = None,
        node_id: int | None = None,
        llm_id: int | None = None,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 30,
        user=Depends(AuthChecker([AuthPermission.WORKFLOW_TRACE_VIEW]))
):
    """Список запусков workflow (только верхний уровень, depth=0) с пагинацией.

    `search` — подстрока в содержимом прогона: его запрос, ответ, ошибка,
    контракт вызова и **шаги** (название, вход, выход, изменённые переменные,
    ошибка), включая шаги подпотоков. Отбор по ноде, workflow, агенту и статусу
    действует вместе с ней и сужает проход.

    ## ⚠⚠ Это полный проход, и он здесь сознательный

    Подстроку по `LONGTEXT` индексом не ускорить: `LIKE '%…%'` не берёт префикс,
    а `FULLTEXT` ищет словами — он не нашёл бы `photo_send` в
    `"topic": "photo_send"` и не дал бы искать по куску имени. Семантика
    подстроки у поиска по открытому прогону уже такая, и расходиться им нельзя.

    Поэтому цена не прячется, а ограничивается:

    - **минимум три знака** — короче отсеивать нечего, проход был бы ради всего;
    - **потолок времени** (`MAX_EXECUTION_TIME`) — запрос, не уложившийся в него,
      база обрывает сама, и ручка честно отвечает «не уложился, сузьте отбор»;
    - **без второго прохода за счётом** — при поиске `COUNT(*)` не считается
      вовсе: он стоил бы ровно столько же, сколько сам поиск. Отдаётся столько
      строк, сколько нашлось в пределах `limit`, и признак `limited`;
    - **`variables_start` не ищется** — это самая толстая колонка таблицы (в
      среднем 2.9 КБ на строку), а её содержимое и так попадает в шаги через
      `metadata_rendered` и `variables_changed`;
    - **шаги ищутся в окне** последних `TRACE_SEARCH_STEP_WINDOW` строк трассы,
      поля прогона — по всей истории. Замер на проде: шаги 7.6 с против 4 мс у
      полей, разница в их размере (1311 МБ против 147 МБ).

    ⚠ Поиск идёт **по запросу человека**, а не на каждую отрисовку страницы —
    в отличие от уборки, которая когда-то стояла здесь же и шла на каждое
    открытие (см. ниже). Это разница между «иногда дорого по нажатию» и
    «дорого всегда».

    Ответ при поиске несёт `search`: `query`, `found`, `limited`, `ms` и
    `steps_window` — сколько прогонов попало в окно поиска по шагам. ⚠ Окно
    обязано быть названо: без него человек считает поиск полным по истории, а
    он полон только по полям прогона.
    """
    where = ["r.depth = 0"]
    params: list = []

    if workflow_id:
        where.append("r.workflow_id = %s")
        params.append(workflow_id)
    if agent_id:
        where.append("r.agent_id = %s")
        params.append(agent_id)
    # Ноды у прогона нет — она у агента. Подзапросом, а не джойном: условие идет и
    # в COUNT, который агента не джойнит, и порядок параметров остается общим
    if node_id:
        where.append("r.agent_id IN (SELECT id FROM agent WHERE node_id = %s)")
        params.append(node_id)
    # Модели у прогона нет — она у шага, и чаще всего у шага ПОДПОТОКА.
    if llm_id:
        where.append(_trace_llm_where())
        params.append(llm_id)
    if status in ('running', 'success', 'error', 'stopped'):
        where.append("r.status = %s")
        params.append(status)

    # Поиск по содержимому: своим условием, чтобы отбор выше сужал ему проход
    needle = str(search or '').strip()
    searching = len(needle) >= TRACE_SEARCH_MIN
    if searching:
        where.append(_trace_search_where())
        params.extend(_trace_search_params(needle))

    where_sql = " AND ".join(where)
    limit = max(1, min(int(limit), 100))
    page = max(1, int(page))
    offset = (page - 1) * limit

    # ⚠ Уборки старых прогонов здесь больше нет — она в кроне
    # (`src/cronjob/workflow_trace_cleanup.py`, раз в час). Стояла она первой
    # строкой этой ручки и шла на каждое открытие страницы: 119 мс полного
    # прохода по таблице в 174 МБ, снесённых строк ноль, плюс next-key-замки на
    # всё просмотренное — то есть открытие страницы трасс запирало запись
    # трассы для идущих в этот момент workflow. Почему именно так — в
    # докстринге `ai_workflow_trace_trim`.
    began = time.monotonic()
    async with mysql_get_db_async() as db:
        if searching:
            # ⚠⚠ При поиске счёта НЕТ: `COUNT(*)` по тому же условию — второй
            # такой же полный проход, то есть ровно удвоение цены ради числа в
            # подписи. Сколько нашлось сверх показанного, человеку скажет
            # признак `limited`, а не точное число.
            total = None
        else:
            await db.execute(f"SELECT COUNT(*) as qty FROM agent_workflow_trace r WHERE {where_sql}", params)
            total = (await db.fetchone())['qty']

        # ⚠ Ни `result`, ни `error` карточка списка не показывает — только
        # заголовок, состояние, время, число шагов и начало промпта. А это
        # LONGTEXT: тянуть их на тридцать строк значило гонять по сети то, что
        # тут же выбрасывается. Целиком они есть на соседней ручке — той, что
        # открывается щелчком по карточке (`workflow_trace_run_detail`).
        #
        # ⚠ `prompt_user` обрезан здесь, а не в браузере: в карточке у него
        # `white-space: nowrap; text-overflow: ellipsis`, то есть видно ровно
        # одну строку, а приезжал он целиком.
        # ⚠ Потолок времени ставится подсказкой оптимизатору, а не `SET STATEMENT`:
        # второе — синтаксис MariaDB, здесь MySQL 8. Не уложился — база обрывает
        # запрос сама (ошибка 3024), и это лучше, чем занятое соединение пула.
        hint = f"/*+ MAX_EXECUTION_TIME({TRACE_SEARCH_TIMEOUT_MS}) */ " if searching else ""
        try:
            await db.execute(
                f"""
                SELECT {hint}
                       r.id, r.run_uuid, r.workflow_id, r.agent_id, r.user_id, r.status,
                       LEFT(r.prompt_user, 300) AS prompt_user,
                       r.started_at, r.duration_ms,
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
        except Exception as error:
            if not searching:
                raise
            # ⚠ Отвечаем отказом, а не пустым списком: «не нашлось» и «искать
            # оказалось дороже отведённого» — разные ответы, и пустой список
            # соврал бы человеку, что текста в прогонах нет.
            logger_info(f"⚠️ Поиск по прогонам не уложился: {error}")
            raise HTTPException(
                status_code=504,
                detail=f'Поиск не уложился в {TRACE_SEARCH_TIMEOUT_MS // 1000} с. '
                       f'Сузьте отбор — нодой, workflow, агентом или состоянием.')

    spent = int((time.monotonic() - began) * 1000)

    if searching:
        # ⚠ Страниц при поиске одна: листать нечем — счёта нет, а узнавать его
        # вторым проходом дороже самого поиска
        return {
            "result": rows,
            "pagination": {"current_page": 1, "total_pages": 1,
                           "total_records": len(rows)},
            "search": {"query": needle, "found": len(rows),
                       "limited": len(rows) >= limit, "ms": spent,
                       "steps_window": await _trace_search_window_runs()},
        }

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
            SELECT r.*, w.title AS workflow_title, w.name AS workflow_name,
                   a.title AS agent_title, a.name AS agent_name
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
                SELECT r.*, w.title AS workflow_title, w.name AS workflow_name,
                       a.title AS agent_title, a.name AS agent_name
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


def _trace_search_where() -> str:
    """Условие «текст встречается в прогоне» — его поля плюс его шаги.

    Шаги берутся **вместе с подпотоками**: совпадение внутри sub-workflow
    принадлежит тому прогону, из которого его позвали, — в списке показываются
    только верхние (`depth = 0`), и без этого найденное в подпотоке не нашлось
    бы вовсе. Подъём от шага к корню идёт рекурсией по `parent_run_id`
    (колонка индексирована), а не обходом дерева сверху: совпадений единицы,
    прогонов тысячи.

    ⚠ `variables_start` не ищется намеренно: самая толстая колонка таблицы
    (в среднем 2.9 КБ на строку), а её содержимое и так попадает в шаги через
    `metadata_rendered` и `variables_changed`. Платить за неё вторым чтением
    всей таблицы — ради того же текста.

    ⚠⚠⚠ **Шаги ограничены окном** (`TRACE_SEARCH_STEP_WINDOW`), поля прогона —
    нет. Так сделано потому, что цена у них разная на два порядка: на проде
    сбор совпадений по шагам стоит 7.6 с (таблица 1311 МБ), по полям прогона —
    4 мс (147 МБ). Без окна поиск на проде обрывался потолком **всегда**.

    ⚠⚠ Порядок `%s` здесь и порядок доводов у зовущего — одно знание, и живёт
    оно в `TRACE_SEARCH_RUN_COLUMNS` / `TRACE_SEARCH_STEP_COLUMNS`. Допишешь
    колонку мимо них — драйвер получит не то число доводов. Окно идёт **после**
    них, своим доводом.
    """
    run_match = ' OR '.join(f'{column} LIKE %s' for column in TRACE_SEARCH_RUN_COLUMNS)
    step_match = ' OR '.join(f'{column} LIKE %s' for column in TRACE_SEARCH_STEP_COLUMNS)

    return f"""({run_match} OR r.id IN (
        WITH RECURSIVE hit AS (
            SELECT DISTINCT s.run_id AS id
              FROM agent_workflow_trace_step s
             WHERE s.run_id >= (SELECT MAX(id) - %s FROM agent_workflow_trace)
               AND ({step_match})
            UNION
            SELECT t.parent_run_id
              FROM agent_workflow_trace t
              JOIN hit ON t.id = hit.id
             WHERE t.parent_run_id IS NOT NULL
        )
        SELECT id FROM hit
    ))"""


def _trace_llm_where() -> str:
    """Условие «прогон обращался к этой модели» — его шаги плюс его подпотоки.

    Модель записана у **шага** (`agent_workflow_trace_step.llm_id`), а в списке
    показываются только верхние прогоны (`depth = 0`). Подъём от шага к корню
    идёт рекурсией по `parent_run_id` — тем же приёмом, что у поиска по тексту
    (`_trace_search_where`), и по той же причине.

    ## ⚠⚠ Без подпотоков фильтр соврал бы в двадцать раз

    Замер на проде 20.10.2026 по самой частой модели (`gx10/qwen-small_nr1`):
    прямые шаги верхних прогонов дают **100** прогонов, вместе с подпотоками —
    **2388**. То есть 96% обращений к модели случаются внутри подпотоков, и
    фильтр «по прямым шагам» показывал бы четыре процента правды, выглядя
    исправным.

    ## ⚠ Окна здесь нет намеренно, в отличие от поиска по тексту

    Там окно обязательно: без него поиск упирался в потолок времени всегда.
    Здесь оно почти ничего не даёт — цена сидит в самой рекурсии, а не в
    просмотре шагов. Тот же замер:

    | окно | прогонов | время |
    |------|----------|-------|
    | 5 000 строк | 281 | 1334 мс |
    | 20 000 строк | 1143 | 1648 мс |
    | без окна | 2388 | 2121 мс |

    Платить третью долей правды за треть секунды незачем: отбор — это не
    поиск, и неполный отбор врёт молча. На редких моделях запрос идёт 3 мс.

    ⚠ Условие стоит **после** отбора по ноде, workflow и агенту: те сужают
    проход, и вместе с ними дорогая рекурсия достаётся меньшему числу строк.
    """
    return """r.id IN (
        WITH RECURSIVE hit AS (
            SELECT DISTINCT s.run_id AS id
              FROM agent_workflow_trace_step s
             WHERE s.llm_id = %s
            UNION
            SELECT t.parent_run_id
              FROM agent_workflow_trace t
              JOIN hit ON t.id = hit.id
             WHERE t.parent_run_id IS NOT NULL
        )
        SELECT id FROM hit
    )"""


def _trace_search_params(needle: str) -> list:
    """Доводы к `_trace_search_where` — в том же порядке, в каком там стоят `%s`.

    ⚠⚠ Живёт рядом с условием и собирается из тех же списков колонок. Пока
    доводы считались числом (`[…] * MARKS`), окно поиска по шагам нельзя было
    вставить в середину, не сломав счёт молча: драйвер получает позиционные
    значения и о смысле их не знает.
    """
    like = f'%{needle}%'

    return ([like] * len(TRACE_SEARCH_RUN_COLUMNS)
            + [TRACE_SEARCH_STEP_WINDOW]
            + [like] * len(TRACE_SEARCH_STEP_COLUMNS))


async def _trace_search_window_runs() -> int:
    """Сколько прогонов верхнего уровня попало в окно поиска по шагам.

    Окно задано в строках трассы (`TRACE_SEARCH_STEP_WINDOW`), а человеку надо
    сказать его в прогонах: «искали в последних 600» понятно, «в последних 5000
    строках» — нет, он таких единиц не видит нигде на странице.

    ⚠ Отдельным запросом, а не вместе с поиском: по индексу `(depth, status,
    id)` он `Using index` и стоит единицы миллисекунд, а приделанный к поиску
    подзапрос мешал бы оптимизатору выбирать план для дорогой части.

    ⚠ Сбой — ноль, а не исключение: число это подпись под уже найденным, и
    ронять из-за неё готовый ответ нельзя.
    """
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                "SELECT COUNT(*) AS qty FROM agent_workflow_trace "
                "WHERE depth = 0 AND id >= (SELECT MAX(id) - %s FROM agent_workflow_trace)",
                (TRACE_SEARCH_STEP_WINDOW,))
            return int((await db.fetchone() or {}).get('qty') or 0)
    except Exception as error:
        logger_info(f"⚠️ Окно поиска не посчитано: {error}")
        return 0

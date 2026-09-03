import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission
from logging_.logging_ import logger_info
from src.mysql_.repository.agent_repository import AgentRepository
from src.project.task.task_abort import task_abort_runs
from src.project.task.task_depend import TASK_DEPEND_DONE_STATES, task_depend_of
from src.project.task.task_role import task_role_of_state, task_role_project_work_dir
from src.project.task.task_spec import task_spec_read
from src.project.task.task_metadata import (
    TASK_METADATA_KEY_DEV,
    TASK_METADATA_KEY_TEST,
    task_metadata_row_apply,
    task_metadata_update,
)
from src.project.task.task_plan import (
    task_plan_goals_get,
    task_plan_goals_normalize,
    task_plan_parse,
    task_plan_serialize,
)
from src.project.task.task_report import task_report_write
from src.project.task.task_revision import task_revision_add
from src.project.task.task_state import task_state_dev_to_testing, task_state_plan_to_development
from src.project.task.task_stop import task_stop_clear
from src.project.team.team_llm_pool import team_llm_pool_forget
from src.project.team.team_shell_pool import team_shell_pool_forget
from src.project.task.task_tree import (task_tree_descendants, task_tree_parent_check,
                                        task_tree_position_next)
from src.project.task.task_worktree import task_worktree_remove_tree

_TASK_AI_AGENT_NAME = 'task_ai_generator'
_TASK_AI_TIMEOUT    = 60.0

router = APIRouter()


@router.get('/tasks')
async def project_task_tasks_all(user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM project_task ORDER BY position, id")
        rows = await db.fetchall()
    tasks = [task_metadata_row_apply(r) for r in rows]
    _tasks_role_attach(tasks)

    return {'tasks': tasks}


@router.get('/tasks/{project_id}')
async def project_task_tasks_list(project_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    # project_id = 0 — это «Без проекта» в селекте. В колонке «без проекта» — всегда
    # NULL: ноль означал бы проект №0, которого не бывает. Чтение остаётся терпимым к
    # нулю ради установок, где старые строки на ноль ещё не переведены: иначе такая
    # задача не показалась бы ни под одним пунктом селекта.
    where = "project_id = 0 OR project_id IS NULL" if project_id == 0 else "project_id = %s"
    params = () if project_id == 0 else (project_id,)

    async with mysql_get_db_async() as db:
        await db.execute(f"SELECT * FROM project_task WHERE {where} ORDER BY position, id", params)
        rows = await db.fetchall()

    tasks = [task_metadata_row_apply(r) for r in rows]
    _tasks_role_attach(tasks)
    # Зависимости — тем же ответом, а не вторым запросом со страницы: строк на
    # странице сотни, и запрос на каждую был бы запросом на пустом месте. Два поля:
    # `depends_on` — что назвал менеджер, `depend_blocked` — кто из них ещё не закрыт.
    # Второе и есть ответ на вопрос «почему подзадача стоит»: связь может быть, а
    # предшественник давно закрыт, и тогда работа просто ждёт очереди.
    await _tasks_depend_attach(tasks)

    return {'tasks': tasks}


def _tasks_role_attach(tasks: list) -> None:
    """
    Положить на каждую строку роль, которая работает над ней **сейчас**.

    Вкладки страницы делят задачи по ролям, а делали это по типу задачи — а тип
    статичен: его ставят при заведении, и он говорит, кто задачу планирует. Работа же
    переходит из рук в руки. QA вернул подзадачу на доработку, её делает разработчик,
    а тип так и остался `test` — живьём #5219 висела на вкладке «Тестировщик» в
    состоянии `developing`.

    Считаем на сервере, а не на странице: карта состояний живёт в `task_role`, и
    вторая её копия в JS разошлась бы с первой на ближайшем новом состоянии.

    Пустая строка — состояние ничьё (ждёт человека, закрыто). Тогда страница остаётся
    при типе задачи: закрытую работу ищут там, где заводили.
    """
    for task in tasks:
        task['pipeline_role'] = task_role_of_state(task.get('pipeline_state'))


async def _tasks_depend_attach(tasks: list) -> None:
    """
    Положить на каждую строку её зависимости. Сбой связей список не роняет.

    Одним запросом на всю выдачу: `task_depend_of` берёт сразу все номера. Строкам
    без связей кладём пустые списки, а не отсутствие ключей, — фронтенду не придётся
    различать «связей нет» и «поле забыли положить».
    """
    for task in tasks:
        task['depends_on'] = []
        task['depend_blocked'] = []

    ids = [int(t['id']) for t in tasks if t.get('id')]
    if not ids:
        return

    try:
        links = await task_depend_of(ids)
        if not links:
            return

        # Кто из предшественников ещё не закрыт — считаем по той же выдаче, без
        # похода в базу: состояния всех строк дерева уже здесь.
        state_by_id = {int(t['id']): str(t.get('pipeline_state') or '') for t in tasks}
        for task in tasks:
            deps = links.get(int(task['id']), [])
            task['depends_on'] = deps
            task['depend_blocked'] = [
                dep for dep in deps
                if state_by_id.get(dep, '') not in TASK_DEPEND_DONE_STATES]
    except Exception as error:
        logger_info(f'project_task: зависимости не приложены: {type(error).__name__}: {error}')


@router.post('/tasks/{project_id}')
async def project_task_create(project_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    title = str(data.get('title') or '').strip()
    if not title:
        raise HTTPException(status_code=400, detail='title required')

    # «Без проекта» приходит в пути нулём — в колонку кладём NULL. Иначе «никакого
    # проекта» пишется двумя способами сразу, и каждый запрос вида «проект задачи =
    # проект оболочки» приходится писать с оговоркой на оба.
    project_id = project_id or None

    async with mysql_get_db_async() as db:
        try:
            parent_id = await task_tree_parent_check(db, None, data.get('parent_id'))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        next_pos = await task_tree_position_next(db, project_id, parent_id)

        task_type_id = data.get('task_type_id')
        metadata = data.get('metadata')
        if metadata is not None and not isinstance(metadata, dict):
            raise HTTPException(status_code=400, detail='metadata must be an object')

        await db.execute(
            "INSERT INTO project_task (project_id, parent_id, title, description, goals, status, report, position, task_type_id, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (project_id, parent_id, title, str(data.get('description') or ''), str(data.get('goals') or ''),
             str(data.get('status') or 'pending'), str(data.get('report') or ''), next_pos, task_type_id,
             json.dumps(metadata, ensure_ascii=False) if metadata else None)
        )
        await db.connection.commit()
        task_id = db.lastrowid

        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()

    return {'task': task_metadata_row_apply(task)}


@router.put('/task/{task_id}')
async def project_task_update(task_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    allowed = {'title', 'description', 'goals', 'status', 'report', 'task_type_id'}
    updates = {k: v for k, v in data.items() if k in allowed}

    # metadata приходит объектом, а в колонке лежит JSON-строка. Здесь именно замена
    # целиком: страница присылает то, что человек видел в форме. Точечная правка
    # одного ключа — `task_metadata_update`, он не трогает чужие ключи.
    if 'metadata' in data:
        meta = data.get('metadata')
        if meta is not None and not isinstance(meta, dict):
            raise HTTPException(status_code=400, detail='metadata must be an object')
        updates['metadata'] = json.dumps(meta, ensure_ascii=False) if meta else None

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
            # Каталог проекта берём тем же запросом, а не отдельным вызовом: он нужен
            # только чтобы привести пути к корню репозитория, и второе соединение
            # внутри уже открытого ради одной колонки не окупается.
            await db.execute(
                'SELECT t.pipeline_plan, t.goals, p.work_dir '
                '  FROM project_task t LEFT JOIN project p ON p.id = t.project_id '
                ' WHERE t.id = %s', (task_id,))
            row = await db.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail='task not found')
            _, subtasks = task_plan_parse(row['pipeline_plan'] or '')
            goals_plan  = task_plan_goals_get(row['pipeline_plan'] or '')
            plan_text   = str(data.get('plan_text') or '').strip()
            # Правку человека приводим наравне с планом менеджера: исполнителю
            # безразлично, кто написал абсолютный путь, — он уведёт из выкладки одинаково.
            updates['pipeline_plan'] = task_plan_serialize(
                plan_text, subtasks, goals_plan,
                repo_dir=str(row.get('work_dir') or '')) if plan_text else ''
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

    return {'task': task_metadata_row_apply(task)}


@router.get('/api/task/{task_id}/spec')
async def project_task_spec_get(task_id: int,
                                user=Depends(AuthChecker([AuthPermission.PLANNING_VIEW]))):
    """
    Спецификация строки: что требуется сделать и чем это считается сделанным.

    У задачи с подзадачами — сводная: их цели, порядок выполнения и зависимости в
    одном документе. У листа — своя, короткая. Различаем по наличию детей, а не по
    типу: подзадача с внуками — тот же родитель для них.

    Отдаём то, что лежит файлом в каталоге строки, — именно это читал агент.
    Пересобранная на лету спецификация отличалась бы от той, по которой работали, и
    разбор «почему сделано не так» шёл бы по чужому документу. Файла нет (каталог не
    заведён либо снят после слияния) — собираем сейчас и честно помечаем `stored`.
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, project_id, parent_id, title FROM project_task '
                         ' WHERE id = %s', (task_id,))
        row = await db.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail='task not found')

    work_dir = await task_role_project_work_dir(row.get('project_id'))
    spec = await task_spec_read(work_dir, task_id)

    return {'result': {**spec, 'task_id': task_id, 'title': str(row.get('title') or ''),
                       'is_parent': bool(await _has_kids(task_id))}}


async def _has_kids(task_id: int) -> bool:
    """Есть ли у строки подзадачи — по этому спецификация сводная, а не своя."""
    async with mysql_get_db_async() as db:
        await db.execute('SELECT 1 FROM project_task WHERE parent_id = %s LIMIT 1', (task_id,))

        return bool(await db.fetchone())


@router.post('/task/{task_id}/metadata')
async def project_task_metadata_patch(task_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """
    Точечно поправить `metadata` задачи: свои ключи перезаписать, чужие оставить.

    Отдельно от `PUT /task/{id}`, который заменяет мешок целиком: там страница
    присылает то, что человек видел в форме, а здесь — одну пометку из строки
    таблицы. Заменять целиком ради одного флажка нельзя — над задачей одновременно
    работают оркестратор и воркеры, и их ключи ушли бы вместе с заменой.

    Значение `null` в патче удаляет ключ (так работает JSON_MERGE_PATCH), поэтому
    отдельной ручки «убрать пометку» нет.

    Две пометки имеют немедленное следствие — «в разработку» и «в тестирование».
    Обычно их ставят заранее, и срабатывают они внутри конвейера, но человек вправе
    поставить пометку и задаче, которая нужного рубежа уже достигла: план написан и
    ждёт утверждения, разработка по всем подзадачам закончена. Смысл флажка ровно тот
    же — «решения от меня не ждать», — а следующий шаг конвейера такой задаче самой не
    полагается, и без вызова отсюда она стояла бы, пока человек не нажмёт «Утвердить»
    или не дождётся конца проверки. Все проверки (тип, состояние, сама пометка) —
    внутри `task_state_*`, поэтому вызовы безвредны и когда рубеж ещё не пройден.

    Пометку «в тестирование» ловим по `is not False`, а не по `is True`: включённое
    состояние там — это отсутствие ключа, и человек, вернувший флажок галкой, шлёт
    `null` (удаление), а не `true`.

    Возвращённый флажок заодно снимает остановку (`task_stop`): останавливая задачу,
    стоп этот флажок снял, и галка обратно — то самое «продолжаем», ради которого
    человек её и ставит. Порядок обязателен: пока пометка остановки на месте,
    `task_state_kanban_sql` держит статус, и переход фазы прошёл бы наполовину.
    """
    patch = data.get('patch')
    if not isinstance(patch, dict) or not patch:
        raise HTTPException(status_code=400, detail='patch must be a non-empty object')

    if patch.get(TASK_METADATA_KEY_DEV) is True \
            or (TASK_METADATA_KEY_TEST in patch and patch[TASK_METADATA_KEY_TEST] is not False):
        await task_stop_clear(task_id, user.username)

    await task_metadata_update(task_id, patch)
    if patch.get(TASK_METADATA_KEY_DEV) is True and await task_state_plan_to_development(task_id):
        await task_report_write(
            task_id,
            f'{user.username} пометил задачу «в разработку»: план утверждён, '
            'тип сменён на «Разработка»')
    if TASK_METADATA_KEY_TEST in patch and patch[TASK_METADATA_KEY_TEST] is not False \
            and await task_state_dev_to_testing(task_id):
        await task_report_write(
            task_id,
            f'{user.username} пометил задачу «в тестирование»: разработка закончена, '
            'тип сменён на «Тестирование»')

    async with mysql_get_db_async() as db:
        await db.execute("SELECT * FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()

    if not task:
        raise HTTPException(status_code=404, detail='task not found')

    return {'task': task_metadata_row_apply(task)}


@router.delete('/task/{task_id}')
async def project_task_delete(task_id: int, user=Depends(AuthChecker([AuthPermission.PLANNING_CREATE]))):
    """
    Удалить строку вместе со всей веткой дерева — и снять их рабочие каталоги.

    Каталоги снимаем потому, что каскад про них не знает: `DELETE` уносит строки,
    а `.claude/worktrees/feature_task_<id>` остаётся на диске сиротой, и его
    приходилось убирать руками после каждой отменённой подзадачи.

    Ветки при этом остаются: закоммиченная работа переживает удаление строки и
    достаётся обычным `git checkout feature/task_<id>`. Пропадает только
    несохранённое — какие строки это задело, видно в ответе (`worktrees.dirty`).

    Порядок важен: сначала база, потом диск. Не снявшийся каталог — это мусор,
    который уберут потом; а снятый каталог при неудавшемся удалении строки был бы
    работающей подзадачей без места работы.

    Захваты модели и оболочки снимаем следом: они лежат в своих таблицах, каскад про
    них не знает, и после удаления строки привязка оставалась висеть за номером, за
    которым больше никого нет. Держалась она вечно — освобождение по концу круга сюда
    не приходит, а протухание `locked_at` строку с уже пустым `locked_at` не трогает.
    Работу это не блокировало (свободной считается и пустая, и протухшая), но панель
    пула показывала занятой модель, за которой никого нет.

    После базы, а не до: снимать захват у задачи, которую не удалось удалить, значило
    бы отобрать модель у идущего круга.

    Идущий круг обрываем там же (`task_abort_runs`). Захваты он не держит — их только
    что сняли, — но сам прогон живёт в воркере и ждёт ответа агента до своего таймаута:
    у багфиксера сорок минут, у разработчика вчетверо больше. Всё это время роль занята,
    а следующая задача, приехав в ту же оболочку, начинает с перезапуска агента и рвёт
    его незаконченный ход. Живьём так и вышло: баг #34226 удалили в 06:44, прогон досидел
    до 06:56, и пришедший в 06:51 сосед оборвал его ответ.
    """
    async with mysql_get_db_async() as db:
        await db.execute("SELECT id, project_id FROM project_task WHERE id = %s", (task_id,))
        task = await db.fetchone()
        if not task:
            return {'ok': True, 'worktrees': {'removed': [], 'kept': [], 'dirty': []}}

        removed_ids = await task_tree_descendants(db, task_id)
        await db.execute("DELETE FROM project_task WHERE id = %s", (task_id,))
        await db.connection.commit()

    await team_llm_pool_forget(removed_ids)
    await team_shell_pool_forget(removed_ids)
    aborted = await task_abort_runs(removed_ids)

    work_dir = await task_role_project_work_dir(task.get('project_id'))
    worktrees = await task_worktree_remove_tree(work_dir, removed_ids)

    return {'ok': True, 'worktrees': worktrees, 'aborted': aborted}


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
    if not parsed:
        raise HTTPException(status_code=502, detail='AI вернул некорректный ответ')

    title       = str(parsed.get('title') or '').strip()
    description = str(parsed.get('description') or '').strip()
    goals_raw   = parsed.get('goals') or []
    if isinstance(goals_raw, list):
        goals = [{'text': str(g), 'done': False} for g in goals_raw if g]
    else:
        goals = []

    return {'title': title, 'description': description, 'goals': goals}

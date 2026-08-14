"""
Manager конвейера задач: читает описание и пишет по нему план, подзадачи и цели.

Работает через обычный агентный движок — агент `task_plan_manager`, workflow
которого прогоняет план и цели через шаги-судьи с возвратом на доработку
(план → судья → цели → судья → результат). Зовётся из воркера очереди, то есть
из отдельного процесса: очередь и поток движка поднимает `src/worker/project/task_worker.py`, здесь
только запуск workflow и разбор ответа. Тик оркестратора сюда не заходит — он
лишь ставит сообщение в Redis-очередь.

Ошибки наружу отдаются исключением — `task_pipeline` ловит его и уводит задачу
в `failed`, воркер от этого не падает.
"""
import asyncio
import uuid

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository
from src.project.task.task_plan import task_plan_goals_normalize, task_plan_parse
from src.project.task.task_role import TASK_ROLE_DEFAULT
from src.project.team.team_session import team_session_restart_role
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_MANAGER_RUN,
    task_setting_timeout_get)

TASK_MANAGER_AGENT_NAME = 'task_plan_manager'

# Все шаги workflow идут через shell-оболочку планировщика: это живой Claude Code,
# он читает проект и думает минутами, а не секундами. С судьями и доработками
# это до тринадцати обращений за прогон (разведка, план, цели, разбиение), и их
# сумма по шаговым таймаутам заведомо больше часа — потолок здесь именно потолок,
# а не сумма шагов, длинный прогон он обрывает.
# Верхняя граница не круглая, а привязана к блокировке задачи (`timeout_task_lock`):
# прогон обязан сорваться раньше, чем блокировку сочтут протухшей и её подберёт
# второй воркер. Само значение правится на `/admin/team` — см. `task_setting_timeout`.
MANAGER_USER_ID = 1  # только для атрибуции session/log


async def task_agent_manager_plan(task: dict, revise: bool = False,
                                  role: str = TASK_ROLE_DEFAULT,
                                  work_dir: str = '') -> dict:
    """
    Разложить глобальную задачу на план, подзадачи и цели.

    Args:
        revise: пересмотр существующего плана вместо написания с нуля. Тогда
            текущий план уходит в `task_plan_current`, и промпт первого шага
            раскрывает ветку «сверь с целями и поправь, а не пиши заново».
            Цели отдельной переменной не требуют: `task_goals` и так везёт
            актуальный список задачи вместе с правками человека.
        role: чья оболочка пишет план — `manager`, `developer` или `qa`
            (см. `task_role`). Уходит в переменную `task_shell_role`, по которой
            шаги workflow адресуют `claude_shell_call`, и той же ролью
            перезапускается оболочка перед прогоном.
        work_dir: каталог проекта задачи. Одной роли для адресации мало: команды
            заведены на каждый проект отдельно, и менеджеры разных проектов
            называются одинаково — без каталога прогон ушёл бы в оболочку
            соседнего проекта. Уходит в переменную `task_shell_work_dir`.
            Пустая строка (задача без проекта) — адресация только по роли.

    Returns:
        plan_text: человекочитаемый план для утверждения человеком.
        subtasks: список {'title', 'description', 'plan', 'goals'} в порядке
            выполнения. `plan` и `goals` — свои для каждой подзадачи: они лягут в
            её собственные `pipeline_plan` и `goals`, и исполнитель читает их, а
            не общий план родителя.
        goals: список {'text': str, 'done': False} — проверяемые цели по плану.
    """
    entity_agent = await _agent_get()
    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        raise RuntimeError(f'у ноды агента {TASK_MANAGER_AGENT_NAME!r} нет LLM-моделей')

    workflow_id   = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)
    session_uuid  = str(uuid.uuid4())
    task_type     = await _task_type_get(task.get('task_type_id'))

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
        # Тип задачи задаёт направление вопросов на шаге разведки: у разработки,
        # багфикса и исследования разные полезные вопросы. Имя (`dev`, `bug`, …)
        # — ключ таблицы направлений в промпте, заголовок — текст для агента.
        'task_type':        str(task_type.get('name') or ''),
        'task_type_title':  str(task_type.get('title') or ''),
        # Пустая строка при обычном планировании — не «нет значения», а осознанная
        # ложь для `%if task_plan_current%`: `ai_workflow_variable_truthy` считает
        # пустую строку ложной, и блок пересмотра в промпте просто не раскроется.
        'task_plan_current': task_plan_parse(task.get('pipeline_plan') or '')[0] if revise else '',
        # Адрес оболочки для шагов `claude_shell_call`: раньше роль была вписана
        # в шаги константой `_const_manager`, теперь её везёт прогон.
        'task_shell_role':   role,
        # Вторая половина адреса — каталог проекта. Роль отвечает «кто», каталог
        # «в чьём проекте»: карточки заведены на каждый проект, и роли у них
        # одинаковые.
        'task_shell_work_dir': str(work_dir or ''),
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    # Ровно один перезапуск на прогон и до первого шага: дочерний Claude Code
    # поднимается заново, и разговор предыдущей задачи не попадает в контекст
    # этой. Между шагами перезапускать нельзя — они продолжают один разговор.
    await team_session_restart_role(role, work_dir)

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
    workflow_task = agent_manager.framework_workflow_run(framework_model, future, loop)

    timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_MANAGER_RUN)
    try:
        result_text = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        # Отменяем сам прогон, а не только ожидание: иначе брошенный workflow
        # продолжает шагать и слать сообщения оболочке (см. framework_workflow_run).
        workflow_task.cancel()
        future.cancel()
        raise RuntimeError(f'менеджер не уложился в {timeout}s')

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


async def _task_type_get(task_type_id) -> dict:
    """
    Строка `project_task_type` по id из задачи.

    Отдельным запросом, а не JOIN'ом в `task_claim`: тип нужен одному только
    менеджеру, а выборку задачи читает весь конвейер, и лишняя пара колонок в
    ней размывает `project_task.*`. Тип не обязателен (`ON DELETE SET NULL`) —
    без него шаг разведки работает по общим вопросам.
    """
    if not task_type_id:
        return {}
    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, title FROM project_task_type WHERE id = %s', (task_type_id,))
        row = await db.fetchone()
    return row or {}


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

    Форма ответа — `{"plan": {plan_text}, "subtasks": [...], "goals": [...]}`:
    план, цели и разбиение собираются разными шагами workflow и склеиваются
    шаблоном последнего шага. Подзадачи лежат в корне, а не внутри плана: их
    пишет отдельный шаг разбиения уже после целей — менеджер сам решает, делится
    ли работа, и «не делится» у него выглядит как одна подзадача на всю задачу.
    Старую форму (`subtasks` внутри `plan`) и плоскую (`plan_text` и `subtasks`
    в корне) тоже разбираем — так отвечал workflow раньше.

    Пустой `subtasks` не чиним и не додумываем: `task_pipeline` считает такой
    план провалом и уводит задачу в `failed`, а не в бесконечное планирование.
    """
    raw    = str(result_text or '').removeprefix('json:').strip()
    parsed = json_from_string(raw)
    # `json_from_string` не бросает и не возвращает не-словарь: сорванный разбор,
    # массив вместо объекта и пустой ответ — всё это приходит пустым словарём.
    # Поэтому «не JSON» ловится по пустоте, а не по типу.
    if not parsed:
        raise RuntimeError(f'менеджер вернул не JSON: {raw[:200]}')

    plan = parsed.get('plan')
    if isinstance(plan, list):
        # Список вместо объекта — это подзадачи без текста плана: так выглядит
        # ответ менеджера, у которого разбор дотянул только до `subtasks`.
        plan = {'subtasks': plan}
    elif not isinstance(plan, dict):
        plan = parsed

    subtasks = []
    for item in (plan.get('subtasks') or parsed.get('subtasks') or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        if title:
            subtasks.append({
                'title':       title,
                'description': str(item.get('description') or '').strip(),
                # План и цели у каждой подзадачи свои: одинаковый план родителя на
                # трёх разных подзадачах ничего не говорит исполнителю. Менеджер их
                # пишет на шаге разбиения, здесь только разбираем.
                # Пустые поля не подставляем родительскими: пусто в подзадаче — это
                # видимый сигнал, что разбиение недоработано, а копия плана родителя
                # выглядела бы как настоящий план подзадачи.
                'plan':        str(item.get('plan') or '').strip(),
                'goals':       task_plan_goals_normalize(item.get('goals')),
            })

    return {
        'plan_text': str(plan.get('plan_text') or '').strip(),
        'subtasks':  subtasks,
        'goals':     task_plan_goals_normalize(parsed.get('goals')),
    }

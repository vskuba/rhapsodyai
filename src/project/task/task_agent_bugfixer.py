"""
Багфиксер конвейера задач: чинит один баг через свою shell-оболочку.

Устроен как QA (`task_agent_qa`) — агентный движок, агент `task_bug_fixer`, свой
workflow. Отличие в объёме работы: у бага нет плана, нет подзадач и нет второго круга.
Один прогон делает всё — воспроизводит, ищет причину, правит код, проверяет — и
возвращает вердикт. Не сошлось — баг уходит человеку в `blocked`, а не на новый круг:
второй заход по той же фактуре дал бы тот же ответ.

Роль `bugfixer` работает в каталоге проекта своей живой оболочкой, а код правит в
отдельной выкладке репозитория с веткой бага. Оболочка остаётся на месте, меняется
только рабочий каталог — так правки не задевают ни главную ветку, ни каталог человека.

Зовётся из воркера очереди (`src/worker/project/task_worker.py`), то есть из отдельного
процесса. Ошибки наружу отдаются исключением — `task_pipeline` ловит их и уводит баг в
повтор, воркер от этого не падает.
"""
import asyncio
import uuid

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import (ai_workflow_load, ai_workflow_variables_base,
                                ai_workflow_variables_defaults_apply)
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository
from src.project.task.task_agent_result import task_agent_result_provider_error
from src.project.task.task_plan import task_plan_goals_text
from src.project.task.task_role import task_role_project_server_url
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_BUGFIX_RUN,
    task_setting_timeout_get)
from src.project.task.task_worktree import task_worktree_branch
from src.project.team.team_session import team_session_restart_role

TASK_BUGFIXER_AGENT_NAME = 'task_bug_fixer'
TASK_BUGFIXER_ROLE = 'bugfixer'

# Потолок на весь прогон, а не сумма шагов: `timeout_bugfix_run` (3600s по умолчанию).
# Граница та же, что у остальных ролей: прогон агента < job воркера < блокировка строки.
# Значение правится на `/admin/team` — см. `task_setting_timeout`.
BUGFIXER_USER_ID = 1  # только для атрибуции session/log


async def task_agent_bugfixer_run(task: dict, role: str = TASK_BUGFIXER_ROLE,
                                  work_dir: str = '', task_dir: str = '') -> dict:
    """
    Починить один баг силами оболочки багфиксера.

    Args:
        task: строка бага. Из неё идут название, описание и `trace_meta` — у багов,
            заведённых сканером трейса, вся фактура лежит именно там: какой workflow,
            какой шаг и с каким текстом упал.
        role: чья оболочка чинит. По умолчанию `bugfixer`.
        work_dir: каталог проекта. Роль отвечает «кто», каталог — «в чьём проекте»:
            команды заведены на каждый проект отдельно, и багфиксеры разных проектов
            называются одинаково. Пустая строка (баг без проекта) — адресация только
            по роли.
        task_dir: рабочий каталог бага — своя выкладка репозитория с выкаченной веткой.
            Пустая строка — каталога нет, работаем в каталоге проекта.

    Returns:
        ok: баг починен, задачу можно закрывать.
        output: отчёт для журнала попыток и отчёта задачи.
        error: почему починить не удалось (пусто при ok) — этот текст уходит человеку
            в `pipeline_error`.
    """
    entity_agent = await _agent_get()
    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        raise RuntimeError(f'у ноды агента {TASK_BUGFIXER_AGENT_NAME!r} нет LLM-моделей')

    workflow_id   = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)
    session_uuid  = str(uuid.uuid4())
    prompt_user   = str(task.get('description') or task.get('title') or '')

    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=prompt_user,
            user_id=BUGFIXER_USER_ID,
            entity_agent=entity_agent,
            session_uuid=session_uuid,
            workflow_id=workflow_id,
        ),
        # Номер задачи промпту не нужен, но по нему карточка команды находит этот
        # прогон в трейсе и показывает, какой шаг идёт (`team_progress`). Времени
        # захвата для поиска не хватает: у роли столько прогонов, сколько проектов.
        'task_id':          str(task.get('id') or ''),
        'task_title':       str(task.get('title') or ''),
        'task_description': str(task.get('description') or ''),
        'task_goals':       task_plan_goals_text(task.get('goals')),
        # Фактура автозаведённого бага: workflow, агент, шаг и текст ошибки. Пустая
        # строка ложна для `%if%` — у бага, заведённого руками, блок не раскроется.
        'task_trace_meta':  _trace_meta_text(task.get('trace_meta')),
        'task_shell_role':  role,
        'task_shell_work_dir': str(work_dir or ''),
        # Где править код. Ветка в каталоге уже выкачена конвейером — переключать её
        # багфиксеру не нужно и не должно.
        'task_work_dir':    str(task_dir or ''),
        'task_branch':      task_worktree_branch(int(task.get('id') or 0)),
        # Адрес сервера проекта — на нём багфиксер проверяет, что фикс работает. Нет
        # каталога бага — нет и своего сервера: проверять было бы негде.
        'task_server_url':  await task_role_project_server_url(
            (task or {}).get('project_id')) if task_dir else '',
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    # Ровно один перезапуск на прогон и до первого шага: оболочка поднимается заново, и
    # прошлый баг не попадает в контекст этого. Между шагами перезапускать нельзя — они
    # продолжают один разговор, и вердикт опирается на проверку, сделанную шагом раньше.
    await team_session_restart_role(role, work_dir)

    loop   = asyncio.get_running_loop()
    future = loop.create_future()

    agent_manager   = AiFrameworkAgentManager()
    framework_model = await agent_manager.framework_model_create({
        'entity_agent':       entity_agent,
        'entities_llm':       entities_llm,
        'workflow_steps':     workflow_data['steps'],
        'workflow_variables': wf_vars,
        'prompt_user':        prompt_user,
        'user_id':            BUGFIXER_USER_ID,
        'companion_id':       None,
        'session_uuid':       session_uuid,
        'tools':              await _tools_load(),
    })
    workflow_task = agent_manager.framework_workflow_run(framework_model, future, loop)

    timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_BUGFIX_RUN)
    try:
        result_text = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        # Отменяем сам прогон, а не только ожидание: иначе брошенный workflow
        # продолжает шагать и слать сообщения оболочке.
        workflow_task.cancel()
        future.cancel()
        raise RuntimeError(f'Багфиксер не уложился в {timeout}s')

    return _result_parse(result_text)


async def _agent_get() -> dict:
    entity_agent = await AgentRepository().find_one_by({'name': TASK_BUGFIXER_AGENT_NAME})
    if not entity_agent:
        raise RuntimeError(f'агент {TASK_BUGFIXER_AGENT_NAME!r} не найден')
    if not entity_agent.get('workflow_id'):
        raise RuntimeError(f'у агента {TASK_BUGFIXER_AGENT_NAME!r} не задан workflow')
    return entity_agent


async def _tools_load() -> dict:
    """
    Карта `имя -> путь` для шагов `tool_invoke`.

    Движок берёт список из метаданных модели, а не из БД, — без этой карты шаг
    `claude_shell_call` не найдёт инструмент и прогон встанет на первом же обращении
    к оболочке.
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, path FROM tool WHERE id > 0')
        rows = await db.fetchall()
    return {r['name'].strip(): r['path'].strip() for r in (rows or []) if r.get('name') and r.get('path')}


def _trace_meta_text(value) -> str:
    """
    `trace_meta` бага — в плоский текст для промпта.

    У бага, заведённого сканером трейса, это единственный источник фактуры: описание
    пересказывает ошибку словами, а здесь лежат номера прогона и шага, по которым её
    можно найти в журнале. Заведённый руками баг сюда не попадает вовсе — пустая
    строка ложна для `%if%`, и блок промпта не раскроется.
    """
    meta = json_from_string(value) if value else {}
    if not meta:
        return ''

    fields = (('workflow_title', 'Workflow'), ('workflow_id', 'ID workflow'),
              ('agent_name', 'Агент'), ('step_title', 'Шаг'), ('step_type', 'Тип шага'),
              ('trace_run_id', 'Прогон трейса'), ('trace_step_id', 'Шаг трейса'),
              ('error_summary', 'Ошибка'))
    lines = []
    for key, title in fields:
        text = str(meta.get(key) or '').strip()
        if text:
            lines.append(f'{title}: {text}')

    return '\n'.join(lines)


def _result_parse(result_text) -> dict:
    """
    Ответ шага `return_response_text` приходит с префиксом `json:`.

    Форма — `{"ok": bool, "report": {...}, "error": str}`, где внешний `ok` говорит
    «прогон состоялся», а `report.ok` — «баг починен». Различие не формальное:
    багфиксер может отработать безупречно и вернуть отрицательный вердикт («не
    воспроизводится», «нужен доступ, которого нет») — это не сбой прогона, но и не
    повод закрывать баг.

    Разбор терпимый к мусору: отчёт пишет живой Claude Code, и сорванный JSON (обрыв
    строки в тексте, лишний markdown) не должен ронять воркер исключением — иначе
    `task_pipeline` счёл бы это техническим срывом и запустил бы прогон заново, хотя
    работа была сделана.
    """
    raw    = str(result_text or '').removeprefix('json:').strip()
    parsed = json_from_string(raw)
    # `json_from_string` не бросает и не возвращает не-словарь: сорванный разбор,
    # массив вместо объекта и пустой ответ — всё это приходит пустым словарём.
    # Поэтому «не JSON» ловится по пустоте, а не по типу.
    if not parsed:
        return {'ok': False, 'env_ok': True, 'output': raw[:2000],
                'error': f'Багфиксер вернул не JSON: {raw[:200]}'}

    # Ошибка провайдера вместо отчёта — прогона не было: промпт до модели не дошёл.
    # Хоронить баг за это нельзя, круг у него один. См. `task_agent_result`.
    provider_error = task_agent_result_provider_error(parsed)
    if provider_error:
        return {'ok': False, 'env_ok': False, 'output': raw[:2000],
                'error': f'багфиксер не начал работу: {provider_error}'}

    report = parsed.get('report')
    if not isinstance(report, dict):
        report = {}

    ok    = bool(parsed.get('ok', True)) and bool(report.get('ok', True))
    error = str(report.get('error') or parsed.get('error') or '').strip()
    if not ok and not error:
        error = 'Багфиксер не назвал причину отказа'

    # `env_ok = false` — чинить не на чем: код бага не импортируется, каталог не
    # поднялся. Хоронить баг в `blocked` за это нельзя: его никто не смотрел, работа
    # не состоялась. Такой ответ конвейер уводит в повтор (`_run_bugfix`) — тем же
    # путём, что и сорвавшийся прогон.
    env_ok = bool(parsed.get('env_ok', report.get('env_ok', True)))

    return {'ok': ok, 'env_ok': env_ok,
            'output': _report_text(report) or raw[:2000], 'error': error}


def _report_text(report: dict) -> str:
    """Отчёт багфиксера — в плоский текст для журнала попыток и отчёта задачи."""
    lines = []
    summary = str(report.get('summary') or '').strip()
    if summary:
        lines.append(summary)

    for key, title in (('cause', 'Причина'), ('files', 'Файлы'),
                       ('checks', 'Проверки'), ('error', 'Не сделано')):
        value = report.get(key)
        if isinstance(value, list):
            value = '; '.join(str(v).strip() for v in value if str(v).strip())
        value = str(value or '').strip()
        if value:
            lines.append(f'{title}: {value}')

    return '\n'.join(lines)

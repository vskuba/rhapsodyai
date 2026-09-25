"""
Developer конвейера задач: выполняет одну подзадачу плана через свою оболочку.

Работает так же, как менеджер (`task_agent_manager`) — через агентный движок,
агент `task_dev_developer`, workflow #56: разбор → реализация → самопроверка с
возвратом на доработку. Разница в адресе оболочки: роль `developer` и каталог
проекта задачи, то есть это другой живой Claude Code, а не тот, что писал план.

Зовётся из воркера очереди (`src/worker/project/task_worker.py`), то есть из
отдельного процесса. Ошибки наружу отдаются исключением — `task_pipeline` ловит
их и уводит подзадачу в `failed_qa`, воркер от этого не падает.
"""
import asyncio
import uuid

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import ai_workflow_load, ai_workflow_variables_base, ai_workflow_variables_defaults_apply
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository
from src.project.task.task_agent_result import task_agent_result_provider_error
from src.project.task.task_plan import task_plan_goals_text, task_plan_parse
from src.project.task.task_question import task_question_decisions_text, task_question_parse
from src.project.task.task_worktree import task_worktree_branch
from src.project.team.team_session import team_session_restart_role
from src.tool.claude_shell.claude_shell import (CLAUDE_SHELL_AGENT_STATUS_BUSY,
                                                claude_shell_session_status)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_DEVELOPER_RUN,
    task_setting_timeout_get)

TASK_DEVELOPER_AGENT_NAME = 'task_dev_developer'
TASK_DEVELOPER_ROLE = 'developer'

# Потолок на весь прогон, а не сумма шагов. Шаговые таймауты в workflow — 600s на
# разбор, 1800s на реализацию, 600s на самопроверку: в один круг это 3000s, но
# круг доработки (`max_dev_iterations` > 1) сумму превышает, и обрывать прогон
# должен этот потолок.
# Граница привязана к лестнице таймаутов: `timeout_developer_run` < `timeout_worker_job`
# < `timeout_task_lock`. Прогон обязан сорваться раньше, чем блокировку сочтут
# протухшей и подзадачу подберёт второй воркер. Значения правятся на `/admin/team`
# — см. `task_setting_timeout`.
DEVELOPER_USER_ID = 1  # только для атрибуции session/log


async def task_agent_developer_run(task: dict, subtask: dict, last_error: str = '',
                                   role: str = TASK_DEVELOPER_ROLE,
                                   work_dir: str = '', subtask_dir: str = '',
                                   shell_session: str = '',
                                   shell_task_prev: int = 0) -> dict:
    """
    Выполнить одну подзадачу плана силами оболочки разработчика.

    Args:
        task: родительская задача — из неё идут название, описание, план и цели.
            Разработчику нужен весь контекст, иначе подзадача читается как
            обрывок фразы.
        subtask: подзадача, которую выполняем. Ровно одна за прогон: соседние
            правит другой круг конвейера, и чужие изменения сорвали бы проверку
            QA этой подзадачи.
        last_error: замечание QA с прошлой попытки. Не пустое — прогон идёт как
            доработка (`[<if task_last_error>]` раскрывает соответствующие блоки
            промптов), а не как работа с нуля.
        role: чья оболочка выполняет работу. По умолчанию `developer`; параметр
            оставлен для симметрии с менеджером и на случай задач, которые ведёт
            другая роль.
        work_dir: каталог проекта задачи. Роль отвечает «кто», каталог — «в чьём
            проекте»: команды заведены на каждый проект отдельно, и разработчики
            разных проектов называются одинаково. Пустая строка (задача без
            проекта) — адресация только по роли.
        subtask_dir: рабочий каталог подзадачи — своя выкладка репозитория, в
            которой уже выкачена ветка подзадачи. Не путать с `work_dir`: тот
            адресует оболочку, а этот говорит ей, где лежит код. Пустая строка —
            каталога завести не вышло, работаем по-старому в каталоге проекта.

    Оболочку перед прогоном перезапускаем только при смене задачи: подзадачи
    одной задачи идут в общем контексте, и разработчик помнит, что уже сделал
    кругом раньше. Какой была прошлая задача, смотрим в журнале попыток.

    Returns:
        ok: работа выполнена и её можно отдавать QA.
        output: отчёт разработчика для журнала попыток.
        error: причина, по которой работа не выполнена (пусто при ok).
    """
    entity_agent = await _agent_get()
    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        raise RuntimeError(f'у ноды агента {TASK_DEVELOPER_AGENT_NAME!r} нет LLM-моделей')

    workflow_id   = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)
    session_uuid  = str(uuid.uuid4())
    prompt_user   = str(subtask.get('description') or subtask.get('title') or '')

    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=prompt_user,
            user_id=DEVELOPER_USER_ID,
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
        # План родительской задачи целиком: подзадача — строка из него, и без
        # соседних строк не видно, где кончается своя работа и начинается чужая.
        'task_plan_current': task_plan_parse(task.get('pipeline_plan') or '')[0],
        'subtask_id':        str(subtask.get('id') or ''),
        'subtask_title':     str(subtask.get('title') or ''),
        'subtask_description': str(subtask.get('description') or ''),
        # Свои план и цели подзадачи — то, по чему работу примут. План родителя
        # выше остаётся для контекста, а сдавать разработчик будет вот это.
        # Пустые строки у подзадач, разложенных старым кодом: там плана и целей
        # не было вовсе, и промпт по `%if%` просто не раскроет эти блоки.
        'subtask_plan':      task_plan_parse(subtask.get('pipeline_plan') or '')[0],
        'subtask_goals':     task_plan_goals_text(subtask.get('goals')),
        # Имя ветки даём готовым, а не описываем правило словами: собранное по шаблону
        # имя промпту не переспорить, а вот правило «назови ветку feature/task_НОМЕР»
        # живой Claude Code переиначивает — то дефис вместо подчёркивания, то номер
        # родителя. По этому же имени страница задач ищет merge request.
        'subtask_branch':    task_worktree_branch(subtask.get('id')),
        # Пустая строка — не «нет значения», а осознанная ложь для
        # `[<if task_last_error>]`: `ai_workflow_variable_truthy` считает пустую
        # строку ложной, и блоки про прошлую ошибку QA не раскроются.
        'task_last_error':   str(last_error or ''),
        # Решения человека по развилкам этой подзадачи — те, что он принял, отвечая
        # на вопросы роли (`task_question`). Идут в каждый круг, а не только в
        # следующий за ответом: решение принимается один раз, кругов после него
        # может быть сколько угодно. Пусто — блок `[<if subtask_decisions>]` в промпте
        # не раскроется, и промпт останется прежним.
        'subtask_decisions': task_question_decisions_text(subtask),
        'task_shell_role':   role,
        'task_shell_work_dir': str(work_dir or ''),
        # Третья часть адреса — конкретная оболочка. У роли их бывает несколько, по
        # одной на открытый терминал, и круг держит свою на всё время работы: шаги
        # ходят в один и тот же Claude Code, иначе следующий шаг не увидит того, что
        # нашёл предыдущий. Пусто — захвата не было, оболочку выберет сам инструмент
        # (самую свежую по пингу), как было до `team_shell_pool`.
        'task_shell_session': str(shell_session or ''),
        # Где работать. Каталог уже создан конвейером, ветка в нём выкачена —
        # промпту остаётся сказать «перейди туда», а не «заведи ветку». Пустая
        # строка ложна для `%if%`: блок про переход не раскроется, и разработчик
        # останется в каталоге проекта — прежнее поведение.
        'subtask_work_dir':  str(subtask_dir or ''),
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    # Перезапуск — на смене задачи, а не на каждой подзадаче. Подзадачи одной
    # задачи идут по одному плану и по одному коду: разработчику полезно помнить,
    # что он уже правил кругом раньше, — иначе каждая подзадача начинается с
    # повторного изучения тех же файлов. Новая задача — обратный случай: чужой
    # контекст там мешает, и оболочку поднимаем с нуля.
    # Если перезапускаем — то до первого шага и ровно один раз. Между шагами
    # нельзя: они продолжают один разговор, и реализация опирается на разбор,
    # сделанный шагом раньше.
    # Второе основание для перезапуска — занятый агент. Новый прогон начинается
    # только после того, как предыдущий отпустил задачу, поэтому «занят» на старте
    # значит одно: оболочка дожёвывает брошенный ход сорвавшегося прогона. Ждать
    # его бессмысленно — ответит он на позапрошлый вопрос.
    #
    # Прошлую задачу берём **у этой оболочки**, а не у роли. Оболочек у роли столько,
    # сколько терминалов открыл человек, и они ведут разные задачи разом: последний круг
    # роли мог идти в соседней, и по нему выходило «задача та же» — оболочка оставалась
    # с чужим контекстом и не перезапускалась, когда брала новую задачу. Номер приходит
    # из захвата (`_shell_assign`), снятый до того, как захват переписал его на нынешнюю.
    task_id      = int(subtask.get('parent_id') or (task or {}).get('id') or 0)
    task_id_last = int(shell_task_prev or 0)
    if not task_id or task_id != task_id_last or await _shell_busy(role, work_dir):
        # Перезапускаем свою оболочку, а не «оболочку роли»: у роли их несколько,
        # и маркер, ушедший соседу, снёс бы его ход посреди работы.
        await team_session_restart_role(role, work_dir, session_uuid=shell_session)

    loop   = asyncio.get_running_loop()
    future = loop.create_future()

    agent_manager   = AiFrameworkAgentManager()
    framework_model = await agent_manager.framework_model_create({
        'entity_agent':       entity_agent,
        'entities_llm':       entities_llm,
        'workflow_steps':     workflow_data['steps'],
        'workflow_variables': wf_vars,
        'prompt_user':        prompt_user,
        'user_id':            DEVELOPER_USER_ID,
        'companion_id':       None,
        'session_uuid':       session_uuid,
        'tools':              await _tools_load(),
    })
    workflow_task = agent_manager.framework_workflow_run(framework_model, future, loop)

    timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_DEVELOPER_RUN)
    try:
        result_text = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        # Прогон отменяем целиком. Отмена одного `future` его не останавливает:
        # брошенный workflow продолжает идти по шагам и слать разработчику
        # промпты — уже никем не ожидаемые, поверх работы следующего круга.
        workflow_task.cancel()
        future.cancel()
        raise RuntimeError(f'разработчик не уложился в {timeout}s')

    # `session_uuid` отдаём наружу: по нему `task_log` находит трассу этого
    # прогона и перекладывает пройденные шаги в журнал строки. Своего способа
    # добраться до трассы у конвейера нет — сессию заводит эта функция.
    return {**_result_parse(result_text), 'session_uuid': session_uuid}


async def _agent_get() -> dict:
    entity_agent = await AgentRepository().find_one_by({'name': TASK_DEVELOPER_AGENT_NAME})
    if not entity_agent:
        raise RuntimeError(f'агент {TASK_DEVELOPER_AGENT_NAME!r} не найден')
    if not entity_agent.get('workflow_id'):
        raise RuntimeError(f'у агента {TASK_DEVELOPER_AGENT_NAME!r} не задан workflow')
    return entity_agent


async def _tools_load() -> dict:
    """
    Карта `имя -> путь` для шагов `tool_invoke`.

    Без неё workflow падает на шаге `counter_increment` — счётчик кругов
    самопроверки вызывается как обычный инструмент, а движок берёт список из
    метаданных модели, а не из БД.
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, path FROM tool WHERE id > 0')
        rows = await db.fetchall()
    return {r['name'].strip(): r['path'].strip() for r in (rows or []) if r.get('name') and r.get('path')}


async def _shell_busy(role: str, work_dir: str) -> bool:
    """
    Занят ли агент прямо сейчас. Спрашиваем реестр, а не ждём освобождения:
    это решение «перезапускать ли», а ожидание своё возьмёт `claude_shell_call`.

    Реестр молчит (оболочки нет вовсе) — считаем незанятым: перезапускать нечего,
    и шаг сам вернёт `no_session`.
    """
    session = await claude_shell_session_status(role, work_dir)
    return str(session.get('agent_status') or '') == CLAUDE_SHELL_AGENT_STATUS_BUSY


def _result_parse(result_text) -> dict:
    """
    Ответ шага return_response_text приходит с префиксом `json:`.

    Форма — `{"ok": bool, "report": {...}, "error": str}`, где внешний `ok`
    говорит «прогон состоялся», а `report.ok` — «подзадача выполнена». Различие
    не формальное: оболочка может ответить и сказать, что сделать не смогла, —
    это не сбой прогона, но и не повод отдавать работу QA.

    Разбор терпимый к мусору: отчёт пишет живой Claude Code, и сорванный JSON
    (обрыв строки в тексте ошибки, лишний markdown) не должен ронять воркер
    исключением — такой ответ уходит в `error` как есть, а подзадача получает
    ещё одну попытку из отведённых `timeout_attempt_max`.
    """
    raw    = str(result_text or '').removeprefix('json:').strip()
    parsed = json_from_string(raw)
    # `json_from_string` не бросает и не возвращает не-словарь: сорванный разбор,
    # массив вместо объекта и пустой ответ — всё это приходит пустым словарём.
    # Поэтому «не JSON» ловится по пустоте, а не по типу.
    if not parsed:
        return {'ok': False, 'output': raw[:2000],
                'error': f'разработчик вернул не JSON: {raw[:200]}'}

    # Ошибка провайдера вместо отчёта — прогона не было: промпт до модели не дошёл.
    # Без этой ветки объект без ключа `ok` разбирался по умолчанию как `ok = True`,
    # и нетронутый код уходил на проверку QA. См. `task_agent_result`.
    provider_error = task_agent_result_provider_error(parsed)
    if provider_error:
        return {'ok': False, 'env_ok': False, 'output': raw[:2000],
                'error': f'разработчик не начал работу: {provider_error}'}

    report = parsed.get('report')
    if not isinstance(report, dict):
        report = {}

    ok    = bool(parsed.get('ok', True)) and bool(report.get('ok', True))
    error = str(report.get('error') or parsed.get('error') or '').strip()
    if not ok and not error:
        error = 'разработчик не отчитался о выполнении'

    # `env_ok = false` — среда не пригодна для работы: сервер подзадачи не поднялся,
    # ветка выкачена от сломанного master. Это не «работа не сошлась», а несостоявшийся
    # прогон: попытку за него жечь не за что, конвейер уводит такой ответ в повтор
    # (`_run_developer`). Умолчание True — старые ответы без поля считаются обычными.
    env_ok = bool(parsed.get('env_ok', report.get('env_ok', True)))

    # Ветка и merge request идут отдельными полями, а не только строкой в отчёте:
    # по ним страница задач рисует ссылку, и разбирать их обратно из текста журнала
    # было бы гаданием. Название ключа у живого агента гуляет — принимаем оба.
    # Вопрос человеку ищем и в отчёте, и на верхнем уровне: развилка может встать
    # раньше, чем разработчику будет о чём отчитываться, и тогда объект `report`
    # он не заполняет вовсе. См. `task_question`.
    return {
        'ok':     ok,
        'env_ok': env_ok,
        'output': _report_text(report) or raw[:2000],
        'error':  error,
        'branch': str(report.get('branch') or '').strip(),
        'mr_url': str(report.get('mr_url') or report.get('merge_request') or '').strip(),
        'question': task_question_parse(report) or task_question_parse(parsed),
    }


def _report_text(report: dict) -> str:
    """Отчёт разработчика — в плоский текст для журнала попыток `task_state`."""
    lines = []
    summary = str(report.get('summary') or '').strip()
    if summary:
        lines.append(summary)

    files = report.get('files')
    if isinstance(files, list):
        paths = [str(f).strip() for f in files if str(f).strip()]
        if paths:
            lines.append('Файлы: ' + ', '.join(paths))

    for key, title in (('branch', 'Ветка'), ('checks', 'Проверки')):
        value = str(report.get(key) or '').strip()
        if value:
            lines.append(f'{title}: {value}')

    return '\n'.join(lines)

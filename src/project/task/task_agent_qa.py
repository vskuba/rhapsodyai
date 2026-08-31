"""
QA конвейера задач: проверяет одну выполненную подзадачу через свою оболочку.

Устроен как разработчик (`task_agent_developer`) — агентный движок, агент
`task_qa_tester`, workflow #57: разбор изменений → прогон проверок → вердикт с
возвратом на второй круг. Разница в адресе оболочки и в праве на запись: роль
`qa` работает в том же каталоге проекта, но своим живым Claude Code — тем, что
не писал код. Проверяющий и автор обязаны быть разными оболочками, иначе
самопроверка разработчика и проверка QA — один и тот же контекст.

Что именно гоняет QA, решает промпт workflow: существующий набор тестов проекта
и ручная сверка с описанием подзадачи. Произвольный сгенерированный код здесь не
исполняется — проверка не должна становиться ещё одним автором изменений.

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
from src.project.task.task_metadata import (
    TASK_METADATA_KEY_QA_MODE,
    task_metadata_parse)
from src.project.task.task_plan import task_plan_goals_text, task_plan_parse
from src.project.task.task_question import task_question_decisions_text, task_question_parse
from src.project.task.task_role import task_role_project_server_url
from src.project.task.task_worktree import task_worktree_branch
from src.project.team.team_session import team_session_restart_role
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_QA_RUN,
    task_setting_timeout_get)

TASK_QA_AGENT_NAME = 'task_qa_tester'
TASK_QA_ROLE = 'qa'

# Режимы проверки из metadata задачи (`TASK_METADATA_KEY_QA_MODE`). Lite — код,
# быстрая сверка документации и соответствия спецификации, ничего не запускаем.
# Full — то же плюс полный прогон тестов и чеклист QA. Слово `lite` выбрано
# дефолтом и на фронте, и здесь: расойтись им негде, читатель один —
# `task_agent_qa_mode`.
QA_MODE_LITE = 'lite'
QA_MODE_FULL = 'full'

# Потолок на весь прогон, а не сумма шагов. Шаговые таймауты в workflow — 600s на
# разбор изменений, 1800s на прогон проверок, 600s на вердикт: в один круг это
# 3000s, но второй круг проверок (`max_qa_iterations` > 1) сумму превышает, и
# обрывать прогон должен именно этот потолок.
# Граница та же, что у разработчика: `timeout_qa_run` < `timeout_worker_job` <
# `timeout_task_lock`. Прогон обязан сорваться раньше, чем блокировку сочтут
# протухшей и подзадачу подберёт второй воркер. Значения правятся на `/admin/team`
# — см. `task_setting_timeout`.
QA_USER_ID = 1  # только для атрибуции session/log


async def task_agent_qa_run(task: dict, subtask: dict, last_error: str = '',
                            role: str = TASK_QA_ROLE,
                            work_dir: str = '', subtask_dir: str = '',
                            shell_session: str = '') -> dict:
    """
    Проверить одну выполненную подзадачу силами оболочки QA.

    Args:
        task: родительская задача — из неё идут название, описание, план и цели.
            Без плана целиком не видно, что именно относилось к этой подзадаче, а
            что делают соседние.
        subtask: подзадача, которую проверяем. Ровно одна за прогон: соседние
            правит другой круг конвейера, и чужие изменения в том же каталоге
            смешали бы результат проверки.
        last_error: замечание с прошлого круга. У QA оно почти всегда пусто —
            подзадача с непустой ошибкой уходит обратно разработчику, а не на
            повторную проверку; параметр оставлен ради единой сигнатуры с
            `task_agent_developer_run` и на случай повторной проверки вручную.
        role: чья оболочка проверяет. По умолчанию `qa`.
        work_dir: каталог проекта задачи. Роль отвечает «кто», каталог — «в чьём
            проекте»: команды заведены на каждый проект отдельно, и QA разных
            проектов называются одинаково. Пустая строка (задача без проекта) —
            адресация только по роли.
        subtask_dir: рабочий каталог подзадачи — та же выкладка репозитория, в
            которой работал разработчик, с выкаченной веткой подзадачи. Проверять
            надо именно её: в общем чекауте лежит чужой код. Пустая строка —
            каталога нет, проверка идёт в каталоге проекта.

    Returns:
        ok: проверки пройдены, подзадачу можно закрывать.
        output: отчёт QA для журнала попыток.
        error: чем проверки не устроили (пусто при ok) — этот текст уходит
            разработчику как замечание следующего круга.
    """
    entity_agent = await _agent_get()
    entities_llm = await ai_llm_node_get(entity_agent.get('node_id'))
    if not entities_llm:
        raise RuntimeError(f'у ноды агента {TASK_QA_AGENT_NAME!r} нет LLM-моделей')

    workflow_id   = entity_agent['workflow_id']
    workflow_data = await ai_workflow_load(workflow_id)
    session_uuid  = str(uuid.uuid4())
    prompt_user   = str(subtask.get('description') or subtask.get('title') or '')

    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=prompt_user,
            user_id=QA_USER_ID,
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
        # Свои план и цели подзадачи — критерий приёмки этого круга. Цели родителя
        # выше проверяются целиком только на финале задачи, здесь же QA обязан
        # смотреть на то, что обещала именно эта подзадача.
        'subtask_plan':      task_plan_parse(subtask.get('pipeline_plan') or '')[0],
        'subtask_goals':     task_plan_goals_text(subtask.get('goals')),
        # Отчёт разработчика с последней удачной попытки: что он менял, в каких
        # файлах и в какой ветке. Без него QA начинает проверку с поиска самих
        # изменений, а это лишний круг обращений к оболочке.
        'task_dev_report':   await _developer_report(int(subtask.get('id') or 0)),
        # Пустая строка — не «нет значения», а осознанная ложь для
        # `%if task_last_error%`: `ai_workflow_variable_truthy` считает пустую
        # строку ложной, и блоки про прошлый круг не раскроются.
        'task_last_error':   str(last_error or ''),
        # Решения человека по развилкам подзадачи (`task_question`). QA они нужны
        # не меньше разработчика: без них проверяющий требует ровно того, от чего
        # человек отказался, и вердикт получается «не сошлось» на пустом месте.
        'subtask_decisions': task_question_decisions_text(subtask),
        'task_shell_role':   role,
        'task_shell_work_dir': str(work_dir or ''),
        # Третья часть адреса — конкретная оболочка. У роли их бывает несколько, по
        # одной на открытый терминал, и круг держит свою на всё время работы: шаги
        # ходят в один и тот же Claude Code, иначе следующий шаг не увидит того, что
        # нашёл предыдущий. Пусто — захвата не было, оболочку выберет сам инструмент
        # (самую свежую по пингу), как было до `team_shell_pool`.
        'task_shell_session': str(shell_session or ''),
        # Где проверять. Каталог тот же, что был у разработчика, ветка в нём уже
        # выкачена — переключать её QA не нужно и не должен. Пустая строка ложна
        # для `%if%`: блок про переход не раскроется.
        'subtask_work_dir':  str(subtask_dir or ''),
        # Имя ветки берём из того же места, что и разработчик: промпт QA раньше
        # склеивал его сам («task/N») и расходился с настоящим именем.
        'subtask_branch':    task_worktree_branch(int(subtask.get('id') or 0)),
        # Адрес сервера этой задачи — свой у каждого проекта. Общий сервер
        # установки для проверки не годится: на нём код основного чекаута, а не
        # ветки подзадачи. Нет каталога подзадачи — нет и своего сервера.
        'subtask_server_url': await task_role_project_server_url(
            (task or {}).get('project_id')) if subtask_dir else '',
        # Глубина проверки: `lite` (умолчание) или `full` — свитчер рядом с кнопкой
        # «лог» на странице задач. Вторя переменная — того же выбора флаг для `%if%`:
        # непустая строка `lite` была бы для условия истинной, поэтому полный прогон
        # тестов раскрывает только `subtask_qa_full`. См. `task_agent_qa_mode`.
        'subtask_qa_mode':   task_agent_qa_mode(task),
        'subtask_qa_full':   task_agent_qa_mode_full(task),
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow_data['variables'])

    # Ровно один перезапуск на прогон и до первого шага: оболочка QA поднимается
    # заново, и проверка предыдущей подзадачи не попадает в контекст этой. Между
    # шагами перезапускать нельзя — они продолжают один разговор, и вердикт
    # опирается на прогон, сделанный шагом раньше.
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
        'user_id':            QA_USER_ID,
        'companion_id':       None,
        'session_uuid':       session_uuid,
        'tools':              await _tools_load(),
    })
    workflow_task = agent_manager.framework_workflow_run(framework_model, future, loop)

    timeout = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_QA_RUN)
    try:
        result_text = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        # Отменяем сам прогон, а не только ожидание: иначе брошенный workflow
        # продолжает шагать и слать сообщения оболочке (см. framework_workflow_run).
        workflow_task.cancel()
        future.cancel()
        raise RuntimeError(f'QA не уложился в {timeout}s')

    # `session_uuid` отдаём наружу: по нему `task_log` находит трассу этого
    # прогона и перекладывает пройденные шаги в журнал строки. Своего способа
    # добраться до трассы у конвейера нет — сессию заводит эта функция.
    return {**_result_parse(result_text), 'session_uuid': session_uuid}


def task_agent_qa_mode(task: dict) -> str:
    """
    Режим проверки QA для этой задачи: `'lite'` или `'full'`.

    Ключ `qa_mode` пишет свитчер на странице `/admin/task` в metadata **родительской**
    задачи — режим свойство задачи целиком, а не отдельной подзадачи, поэтому читаем
    строку родителя, а не ребёнка. Ключа нет или значение пустое — `lite`: это
    умолчание задано ещё на фронте, и прогон, у которого никто не спрашивал, обязан
    оставаться дешёвым.

    Значение нормализуем: в мешке случаются `false`, число и мусор от ручной правки,
    а промпту нужна одна из двух строк — на них ветвится глубина проверки.
    """
    mode = str(task_metadata_parse((task or {}).get('metadata')).get(TASK_METADATA_KEY_QA_MODE) or '')
    return mode.strip().lower() if mode.strip().lower() == QA_MODE_FULL else QA_MODE_LITE


def task_agent_qa_mode_full(task: dict) -> str:
    """
    Флаг полного режима для промпта — `'yes'` или `''`.

    Промпту нельзя подставить сам режим и сравнить его с `full`: `%if%` в workflow
    проверяет только непустоту (`ai_workflow_variable_truthy`), и строка `lite`
    оказалась бы истинной. Поэтому в промпт едут две переменные: `subtask_qa_mode`
    говорит человеку и агенту, какой режим выбран, а `subtask_qa_full` — пустая
    строка в lite — раскрывает блок про запуск всех тестов.
    """
    return 'yes' if task_agent_qa_mode(task) == QA_MODE_FULL else ''


async def _agent_get() -> dict:
    entity_agent = await AgentRepository().find_one_by({'name': TASK_QA_AGENT_NAME})
    if not entity_agent:
        raise RuntimeError(f'агент {TASK_QA_AGENT_NAME!r} не найден')
    if not entity_agent.get('workflow_id'):
        raise RuntimeError(f'у агента {TASK_QA_AGENT_NAME!r} не задан workflow')
    return entity_agent


async def _tools_load() -> dict:
    """
    Карта `имя -> путь` для шагов `tool_invoke`.

    Без неё workflow падает на шаге `counter_increment` — счётчик кругов проверки
    вызывается как обычный инструмент, а движок берёт список из метаданных
    модели, а не из БД.
    """
    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, path FROM tool WHERE id > 0')
        rows = await db.fetchall()
    return {r['name'].strip(): r['path'].strip() for r in (rows or []) if r.get('name') and r.get('path')}


async def _developer_report(subtask_id: int) -> str:
    """
    Отчёт последней удачной попытки разработчика по этой подзадаче.

    Берём именно удачную: провальные попытки описывают, почему работа не вышла, а
    QA проверяет то, что до него дошло. Нет строки (например, подзадачу отдали на
    проверку вручную) — пустая строка, и промпт раскроет ветку «изменения ищи
    сам».
    """
    if not subtask_id:
        return ''

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT output FROM project_task_attempt "
            "WHERE task_id = %s AND role = 'developer' AND status = 'ok' "
            "ORDER BY attempt_no DESC, id DESC LIMIT 1",
            (subtask_id,),
        )
        row = await db.fetchone()

    return str((row or {}).get('output') or '').strip()


def _result_parse(result_text) -> dict:
    """
    Ответ шага return_response_text приходит с префиксом `json:`.

    Форма — `{"ok": bool, "report": {...}, "error": str}`, где внешний `ok`
    говорит «прогон состоялся», а `report.ok` — «проверки пройдены». Различие не
    формальное: QA может отработать безупречно и вернуть отрицательный вердикт —
    это не сбой прогона, но и не повод закрывать подзадачу.

    Разбор терпимый к мусору: отчёт пишет живой Claude Code, и сорванный JSON
    (обрыв строки в тексте замечания, лишний markdown) не должен ронять воркер
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
                'error': f'QA вернул не JSON: {raw[:200]}'}

    # Ошибка провайдера вместо отчёта — проверки не было: промпт до модели не дошёл.
    # Вернуть за это подзадачу разработчику нельзя, его работу никто не смотрел.
    # См. `task_agent_result`.
    provider_error = task_agent_result_provider_error(parsed)
    if provider_error:
        return {'ok': False, 'env_ok': False, 'output': raw[:2000],
                'error': f'QA не начал проверку: {provider_error}'}

    report = parsed.get('report')
    if not isinstance(report, dict):
        report = {}

    ok    = bool(parsed.get('ok', True)) and bool(report.get('ok', True))
    error = str(report.get('error') or parsed.get('error') or '').strip()
    if not ok and not error:
        error = 'QA не назвал причину отказа'

    # `env_ok = false` — проверять не на чем: сервер подзадачи не поднялся. Вернуть
    # за это подзадачу разработчику нельзя — его работу никто не смотрел, поэтому
    # конвейер уводит такой ответ в повтор (`_run_qa`), не сжигая попытку.
    env_ok = bool(parsed.get('env_ok', report.get('env_ok', True)))

    # Вопрос человеку ищем и в отчёте, и на верхнем уровне: развилка может встать
    # раньше, чем QA будет о чём отчитываться. См. `task_question`.
    return {'ok': ok, 'env_ok': env_ok,
            'output': _report_text(report) or raw[:2000], 'error': error,
            'question': task_question_parse(report) or task_question_parse(parsed)}


def _report_text(report: dict) -> str:
    """Отчёт QA — в плоский текст для журнала попыток `task_state`."""
    lines = []
    summary = str(report.get('summary') or '').strip()
    if summary:
        lines.append(summary)

    for key, title in (('checks', 'Проверки'), ('failed', 'Провалено'), ('coverage', 'Покрытие')):
        value = report.get(key)
        if isinstance(value, list):
            items = [str(v).strip() for v in value if str(v).strip()]
            value = '; '.join(items)
        value = str(value or '').strip()
        if value:
            lines.append(f'{title}: {value}')

    return '\n'.join(lines)

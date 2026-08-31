"""
Конвейер без агентов: подмена ролей и прогон действий в процессе теста.

Зачем. Тесты конвейера проверяют **маршрутизацию** — какое действие достанется задаче
в таком-то состоянии и куда она перейдёт после него. Живой агент к этому не имеет
отношения: он пишет план, а проверяем мы, что план вообще запросили и что состояние
сменилось.

Раньше эти тесты гоняли всю установку: HTTP → Cronicle-тик → Redis → контейнер воркера →
Claude Code → LLM. Ответа ждали опросом до `WAIT_TIMEOUT = 900` секунд на тест. При
пустой корзине оболочек (задача заводится без проекта, а менеджеры подняты в проекте)
ждать было и вовсе некого: восемнадцать тестов упирались в дедлайн и давали шесть часов
прогона вместо секунд — при том, что ни одного дефекта такое ожидание не ловит.

Здесь агенты подменяются, а действие выполняется прямо в процессе теста. Остаётся ровно
то, ради чего тест писался: отбор работы, переходы состояний, запись в базу.

**Что подменяется и почему именно это.** Три вещи, каждая — внешняя зависимость, без
которой круг не начнётся: сам агент (поход в LLM), захват оболочки и захват модели. Всё
остальное — настоящее: и `_action_claim`, и раннеры, и запись состояний.
"""

import contextlib
import itertools
from unittest.mock import patch

# Счётчик кругов планирования. Каждый следующий план обязан отличаться от прежнего:
# настоящий менеджер, переписывая план, выдаёт другой текст, и на этом держится
# ревизия — она заводится только на изменившийся план.
#
# Счётчик модульный, а не на вход в подмену: один тест открывает её несколько раз
# (план, потом пересмотр), и локальный сбрасывался бы к единице. Планы выходили
# одинаковыми, ревизия не заводилась, и тест винил конвейер в том, чего тот не делал.

# Что «менеджер» отвечает по умолчанию. Форма — та же, что у настоящего
# `task_agent_manager_plan`: тест, проверяющий разбор ответа, должен ловить расхождение
# формы, а не подстраиваться под удобную заглушку.
_PLAN_ROUND = itertools.count(1)

PIPELINE_MOCK_PLAN = {
    'plan_text': 'план из заглушки',
    'subtasks': [
        {'title': 'первая подзадача', 'description': 'что сделать',
         'plan': '- шаг', 'goals': [{'text': 'цель подзадачи', 'done': False}]},
    ],
    'goals': [{'text': 'цель задачи', 'done': False}],
    'question': {},
    'questions': [],
}

# Ответ «разработчика»: работа сделана, коммит есть.
PIPELINE_MOCK_DEV = {'ok': True, 'output': 'сделано заглушкой', 'error': '',
                     'mr_url': '', 'question': {}}

# Ответ «QA»: принято.
PIPELINE_MOCK_QA = {'ok': True, 'qa_ok': True, 'output': 'проверено заглушкой',
                    'error': '', 'question': {}}


@contextlib.asynccontextmanager
async def pipeline_agents_mocked(plan: dict | None = None, dev: dict | None = None,
                                 qa: dict | None = None, roles: dict | None = None):
    """
    Конвейер с подменёнными агентами.

    Args:
        plan: что «менеджер» вернёт вместо похода в LLM.
        dev: что вернёт «разработчик».
        qa: что вернёт «QA».
        roles: живые оболочки по проектам. По умолчанию — все роли в корзине «без
            проекта», потому что тесты заводят задачи через `/tasks/0`.

    Подменяем и захват оболочки с моделью: без них круг не начнётся вовсе — раннер
    вернёт «ждёт свободной оболочки» и ничего не сделает. Это не обход проверки, а
    замена той же внешней зависимости: живого терминала на машине.
    """
    import src.project.task.task_pipeline as pipeline

    sessions = roles or {0: {'manager': ['mock-manager'], 'developer': ['mock-dev'],
                             'qa': ['mock-qa'], 'bugfixer': ['mock-bugfixer']}}

    async def _sessions():
        return sessions

    async def _plan(*args, **kwargs):
        answer = dict(plan or PIPELINE_MOCK_PLAN)
        if not plan:
            answer['plan_text'] = f"{answer['plan_text']}, круг {next(_PLAN_ROUND)}"

        return answer

    async def _dev(*args, **kwargs):
        return dict(dev or PIPELINE_MOCK_DEV)

    async def _qa(*args, **kwargs):
        return dict(qa or PIPELINE_MOCK_QA)

    async def _shell(action, task, role):
        return 'mock-session'

    async def _llm(action, task, role):
        return {}

    # Single-flight держится на Redis, а он в compose наружу не опубликован: с хоста
    # `redis:6379` не разрешается. Подменяем его памятью процесса — и это не подмена
    # проверяемого: ключ single-flight стоит только на подметальщиках
    # (`TASK_WORKER_SINGLE_FLIGHT` — скан багов, финализация), а работа задач
    # дедуплицируется захватом строки в базе, который остаётся настоящим.
    taken: set = set()

    def _flight_acquire(kind, job_timeout):
        if kind in taken:
            return False
        taken.add(kind)

        return True

    def _flight_release(kind):
        taken.discard(kind)

    def _enqueue(action, job_timeout):
        # Очередь тоже подменяем: настоящий `task_worker_enqueue` кладёт сообщение в
        # живой Redis, откуда его подхватит контейнер воркера — и пойдёт в LLM уже
        # мимо всех наших заглушек. Тест, проверяющий тик, обязан оставаться внутри
        # своего процесса.
        return f"mock-job-{action.get('kind')}"

    with patch.object(pipeline, 'task_role_shell_sessions_by_project', _sessions), \
         patch.object(pipeline, 'task_agent_manager_plan', _plan), \
         patch.object(pipeline, 'task_agent_developer_run', _dev), \
         patch.object(pipeline, 'task_agent_qa_run', _qa), \
         patch.object(pipeline, '_shell_assign', _shell), \
         patch.object(pipeline, '_llm_assign', _llm), \
         patch.object(pipeline, 'task_worker_enqueue', _enqueue), \
         patch.object(pipeline, 'task_worker_flight_acquire', _flight_acquire), \
         patch.object(pipeline, 'task_worker_flight_release', _flight_release):
        yield


async def pipeline_run(kind: str, **fields) -> str | None:
    """
    Выполнить одно готовое действие. Returns: строку итога, как у воркера.

    Годится там, где состояние строки уже подходит раннеру. Первый круг задачи так не
    запустить: запись плана требует состояния `planning`, а ставит его захват — см.
    `pipeline_drive`.
    """
    from src.project.task.task_pipeline import task_pipeline_action_run

    return await task_pipeline_action_run({'kind': kind, **fields})


async def pipeline_claim(worker: str = 'pytest') -> dict | None:
    """Что конвейер выбрал бы к исполнению прямо сейчас. Захват метит строку в базе."""
    from src.project.task.task_pipeline import _action_claim

    return await _action_claim(worker)


async def pipeline_drive(task_id: int, states: tuple, steps: int = 40) -> str:
    """
    Гонять конвейер, пока задача не дойдёт до одного из `states`. Returns: состояние.

    Захват и раннеры настоящие — подменены только агенты. Через захват, а не сборкой
    действия руками, потому что он часть проверяемого: он же переводит задачу
    `NULL -> planning`, и без этого перехода запись плана не найдёт строку
    (`task_state_plan_save` пишет только по `planning` и `reviewing`).

    **Чужую работу не двигаем.** Захват выбирает по живым оболочкам, а в подмене они
    заведены только в корзине «без проекта» — туда попадают лишь задачи, заведённые
    через `/tasks/0`, то есть тестовые. Настоящие задачи установки принадлежат проекту
    и в отбор не попадают. Действие не нашей задачи всё равно пропускаем.

    Шаги считаны, а не бесконечны: полный проход задачи — это план, утверждение,
    разбор на подзадачи, по два круга на каждую и финализация, то есть десятки
    переходов, но конечное их число. Зацикленный конвейер обязан упереться в предел и
    показать это тесту, а не крутиться до таймаута — ровно от этого мы здесь и уходим.
    """
    from mysql_.mysql_ import mysql_get_db_async
    from src.project.task.task_pipeline import task_pipeline_action_run

    swept = False
    for _ in range(steps):
        async with mysql_get_db_async() as db:
            await db.execute('SELECT pipeline_state FROM project_task WHERE id = %s', (task_id,))
            row = await db.fetchone() or {}
        state = row.get('pipeline_state')
        if state in states:
            return state

        action = await pipeline_claim()
        if not action:
            # Захват отбирает работу по строкам, а подметальщиков (`finalize`) ставит
            # сам тик — они ищут работу уже в воркере и адресата не имеют. Без них
            # задача с закрытыми подзадачами так и стоит в `processing`: закрывает её
            # именно финализация, сведя состояние с детьми.
            #
            # Зовём, когда отбирать больше нечего: пока идут круги подзадач, сводить
            # ещё рано.
            if not swept:
                swept = True
                await task_pipeline_action_run({'kind': 'finalize'})
                continue

            return state
        if not await _action_is_ours(action, task_id):
            continue
        await task_pipeline_action_run(action)
        swept = False

    async with mysql_get_db_async() as db:
        await db.execute('SELECT pipeline_state FROM project_task WHERE id = %s', (task_id,))

        return (await db.fetchone() or {}).get('pipeline_state')


async def _action_is_ours(action: dict, task_id: int) -> bool:
    """
    Действие нашей задачи или её подзадачи.

    Подзадачи проверяем отдельно: их действия адресуются `subtask_id`, а номера у них
    свои. Сверив их с номером задачи, полный проход обрывался бы сразу после разбора
    плана — круги Developer и QA считались бы чужими.

    Действия без номера — подметальщики, и они пропускаются всегда: см. ниже.
    """
    from mysql_.mysql_ import mysql_get_db_async

    if int(action.get('task_id') or 0) == int(task_id):
        return True

    subtask_id = int(action.get('subtask_id') or 0)
    if not subtask_id:
        # Действие без номера — подметальщик (`finalize`, `bug_scan`): он ищет работу
        # сам и адресата не имеет. Пропускаем, потому что без финализации задача не
        # дойдёт до `done`: закрывает её именно она, сведя состояние с подзадачами.
        #
        # Чужие строки он при этом тоже сводит — и это ровно то, что делает боевой тик
        # каждую минуту. Своей работы он не выдумывает: закрывает то, у чего все дети
        # терминальны, и возвращает то, у чего ребёнок ожил.
        return True

    async with mysql_get_db_async() as db:
        await db.execute('SELECT parent_id FROM project_task WHERE id = %s', (subtask_id,))
        row = await db.fetchone() or {}

    return int(row.get('parent_id') or 0) == int(task_id)


async def pipeline_tick(max_actions: int = 1) -> dict:
    """
    Тик оркестратора в этом же процессе. Returns: его статистику.

    Настоящий, со всем отбором и single-flight, — подменена только постановка в
    очередь. Через HTTP `/cronjob` то же самое ушло бы в живой Redis, и работу забрал
    бы контейнер воркера: заглушки теста до него не достают, и круг пошёл бы в LLM.

    Зовём внутри `pipeline_agents_mocked`.
    """
    from src.project.task.task_pipeline import task_pipeline_tick

    return await task_pipeline_tick(max_actions=max_actions)

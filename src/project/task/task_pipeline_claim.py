"""
Отбор работы конвейера: что тик кладёт в очередь.

Триггер тика (`task_pipeline_tick`) не ходит к агентам — он только решает, какую
строку взять. Вся эта логика отбора живёт здесь: `_action_claim` перебирает шаги
по приоритету ролей, каждый шаг (`_claim_*`) ловит свою строку у `task_claim`, а
`_roles_by_project_free` отсеивает проекты, выбравшие свой предел «Parallel LLM».

Порядок перебора и есть приоритет ролей: QA → Developer → Багфиксер → разбор плана
→ Manager (пересмотр, потом планирование). Работа, начатая раньше, важнее начатой
позже: проверить сделанное — значит закрыть подзадачу и освободить круг, а взять в
планирование новую задачу — значит добавить работы к незакрытой.

Соседние модули: `task_pipeline` — триггер и карта исполнения, `task_pipeline_run` —
то, что воркер делает с захваченной строкой, `task_claim` — сами блокировки.
"""
from src.project.task.task_claim import (
    task_claim_inflight_by_project,
    task_claim_subtask_developable,
    task_claim_subtask_testable,
    task_claim_task,
    task_claim_task_bug,
    task_claim_task_review,
    task_claim_task_unplanned,
)
from src.project.task.task_plan import task_plan_parse
from src.project.task.task_report import task_report_write
from src.project.task.task_role import (
    task_role_of_task,
    task_role_planners_only,
    task_role_shell_live_by_project,
)
from src.project.task.task_setting_parallel import (
    TASK_SETTING_PARALLEL_DEFAULT,
    task_setting_parallel_all)
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_ATTEMPT_MAX,
    task_setting_timeout_get)


async def _action_claim(worker: str) -> dict | None:
    """
    Захватить первое подошедшее действие. None — работы нет.

    Планирование отбирается только для живых карточек своего проекта: план пишет
    владелец вкладки (менеджер, разработчик или QA — см. `task_role`) той команды,
    которой задача принадлежит. Захватывать задачу для погасшей карточки нельзя —
    прогон сорвался бы на первом же шаге, а задача ушла бы в `failed`; захватывать
    её карточкой чужого проекта нельзя тем более — оболочка работает в чужом
    каталоге и о задаче ничего не знает.

    Так же отбирается и работа Developer: подзадачу берём только там, где жива
    карточка разработчика своего проекта — он работает в оболочке каталога этого
    проекта. Без живой карточки прогон сорвался бы и сжёг попытку из отведённых.

    Тем же порядком отбирается и круг QA — по живой карточке роли `qa` своего
    проекта. Роль здесь именно `qa`, а не `developer`: проверяющая оболочка обязана
    быть не той, что писала код.

    Разбор плана на подзадачи проектом не ограничен: там оболочки нет вовсе,
    подзадачи создаются прямо в воркере.

    Сверх живости карточек действует предел «Parallel LLM» проекта: проект,
    выбравший свой лимит прогонов, из отбора выпадает целиком — см.
    `_roles_by_project_free`.

    Порядок перебора и есть приоритет ролей: QA → Developer → Manager. Работа,
    начатая раньше, важнее начатой позже: проверить сделанное — значит закрыть
    подзадачу и освободить круг, а взять в планирование новую задачу — значит
    добавить работы к незакрытой. При QA впереди подзадачи идут парами
    dev(1) → qa(1) → dev(2) → qa(2), а не копятся непроверенными.

    Голодания это не создаёт: очередь QA конечна и берётся только из того, что уже
    сделал разработчик, — вычерпав её, тик доходит до разработки, а вычерпав и её,
    до менеджера.
    """
    roles_by_project = _roles_by_project_free(
        await task_role_shell_live_by_project(),
        await task_claim_inflight_by_project(),
        await task_setting_parallel_all())
    for claim in (
        _claim_qa,
        _claim_developer,
        # Починка бага — такая же работа роли, как разработка, поэтому идёт до
        # планирования: закрыть начатое важнее, чем добавить незакрытого. После
        # разработки, а не до неё: подзадача идущего плана ближе к финишу, чем баг,
        # которым ещё не занимались.
        _claim_bugfix,
        # Разбор плана на подзадачи — перед менеджерскими шагами, но после работы
        # ролей: оболочки и похода в LLM тут нет, зато он даёт разработчику работу.
        _claim_plan_split,
        # Пересмотр — первый из менеджерских: на другом конце этого шага человек,
        # который нажал «Обновить план» и ждёт результата.
        _claim_manager_review,
        _claim_manager_plan,
    ):
        action = await claim(worker, roles_by_project)
        if action:
            return action
    return None


def _roles_by_project_free(roles_by_project: dict, inflight: dict, limits: dict) -> dict:
    """
    Убрать из отбора проекты, выбравшие свой предел «Parallel LLM».

    Предел один на проект и считается прогонами агента, а не карточками: карточки
    одного проекта ходят в один аккаунт и один рабочий каталог, и второй прогон
    при пределе 1 перебивал бы первый — агент менеджера получал бы второй промпт
    посреди чужого хода. Пока лимит выбран, задачи проекта просто ждут своей
    очереди, а следующий тик подберёт их сразу, как только прогон завершится.

    Фильтруется именно `roles_by_project`, потому что из него строится условие
    отбора каждого шага — так один фильтр закрывает и планирование, и пересмотр,
    и Developer, и QA. Разбор плана (`_claim_plan_split`) этот словарь не смотрит и
    под предел не попадает: там нет ни оболочки, ни похода в LLM.

    Проекта нет в `limits` — действует `TASK_SETTING_PARALLEL_DEFAULT`.
    """
    free = {}
    for project_id, roles in (roles_by_project or {}).items():
        limit = int(limits.get(project_id, TASK_SETTING_PARALLEL_DEFAULT))
        if int(inflight.get(project_id, 0)) < limit:
            free[project_id] = roles

    return free


async def _claim_manager_review(worker: str, roles_by_project) -> dict | None:
    # Багфиксер плана не пишет: тип `bug` принадлежит ему, и без отсева менеджерский
    # шаг забрал бы баг себе (`task_role_planners_only`).
    task = await task_claim_task_review(worker, task_role_planners_only(roles_by_project))
    if not task:
        return None
    role = await task_role_of_task(task)
    await task_report_write(task['id'], f'План отправлен на пересмотр ({_role_title(role)})', ok=None)
    return {'kind': 'manager_review', 'task_id': task['id'], 'revise': True, 'role': role}


async def _claim_manager_plan(worker: str, roles_by_project) -> dict | None:
    task = await task_claim_task_unplanned(worker, task_role_planners_only(roles_by_project))
    if not task:
        return None
    # Если план уже есть (есть subtasks), но goals пуст — пересматриваем,
    # а не пишем заново: менеджер удалит subtasks при write-from-scratch.
    _, existing_subtasks = task_plan_parse(task.get('pipeline_plan') or '')
    role = await task_role_of_task(task)
    await task_report_write(task['id'], f'Задача взята в планирование ({_role_title(role)})', ok=None)
    return {'kind': 'manager_plan', 'task_id': task['id'],
            'revise': len(existing_subtasks) > 0, 'role': role}


async def _claim_plan_split(worker: str, roles_by_project) -> dict | None:
    task = await task_claim_task('approved', 'processing', worker)
    return {'kind': 'plan_split', 'task_id': task['id']} if task else None


async def _claim_developer(worker: str, roles_by_project) -> dict | None:
    max_attempts = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_ATTEMPT_MAX)
    subtask = await task_claim_subtask_developable(worker, roles_by_project, max_attempts)
    return {'kind': 'developer', 'subtask_id': subtask['id']} if subtask else None


async def _claim_qa(worker: str, roles_by_project) -> dict | None:
    subtask = await task_claim_subtask_testable(worker, roles_by_project)
    return {'kind': 'qa', 'subtask_id': subtask['id']} if subtask else None


async def _claim_bugfix(worker: str, roles_by_project) -> dict | None:
    task = await task_claim_task_bug(worker, roles_by_project)
    if not task:
        return None
    await task_report_write(task['id'], 'Баг взят в работу (Багфиксер)', ok=None)
    return {'kind': 'bugfix', 'task_id': task['id']}


# ── детали реализации ──────────────────────────────────────────────────────────

from src.project.task.task_role import TASK_ROLE_DEFAULT, TASK_ROLE_TITLE


def _role_title(role: str) -> str:
    """Подлежащее для строки отчёта: «Менеджер составил план», «QA составил план»."""
    return TASK_ROLE_TITLE.get(role, TASK_ROLE_TITLE[TASK_ROLE_DEFAULT])

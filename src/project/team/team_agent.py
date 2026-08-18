"""
Чем роль карточки `/admin/team` работает: агент движка и его workflow.

Карточка показывает живую оболочку claude-shell, но работу через неё гоняет
агент приложения — тот же, что виден на `/admin/agent`. Пока связь не написана
на карточке, «менеджер проекта → workflow #55» держится только в голове, и чтобы
посмотреть промпт планирования, приходится искать агента по имени руками.

Роль, чей агент не заведён в этой установке, отдаёт пустой слот, а не выдумывает
ссылку: строки на карточке тогда просто не рисуются.
"""
from src.mysql_.repository.agent_repository import AgentRepository
from src.mysql_.repository.agent_workflow_repository import AgentWorkflowRepository
from src.project.task.task_agent_bugfixer import TASK_BUGFIXER_AGENT_NAME
from src.project.task.task_agent_developer import TASK_DEVELOPER_AGENT_NAME
from src.project.task.task_agent_manager import TASK_MANAGER_AGENT_NAME
from src.project.task.task_agent_qa import TASK_QA_AGENT_NAME

# Роль карточки → имя агента, который делает её работу. Имя, а не id: id агента
# зависит от установки, имя — часть контракта (по нему агента ищет и сам конвейер).
TEAM_AGENT_BY_ROLE = {
    'manager':   TASK_MANAGER_AGENT_NAME,
    'developer': TASK_DEVELOPER_AGENT_NAME,
    'bugfixer':  TASK_BUGFIXER_AGENT_NAME,
    'qa':        TASK_QA_AGENT_NAME,
}


async def team_agent_by_role() -> dict[str, dict]:
    """
    Агент и workflow каждой роли: `{role: {'agent_id', 'agent_title', 'workflow_id',
    'workflow_title'}}`.

    Роли, у которых агента нет или он не заведён в этой установке, в словаре
    отсутствуют — карточке нечего показать. Нулевой `workflow_id` тоже возможен:
    агент без workflow движок не ломает, просто ссылки на workflow не будет.

    Запросов столько же, сколько ролей в карте, — их три, и словарь строится один
    раз на всю страницу, а не на карточку.
    """
    repo_agent = AgentRepository()
    repo_workflow = AgentWorkflowRepository()

    by_role: dict[str, dict] = {}
    for role, name in TEAM_AGENT_BY_ROLE.items():
        agent = await repo_agent.find_one_by({'name': name})
        if not agent:
            continue
        workflow_id = int(agent.get('workflow_id') or 0)
        workflow = await repo_workflow.find(workflow_id) if workflow_id else None
        by_role[role] = {
            'agent_id': int(agent.get('id') or 0),
            'agent_title': _title_of(agent),
            'workflow_id': int((workflow or {}).get('id') or 0),
            'workflow_title': _title_of(workflow),
        }

    return by_role


def _title_of(row) -> str:
    """Человеческое имя строки: `title`, а если он пуст — техническое `name`.

    `title` в обеих таблицах NOT NULL, но пустой строкой заполнен сплошь и рядом —
    без запасного `name` на карточке оказалась бы ссылка без подписи.
    """
    row = row or {}

    return str(row.get('title') or '').strip() or str(row.get('name') or '').strip()

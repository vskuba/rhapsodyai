from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.mysql_.repository.agent_repository import AgentRepository


async def agent_create_or_update(
        name: str,
        title: str,
        node_id: int | None = None,
        workflow_id: int | None = None,
        workflow_variable: str | None = None,
        prompt_system: str = '',
        description: str = '',
        greeting: str = '',
        user_id: int | None = None
) -> int:
    """
    Создает или обновляет агента по системному имени.
    user_id — активный пользователь (workflow-переменная user_id из сессии):
    агент получает те же роли, что и пользователь (agent_role).
    """
    repo = AgentRepository()
    entity_agent = await repo.find_one_by({"name": name})

    if entity_agent:
        # Сначала собираем полный список пришедших полей
        all_fields = {
            "title": title,
            "node_id": node_id,
            "workflow_id": workflow_id,
            "workflow_variable": workflow_variable,
            "prompt_system": prompt_system,
            "description": description,
            "greeting": greeting
        }

        # Отфильтровываем: убираем None и пустые строки ''
        update_data = {
            k: v for k, v in all_fields.items()
            if v is not None and v != ''
        }

        # Обновляем в БД только отфильтрованные поля
        if update_data:
            await repo.update(entity_agent.get("id"), update_data)

        agent_id = entity_agent.get("id")

    else:
        # При создании нового агента записываем все переданные поля как обычно
        agent_id = await repo.add({
            "name": name,
            "title": title,
            "node_id": node_id,
            "workflow_id": workflow_id,
            "workflow_variable": workflow_variable,
            "prompt_system": prompt_system,
            "description": description,
            "greeting": greeting
        })

    # Роли агента = роли активного пользователя
    if user_id:
        await _agent_roles_add_from_user(agent_id, int(user_id))

    return agent_id


async def _agent_roles_add_from_user(agent_id: int, user_id: int):
    """Добавляет агенту роль активного пользователя (agent_role).
    Существующие роли агента не трогаем: повторное сохранение другим
    пользователем не должно отбирать доступ у ролей, назначенных ранее."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT role_id FROM `user` WHERE id = %s", (user_id,))
        row = await db.fetchone()
        role_id = row.get('role_id') if row else None

        if not role_id:
            logger_info(f"⚠️ agent_create_or_update: у пользователя {user_id} нет роли — agent_role не обновлен")
            return

        await db.execute(
            "INSERT IGNORE INTO agent_role (agent_id, role_id) VALUES (%s, %s)",
            (agent_id, role_id)
        )


async def agent_exists(find_by: dict) -> bool:
    repo = AgentRepository()
    entity_agent = await repo.find_one_by(find_by)

    return bool(entity_agent)

from src.mysql_.repository.agent_repository import AgentRepository


async def agent_create_or_update(
        name: str,
        title: str,
        node_id: int | None = None,
        workflow_id: int | None = None,
        workflow_variable: str | None = None,
        prompt_system: str = '',
        description: str = '',
        greeting: str = ''
) -> int:
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

    else:
        # При создании нового агента записываем все переданные поля как обычно
        return await repo.add({
            "name": name,
            "title": title,
            "node_id": node_id,
            "workflow_id": workflow_id,
            "workflow_variable": workflow_variable,
            "prompt_system": prompt_system,
            "description": description,
            "greeting": greeting
        })

    return entity_agent.get("id")

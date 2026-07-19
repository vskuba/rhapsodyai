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
    Всегда проставляет agent.dynamic=1 - это единственная точка создания
    агентов в рантайме (девушки в dating, подозреваемые/сержант в detective
    и т.п.), в отличие от статичных ботов, которые заводятся только через
    INSERT в миграциях. Флаг нужен mysql_export_node_to_migration, чтобы не
    запекать реальные игровые данные в seed-экспорт подпроекта.
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
        update_data["dynamic"] = 1

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
            "dynamic": 1,
            "greeting": greeting
        })

    # Роли агента = роли активного пользователя
    if user_id:
        await _agent_roles_add_from_user(agent_id, int(user_id))

    return agent_id


async def agent_exists(find_by: dict) -> bool:
    repo = AgentRepository()
    entity_agent = await repo.find_one_by(find_by)

    return bool(entity_agent)


async def agent_list(user_id: int, workflow_name: str = '') -> dict:
    """
    Возвращает список агентов, доступных пользователю: агенты, роли которых
    пересекаются с ролью пользователя (agent_role), опционально отфильтрованные
    по workflow. Админ видит ВСЕ агенты независимо от роли создателя.
     - user_id: активный пользователь (workflow-переменная user_id)
     - workflow_name: системное имя workflow для фильтра; пустая строка - все агенты
    Returns:
        dict: Словарь со списком агентов, содержащий:
            chips (str): чипсы вида [[Название1]] [[Название2]] для выбора в чате.
            qty (int): количество найденных агентов.
    """
    workflow_name = str(workflow_name or '').strip()
    is_admin = await _user_is_admin(user_id)

    sql = "SELECT DISTINCT a.title FROM agent a"
    params: list = []
    if not is_admin:
        sql += " JOIN agent_role ar ON ar.agent_id = a.id JOIN `user` u ON u.role_id = ar.role_id AND u.id = %s"
        params.append(int(user_id))
    if workflow_name:
        sql += " JOIN agent_workflow w ON w.id = a.workflow_id AND w.name = %s"
        params.append(workflow_name)
    sql += " ORDER BY a.title ASC"

    async with mysql_get_db_async() as db:
        await db.execute(sql, params)
        rows = await db.fetchall()

    titles = [r['title'] for r in rows if r.get('title')]
    return {
        "chips": " ".join(f"[[{t}]]" for t in titles),
        "qty": len(titles)
    }


async def agent_remove(title: str, user_id: int, workflow_name: str = '') -> dict:
    """
    Удаляет агента по названию (title или name), если он доступен пользователю:
    роли агента пересекаются с ролью пользователя (agent_role), опциональный
    фильтр по workflow. Админ может удалить ЛЮБОЙ агент независимо от роли
    создателя. Связи agent_role удаляются каскадом, agent_session отвязывается
    (SET NULL) — история переписок сохраняется.
     - title: название агента из чипса (сравнивается с agent.title и agent.name)
     - user_id: активный пользователь (workflow-переменная user_id)
     - workflow_name: системное имя workflow для фильтра; пустая строка - без фильтра
    Returns:
        dict: Словарь с результатом удаления, содержащий:
            removed (int): 1 - агент удален, 0 - не найден среди доступных.
            title (str): название удаленного агента (пустая строка, если не найден).
    """
    title = str(title or '').strip()
    if not title:
        return {"removed": 0, "title": ""}

    workflow_name = str(workflow_name or '').strip()
    is_admin = await _user_is_admin(user_id)

    sql = "SELECT DISTINCT a.id, a.title FROM agent a"
    params: list = []
    if not is_admin:
        sql += " JOIN agent_role ar ON ar.agent_id = a.id JOIN `user` u ON u.role_id = ar.role_id AND u.id = %s"
        params.append(int(user_id))
    if workflow_name:
        sql += " JOIN agent_workflow w ON w.id = a.workflow_id AND w.name = %s"
        params.append(workflow_name)
    sql += " WHERE (a.title = %s OR a.name = %s) LIMIT 1"
    params += [title, title]

    async with mysql_get_db_async() as db:
        await db.execute(sql, params)
        entity_agent = await db.fetchone()

        if not entity_agent:
            return {"removed": 0, "title": ""}

        await db.execute("DELETE FROM agent WHERE id = %s", (entity_agent['id'],))
        await db.connection.commit()

    logger_info(f"🗑 Агент удален: id={entity_agent['id']}, title='{entity_agent['title']}' (user {user_id})")
    return {"removed": 1, "title": entity_agent['title']}


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


async def _user_is_admin(user_id: int) -> bool:
    """Проверяет, обладает ли пользователь ролью 'admin' (тогда фильтр по agent_role снимается)."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT r.name FROM `user` u JOIN `role` r ON r.id = u.role_id WHERE u.id = %s",
            (int(user_id),)
        )
        row = await db.fetchone()
        return bool(row) and row.get('name') == 'admin'

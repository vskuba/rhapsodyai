from config.config import config_get


async def env_is_prod() -> dict:
    """
    Проверяет, выполняется ли приложение на проде (APP_ENV содержит 'prod' -
    на проде выставлен в '_prod', см. docker-compose.yml). Используется для
    прод-заглушек в workflow (например workflow_shell_test - тестовые прогоны
    должны выполняться только локально).
    Returns:
        dict: Словарь с результатом, содержащий:
            is_prod (str): '1' - выполняется на проде, '0' - локально/иное окружение.
    """
    return {"is_prod": '1' if 'prod' in config_get('APP_ENV', '').lower() else '0'}

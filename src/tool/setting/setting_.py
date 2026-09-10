from setting_.setting_ import setting_get


async def setting_value_get(name: str, node_id: int = 0, default: str = '') -> dict:
    """
    Возвращает значение настройки по названию (ключу).
    Порядок поиска: сначала настройка конкретной ноды (если передан node_id),
    затем общая настройка (без ноды), затем default.
     - name: название (ключ) настройки, например 'timezone'
     - node_id: ID ноды; 0 или пусто — искать только общую настройку
     - default: значение, которое вернется, если настройка не найдена
    Returns:
        dict: Словарь со значением настройки, содержащий:
            value (str): значение настройки — нодовое, иначе общее, иначе default.
    """
    value = None

    node_id = int(node_id or 0)
    if node_id:
        value = await setting_get(name, None, node_id=node_id)

    if value is None:
        value = await setting_get(name, None)

    if value is None:
        value = default

    return {"value": str(value)}

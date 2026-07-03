from src.mysql_.repository.companion_repository import CompanionRepository


async def companion_create(name: str, title: str) -> str:
    repo = CompanionRepository()

    entity_companion = await repo.find_one_by({"name": name})
    if entity_companion:
        return f"Собеседник '{title}' уже есть в базе данных."

    await repo.add({"name": name, 'title': title})
    return f"Собеседник '{title}' добавлен в базу данных."


async def companion_id(name: str) -> int:
    repo = CompanionRepository()
    entity_companion = await repo.find_one_by({"name": name})

    if not entity_companion:
        return 0

    return entity_companion.get("id")


async def companion_title(name: str) -> str:
    repo = CompanionRepository()
    entity_companion = await repo.find_one_by({"name": name})

    if not entity_companion:
        return 'Unknown'

    return entity_companion.get("title")

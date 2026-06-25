from src.mysql_.repository.dating_girl_repository import DatingGirlRepository


async def dating_girl_create(name: str, title: str) -> str:
    repo = DatingGirlRepository()

    entity_girl = await repo.find_one_by({"name": name})
    if entity_girl:
        return f"Девушка '{title}' уже есть в базе данных."

    await repo.add({"name": name, 'title': title})
    return f"Девушка '{title}' добавлена в базу данных."


async def dating_girl_id(name: str) -> int:
    repo = DatingGirlRepository()
    entity_girl = await repo.find_one_by({"name": name})

    if not entity_girl:
        return 0

    return entity_girl.get("id")


async def dating_girl_title(name: str) -> str:
    repo = DatingGirlRepository()
    entity_girl = await repo.find_one_by({"name": name})

    if not entity_girl:
        return 'Unknown'

    return entity_girl.get("title")

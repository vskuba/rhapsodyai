from src.mysql_.repository.dating_girl_repository import DatingGirlRepository


async def dating_girl_create(name: str) -> str:
    repo = DatingGirlRepository()

    entity_girl = await repo.find_one_by({"name": name})
    if entity_girl:
        return f"Девушка '{name}' уже есть в базе данных."

    await repo.add({"name": name})
    return f"Девушка '{name}' добавлена в базу данных."
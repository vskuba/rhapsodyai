"""Запись собеседника у нас: завести, найти номер, спросить имя.

⚠⚠ Довод `name` во всех трёх — это **ключ** записи (`companion.unique_id`), а не
имя человека. Имя лежит в `title`. Столбец звался `name`, и путаница стоила
дорого: факты ключевались «именем», а в промпт вместо имени приезжало
`dating_343_128282`. Столбец переименован (`…_companion_unique_id`), довод
остался прежним — его имя часть договора с workflow.
"""
from src.mysql_.repository.companion_repository import CompanionRepository

# Ширина `companion.unique_id` и `companion.title` в базе
# (`…_companion_unique_id_wider`). ⚠ Обрезаем по ней же: длиннее не влезет, а
# молча укоротить значит завести запись, которую потом не найти по её ключу.
COMPANION_FIELD_MAX = 190


async def companion_create(unique_id: str, title: str = '') -> dict:
    """Завести запись собеседника, если её ещё нет. Вернуть её номер.

    Args:
        unique_id: ключ записи — собирает **шаг-конверсия** workflow, а не этот
            инструмент.
        title: имя, которым агент зовёт человека в тексте.

    Returns:
        dict: `id` — номер записи (новой или найденной), `unique_id` — её ключ,
        `created` — завели сейчас или она уже была.

    ## ⚠⚠ Ключ приходит готовым, и это решение

    Склеить его мог бы и сам инструмент, взяв части доводами. Но тогда правило
    «из чего состоит ключ» лежало бы в коде, а читают workflow — в редакторе. Шаг
    «Переменные» показывает `%companion_id%_%companion_name%` прямо в списке:
    видно, что в ключе, и правится там же, где промпты.

    ## ⚠ Зачем вообще запись на человека

    Факты в Qdrant ключуются номером записи. Пока собеседники ходят под одной
    общей (`dating_person`), факты обо всех мужчинах складываются в один
    документ — агент «помнит» про Gerard то, что рассказал Bartholomew.
    """
    key = str(unique_id or '').strip()

    if not key:
        # ⚠ Пустой ключ — не «заведи что-нибудь», а «части не доехали». Заведи мы
        # запись, она собрала бы факты всех, у кого метка не раскрылась.
        return {'id': 0, 'unique_id': '', 'created': 0}

    repo = CompanionRepository()
    entity_companion = await repo.find_one_by({'unique_id': key})

    if entity_companion:
        return {'id': entity_companion.get('id'), 'unique_id': key, 'created': 0}

    # ⚠ Имя обязательно: столбец `NOT NULL`, а пустое название в списке
    # собеседников не отличить от соседнего пустого.
    # ⚠ Обрезка по ширине столбца (`varchar(190)`), а не по круглому числу:
    # прежде она стояла на 25, и ключ длиннее молча терял хвост — поиск шёл по
    # полному, не находил и вставлял снова, упираясь в уникальный индекс.
    # Сообщение «Duplicate entry» при том, что записи нет, уводит искать гонку
    # вставок вместо ширины поля.
    made = await repo.add({'unique_id': key[:COMPANION_FIELD_MAX],
                           'title': str(title or key)[:COMPANION_FIELD_MAX]})

    return {'id': made, 'unique_id': key, 'created': 1}


async def companion_id(name: str) -> int:
    repo = CompanionRepository()
    entity_companion = await repo.find_one_by({"unique_id": name})

    if not entity_companion:
        return 0

    return entity_companion.get("id")


async def companion_title(name: str) -> str:
    repo = CompanionRepository()
    entity_companion = await repo.find_one_by({"unique_id": name})

    if not entity_companion:
        return 'Unknown'

    return entity_companion.get("title")

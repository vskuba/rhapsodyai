"""
Реестр веток и тем: чтение и выбор темы по меткам.

Ветка — род разговора со своим контрактом и необязательным subflow. Тема —
запись внутри ветки: метки и три текста (разрешено / желательно / запрещено).
Правила здесь, хранение — в `agent_workflow_branch` и `agent_workflow_branch_topic`,
исполнение — в шаге `branch` движка.

⚠⚠ Выбор идёт ПО ВСЕМУ реестру ноды, а не по темам одной ветки. Шагов `branch` в
потоке несколько, по одному на ветку, и считай каждый только своё — цепочка
брала бы первую прошедшую порог, а не лучшую. Промах случился бы ровно там, ради
чего заведены двухсловные метки: «почта как служба» со счётом 2 у ветки, стоящей
выше, увела бы поток мимо «обмена письмами» со счётом 4.

⚠ Отсюда же свойство, за которое это и сделано: арифметика у всех шагов
одинаковая, вход один, победитель один — и **порядок шагов веток в workflow не
значит ничего**. Грабля с позициями, на которую наступали при заведении ветки
про фото, здесь не действует.
"""

from mysql_.mysql_ import mysql_get_db_async


def ai_workflow_branch_tags_split(tags_raw: str) -> list[str]:
    """
    Метки строкой через запятую — в список приведённых меток без повторов.

    Приведение: нижний регистр и схлопывание пробелов. Больше ничего не нужно —
    словарь меток закрытый, и модель возвращает нашу же строку.

    Args:
        tags_raw: «Обмен  Письмами , пришли письмо».

    Returns:
        `['обмен письмами', 'пришли письмо']`; пусто на пустом входе.
    """
    if not tags_raw:
        return []

    tags = []
    for tag in str(tags_raw).split(','):
        tag = ' '.join(tag.split()).lower()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def ai_workflow_branch_pick(topics: list[dict], tags_raw: str) -> dict | None:
    """
    Выбрать тему: наибольший счёт совпавших меток, при равенстве — большая доля.

    Args:
        topics: записи тем с ключами `tags`, `branch_id`, `match_min`.
        tags_raw: метки, названные моделью, строкой через запятую.

    Returns:
        Запись победившей темы либо `None` — меток нет, никто не прошёл порог
        своей ветки, либо ничья по счёту и доле.
    """
    found = ai_workflow_branch_tags_split(tags_raw)
    if not found:
        return None

    best_mark = None
    best_topic = None
    best_tied = False

    for topic in topics:
        own = ai_workflow_branch_tags_split(topic.get('tags'))
        if not own:
            continue

        score = sum(1 for tag in own if tag in found)

        # ⚠ Порог берётся у ВЕТКИ темы, а не у шага: на шаге строгая ветка
        # глушила бы и чужую тему — победила её тема со счётом 2 при пороге 3,
        # и разговор остался бы без темы при годной тройке у соседней ветки.
        if score < int(topic.get('match_min') or 1):
            continue

        # ⚠ Доля — лекарство от перекоса: тема с двадцатью метками набирает
        # совпадений чаще темы с тремя просто потому, что меток больше.
        mark = (score, score / len(own))
        if best_mark is None or mark > best_mark:
            best_mark, best_topic, best_tied = mark, topic, False
        elif mark == best_mark:
            best_tied = True

    # ⚠ Ничья — это «темы нет». Неверная тема хуже отсутствия темы: она подставит
    # в промпт чужие инструкции, и отказ будет молчаливым — ответ придёт, просто
    # не тот.
    if best_topic is None or best_tied:
        return None
    return best_topic


async def ai_workflow_branch_topics(node_id: int) -> list[dict]:
    """
    Все включённые темы включённых веток ноды — материал для выбора.

    ⚠ `workflow_id` и `match_min` берутся у ВЕТКИ: у темы своих нет, и смотреть
    их надо там же, где они заданы.
    """
    sql = """
        SELECT t.`id`, t.`branch_id`, t.`name`, t.`title`, t.`tags`,
               t.`acceptance`, t.`direction`, t.`restriction`,
               b.`name` AS `branch_name`, b.`title` AS `branch_title`,
               b.`match_min`, b.`workflow_id`
          FROM `agent_workflow_branch_topic` t
          JOIN `agent_workflow_branch` b ON b.`id` = t.`branch_id`
         WHERE b.`node_id` = %s AND b.`is_enabled` = 1 AND t.`is_enabled` = 1
         ORDER BY b.`position` ASC, t.`position` ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        return list(await db.fetchall())


async def ai_workflow_branch_catalog(node_id: int) -> str:
    """
    Плоский список меток всех включённых тем ноды, без повторов, через запятую.

    Его видит шаг-развилка «Тема разговора»: словарь закрытый, и модель выбирает
    из него, своих меток не выдумывая.

    ⚠⚠ Плоский и БЕЗ группировки по темам намеренно. Увидев группировку, модель
    выберет тему сама, и выбор перестанет быть детерминированным. Модель
    размечает — выбирает арифметика.

    ⚠ Выдуманную метку отбрасывать не нужно: она ни с чем не совпадёт, и отказ
    выйдет мягким — тема не выбрана, разговор идёт обычным путём.
    """
    tags = []
    for topic in await ai_workflow_branch_topics(node_id):
        for tag in ai_workflow_branch_tags_split(topic.get('tags')):
            if tag not in tags:
                tags.append(tag)
    return ', '.join(tags)

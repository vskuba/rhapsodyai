"""
Отсев тем по вхождению меток в текст разговора — дешёвый заслон перед вопросами.

Шаг `topic_action` работает в два приёма: сперва код ищет метки темы **в тексте
истории**, и только выжившие темы идут в подпоток, где их проверяют вопросами.
Здесь первый приём: он не зовёт модель вовсе.

⚠⚠ Метка здесь — ИГЛА ДЛЯ ПОИСКА В ТЕКСТЕ, а не ярлык, который выбирает модель.
Прежняя развилка показывала модели словарь меток и просила выбрать подходящие;
метки под это и писались — `exchange of letters`, `why aren't you replying with
a letter`. На проде проверено: ни одна из пятнадцати таких меток не встречается
в тексте живой истории **ни разу на 255 прогонов** — люди пишут «send me a pic»,
а не «send a pic». Под этот модуль метки обязаны быть короткими и широкими
(`letter`, `photo`, `pic`, `send`), а точность даёт не метка, а вопрос в
подпотоке. Правило «метки из двух слов и больше» (`workflow_topic.md`)
относилось к прежнему приёму и здесь не действует — оно перевёрнуто.

⚠⚠ Совпадение — ТОЛЬКО СЛОВОМ ЦЕЛИКОМ. Подстрокой отсев врёт: на тех же 255
прогонах `pic` встретилась подстрокой 18 раз, а словом — 1 (остальное `picture`
и прочие хвосты). Словом целиком у этого есть и второе, менее очевидное
свойство: формы одного слова становятся непересекающимися. Подстрокой `photo` и
`photos` обе сработали бы на одном «photos» и бесплатно подняли счётчик
уникальных меток до двух — порог перестал бы означать то, что написано.

⚠ Цена того же решения: форму надо заводить меткой. `photo` не найдёт `photos`,
`секс` не найдёт `сексом`. Для английской ноды это десяток меток на тему, для
русской морфологии — больше; выбор сознательный, не недосмотр.
"""

import re

from mysql_.mysql_ import mysql_get_db_async


def ai_workflow_topic_action_tags_split(tags_raw: str) -> list[str]:
    """
    Метки строкой через запятую — в список приведённых меток без повторов.

    Приведение: нижний регистр и схлопывание пробелов внутри метки.

    Args:
        tags_raw: «Letter, send  a  pic , letter».

    Returns:
        `['letter', 'send a pic']`; пусто на пустом входе.
    """
    if not tags_raw:
        return []

    tags = []
    for tag in str(tags_raw).split(','):
        tag = ' '.join(tag.split()).lower()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def ai_workflow_topic_action_tags_found(text: str, tags_raw: str) -> list[str]:
    """
    Какие метки темы встретились в тексте — словом целиком, каждая не больше раза.

    Повтор одной метки в тексте счёта не прибавляет: порог темы измеряет, сколько
    РАЗНЫХ меток поднялось, а трижды сказанное «letter» — всё тот же один повод.

    Args:
        text: текст истории разговора (значение переменной, названной на шаге).
        tags_raw: метки темы строкой через запятую.

    Returns:
        Подсписок меток в порядке их объявления у темы; пусто — ни одной.
    """
    if not text:
        return []

    haystack = str(text)
    return [tag for tag in ai_workflow_topic_action_tags_split(tags_raw)
            if _tag_in_text(tag, haystack)]


def ai_workflow_topic_action_topics_raised(topics: list[dict], text: str) -> list[dict]:
    """
    Темы, у которых в тексте нашлось меток не меньше, чем требует их запись.

    ⚠⚠ Возвращается СПИСОК, а не победитель. Прежний приём выбирал одну тему
    арифметикой по счёту и доле; здесь отбор только отсеивает, а решают вопросы
    в подпотоке — и подняться может сразу несколько тем. Порядок списка = порядок
    `topics` на входе (то есть `position`), и он же становится порядком
    инструкций в накопителе: подпоток зовут темами по очереди.

    Args:
        topics: записи тем с ключами `tags` и `tags_qty_accept` (сколько разных
            меток обязано найтись; меньше единицы читается как единица).
        text: текст истории разговора.

    Returns:
        Записи прошедших тем, каждая с добавленными `tags_found` (какие именно
        метки подняли тему) и `tags_qty_found` (сколько их). ⚠ Эти два ключа —
        не украшение: без них в трассе видно «тема поднялась», но не видно
        почему, а разбор ложной сработки начинается именно с этого вопроса.
    """
    raised = []
    for topic in topics:
        found = ai_workflow_topic_action_tags_found(text, topic.get('tags'))
        # ⚠ Тема без меток не поднимается никогда: метки — единственный вход в
        # отсев, и «нет меток» значит «нет повода», а не «подходит всегда».
        if not found:
            continue
        if len(found) < max(1, int(topic.get('tags_qty_accept') or 1)):
            continue
        raised.append({**topic, 'tags_found': found, 'tags_qty_found': len(found)})
    return raised


async def ai_workflow_topic_action_topics(topic_group_id: int) -> list[dict]:
    """
    Включённые темы включённой группы — вместе со своими вопросами.

    ⚠⚠ Темы берутся у ГРУППЫ ШАГА, а не по всей ноде. У прежней развилки было
    наоборот, и не от прихоти: она выбирала ОДНОГО победителя, а считай каждый
    шаг только свои темы — цепочка брала бы первую прошедшую порог, а не лучшую.
    Здесь победитель не один: отбор только отсеивает, решают вопросы, и
    подняться может сразу несколько тем. Выбирать между группами стало нечего —
    каждый шаг честно ведёт свою.

    ⚠ Вопросы доезжают ОДНИМ запросом, а не по теме в цикле: тем в группе
    десятки, и поход в базу на каждую превратил бы дешёвый отсев в дорогой.

    Args:
        topic_group_id: группа тем, выбранная на шаге.

    Returns:
        Записи тем в порядке `position`, у каждой список `questions` (тексты
        включённых вопросов в своём `position`); пусто — группа выключена,
        пуста или не существует.
    """
    sql_topics = """
        SELECT t.`id`, t.`topic_group_id`, t.`name`, t.`title`, t.`tags`,
               t.`tags_qty_accept`, t.`questions_qty_yes_accept`,
               t.`instructions`,
               g.`name` AS `group_name`, g.`title` AS `group_title`
          FROM `agent_workflow_topic` t
          JOIN `agent_workflow_topic_group` g ON g.`id` = t.`topic_group_id`
         WHERE t.`topic_group_id` = %s AND g.`is_enabled` = 1 AND t.`is_enabled` = 1
         ORDER BY t.`position` ASC, t.`id` ASC
    """
    sql_questions = """
        SELECT `topic_id`, `question`
          FROM `agent_workflow_topic_question`
         WHERE `topic_id` IN ({holes}) AND `is_enabled` = 1
         ORDER BY `position` ASC, `id` ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql_topics, (int(topic_group_id),))
        topics = [dict(row) for row in await db.fetchall()]
        if not topics:
            return []

        ids = [topic['id'] for topic in topics]
        holes = ','.join(['%s'] * len(ids))
        await db.execute(sql_questions.format(holes=holes), tuple(ids))
        asked: dict[int, list[str]] = {}
        for row in await db.fetchall():
            asked.setdefault(row['topic_id'], []).append(row['question'])

    for topic in topics:
        topic['questions'] = asked.get(topic['id'], [])
    return topics


def _tag_in_text(tag: str, text: str) -> bool:
    """
    Стоит ли метка в тексте отдельным словом (или отдельной цепочкой слов).

    ⚠ Границы спрашиваются взглядом назад и вперёд (`(?<!\\w)` / `(?!\\w)`), а не
    `\\b`: метка, кончающаяся не буквой, границы слова после себя не имеет вовсе,
    и `\\b` не совпал бы с ней никогда. Вопрос здесь другой — «не часть ли это
    более длинного слова», и взгляд по сторонам задаёт именно его.

    ⚠ Пробелы внутри метки превращаются в `\\s+`: в истории реплики переносятся,
    и «send a pic» через перевод строки — то же самое вхождение.

    ⚠ Компиляция отдана кэшу `re` (по паре «шаблон + флаги», 512 записей): метки
    на прогоне повторяются от темы к теме, а своего кэша здесь хватило бы ровно
    на то, чтобы разойтись с ним в многопоточности.
    """
    body = r'\s+'.join(re.escape(part) for part in tag.split())
    return re.search(rf'(?<!\w){body}(?!\w)', text, re.IGNORECASE) is not None

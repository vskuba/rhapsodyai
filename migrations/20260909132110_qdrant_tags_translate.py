"""Перевод накопленных тегов фактов на английский и чистка словаря.

Промпты уже требуют английских тегов (миграция 20260909124754), но факты,
созданные до неё, остались с русскими и украинскими. Плюс сам английский
словарь оброс вариантами одного понятия.

Считалось на живых данных: 367 уникальных тегов сводятся к 224.
Классы дублей, которые это убирает:
  * язык        — «хобби»/hobbies, «работа»/work, «харків»/«харьков»/kharkiv;
  * число       — hobby/hobbies, cars/car, travels/travel;
  * опечатки    — serils→series, embanment→embankment, а также написания
                  с латиницей вперемешку: «cкорoсть», «gонокa», «сериaлы»;
  * разделитель — «big bang theory» против «meeting_proposal».

Миграция на Python, а не на SQL, намеренно: правка идёт по содержимому тегов,
а не по номерам строк. На каждой инсталляции свои факты со своими id, и
id-based UPDATE записал бы туда чужие значения.

Обратного шага нет: исходные написания после схлопывания не восстановимы.
"""
from yoyo import step

# Исходный тег (нижний регистр) -> английский. Русский и украинский.
MAP_LANG = {'cкорoсть': 'speed',
 'gонокa': 'racing',
 'oтказ oт встреч': 'meeting_refusal',
 'авто': 'car',
 'автомобили': 'car',
 'автомобиль': 'car',
 'автомобілі': 'car',
 'адреналин': 'adrenaline',
 'активный_отдых': 'outdoor_activities',
 'баланс': 'balance',
 'барсик': 'barsik',
 'бег': 'running',
 'бега': 'running',
 'биография': 'biography',
 'боевики': 'action_movies',
 'бот': 'bot',
 'біографія': 'biography',
 'вверх ногами': 'stranger_things',
 'велик': 'bicycle',
 'вело': 'bicycle',
 'велосипед': 'bicycle',
 'велосипеды': 'bicycle',
 'виртуальное общение': 'virtual talk',
 'водительство': 'driving',
 'вождение': 'driving',
 'возврат': 'refund',
 'вопрос': 'question',
 'воспоминания': 'memories',
 'впечатления': 'impressions',
 'встреча': 'meeting',
 'встречи': 'meeting',
 'выпечка': 'baking',
 'выходные': 'weekend',
 'гонки': 'racing',
 'город': 'city',
 'границы': 'boundaries',
 'деньги': 'money',
 'дистанции': 'distance',
 'дом': 'home',
 'друзі': 'friends',
 'еда': 'food',
 'жанры': 'genres',
 'жилье': 'housing',
 'заезд': 'racing',
 'знакомство': 'dating',
 'зустріч': 'meeting',
 'игры': 'games',
 'избегание': 'meeting_avoidance',
 'имя': 'name',
 'интересы': 'interests',
 'йога': 'yoga',
 'кайкинг': 'kayaking',
 'каякинг': 'kayaking',
 'киев': 'kyiv',
 'кино': 'movies',
 'классики': 'hopscotch',
 'клубы': 'club',
 'книга': 'books',
 'комeдии': 'comedies',
 'комедии': 'comedies',
 'кофе': 'coffee',
 'кулинария': 'cooking',
 'лижі': 'skiing',
 'локация': 'location',
 'лучшая подруга': 'best_friend',
 'марафон': 'marathon',
 'марафоны': 'marathon',
 'машина': 'car',
 'метро': 'metro',
 'мнения': 'opinions',
 'навчання': 'education',
 'название': 'name',
 'наука': 'science',
 'небот': 'bot',
 'невстреча': 'meeting_refusal',
 'недоверие': 'distrust',
 'обвинения': 'distrust',
 'образование': 'education',
 'обсуждение': 'discussion',
 'общение': 'chat',
 'ответы_девушки': 'girl_answers',
 'отдых': 'relaxation',
 'отказ': 'rejection',
 'отказ во встрече': 'meeting_refusal',
 'отказ от встреч': 'meeting_refusal',
 'отказ_от_встречи': 'meeting_refusal',
 'отчет': 'reports',
 'отчеты': 'reports',
 'парки': 'parks',
 'пенни': 'penny',
 'перелет': 'flight',
 'перемены': 'school_breaks',
 'переписка': 'messaging',
 'пироги': 'baking',
 'плавание': 'swimming',
 'подозрения': 'distrust',
 'подорожі': 'travel',
 'подписка': 'subscription',
 'подруга': 'friends',
 'покер': 'poker',
 'полумарафон': 'half_marathon',
 'предложение': 'meeting_proposal',
 'предложение_встречи': 'meeting_proposal',
 'предложения_встреч': 'meeting_proposal',
 'предпочтения': 'preferences',
 'прогулки': 'walks',
 'происхождение': 'origin',
 'пропозиція': 'meeting_proposal',
 'противоречие': 'contradiction',
 'профиль': 'profile',
 'путешествия': 'travel',
 'работа': 'work',
 'растяжка': 'stretching',
 'резиночка': 'chinese_jump_rope',
 'робот': 'bot',
 'русский': 'russian',
 'рядом': 'nearby',
 'сериaлы': 'series',
 'сериал': 'series',
 'сериалы': 'series',
 'скорость': 'speed',
 'скриншот': 'screenshots',
 'скриншоты': 'screenshots',
 'спектакли': 'theatre',
 'спор': 'discussion',
 'спорт': 'sport',
 'спортивный': 'sport',
 'сравнение': 'comparison',
 'сценки': 'theatre',
 'театр': 'theatre',
 'теория большого взрыва': 'big bang theory',
 'теория_большого_взрыва': 'big bang theory',
 'тест_драйв': 'test_drive',
 'торт': 'baking',
 'транспорт': 'transport',
 'уединение': 'solitude',
 'украина': 'ukraine',
 'украинский': 'ukrainian',
 'улица': 'street',
 'усталость': 'fatigue',
 'фильмы': 'movies',
 'финансы': 'money',
 'флирт': 'flirt',
 'фокус': 'focus',
 'фото': 'photos',
 'характер': 'character',
 'харків': 'kharkiv',
 'харьков': 'kharkiv',
 'хобби': 'hobbies',
 'хореограф': 'choreographer',
 'чай': 'tea',
 'черное зepкало': 'black mirror',
 'черное_зеркало': 'black mirror',
 'чтение': 'reading',
 'шейлах': 'sheilah',
 'шелдон': 'sheldon',
 'шеледон': 'sheldon',
 'школа': 'school',
 'школьные годы': 'school_years',
 'шутка': 'humor',
 'эмоции': 'emotions',
 'юмор': 'humor'}

# Английские варианты одного понятия -> каноническое написание.
MAP_EN = {'auto': 'car',
 'bicycles': 'bicycle',
 'birthplace': 'origin',
 'books': 'reading',
 'cars': 'car',
 'chat-only': 'chat',
 'comedy': 'comedies',
 'cycling': 'bicycle',
 'dancing': 'dance',
 'embanment': 'embankment',
 'emotion': 'emotions',
 'emotional': 'emotions',
 'friendship': 'friends',
 'hobby': 'hobbies',
 'job': 'career',
 'learning': 'education',
 'light_comedy': 'comedies',
 'meeting refusal': 'meeting_refusal',
 'no-meetings': 'meeting_refusal',
 'offline meeting refused': 'meeting_refusal',
 'offline meetings': 'meeting',
 'online chat': 'chat',
 'online chat preference': 'chat',
 'online_only': 'chat',
 'petersburg': 'saint_petersburg',
 'preference': 'preferences',
 'profession': 'career',
 'relationship': 'relationships',
 'relax': 'relaxation',
 'rides': 'ride',
 'roots': 'origin',
 'serils': 'series',
 'spb': 'saint_petersburg',
 'study': 'education',
 'teens': 'teenager',
 'travels': 'travel',
 'tv series': 'series',
 'tv show': 'series',
 'tv shows': 'series',
 'velo': 'bicycle',
 'virtual talk': 'chat'}


def _tag_canonical(tag):
    """Единый вид тега: перевод, канон английского, нижний регистр, подчёркивания."""
    t = str(tag).strip().lower()
    t = MAP_LANG.get(t, t)
    t = MAP_EN.get(t, t)
    t = t.replace(" ", "_").replace("-", "_")
    while "__" in t:
        t = t.replace("__", "_")
    return t.strip("_")


def _tags_rewrite(conn):
    """Переписывает `fact`.`tags` и сбрасывает `qdrant_synced` у изменённых строк."""
    cursor = conn.cursor()
    cursor.execute("SELECT `id`, `tags` FROM `fact` WHERE `tags` <> ''")
    rows = cursor.fetchall()

    changed = 0
    for fact_id, tags in rows:
        seen, out = set(), []
        for raw in str(tags).split(","):
            tag = _tag_canonical(raw)
            if tag and tag not in seen:
                seen.add(tag)
                out.append(tag)
        new_tags = ",".join(out)
        if new_tags != str(tags):
            # qdrant_synced = 0 — вектор пересоберёт крон синхронизации
            cursor.execute(
                "UPDATE `fact` SET `tags` = %s, `qdrant_synced` = 0 WHERE `id` = %s",
                (new_tags, fact_id))
            changed += 1

    print(f"[tags] переписано фактов: {changed} из {len(rows)}")


steps = [step(_tags_rewrite)]

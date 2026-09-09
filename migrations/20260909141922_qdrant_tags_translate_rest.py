"""Догоняющий перевод тегов: написания, которых не было в первой партии.

Первая миграция (20260909132110) собиралась по словарю с машины разработчика.
На других инсталляциях свои факты со своими тегами, и 43 русских написания
в него не попали — после прогона они остались как были. Здесь они добавлены.

Логика та же и идемпотентна: канонический тег отображается сам в себя,
поэтому повторный прогон по уже переведённым фактам ничего не меняет.

Обратного шага нет: «мама» и «папа» схлопнуты в parents, исходное различие
после этого не восстановимо.
"""
from yoyo import step

MAP_LANG = {
    # родня и близкие
    "семья": "family", "брат": "siblings", "родители": "parents",
    "мама": "parents", "папа": "parents", "связь_с_родителями": "parents",
    "дети": "children", "артем": "artem",
    # жильё и место
    "место_проживания": "residence", "продолжительность_проживания": "residence_duration",
    "жилищные_условия": "housing", "квартира": "housing",
    "местоположение_квартиры": "location", "местоположение": "location",
    "место_рождения": "origin", "страны": "country", "япония": "japan",
    "парк": "parks", "студия": "studio",
    # работа и учёба
    "место_работы": "workplace", "профессия": "career", "инженер": "engineer",
    "университет": "university", "студент": "student", "знания": "knowledge",
    # быт и досуг
    "питание": "food", "готовка": "cooking", "кофейни": "cafe",
    "танцы": "dance", "музыка": "music", "литература": "reading",
    "пробежки": "running", "возраст": "age", "планы": "plans",
    "домашний_питомец": "pets", "питомец": "pets",
    # отношения и состояния
    "отношения": "relationships", "любовные_отношения": "relationships",
    "личная_жизнь": "personal_life", "расставание": "breakup",
    "одиночество": "solitude", "спокойствие": "calm",
    "продолжительность": "duration",
}


def _tag_canonical(tag):
    """Тег к единому виду: перевод, нижний регистр, слова через подчёркивание."""
    t = str(tag).strip().lower()
    t = MAP_LANG.get(t, t)
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
            cursor.execute(
                "UPDATE `fact` SET `tags` = %s, `qdrant_synced` = 0 WHERE `id` = %s",
                (new_tags, fact_id))
            changed += 1

    print(f"[tags-rest] переписано фактов: {changed} из {len(rows)}")


steps = [step(_tags_rewrite)]

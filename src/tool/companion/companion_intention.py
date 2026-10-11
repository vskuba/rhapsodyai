"""Намерения разговора пары: что агент пометил словом и когда.

## ⚠⚠ Зачем хранить, если намерение и так уезжает в ответ

Намерение находится по тексту истории, а история накапливается: реплика «can you
send me your photos» остаётся в окне двадцати обменов, и тема поднимается на
каждом следующем ответе. Без памяти одно обещание уезжало бы вызывающему
двадцать раз подряд.

## ⚠⚠⚠ Но «было — больше не отдаём» НЕЛЬЗЯ

Обещание, повторённое через две реплики, — **новое** намерение, и его ждут:

    он:  can you send me your photos?
    она: sure, i'll send soon          ← намерение №1
    он:  can you send one more photo?
    она: yes, of course                ← намерение №2, и это не дубль

Строка при этом одна и та же: `instructions` темы — константа, и по самому
намерению первое от второго не отличить ничем.

Отличает их **время**. Намерение №2 родилось из реплик, пришедших позже
намерения №1 — значит хранить надо не «было/не было», а **отметку**. По ней
история режется надвое (`companion_session_history`, доводы `since`/`until`), и
модель ищет новое только в свежей половине, видя при этом разговор целиком.

⚠ Строка на каждое намерение, а не одна на пару: два обещания фото — две
записи. По ним же видно историю обещаний разговора.
"""
from mysql_.mysql_ import mysql_get_db_async
from src.tool.companion.companion import companion_create

# Вид отметки времени, которым её читает лента разговора (`since`/`until`).
#
# ⚠ Одной константой, а не литералом по месту: отдают отметку две функции, и
# разойдись их запись — половины разговора разъехались бы с границей, причём
# молча: строка-то в обеих осталась бы похожей.
COMPANION_INTENTION_AT_SHAPE = '%Y-%m-%d %H:%M:%S'


async def companion_intention_add(owner_unique_id: str, companion_unique_id: str,
                                  intention: str) -> dict:
    """Записать найденное намерение разговора — с отметкой времени.

    Args:
        owner_unique_id: ключ нашей стороны (`companion.unique_id`).
        companion_unique_id: ключ той стороны.
        intention: метка словом, вида `she_promised_send_photo`.

    Returns:
        dict: `id` — номер записи (0, если не записали), `saved` — записали ли,
        `at` — отметка времени записи, `why` — причина отказа словами.

    ⚠ Повтор той же метки — **не отказ**: второе обещание законно и пишется
    своей строкой. Отличать их будет время, а не текст.
    """
    owner_key = str(owner_unique_id or '').strip()
    companion_key = str(companion_unique_id or '').strip()
    said = str(intention or '').strip()

    if not owner_key or not companion_key:
        return {'id': 0, 'saved': 0, 'at': '', 'why': 'не названа пара разговора'}

    if not said:
        return {'id': 0, 'saved': 0, 'at': '', 'why': 'намерение пустое'}

    # ⚠ Запись стороны заводится, если её нет, — тем же инструментом, что у
    # ленты разговора (`companion_create` — get-or-create). Полагаться на
    # порядок шагов workflow значило бы терять намерение всякий раз, когда шаги
    # переставят.
    owner_id = int((await companion_create(owner_key)).get('id') or 0)
    companion_id = int((await companion_create(companion_key)).get('id') or 0)

    if not owner_id or not companion_id:
        return {'id': 0, 'saved': 0, 'at': '', 'why': 'стороны разговора не завелись'}

    async with mysql_get_db_async() as db:
        await db.execute(
            'INSERT INTO `companion_intention` '
            '(`owner_id`, `companion_id`, `intention`) VALUES (%s, %s, %s)',
            (owner_id, companion_id, said))
        made = db.lastrowid

        await db.execute(
            'SELECT `created_at` FROM `companion_intention` WHERE `id` = %s',
            (made,))
        row = await db.fetchone()

    at = row.get('created_at') if row else None

    return {'id': int(made or 0), 'saved': 1,
            'at': at.strftime(COMPANION_INTENTION_AT_SHAPE) if at else '', 'why': ''}


async def companion_intention_last_at(owner_unique_id: str,
                                      companion_unique_id: str) -> str:
    """Когда у этой пары последний раз находили намерение. Пусто — ни разу.

    Returns:
        str: `ГГГГ-ММ-ДД ЧЧ:ММ:СС` (UTC) или пустая строка.

    ## ⚠⚠ Это граница свежести, и пустота у неё законна

    Отметку подают доводом `since` ленте разговора: что позже — «свежее», в чём
    и ищут новое намерение. Ни одного намерения ещё не было — граница пуста, и
    свежим считается **весь** разговор. Так и надо: первое обещание надо найти,
    а резать нечего.

    ## ⚠⚠⚠ Граница НЕ РЕЖЕТ ОБМЕН ПОПОЛАМ, и это главное здесь

    Намерение находят **до** того, как прогон запишет свой ответ: шаг темы стоит
    раньше шага записи. Значит отметка ложится между его репликой и нашей — то
    есть внутрь одного обмена.

    Оставь мы её так — наш ответ выпал бы из половины «до намерений» (он позже
    отметки) и всплыл бы в «свежей». А в нём те же слова, что в обещании («sure,
    i will send you a photo»), и модель приняла бы **наше собственное обещание**
    за новое, выданное собеседником. Дубль на ровном месте.

    Поэтому отметка, попавшая внутрь обмена, сдвигается до его конца. Обмен —
    неделимая пара «он сказал / мы ответили», и граница проходит между обменами,
    а не сквозь них.

    ⚠ Так решается и порядок шагов: workflow волен ставить запись намерения
    и до, и после записи ответа — результат один. Полагаться на порядок значило
    бы, что перестановка шагов тихо ломает дедупликацию.

    ⚠ Отдаётся строкой, а не датой: значение едет в workflow-переменную, а
    оттуда — доводом инструмента, и оба пути строковые.
    """
    owner_key = str(owner_unique_id or '').strip()
    companion_key = str(companion_unique_id or '').strip()

    if not owner_key or not companion_key:
        return ''

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT i.`created_at`'
            '  FROM `companion_intention` i'
            '  JOIN `companion` o ON o.`id` = i.`owner_id`'
            '  JOIN `companion` c ON c.`id` = i.`companion_id`'
            ' WHERE o.`unique_id` = %s AND c.`unique_id` = %s'
            ' ORDER BY i.`created_at` DESC, i.`id` DESC LIMIT 1',
            (owner_key, companion_key))
        row = await db.fetchone()

        at = (row or {}).get('created_at')

        if not at:
            return ''

        # Обмен, внутрь которого попала отметка: он начался не позже её, а наш
        # ответ лёг позже. Такой обмен уже разобран — граница идёт за ним.
        await db.execute(
            'SELECT MAX(s.`answer_at`) AS `edge`'
            '  FROM `companion_session` s'
            '  JOIN `companion` o ON o.`id` = s.`owner_id`'
            '  JOIN `companion` c ON c.`id` = s.`companion_id`'
            ' WHERE o.`unique_id` = %s AND c.`unique_id` = %s'
            '   AND s.`question_at` <= %s AND s.`answer_at` > %s',
            (owner_key, companion_key, at, at))
        edge = (await db.fetchone() or {}).get('edge')

    return (edge or at).strftime(COMPANION_INTENTION_AT_SHAPE)

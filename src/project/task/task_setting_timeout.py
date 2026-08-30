"""
Таймауты конвейера: значения живут в таблице `setting`, а не в константах кода.

Каждое ожидание раньше было числом в своём модуле: сколько ждать ответа агента,
сколько — подтверждения оболочки, через сколько считать блокировку строки
протухшей. Подобрать их можно только на живых задачах, а правка константы значит
правку кода и перезапуск контейнеров. Поэтому все они собраны в один реестр и
читаются из настроек — карточки на `/admin/team` показывают текущие значения и
правят их на месте.

Настройка общая (`user_id`/`node_id` = NULL): одно значение на инсталляцию, роли
и проекты его не переопределяют. Ячейки в таблице может не быть вовсе — тогда
работает `default` из реестра, и до первой правки страница показывает ровно те
числа, что были константами.

Значения связаны лестницей: прогон агента < job воркера < блокировка строки.
Сорваться обязан прогон — иначе rq убьёт воркера посреди работы, а строку тем
временем заберёт соседний тик. `task_setting_timeout_ladder_problem()` проверяет это
и объясняет словами, что нарушено; запрещать правку нельзя — при подъёме всех
трёх значений промежуточное состояние законно.
"""
from mysql_.mysql_ import mysql_get_db_async

TASK_SETTING_TIMEOUT_MANAGER_RUN = 'timeout_manager_run'
TASK_SETTING_TIMEOUT_DEVELOPER_RUN = 'timeout_developer_run'
TASK_SETTING_TIMEOUT_QA_RUN = 'timeout_qa_run'
TASK_SETTING_TIMEOUT_BUGFIX_RUN = 'timeout_bugfix_run'
TASK_SETTING_TIMEOUT_SHELL_CALL = 'timeout_shell_call'
TASK_SETTING_TIMEOUT_SHELL_ACK = 'timeout_shell_ack'
TASK_SETTING_TIMEOUT_SHELL_BUSY = 'timeout_shell_busy'
TASK_SETTING_TIMEOUT_SHELL_STALE = 'timeout_shell_stale'
TASK_SETTING_TIMEOUT_RESTART_ACK = 'timeout_restart_ack'
TASK_SETTING_TIMEOUT_RESTART_SETTLE = 'timeout_restart_settle'
TASK_SETTING_TIMEOUT_RESTART_READY = 'timeout_restart_ready'
TASK_SETTING_TIMEOUT_WORKER_JOB = 'timeout_worker_job'
TASK_SETTING_TIMEOUT_TASK_LOCK = 'timeout_task_lock'
TASK_SETTING_TIMEOUT_PING_STALE = 'timeout_ping_stale'
TASK_SETTING_TIMEOUT_RETRY_MAX = 'timeout_retry_max'
TASK_SETTING_TIMEOUT_ATTEMPT_MAX = 'timeout_attempt_max'

# Группы для карточки: агентские ожидания зависят от роли, остальные общие.
TASK_SETTING_TIMEOUT_GROUP_AGENT = 'Агент'
TASK_SETTING_TIMEOUT_GROUP_SHELL = 'Оболочка'
TASK_SETTING_TIMEOUT_GROUP_RESTART = 'Перезапуск'
TASK_SETTING_TIMEOUT_GROUP_PIPELINE = 'Конвейер'
TASK_SETTING_TIMEOUT_GROUP_RETRY = 'Повторы'

# Реестр правимых значений. `role` непустая — строка показывается только на
# карточке этой роли: ждать ответа менеджера и ждать ответа QA — разные числа,
# и на чужой карточке такая строка сбивала бы с толку. `min`/`max` — грубые
# границы здравого смысла: ноль means «не ждать вовсе», а сутки в ожидании
# подтверждения доставки означают, что конвейер встал молча.
TASK_SETTING_TIMEOUT_ITEMS = (
    {'key': TASK_SETTING_TIMEOUT_MANAGER_RUN, 'default': 3600, 'min': 60, 'max': 86400,
     'group': TASK_SETTING_TIMEOUT_GROUP_AGENT, 'role': 'manager', 'unit': 'с',
     'title': 'Ответ менеджера',
     'hint': 'Сколько ждать разбиение задачи на подзадачи. Должно быть меньше job воркера.'},
    {'key': TASK_SETTING_TIMEOUT_DEVELOPER_RUN, 'default': 3600, 'min': 60, 'max': 86400,
     'group': TASK_SETTING_TIMEOUT_GROUP_AGENT, 'role': 'developer', 'unit': 'с',
     'title': 'Ответ разработчика',
     'hint': 'Сколько ждать выполнение подзадачи. Должно быть меньше job воркера.'},
    {'key': TASK_SETTING_TIMEOUT_QA_RUN, 'default': 3600, 'min': 60, 'max': 86400,
     'group': TASK_SETTING_TIMEOUT_GROUP_AGENT, 'role': 'qa', 'unit': 'с',
     'title': 'Ответ тестировщика',
     'hint': 'Сколько ждать проверку подзадачи. Должно быть меньше job воркера.'},
    {'key': TASK_SETTING_TIMEOUT_BUGFIX_RUN, 'default': 3600, 'min': 60, 'max': 86400,
     'group': TASK_SETTING_TIMEOUT_GROUP_AGENT, 'role': 'bugfixer', 'unit': 'с',
     'title': 'Ответ багфиксера',
     'hint': 'Сколько ждать починку бага. Должно быть меньше job воркера.'},

    {'key': TASK_SETTING_TIMEOUT_SHELL_CALL, 'default': 300, 'min': 30, 'max': 86400,
     'group': TASK_SETTING_TIMEOUT_GROUP_SHELL, 'role': '', 'unit': 'с',
     'title': 'Шаг workflow в оболочке',
     'hint': 'Ожидание ответа claude-shell на один шаг, когда workflow не задал своё значение.'},
    {'key': TASK_SETTING_TIMEOUT_SHELL_ACK, 'default': 120, 'min': 10, 'max': 3600,
     'group': TASK_SETTING_TIMEOUT_GROUP_SHELL, 'role': '', 'unit': 'с',
     'title': 'Подтверждение доставки',
     'hint': 'Оболочка вводит текст в Claude Code только на свободном терминале.'},
    {'key': TASK_SETTING_TIMEOUT_SHELL_BUSY, 'default': 300, 'min': 10, 'max': 3600,
     'group': TASK_SETTING_TIMEOUT_GROUP_SHELL, 'role': '', 'unit': 'с',
     'title': 'Ожидание занятого агента',
     'hint': 'Сколько ждать, пока агент дойдёт до конца предыдущего хода.'},
    {'key': TASK_SETTING_TIMEOUT_SHELL_STALE, 'default': 30, 'min': 5, 'max': 3600,
     'group': TASK_SETTING_TIMEOUT_GROUP_SHELL, 'role': '', 'unit': 'с',
     'title': 'Протухший пинг сессии',
     'hint': 'Пинг старше этого — оболочка считается закрытой, сообщение ей не уходит.'},

    {'key': TASK_SETTING_TIMEOUT_RESTART_ACK, 'default': 60, 'min': 5, 'max': 3600,
     'group': TASK_SETTING_TIMEOUT_GROUP_RESTART, 'role': '', 'unit': 'с',
     'title': 'Приём маркера перезапуска',
     'hint': 'Не подтвердила за это время — watch не читает очередь.'},
    {'key': TASK_SETTING_TIMEOUT_RESTART_SETTLE, 'default': 10, 'min': 1, 'max': 600,
     'group': TASK_SETTING_TIMEOUT_GROUP_RESTART, 'role': '', 'unit': 'с',
     'title': 'Пауза после перезапуска',
     'hint': 'Пока старый процесс не убит, heartbeat отдаёт ready — эту паузу мы его не слушаем.'},
    {'key': TASK_SETTING_TIMEOUT_RESTART_READY, 'default': 180, 'min': 10, 'max': 3600,
     'group': TASK_SETTING_TIMEOUT_GROUP_RESTART, 'role': '', 'unit': 'с',
     'title': 'Готовность после перезапуска',
     'hint': 'Холодный старт Claude Code с большим CLAUDE.md — десятки секунд.'},

    {'key': TASK_SETTING_TIMEOUT_WORKER_JOB, 'default': 3900, 'min': 60, 'max': 86400,
     'group': TASK_SETTING_TIMEOUT_GROUP_PIPELINE, 'role': '', 'unit': 'с',
     'title': 'Job воркера',
     'hint': 'Потолок одного тика конвейера. Между таймаутом агента и блокировкой строки.'},
    {'key': TASK_SETTING_TIMEOUT_TASK_LOCK, 'default': 4200, 'min': 60, 'max': 86400,
     'group': TASK_SETTING_TIMEOUT_GROUP_PIPELINE, 'role': '', 'unit': 'с',
     'title': 'Блокировка строки',
     'hint': 'Через это время задачу заберёт следующий тик, даже если воркер молчит.'},
    # 90 секунд — это 45 пропущенных пингов подряд (оболочка шлёт каждые две). Такой
    # запас нужен не оболочке, а сети: heartbeat идёт на публичный адрес установки, и
    # короткий провал канала гасил карточки пачкой, хотя все они прекрасно работали.
    # Прежние 30 секунд переживали 15 пингов и на такой провал не рассчитывали.
    {'key': TASK_SETTING_TIMEOUT_PING_STALE, 'default': 90, 'min': 5, 'max': 3600,
     'group': TASK_SETTING_TIMEOUT_GROUP_PIPELINE, 'role': '', 'unit': 'с',
     'title': 'Свежесть карточки',
     'hint': 'Пинг старше — карточка гаснет. Оболочка шлёт каждые 2с; меньше 30с карточки мигают на сетевой заминке.'},

    {'key': TASK_SETTING_TIMEOUT_RETRY_MAX, 'default': 3, 'min': 1, 'max': 10,
     'group': TASK_SETTING_TIMEOUT_GROUP_RETRY, 'role': '', 'unit': 'раз',
     'title': 'Технических повторов',
     'hint': 'Агент не ответил — перезапуск оболочки и тот же вход заново, не больше этого числа.'},
    {'key': TASK_SETTING_TIMEOUT_ATTEMPT_MAX, 'default': 3, 'min': 1, 'max': 10,
     'group': TASK_SETTING_TIMEOUT_GROUP_RETRY, 'role': '', 'unit': 'раз',
     'title': 'Кругов Developer → QA',
     'hint': 'Сколько раз QA возвращает подзадачу разработчику, прежде чем она станет blocked.'},
)

TASK_SETTING_TIMEOUT_BY_KEY = {item['key']: item for item in TASK_SETTING_TIMEOUT_ITEMS}


async def task_setting_timeout_get(key: str) -> int:
    """Значение таймаута из настроек, иначе значение по умолчанию из реестра.

    Читается в момент ожидания, а не при импорте: правка на `/admin/team` обязана
    работать без перезапуска контейнеров. Запрос дешёвый и делается раз на прогон,
    а не в цикле опроса — цикл получает уже вычисленный дедлайн.
    """
    item = TASK_SETTING_TIMEOUT_BY_KEY.get(str(key or ''))
    if not item:
        raise ValueError(f'Неизвестный таймаут: {key}')

    values = await _values_load([item['key']])

    return _value_normalize(values.get(item['key']), item)


async def task_setting_timeout_all() -> list[dict]:
    """Весь реестр с текущими значениями — для страницы команды.

    Одним запросом: строк полтора десятка, и пятнадцать отдельных `setting_get()`
    на каждую перерисовку карточек — это пятнадцать походов в базу раз в 15 секунд.
    """
    values = await _values_load([item['key'] for item in TASK_SETTING_TIMEOUT_ITEMS])

    return [_item_with_value(item, _value_normalize(values.get(item['key']), item))
            for item in TASK_SETTING_TIMEOUT_ITEMS]


async def task_setting_timeout_set(key: str, value) -> dict:
    """Записать значение таймаута. Возвращает элемент реестра с новым значением.

    Ключи чужие сюда не пролезают: правится только то, что перечислено в реестре,
    иначе страница команды стала бы редактором произвольных настроек.

    Raises:
        ValueError: неизвестный ключ или значение вне границ элемента.
    """
    item = TASK_SETTING_TIMEOUT_BY_KEY.get(str(key or ''))
    if not item:
        raise ValueError(f'Неизвестный таймаут: {key}')

    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f'{item["title"]}: нужно целое число')

    if not item['min'] <= number <= item['max']:
        raise ValueError(f'{item["title"]}: допустимо от {item["min"]} до {item["max"]}')

    await _value_save(item['key'], number)

    return _item_with_value(item, number)


def task_setting_timeout_ladder_problem(values: dict) -> str:
    """Нарушение лестницы «прогон агента < job воркера < блокировка строки».

    Args:
        values: {ключ: значение} — то, что отдаёт `task_setting_timeout_all()`.

    Returns: пустая строка, если порядок соблюдён, иначе объяснение для страницы.
    """
    job = int(values.get(TASK_SETTING_TIMEOUT_WORKER_JOB) or 0)
    lock = int(values.get(TASK_SETTING_TIMEOUT_TASK_LOCK) or 0)
    # Потолок берём максимальный из агентских: лестницу ломает самый долгий прогон,
    # а не «средний по ролям» — job воркера убьёт любого из них одинаково.
    agent = max(int(values.get(TASK_SETTING_TIMEOUT_MANAGER_RUN) or 0),
                int(values.get(TASK_SETTING_TIMEOUT_DEVELOPER_RUN) or 0),
                int(values.get(TASK_SETTING_TIMEOUT_QA_RUN) or 0),
                int(values.get(TASK_SETTING_TIMEOUT_BUGFIX_RUN) or 0))

    if agent >= job:
        return (f'Ожидание агента ({agent}с) не меньше job воркера ({job}с): '
                f'воркера убьют раньше, чем прогон успеет сорваться сам')
    if job >= lock:
        return (f'Job воркера ({job}с) не меньше блокировки строки ({lock}с): '
                f'задачу заберёт соседний тик, пока над ней ещё работают')

    return ''


def _item_with_value(item: dict, value: int) -> dict:
    """Элемент реестра с текущим значением — то, что уходит на страницу команды.

    `custom` — «отличается от заводского», а не «есть строка в таблице»: карточка
    подсвечивает им правленые руками значения, и вернув поле к умолчанию человек
    ждёт, что подсветка погаснет, хотя строка в `setting` остаётся.
    """
    return {**item, 'value': int(value), 'custom': int(value) != int(item['default'])}


async def _values_load(keys: list[str]) -> dict:
    """Значения общих настроек по списку ключей: {ключ: строка из таблицы}."""
    if not keys:
        return {}

    placeholders = ', '.join(['%s'] * len(keys))
    async with mysql_get_db_async() as db:
        await db.execute(
            f"SELECT `key`, value FROM setting "
            f" WHERE `key` IN ({placeholders}) AND user_id IS NULL AND node_id IS NULL",
            keys)
        rows = await db.fetchall()

    return {str(row['key']): row['value'] for row in rows or []}


async def _value_save(key: str, value: int) -> None:
    """Upsert общей настройки.

    Свой upsert, а не ON DUPLICATE KEY: уникальный индекс `setting` включает
    скоуп-колонки, а NULL в них дублей не ловит — так же делает `setting_set()`.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE setting SET value = %s, dynamic = 0 "
            " WHERE `key` = %s AND user_id IS NULL AND node_id IS NULL",
            (str(value), key))
        if not db.rowcount:
            await db.execute(
                "SELECT id FROM setting "
                " WHERE `key` = %s AND user_id IS NULL AND node_id IS NULL", (key,))
            if not await db.fetchone():
                await db.execute(
                    "INSERT INTO setting (`key`, value, user_id, node_id, dynamic) "
                    "VALUES (%s, %s, NULL, NULL, 0)", (key, str(value)))
        await db.connection.commit()


def _value_normalize(raw, item: dict) -> int:
    """Значение из таблицы в целое, с откатом к умолчанию.

    Ячейку правит человек, и опечатка в ней не должна ронять ожидание: пустая
    строка, буквы или число вне границ читаются как «значение по умолчанию».
    """
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return int(item['default'])

    if not item['min'] <= number <= item['max']:
        return int(item['default'])

    return number

"""
Сроки шагов агентских workflow — те, что обрывают прогон первыми.

Потолок роли (`timeout_manager_run` и соседи) лежит в таблице `setting`, а ждать
ответа оболочки workflow умеет своим сроком: у каждого шага `claude_shell_call`
он записан литералом `_const_600` в `inputs_map`. Настройка `timeout_shell_call`
такие шаги не трогает — инструмент подставляет её, только когда шаг передал ноль,
а таких шагов в WF55/56/57 нет ни одного. Поэтому карточка команды показывала
потолок в час, хотя планирование гибло на десятой минуте: срок, который сработает,
в реестре настроек не значился вовсе.

Отсюда этот модуль: срок шага правится там, где он лежит, — в определении
workflow, а карточка получает его такой же строкой, как настройку, и пишет тем же
запросом. Ключ строки — `step_timeout_<id шага>`: в реестре общих таймаутов такого
ключа нет и быть не может, и по нему `/api/team/timeout` отличает правку шага от
правки настройки.

Роли сопоставляется её workflow (`team_agent_by_role`), а не наоборот: у карточки
роли есть агент, у агента — workflow, и других шагов на карточке быть не должно.
"""
import json

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.project.team.team_agent import team_agent_by_role

# Ждать умеет только обращение к живому агенту: остальные типы шагов отрабатывают
# за миллисекунды, и срока у них нет.
TASK_SETTING_STEP_TOOL = 'claude_shell_call'

# Литерал в `inputs_map`: движок отрезает префикс и подставляет остаток значением
# аргумента (`ai_framework_manager`), поэтому число видно прямо в шаге.
TASK_SETTING_STEP_CONST_PREFIX = '_const_'

# Ключ строки на карточке. Отдельное пространство имён: реестр настроек правится
# по ключу настройки, шаг — по своему id, и перепутать их нельзя.
TASK_SETTING_STEP_KEY_PREFIX = 'step_timeout_'

# Заголовок группы строк на карточке — рядом с «Агент», «Оболочка», «Конвейер».
TASK_SETTING_STEP_GROUP = 'Шаги агента'

# Обычный шаг ждёт десять минут; длинные (реализация, прогон проверок) заданы
# больше и подсвечиваются на карточке как «правленое» — это и требуется увидеть.
TASK_SETTING_STEP_DEFAULT = 600

# Границы здравого смысла: полминуты мало даже на короткий ответ, сутки означают,
# что прогон встал молча. Совпадают с границами `timeout_shell_call`.
TASK_SETTING_STEP_MIN = 30
TASK_SETTING_STEP_MAX = 86400


def task_setting_step_timeout_of(metadata: dict, variables: dict = None) -> int | None:
    """Срок шага по его метаданным и переменным его потока.

    Args:
        metadata: метаданные шага.
        variables: переменные потока — `{имя: умолчание}`. Нужны, когда шаг
            ссылается на переменную; без них такая ссылка читается как «своего
            срока нет».

    Returns:
        None — шаг ничего не ждёт (не ходит в оболочку), срока у него нет вовсе;
        0 — шаг ждёт, но своего срока не задал: значение возьмётся из настройки
        `timeout_shell_call` (так же поступит и сам инструмент);
        иначе — секунды.

    ## ⚠⚠ Два вида записи, и второй вытесняет первый

    Исторически срок стоял литералом `_const_600` прямо в карте входов.
    Значение при этом лежало в метаданных шага: в списке переменных потока его
    нет, на странице оно видно только раскрыв шаг, и правится вслепую. Теперь
    шаг ссылается на **объявленную переменную** — у неё есть имя, подпись и
    одно место правки.

    ⚠ Литерал читается по-прежнему: он ещё стоит в чужих потоках
    (`planning_*`), и переезд идёт по одному потоку. Перестань мы его понимать
    раньше времени — карточка показала бы ноль там, где шаг ждёт два часа, и
    человек правил бы настройку, которая ничего не решает.

    ⚠ Функция остаётся **чистой**: переменные приходят доводом, а не читаются
    из базы. Иначе её нельзя было бы звать из `team_progress`, который считает
    прогресс в цикле и в базу за этим не ходит.
    """
    invoke = (metadata or {}).get('tool_invoke') or {}
    if invoke.get('tool_name') != TASK_SETTING_STEP_TOOL:
        return None

    raw = str((invoke.get('inputs_map') or {}).get('timeout') or '').strip()

    if raw.startswith(TASK_SETTING_STEP_CONST_PREFIX):
        raw = raw[len(TASK_SETTING_STEP_CONST_PREFIX):]
    elif raw:
        # ⚠ Имя переменной — не число: значение берём из умолчаний потока.
        # Нет такой переменной — отвечаем нулём, то есть «своего срока нет»:
        # это честнее выдуманного числа, и инструмент поступит так же.
        raw = str((variables or {}).get(raw) or '').strip()

    return int(raw) if raw.isdigit() else 0


def task_setting_step_key_is(key: str) -> bool:
    """Ключ строки — шаг workflow, а не настройка из реестра таймаутов."""
    return str(key or '').startswith(TASK_SETTING_STEP_KEY_PREFIX)


async def task_setting_step_all() -> list[dict]:
    """Строки сроков шагов для карточек команды — тем же видом, что и настройки.

    Порядок — по позиции шага в workflow: карточка читается сверху вниз как сам
    прогон. Роли без агента или без workflow строк не дают: показывать чужие шаги
    на карточке роли неоткуда и незачем.

    Шаги, задающие срок переменной, а не литералом, в список не попадают: править
    в них нечего, значение придёт из настройки `timeout_shell_call`.
    """
    by_role = await team_agent_by_role()
    workflow_role = {int(data.get('workflow_id') or 0): role
                     for role, data in by_role.items() if data.get('workflow_id')}
    if not workflow_role:
        return []

    # ⚠ Переменные читаем **одним запросом на все потоки**: шагов у карточки
    # четыре десятка, и поход за каждым означал бы сорок запросов на открытие.
    variables = await _variables_load(list(workflow_role))

    items = []
    for row in await _steps_load(list(workflow_role)):
        seconds = task_setting_step_timeout_of(
            json_from_string(row.get('metadata')),
            variables.get(int(row['workflow_id']), {}))
        if not seconds:
            continue
        items.append(_item_build(row, workflow_role[int(row['workflow_id'])], seconds))

    return items


async def task_setting_step_set(key: str, value) -> dict:
    """Записать срок шага в его же определение. Возвращает строку с новым значением.

    Правится ровно один литерал `inputs_map.timeout`, остальные метаданные шага
    переписываются как есть: в них лежат промпт и переходы, и терять их из-за
    правки числа нельзя.

    Raises:
        ValueError: ключ не про шаг, шага нет, шаг не ждёт оболочку либо значение
            вне границ.
    """
    step_id = str(key or '')[len(TASK_SETTING_STEP_KEY_PREFIX):]
    if not task_setting_step_key_is(key) or not step_id.isdigit():
        raise ValueError(f'Неизвестный таймаут шага: {key}')

    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError('Срок шага: нужно целое число')

    if not TASK_SETTING_STEP_MIN <= number <= TASK_SETTING_STEP_MAX:
        raise ValueError(f'Срок шага: допустимо от {TASK_SETTING_STEP_MIN} '
                         f'до {TASK_SETTING_STEP_MAX}')

    row = await _step_load(int(step_id))
    metadata = json_from_string((row or {}).get('metadata'))
    flow = int(row['workflow_id'])
    variables = (await _variables_load([flow])).get(flow, {})

    if task_setting_step_timeout_of(metadata, variables) is None:
        raise ValueError(f'Шаг {step_id} не ждёт ответа оболочки — срока у него нет')

    # ⚠⚠ Пишем **туда, откуда прочитали**. Шаг, ссылающийся на переменную,
    # правится в ней: перепиши мы его на литерал, значение вернулось бы в
    # метаданные — то есть правка карточки откатывала бы перевод, и делала бы
    # это молча, по одному шагу за нажатие.
    name = str((metadata['tool_invoke'].get('inputs_map') or {})
               .get('timeout') or '').strip()

    if name.startswith(TASK_SETTING_STEP_CONST_PREFIX) or not name:
        metadata['tool_invoke']['inputs_map']['timeout'] = (
            f'{TASK_SETTING_STEP_CONST_PREFIX}{number}')
        await _metadata_save(int(step_id), metadata)
    else:
        await _variable_save(flow, name, number)

    role = next((name for name, data in (await team_agent_by_role()).items()
                 if int(data.get('workflow_id') or 0) == int(row['workflow_id'])), '')

    return _item_build(row, role, number)


def _item_build(row: dict, role: str, seconds: int) -> dict:
    """Строка карточки: тот же набор полей, что у элемента реестра таймаутов.

    `custom` — «дольше или короче обычного шага»: заводского значения у шага нет,
    но десять минут стоят у большинства, и отличие от них стоит подсветить.
    """
    title = str(row.get('title') or '').strip() or f"Шаг #{row.get('id')}"

    return {
        'key': f"{TASK_SETTING_STEP_KEY_PREFIX}{int(row['id'])}",
        'title': title,
        'value': int(seconds),
        'default': TASK_SETTING_STEP_DEFAULT,
        'min': TASK_SETTING_STEP_MIN,
        'max': TASK_SETTING_STEP_MAX,
        'group': TASK_SETTING_STEP_GROUP,
        'role': role,
        'unit': 'с',
        'custom': int(seconds) != TASK_SETTING_STEP_DEFAULT,
        'hint': (f'Ожидание ответа оболочки на шаге «{title}». Задано в самом шаге '
                 f'workflow, а не в настройках: прогон обрывается по нему раньше, '
                 f'чем по потолку роли.'),
    }


async def _steps_load(workflow_ids: list[int]) -> list[dict]:
    """Шаги перечисленных workflow в порядке исполнения по умолчанию."""
    marks = ', '.join(['%s'] * len(workflow_ids))
    sql = (f"SELECT id, workflow_id, title, metadata FROM agent_workflow_step "
           f" WHERE workflow_id IN ({marks}) ORDER BY workflow_id, position, id")

    async with mysql_get_db_async() as db:
        await db.execute(sql, tuple(workflow_ids))
        rows = await db.fetchall()

    return [dict(row) for row in (rows or [])]


async def _step_load(step_id: int) -> dict:
    async with mysql_get_db_async() as db:
        await db.execute("SELECT id, workflow_id, title, metadata FROM agent_workflow_step "
                         " WHERE id = %s", (step_id,))
        row = await db.fetchone()

    if not row:
        raise ValueError(f'Шаг {step_id} не найден')

    return dict(row)


async def _variables_load(workflow_ids: list[int]) -> dict:
    """Умолчания переменных перечисленных потоков: `{поток: {имя: значение}}`.

    ⚠ Одним запросом на все потоки: шагов у карточки четыре десятка, и поход
    за каждым означал бы сорок запросов на одно её открытие.
    """
    if not workflow_ids:
        return {}

    marks = ', '.join(['%s'] * len(workflow_ids))
    sql = ('SELECT workflow_id, name, `default` FROM agent_workflow_variable'
           f' WHERE workflow_id IN ({marks})')

    async with mysql_get_db_async() as db:
        await db.execute(sql, tuple(workflow_ids))
        rows = await db.fetchall()

    got: dict[int, dict] = {}
    for row in (rows or []):
        got.setdefault(int(row['workflow_id']), {})[
            str(row['name'] or '').strip()] = row['default']

    return got


async def _variable_save(workflow_id: int, name: str, value: int) -> None:
    """Записать срок в умолчание переменной потока.

    ⚠ Переменной может не оказаться — например, её удалили со страницы, а шаг
    на неё ссылается. Тогда заводим: отказ оставил бы карточку без способа
    поправить срок, который шаг всё равно спросит.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id FROM agent_workflow_variable'
            ' WHERE workflow_id = %s AND name = %s', (workflow_id, name))

        if await db.fetchone():
            await db.execute(
                'UPDATE agent_workflow_variable SET `default` = %s'
                ' WHERE workflow_id = %s AND name = %s',
                (str(value), workflow_id, name))
        else:
            await db.execute(
                'INSERT INTO agent_workflow_variable'
                "  (workflow_id, name, type, `default`, description)"
                " VALUES (%s, %s, 'workflow', %s, %s)",
                (workflow_id, name, str(value),
                 'Срок ожидания оболочки на этом шаге, секунды'))

        await db.connection.commit()


async def _metadata_save(step_id: int, metadata: dict) -> None:
    async with mysql_get_db_async() as db:
        await db.execute("UPDATE agent_workflow_step SET metadata = %s WHERE id = %s",
                         (json.dumps(metadata, ensure_ascii=False), step_id))
        await db.connection.commit()

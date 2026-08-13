"""
«Parallel LLM» — сколько карточек проекта работают одновременно.

Карточки команды одного проекта ходят в свои живые оболочки Claude Code, а те
делят один и тот же аккаунт и один и тот же каталог: менеджер, разработчик и QA,
запущенные разом, жгут квоту втроём и правят одно рабочее дерево. Поэтому у
проекта есть предел параллельной работы — по умолчанию единица: пока одна
карточка занята, остальные ждут своей очереди, и в конвейере проекта живёт ровно
один прогон агента.

Предел — свойство проекта, а не установки: у одного проекта работа идёт в три
руки, у соседнего очередь строго по одной. Отдельной колонки под него нет,
значение лежит в общей таблице `setting` ключом `parallel_llm_<project_id>`
(`parallel_llm_0` — блок «Без проекта»). Схему это не трогает, а проектов на
установке десятки, и колонка ради одного числа их таблице ни к чему.

Правится на `/admin/team` селектом в шапке блока проекта, читается при отборе
работы (`task_pipeline._action_claim`) — перезапуск не нужен, значение берётся
на каждом тике. Соседний реестр настроек — `task_setting_timeout` (таймауты,
общие на всю установку).
"""
from mysql_.mysql_ import mysql_get_db_async

# Ключ настройки собирается из префикса и id проекта: 0 — блок «Без проекта»
# (задачи и оболочки вне проектов, тот же ключ, что `TASK_ROLE_PROJECT_NONE`).
TASK_SETTING_PARALLEL_KEY_PREFIX = 'parallel_llm_'

# Значения селекта. Больше трёх карточек у проекта и нет — менеджер, разработчик
# и QA, так что верхняя граница это «все роли разом».
TASK_SETTING_PARALLEL_OPTIONS = (1, 2, 3)
TASK_SETTING_PARALLEL_DEFAULT = 1
TASK_SETTING_PARALLEL_MIN = TASK_SETTING_PARALLEL_OPTIONS[0]
TASK_SETTING_PARALLEL_MAX = TASK_SETTING_PARALLEL_OPTIONS[-1]

# Проект «никакой»: оболочка из каталога, не принадлежащего ни одному проекту.
TASK_SETTING_PARALLEL_PROJECT_NONE = 0


async def task_setting_parallel_all() -> dict[int, int]:
    """Пределы всех проектов разом: `{project_id: предел}`.

    Проектов без своей строки в словаре нет вовсе — читающий берёт для них
    `TASK_SETTING_PARALLEL_DEFAULT`. Одним запросом, потому что и страница
    команды, и отбор работы в тике смотрят сразу на все проекты, а запрос на
    каждый был бы запросом на пустом месте: читателей поштучного значения нет.

    Настройка пустая или испорчена — берётся умолчание: селект в шапке блока
    правит человек, и опечатка в таблице не должна останавливать конвейер.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT `key`, value FROM setting "
            " WHERE `key` LIKE %s AND user_id IS NULL AND node_id IS NULL",
            (TASK_SETTING_PARALLEL_KEY_PREFIX + '%',))
        rows = await db.fetchall()

    limits = {}
    for row in rows or []:
        project_id = _project_id_of_key(str(row.get('key') or ''))
        if project_id is None:
            continue
        limits[project_id] = _value_normalize(row.get('value'))

    return limits


async def task_setting_parallel_set(project_id, value) -> int:
    """Записать предел проекта. Возвращает записанное значение.

    Raises:
        ValueError: значение не число или вне границ селекта.
    """
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError('Parallel LLM: нужно целое число')

    if number not in TASK_SETTING_PARALLEL_OPTIONS:
        raise ValueError(
            f'Parallel LLM: допустимо от {TASK_SETTING_PARALLEL_MIN} '
            f'до {TASK_SETTING_PARALLEL_MAX}')

    await _value_save(task_setting_parallel_key(project_id), number)

    return number


def task_setting_parallel_key(project_id) -> str:
    """Ключ настройки проекта в таблице `setting`."""
    return f'{TASK_SETTING_PARALLEL_KEY_PREFIX}{int(project_id or TASK_SETTING_PARALLEL_PROJECT_NONE)}'


def _project_id_of_key(key: str):
    """Обратное преобразование ключа в id проекта; None — ключ не наш.

    Выборка идёт по `LIKE`, и под шаблон может попасть чужой ключ, начинающийся
    так же, — такой пропускаем, а не роняем разбор.
    """
    tail = key[len(TASK_SETTING_PARALLEL_KEY_PREFIX):]
    if not tail.isdigit():
        return None

    return int(tail)


async def _value_save(key: str, value: int) -> None:
    """Upsert настройки без скоупа.

    Свой upsert, а не ON DUPLICATE KEY: уникальный индекс `setting` включает
    скоуп-колонки, а NULL в них дублей не ловит — так же делает `setting_set()`
    и `task_setting_timeout`.
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


def _value_normalize(raw) -> int:
    """Значение из таблицы в целое, с откатом к умолчанию."""
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return TASK_SETTING_PARALLEL_DEFAULT

    if number not in TASK_SETTING_PARALLEL_OPTIONS:
        return TASK_SETTING_PARALLEL_DEFAULT

    return number

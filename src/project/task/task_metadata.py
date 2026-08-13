"""
Произвольные данные задачи — колонка `project_task.metadata`.

Мешок «ключ -> значение» для того, под что заводить колонку рано: пометки агентов,
ссылки на внешние сущности, счётчики попыток чего-нибудь частного. Схема о составе
ничего не знает, контракт держит код, который пишет конкретный ключ, — поэтому
читатель всегда готов к тому, что ключа нет.

Не путать с `trace_meta`: тот — след интеграции, привязка задачи к источнику ошибки,
по нему идёт дедуп баг-задач (`task_bug_dedup`). Сюда его данные не переезжают.

Пустое значение — всегда `{}`, а не None: колонка допускает NULL (у задач, заведённых
до появления поля, там NULL), и разбирать эти два случая по коду смысла нет.

Правки идут через `task_metadata_update` — MySQL сливает патч в существующий JSON
одним UPDATE. Читать-править-писать на стороне Python нельзя: над одной задачей
одновременно работают оркестратор, воркеры и страница задач, и второй писатель
затёр бы ключ первого.
"""
import json

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async

# Пометка «в разработку»: человек ставит её флажком на вкладке «Планирование» ещё до
# того, как план написан, — этим он говорит, что решение «делаем» уже принято и второй
# раз утверждать готовый план не потребуется. Ставит страница `/admin/task`, снимает
# `task_state_plan_to_development`, когда пометка сработала.
#
# Ключа нет — пометки нет: отдельного `false` не пишем, чтобы в мешке не копился след
# от каждой задачи, которую когда-то отметили и передумали.
TASK_METADATA_KEY_DEV = 'to_development'

# Пометка «в тестирование»: флажок на вкладке «Разработка». Хранится наизнанку по
# сравнению с `to_development` — умолчание здесь «включено», потому что сделанная
# работа обязана попадать на проверку сама, а решением человека является как раз
# отказ от неё. Поэтому ключа нет = пометка стоит, а снятый флажок пишется явным
# `false`; читатель обязан отличать «нет ключа» от `false` (`<> FALSE`, а не `= TRUE`).
#
# Пометка не одноразовая, в отличие от `to_development`: она не «согласие на один
# переход», а постоянное свойство задачи — так и остаётся в мешке после срабатывания.
# Читает `task_state_dev_to_testing`.
TASK_METADATA_KEY_TEST = 'to_testing'

# Ветка и merge request подзадачи — то, что разработчик отдаёт вместе с отчётом. Живут
# в мешке, а не в колонках: пишет их один шаг конвейера, читает одна ячейка страницы
# задач, и половина установок вообще работает без внешнего хостинга репозитория.
#
# Ключи только у подзадач: ветку заводят под конкретную работу, а родитель — это план,
# у него своего кода нет.
TASK_METADATA_KEY_BRANCH = 'branch'
TASK_METADATA_KEY_MR = 'mr_url'

# Счётчик сорвавшихся прогонов строки: `{'count', 'total', 'role', 'error', 'at'}`.
# Пишет и читает `task_retry.py` — там же описано, чем этот счётчик отличается от
# `pipeline_attempt_count` и почему живёт в мешке, а не в колонке.
TASK_METADATA_KEY_RETRY = 'retry'


def task_metadata_parse(value) -> dict:
    """
    Разобрать значение колонки в dict.

    Для строк задачи, которые уже прочитаны (`SELECT * FROM project_task`), — незачем
    ходить в БД второй раз. NULL, пустая строка и не-объект дают `{}`.
    """
    return json_from_string(value) if value else {}


def task_metadata_row_apply(row) -> dict:
    """
    Строка задачи -> dict для ответа API с разобранным `metadata`.

    Из MySQL JSON-колонка приходит строкой, а внутрь API приходит объектом. Без
    разбора контракт эндпоинта разъезжается: клиент отправил `{...}`, а в ответе
    получил строку с экранированным юникодом. Применяется на границе API — всюду,
    где строка `project_task` уходит наружу.
    """
    task = dict(row)
    if 'metadata' in task:
        task['metadata'] = task_metadata_parse(task['metadata'])
    return task


async def task_metadata_get(task_id: int) -> dict:
    """Прочитать metadata задачи. Нет задачи или нет данных — `{}`."""
    if not task_id:
        return {}

    async with mysql_get_db_async() as db:
        await db.execute("SELECT metadata FROM project_task WHERE id = %s", (task_id,))
        row = await db.fetchone()

    return task_metadata_parse(row['metadata']) if row else {}


async def task_metadata_set(task_id: int, data: dict | None) -> None:
    """
    Записать metadata целиком, затерев прежнее содержимое.

    Для точечной правки одного ключа есть `task_metadata_update` — он не сносит
    чужие ключи. `None` или `{}` очищают поле в NULL.
    """
    if not task_id:
        return

    dumped = _task_metadata_dump(data)
    async with mysql_get_db_async() as db:
        await db.execute("UPDATE project_task SET metadata = %s WHERE id = %s", (dumped, task_id))
        await db.connection.commit()


async def task_metadata_update(task_id: int, patch: dict | None) -> None:
    """
    Слить патч в metadata задачи: свои ключи перезаписать, чужие оставить.

    Значение `None` в патче удаляет ключ — так работает JSON_MERGE_PATCH, и отдельная
    функция «удалить ключ» поэтому не нужна. Слияние поверхностное только на верхнем
    уровне вложенных объектов: словарь-значение сливается рекурсивно, список
    заменяется целиком.
    """
    if not task_id or not patch:
        return

    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task "
            "   SET metadata = JSON_MERGE_PATCH(COALESCE(metadata, '{}'), CAST(%s AS JSON)) "
            " WHERE id = %s",
            (json.dumps(patch, ensure_ascii=False), task_id),
        )
        await db.connection.commit()


def _task_metadata_dump(data: dict | None) -> str | None:
    """dict -> строка для колонки. Пустое и не-словарь дают NULL."""
    if not data or not isinstance(data, dict):
        return None
    return json.dumps(data, ensure_ascii=False)

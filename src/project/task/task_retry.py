"""
Технические повторы шага конвейера: прогон не состоялся — повторить, а не хоронить.

Сорвавшийся прогон и несошедшаяся работа — разные вещи. QA вернул список замечаний,
менеджер написал план, который человек отверг, — работа состоялась, просто не сошлась:
круг закрыт, попытка сожжена, следующий круг идёт с этим замечанием на входе. Агент не
ответил вовсе (таймаут, зависшая оболочка, упавший движок) — работы не было: жечь за
это круг не за что, повторять нужно тот же самый вход.

Отсюда два независимых счётчика. `pipeline_attempt_count` (`task_state_subtask_fail`,
потолок `timeout_attempt_max`) считает круги работы. Этот модуль считает сорвавшиеся
прогоны (`metadata.retry`, потолок `timeout_retry_max`). Подзадача может трижды сорваться по
таймауту и всё ещё иметь впереди все свои круги QA.

Внутри счётчика тоже двое. `count` — серия подряд, обнуляется первым же состоявшимся
прогоном: по ней решается, повторять ли ещё. `total` — за всё время строки, не
обнуляется никогда: это и есть статистика повторов, по ней видно, каким задачам агенты
даются тяжело. Обе цифры уходят на страницу задач вместе с `metadata`.

Хранение — `project_task.metadata`, своей колонки нет: счётчик частный, а ради него
трогать `migrations/0001.sql` (единственный DDL проекта) незачем. Инкремент считает
MySQL внутри одного UPDATE, без чтения в Python: над строкой одновременно работают тик,
воркер и страница задач, и read-modify-write затёр бы чужую правку.

Повтор всегда идёт вместе с перезапуском оболочки — за него отвечает вызывающий
(`task_pipeline`): агент, не ответивший в срок, почти всегда завис, и второй прогон в
том же живом Claude Code сорвётся ровно так же.
"""
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_metadata import TASK_METADATA_KEY_RETRY
from src.project.task.task_setting_timeout import (
    TASK_SETTING_TIMEOUT_RETRY_MAX,
    task_setting_timeout_get)

# Сколько раз повторяем сорвавшийся прогон, прежде чем признать шаг проваленным —
# настройка `timeout_retry_max` с `/admin/team` (см. `task_setting_timeout`). Повтор
# недёшев: у каждого свой таймаут агента (по часу) плюс перезапуск оболочки, так что
# бесконечно долбиться в мёртвого агента смысла нет — задача уходит человеку.

# Причину срыва режем: в мешок пишется текст ошибки агента, а он бывает с целым
# трейсбеком внутри. Для страницы задач хватает первой строки смысла.
TASK_RETRY_ERROR_MAX = 500


async def task_retry_take(task_id: int, role: str, error: str) -> dict:
    """
    Засчитать сорвавшийся прогон строки и сказать, повторять ли.

    Args:
        task_id: строка `project_task` — задача или подзадача, всё равно.
        role: чей прогон сорвался (`manager` | `developer` | `qa`).
        error: причина срыва как есть, для страницы задач.

    Returns:
        `{'allowed': bool, 'count': int, 'total': int, 'max': int}` — `allowed` значит,
        что повтор в пределах лимита и строку можно возвращать в работу; `count` — какой
        это повтор подряд (1 — первый); `total` — сколько прогонов сорвалось за всё время;
        `max` — действующий потолок, его же вызывающий показывает человеку в отчёте.
    """
    retry_max = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_RETRY_MAX)
    if not task_id:
        return {'allowed': False, 'count': 0, 'total': 0, 'max': retry_max}

    # CAST в UNSIGNED обязателен: арифметика над JSON даёт DOUBLE, и в мешок легло бы
    # `"count": 4.0` — ровно в таком виде цифра и уехала бы на страницу задач.
    path = f'$.{TASK_METADATA_KEY_RETRY}'
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task "
            f"  SET metadata = JSON_SET(COALESCE(metadata, '{{}}'), '{path}', JSON_OBJECT("
            f"          'count', CAST(COALESCE(JSON_EXTRACT(metadata, '{path}.count'), 0) + 1 AS UNSIGNED), "
            f"          'total', CAST(COALESCE(JSON_EXTRACT(metadata, '{path}.total'), 0) + 1 AS UNSIGNED), "
            "           'role',  %s, "
            "           'error', LEFT(%s, %s), "
            "           'at',    DATE_FORMAT(NOW(), '%%Y-%%m-%%d %%H:%%i:%%s'))) "
            " WHERE id = %s",
            (str(role or ''), str(error or ''), TASK_RETRY_ERROR_MAX, task_id),
        )
        await db.connection.commit()
        await db.execute(
            f"SELECT CAST(COALESCE(JSON_EXTRACT(metadata, '{path}.count'), 0) AS UNSIGNED) AS cnt, "
            f"       CAST(COALESCE(JSON_EXTRACT(metadata, '{path}.total'), 0) AS UNSIGNED) AS total "
            "  FROM project_task WHERE id = %s",
            (task_id,),
        )
        row = await db.fetchone()

    count = int(row['cnt'] or 0) if row else 0
    total = int(row['total'] or 0) if row else 0
    allowed = 0 < count <= retry_max
    logger_info(f'task_retry: task#{task_id} {role} срыв #{count}/{retry_max} '
                f'(всего {total}), повтор={"да" if allowed else "нет"}: {error}')
    return {'allowed': allowed, 'count': count, 'total': total, 'max': retry_max}


async def task_retry_clear(task_id: int) -> None:
    """
    Обнулить серию повторов: прогон состоялся, чем бы он ни кончился.

    Именно серию, а не `total`: строке, у которой агент однажды завис, а потом ожил,
    полагаются все три повтора и в следующий раз. Сколько раз она срывалась за свою
    жизнь, остаётся в `total`.

    Строки без повторов не трогаем — JSON_SET по несуществующему пути всё равно
    ничего не сделает, а лишний UPDATE по каждой успешной подзадаче ни к чему.
    """
    if not task_id:
        return

    path = f'$.{TASK_METADATA_KEY_RETRY}.count'
    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task SET metadata = JSON_SET(metadata, %s, 0) "
            " WHERE id = %s AND JSON_EXTRACT(metadata, %s) > 0",
            (path, task_id, path),
        )
        await db.connection.commit()

"""
Вернуть вставшую подзадачу менеджеру: пусть разложит её на более мелкие.

Зачем. У подзадачи с одной целью нет развилки по охвату: раздробить единственную
цель нечем, а убрать её — значит отменить работу. Между тем именно такие строки
встают чаще всего, и причина у них общая: охват задали неподъёмный. Ошиблось не
исполнение, а планирование.

Поймано живьём на подзадаче #1628 («порядок функций», 2668 строк контекста): круг
прошёл целиком, сорок минут, отчёт есть — а кода не появилось ни строки, агент
только разобрался и остановился. Отвечать там человеку нечего: цель одна, дробить
нечего, повтор с тем же охватом кончится тем же.

Как устроено. Строка уходит в состояние `new`, и этого достаточно: планирование
забирает строки, у которых нет своих подзадач и состояние `new`
(`task_claim_task_unplanned`), а менеджер раскладывает их обычным заходом. Той же
дорогой уже идёт дробление в глубину по объёму (`task_state._subtask_state`), так
что третий уровень вложенности механике не в новинку.

Что подчищаем и почему. Счётчик кругов обнуляется: они потрачены на охват,
которого больше не будет, и переносить их на новые строки нечестно. Цели
остаются — менеджер разложит их по детям сам, а стереть их значило бы отдать ему
строку без описания приёмки. Замечание QA (`pipeline_error`) сохраняем: оно
пойдёт менеджеру подсказкой, обо что споткнулись.

Одноразово. Повторно на планирование сама строка не уйдёт: пометка
`metadata.replanned` остаётся навсегда, и второй такой же тупик уже показывается
человеку вопросом. Иначе связка «планирование → тупик → планирование» крутилась бы
сама по себе и плодила уровни вложенности без конца.
"""
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_metadata import (TASK_METADATA_KEY_REPLANNED,
                                            task_metadata_parse, task_metadata_update)

# Состояние, из которого работу забирает планирование. То же, что у подзадачи,
# помеченной менеджером «дробить дальше», — отдельной ветки для возврата не нужно.
TASK_GOAL_REPLAN_STATE = 'new'


async def task_goal_replan_send(subtask: dict) -> dict:
    """
    Отправить подзадачу менеджеру на разбиение.

    Args:
        subtask: строка подзадачи целиком — нужны номер, родитель и мешок.

    Returns:
        `{'ok': True, 'subtask_id': int}` — отправлена. `{'ok': False, 'error': ...}`
        — отправлять нельзя: это не подзадача или её уже возвращали однажды.
    """
    subtask_id = int((subtask or {}).get('id') or 0)
    if not subtask_id or not (subtask or {}).get('parent_id'):
        return {'ok': False, 'error': 'На планирование возвращается подзадача, а не задача целиком'}

    if task_metadata_parse(subtask.get('metadata')).get(TASK_METADATA_KEY_REPLANNED):
        return {'ok': False,
                'error': 'Эту строку уже возвращали на планирование — второй раз нужен человек'}

    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task "
            "   SET pipeline_state = %s, pipeline_attempt_count = 0, "
            "       pipeline_locked_at = NULL, pipeline_locked_by = '' "
            " WHERE id = %s AND parent_id IS NOT NULL",
            (TASK_GOAL_REPLAN_STATE, subtask_id))
        sent = db.rowcount > 0
        await db.connection.commit()

    if not sent:
        return {'ok': False, 'error': 'Строка не найдена'}

    await task_metadata_update(subtask_id, {TASK_METADATA_KEY_REPLANNED: True})
    logger_info(f'[task] subtask#{subtask_id}: возвращена на планирование — охват неподъёмный')

    return {'ok': True, 'subtask_id': subtask_id}


def task_goal_replan_needed(subtask: dict, goals: list, lines_changed: int) -> bool:
    """
    Случай, когда решать нечего и возврат очевиден.

    Три условия разом: строка встала, цель ровно одна и круг не оставил кода.
    Каждое по отдельности ничего не значит — вместе они означают, что охват
    неподъёмный, а не что исполнитель ошибся.

    Почему именно «не оставил кода», а не «не сошёлся по вердикту QA». Круг,
    который что-то написал, но не убедил QA, — это спор о качестве, и там человеку
    есть что сказать. Круг, не написавший ничего, — это упёршийся охват, и мнение
    человека ничего не добавит: он видит ровно то же, что и мы.

    Уже возвращали — не наш случай: второй тупик подряд показываем человеку.
    """
    if str((subtask or {}).get('pipeline_state') or '') not in ('failed_qa', 'blocked'):
        return False
    if task_metadata_parse((subtask or {}).get('metadata')).get(TASK_METADATA_KEY_REPLANNED):
        return False

    open_goals = [g for g in (goals or []) if not g.get('done')]

    return len(open_goals) == 1 and int(lines_changed or 0) == 0

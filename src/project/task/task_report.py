"""
Отчёт по задаче: чем занимался оркестратор и почему задача там, где она есть.

`pipeline_state` отвечает на вопрос «где задача сейчас», `report` — «почему».
Поле читает человек: на странице задач оно висит подсказкой на статусных чипсах,
поэтому пишем живым языком, а не кодами состояний. Правило простое — каждый
переход конвейера оставляет здесь строку, и у задачи, которой оркестратор
касался, отчёт пустым не бывает.

Отчёт — журнал: новая запись встаёт первой строкой, прежние сдвигаются вниз.
Первая строка потому всегда объясняет текущий статус, а история остаётся под
ней и обрезается по REPORT_LINES_MAX.

Пишется одним UPDATE с `NOW()` на стороне MySQL: время отчёта тогда идёт по тем
же часам, что `created_at`/`updated_at` соседних колонок, и не разъезжается с
ними, если у воркера своя таймзона.
"""
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

REPORT_LINES_MAX  = 20    # сколько записей журнала храним
REPORT_LENGTH_MAX = 4000  # страховка от длинных трейсбеков в тексте ошибки

# Маркер исхода в начале строки: по нему видно результат, не читая саму строку.
_REPORT_MARKS = {True: '✓', False: '✗', None: '·'}


async def task_report_write(task_id: int, text: str, ok: bool | None = None) -> None:
    """
    Дописать строку в отчёт задачи.

    ok: True — шаг удался, False — сорвался, None — промежуточное событие
    («взята в планирование»), у которого исхода ещё нет.
    """
    if not task_id:
        return

    line = f'{_REPORT_MARKS[ok]} {" ".join(str(text or "").split())}'.strip()
    if not line:
        return

    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_task SET report = LEFT(SUBSTRING_INDEX(CONCAT("
            "    DATE_FORMAT(NOW(), '[%%d.%%m.%%Y %%H:%%i]'), ' ', %s,"
            "    IF(report = '', '', CONCAT('\n', report))"
            "), '\n', %s), %s) WHERE id = %s",
            (line, REPORT_LINES_MAX, REPORT_LENGTH_MAX, task_id),
        )
        await db.connection.commit()
    logger_info(f'[task] отчёт task#{task_id}: {line}')


async def task_report_subtasks_summary(task_id: int) -> str:
    """
    Сводка по подзадачам одной строкой: «готово 2 из 5, в разработке 1».

    Нужна отчётам шагов Developer/QA: сама по себе строка «подзадача #17 ушла на
    проверку» не говорит человеку, далеко ли задача от финиша.

    Подзадачи — дети задачи в том же `project_task`; берём только разложенные из плана
    (`pipeline_from_plan`), — подзадачи, заведённые человеком руками, в сводке шага
    Developer/QA считать нечего.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT pipeline_state AS state, COUNT(*) AS cnt FROM project_task "
            " WHERE parent_id = %s AND pipeline_from_plan = 1 GROUP BY pipeline_state",
            (task_id,),
        )
        rows = await db.fetchall()

    counts = {str(r['state']): int(r['cnt']) for r in rows}
    total  = sum(counts.values())
    if not total:
        return ''

    parts = [f'готово {counts.get("done", 0)} из {total}']
    parts += [f'{label} {counts[state]}' for state, label in _REPORT_STATE_LABELS.items()
              if counts.get(state)]
    return ', '.join(parts)


# Состояния подзадач для сводки. `done` считается отдельно (он в знаменателе),
# `planned` не показываем — это «ещё не начинали», остаток и так виден из «готово X из Y».
_REPORT_STATE_LABELS = {
    'developing': 'в разработке',
    'qa_pending': 'на проверке',
    'failed_qa':  'вернулось от QA',
    'blocked':    'заблокировано',
}

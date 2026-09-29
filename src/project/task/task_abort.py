"""
Обрыв идущего прогона: задачи больше нет, а круг по ней ещё идёт.

Удаление строки задачи снимает захваты модели и оболочки и уносит рабочий каталог, но
про сам прогон не знает: тот живёт в воркере, сидит в ожидании ответа агента и о том,
что работает впустую, узнать ниоткуда не может. Ждёт он до своего таймаута — у
багфиксера это сорок минут, у разработчика вчетверо больше.

Стоит это дорого, и не только временем. Пока прогон-сирота ждёт, роль занята: оболочка
у роли одна, и следующая задача уедет в неё же. А выдача новой задачи начинается с
`__SWITCH_LLM__` и перезапуска агента — тот обрывает незаконченный ход соседа, и сирота
не получает ответа уже никогда. Живьём: баг #34226 удалили в 06:44, его прогон досидел
до 06:56, а пришедший в 06:51 баг #34543 перезапуском оболочки оборвал его ход.

**Обрываем через очередь, а не перезапуском оболочки.** Прогон ждёт строку
`ai_claude_session` в фазе `answered` или `failed` (`claude_shell._row_wait`), опрашивая
её раз в пару секунд. Поэтому достаточно перевести незакрытое задание в `failed` — и
ожидание кончится само, штатным путём, тем же, каким кончается сбой доставки. Оболочку
при этом не трогаем: перезапуск гасит агента целиком, а на ней может идти круг соседней
задачи — ровно та беда, от которой мы здесь и уходим.

Ответ агента, если он всё-таки придёт после пометки, ничего не сломает: строку задачи
он уже не найдёт, а `task_state_kanban_sql` не даёт прогону перебить чужое состояние.
"""
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Фазы задания, которые ещё ждут ответа. `queued` — оболочка не забрала, `delivered` —
# забрала и передала агенту; обе означают, что прогон сидит в ожидании.
TASK_ABORT_PENDING_STATES = ('queued', 'delivered')

# Что окажется в ответе оборванного задания. Текст уходит в `error` прогона и оттуда в
# отчёт, поэтому говорит причину, а не «ошибку»: круг не сорвался, его отменили.
TASK_ABORT_REASON = 'Задача удалена — круг оборван, ответ агента больше некому принять'


async def task_abort_runs(task_ids) -> int:
    """
    Оборвать круги удалённых задач. Returns: сколько заданий сняли с ожидания.

    Args:
        task_ids: номера удаляемых строк — задача и всё, что ушло с ней каскадом.

    Ищем по трассе, а не по захвату оболочки: захват к середине круга уже снят
    (`team_shell_pool_release` отдаёт оболочку, оставляя привязку), а живая трасса
    держится до конца прогона и знает обе нужные вещи — чья она и в какой сессии
    работает. Номер задачи лежит в `subtask_id` у кругов плана и в `task_id` у багов,
    поэтому смотрим оба.

    Пустой список — ноль без запроса: `IN ()` неверен синтаксически, а «оборвать
    ничего» не должно означать «оборвать всё».
    """
    ids = [int(i) for i in (task_ids or []) if int(i or 0)]
    if not ids:
        return 0

    runs = await _runs_live(ids)
    if not runs:
        return 0

    aborted = 0
    for run in runs:
        session_uuid = str(run.get('session_uuid') or '').strip()
        if not session_uuid:
            # Прогон без сессии до оболочки не дошёл — обрывать нечего, он кончится
            # сам на ближайшем шаге.
            continue

        aborted += await _inbox_fail(session_uuid, run.get('started_at'), run.get('id'))

    if aborted:
        logger_info(f'[task] удаление задач {ids}: оборвано заданий оболочки — {aborted}')

    return aborted


async def _runs_live(ids: list) -> list[dict]:
    """
    Живые прогоны этих задач: `[{'id', 'started_at', 'session_uuid'}]`.

    Сравниваем числом, а не строкой: движок кладёт переменные как есть, и номер
    задачи попадает в трассу то числом, то строкой — по строковому сравнению
    `'34226'` и `34226` разошлись бы молча.

    ⚠ Приведение к числу делает теперь не запрос, а сама колонка: `subtask_id` и
    `task_id` считаются из `variables_start` при вставке (миграция
    `20260929123812`) и уже `INT`. Прежние `JSON_EXTRACT` в условии заставляли
    базу прочитать LONGTEXT у каждой строки таблицы — `type: ALL`, 174 МБ.

    ⚠ `task_shell_session` остаётся разбором JSON: своей колонки у него нет, но и
    отбора по нему здесь нет — он только читается у уже найденных строк.
    """
    placeholders = ', '.join(['%s'] * len(ids))
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, started_at, "
            "       JSON_UNQUOTE(JSON_EXTRACT(variables_start, '$.task_shell_session')) "
            "           AS session_uuid "
            "  FROM agent_workflow_trace "
            " WHERE status = 'running' "
            f"   AND COALESCE(subtask_id, task_id, 0) IN ({placeholders})",
            tuple(ids))

        return [dict(row) for row in (await db.fetchall() or [])]


async def _inbox_fail(session_uuid: str, started_at, run_id) -> int:
    """
    Снять с ожидания незакрытые задания этого прогона. Returns: сколько сняли.

    Окно обязательно, и обе его границы по делу. Снизу — старт прогона: в сессии
    остаются задания прошлых кругов, и переписывать их итог нельзя. Сверху — старт
    следующего прогона в той же оболочке: он уже прислал своё задание, и снять его
    значило бы оборвать живой круг чужой задачи вместо своего.

    Верхней границы нет — берём всё до конца: следующего круга в этой оболочке не
    начиналось, и любое незакрытое задание после нашего старта принадлежит нам.
    """
    if not started_at:
        return 0

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT MIN(started_at) AS next_at FROM agent_workflow_trace "
            " WHERE id <> %s AND started_at > %s "
            "   AND JSON_UNQUOTE(JSON_EXTRACT(variables_start, '$.task_shell_session')) = %s",
            (run_id, started_at, session_uuid))
        next_at = (await db.fetchone() or {}).get('next_at')

        where = ["session_uuid = %s", "created_at >= %s",
                 f"status IN ({', '.join(['%s'] * len(TASK_ABORT_PENDING_STATES))})"]
        params = [session_uuid, started_at, *TASK_ABORT_PENDING_STATES]
        if next_at:
            where.append("created_at < %s")
            params.append(next_at)

        await db.execute(
            "UPDATE ai_claude_session "
            "   SET status = 'failed', handled = 1, response = %s, responded_at = NOW() "
            f" WHERE {' AND '.join(where)}",
            (TASK_ABORT_REASON, *params))
        count = db.rowcount
        await db.connection.commit()

    return int(count or 0)

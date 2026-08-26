"""
Замеры работы ролей: объём контекста против времени и токенов.

Зачем. Порог разбиения по объёму (`context_lines`, 2500 строк) и таймауты ролей
(`timeout_developer_run` и соседние) сейчас — числа, взятые из головы. Проверить
их можно только одним способом: копить факты и смотреть, что получается. Отсюда
три величины на каждый шаг — сколько строк агенту дали прочесть, сколько он
работал и сколько токенов при этом сгенерировала модель.

Что из этого выйдет. Средние по роли и шагу дают три ответа сразу: каким ставить
таймаут (не «с потолка», а по разбросу настоящих кругов), какой объём считать
крупным (тот, после которого время растёт быстрее объёма) и сколько займёт план
целиком (сумма прогнозов по подзадачам).

Откуда берутся числа. Строки — оценка менеджера при разбиении (`metadata`),
время и токены — из трассы прогона: их туда кладёт `claude_shell_call`, который
единственный знает обе границы хода агента. Здесь только перекладываем.

Замер не влияет на работу. Сбой записи, недоступные счётчики модели, отсутствие
трассы — всё это молча даёт меньше данных, но не роняет круг: цена ошибки в
статистике несопоставима с ценой сорванного прогона.
"""
import ast
import json

from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Ниже этого порога шаг не замеряем. Сборка промпта и счётчики идут за
# миллисекунды и к объёму отношения не имеют — в средних они только сдвигали бы
# картину вниз.
TASK_METRIC_STEP_MIN_MS = 20000

# Сколько замеров показывать в списке. Сводки считает MySQL, а сырые строки нужны
# человеку только последние: по ним видно, что замер вообще идёт.
TASK_METRIC_LIST_MAX = 200


async def task_metric_collect(task_id: int, parent_id, role: str, attempt_no: int,
                              session_uuid: str, context_lines: int,
                              task_title: str = '', lines_changed: int = 0) -> int:
    """
    Переложить замеры прогона из трассы в таблицу. Returns: сколько строк записали.

    Зовётся по концу круга, оттуда же, откуда пишется журнал (`task_log`): к этому
    моменту трасса полна, а строка ещё не ушла следующему исполнителю.

    Берём только шаги, ходившие к агенту: у них есть и длительность, и токены.
    Остальные (сборка промпта, счётчики, снимки ветки) — служебные.

    `task_title` пишем копией: задачу удалят вместе с планом, а замер останется, и
    по одному номеру строку в отчёте уже не прочесть.

    `lines_changed` — правка круга целиком, и она ставится **на одну строку**, на
    последний шаг. Повтори мы её на каждом шаге, сумма по задаче считала бы одну и
    ту же работу столько раз, сколько в круге было шагов.

    Ошибку глотаем: круг состоялся, и незаписанная статистика его не отменяет.
    """
    if not task_id:
        return 0

    try:
        # Сорвавшийся прогон номера сессии не отдаёт: агентная функция уходит
        # исключением, и результата с ним не возвращает вовсе. А это ровно те
        # круги, ради которых замер и заводили: «шёл пятьдесят минут и всё равно
        # не дошёл» говорит о потолке больше, чем десяток удачных. Берём последнюю
        # трассу строки — её шаги дошли до обрыва и лежат нетронутыми.
        steps = await _steps_measured(session_uuid) if session_uuid else []
        if not steps:
            steps = await _steps_measured(await _trace_last_session(task_id))
        if not steps:
            return 0

        last = len(steps) - 1
        rows = [(int(task_id), int(parent_id) if parent_id else None,
                 str(task_title or '')[:255], str(role or ''),
                 str(step['step_title'] or '')[:190], int(attempt_no or 0),
                 int(context_lines or 0), int(lines_changed or 0) if number == last else 0,
                 int(step['duration_ms'] or 0),
                 step['tokens_out'], step['tokens_prompt'], step['tokens_sec'],
                 str(step['status'] or ''))
                for number, step in enumerate(steps)]

        async with mysql_get_db_async() as db:
            await db.executemany(
                "INSERT INTO project_task_metric "
                "  (task_id, parent_id, task_title, role, step_title, attempt_no, "
                "   context_lines, lines_changed, duration_ms, tokens_output, "
                "   tokens_prompt, tokens_per_sec, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", rows)
            await db.connection.commit()
    except Exception as e:
        logger_info(f'task_metric: замеры строки {task_id} не записаны: {type(e).__name__}: {e}')
        return 0

    return len(rows)


async def task_metric_delete(task_id=None, parent_id=None) -> int:
    """
    Убрать замеры руками. Returns: сколько строк удалили.

    Пересчитывать после этого нечего: средние нигде не хранятся, их считает запрос
    по оставшимся строкам — удалили мусорный прогон, и следующая же сводка идёт
    без него. Хранимые агрегаты пришлось бы чинить отдельно, и они разошлись бы с
    сырыми данными при первом же сбое.

    Без обоих номеров не делаем ничего. Удаление всей таблицы одним нажатием —
    не та операция, которую стоит уметь: накопленное здесь не восстановить, оно
    копится кругами по сорок минут.
    """
    if not task_id and not parent_id:
        return 0

    where, params = ('task_id = %s', [int(task_id)]) if task_id else ('parent_id = %s', [int(parent_id)])

    async with mysql_get_db_async() as db:
        await db.execute(f'DELETE FROM project_task_metric WHERE {where}', params)
        removed = db.rowcount
        await db.connection.commit()

    logger_info(f'task_metric: удалено замеров {removed} '
                f"({'строка ' + str(task_id) if task_id else 'дерево ' + str(parent_id)})")

    return removed


async def task_metric_summary(parent_id=None) -> list[dict]:
    """
    Средние по роли и шагу: главный ответ таблицы.

    `parent_id` — сузить до одной задачи. Пусто — по всем: именно накопленное за
    всё время и говорит, каким ставить таймаут.

    Отдаём и среднее, и максимум. Таймаут ставят не по среднему, а по хвосту:
    круг, уложившийся в среднее, никогда не срывался, — срываются длинные.
    """
    where, params = ('WHERE parent_id = %s', [parent_id]) if parent_id else ('', [])

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT role, step_title, COUNT(*) AS runs, "
            "       ROUND(AVG(context_lines)) AS lines_avg, "
            "       ROUND(AVG(duration_ms) / 1000) AS sec_avg, "
            "       ROUND(MAX(duration_ms) / 1000) AS sec_max, "
            "       ROUND(AVG(tokens_output)) AS tokens_avg, "
            "       ROUND(AVG(NULLIF(tokens_per_sec, 0)), 1) AS speed_avg, "
            "       SUM(lines_changed) AS lines_changed, "
            "       ROUND(AVG(duration_ms) / 1000 / GREATEST(AVG(context_lines), 1) * 1000) AS sec_per_1k "
            f"  FROM project_task_metric {where} "
            # Сначала по роли, потом по тяжести шага. Роль первой — чтобы её шаги
            # шли группой: страница красит группы полосой, а вперемешку полоса не
            # складывается. Внутри роли самый долгий шаг всё равно первый, и
            # главный вопрос «на что уходит круг» читается сразу.
            " GROUP BY role, step_title ORDER BY role, AVG(duration_ms) DESC", params)

        return [dict(row) for row in (await db.fetchall() or [])]


async def task_metric_rows(parent_id=None, limit: int = TASK_METRIC_LIST_MAX) -> list[dict]:
    """Последние замеры по одному на шаг — сырьё, по которому видно разброс."""
    where, params = ('WHERE m.parent_id = %s', [parent_id]) if parent_id else ('', [])

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT m.id, m.task_id, m.parent_id, m.role, m.step_title, m.attempt_no, "
            "       m.context_lines, m.lines_changed, m.duration_ms, m.tokens_output, "
            "       m.tokens_prompt, m.tokens_per_sec, m.status, m.created_at, "
            # Название берём из живой задачи, а копию держим на случай, когда её
            # уже удалили: замер задачу переживает, и строка обязана читаться.
            "       COALESCE(NULLIF(t.title, %s), m.task_title) AS title, "
            "       (t.id IS NULL) AS task_gone "
            "  FROM project_task_metric m "
            "  LEFT JOIN project_task t ON t.id = m.task_id "
            f" {where} ORDER BY m.id DESC LIMIT %s", ['', *params, int(limit)])

        return [dict(row) for row in (await db.fetchall() or [])]


async def task_metric_parents() -> list[dict]:
    """
    Задачи, у которых есть замеры, — для выбора разреза.

    Строим по самой таблице замеров, а не по дереву задач, и это принципиально.
    Дерево на странице зависит от выбранного проекта и бывает пустым; главное же —
    замеры задачу переживают, и удалённая задача обязана остаться в разрезе:
    накопленное по ней никуда не делось, а посмотреть его иначе будет нельзя.

    Название берём у живой задачи, а копию держим на случай удалённой.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT m.parent_id, "
            "       COALESCE(NULLIF(MAX(t.title), ''), MAX(m.task_title)) AS title, "
            "       COUNT(*) AS runs, MAX(t.id) IS NULL AS gone "
            "  FROM project_task_metric m "
            "  LEFT JOIN project_task t ON t.id = m.parent_id "
            " WHERE m.parent_id IS NOT NULL "
            " GROUP BY m.parent_id ORDER BY MAX(m.id) DESC")

        return [dict(row) for row in (await db.fetchall() or [])]


async def task_metric_totals(parent_id=None) -> dict:
    """
    Итог одной строкой: сколько замеров, времени и токенов накоплено.

    Скорость усредняем по ненулевым (`NULLIF`): ноль означает «счётчики модели
    не читались», и в среднее он входить не должен — иначе каждый сбой замера
    занижал бы скорость модели.
    """
    where, params = ('WHERE parent_id = %s', [parent_id]) if parent_id else ('', [])

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT COUNT(*) AS runs, "
            "       COALESCE(SUM(duration_ms), 0) AS ms_total, "
            "       COALESCE(SUM(tokens_output), 0) AS tokens_total, "
            "       COALESCE(SUM(lines_changed), 0) AS lines_changed_total, "
            "       ROUND(AVG(NULLIF(tokens_per_sec, 0)), 1) AS speed_avg, "
            "       ROUND(AVG(NULLIF(context_lines, 0))) AS lines_avg "
            f"  FROM project_task_metric {where}", params)

        return dict(await db.fetchone() or {})


async def _trace_last_session(task_id: int) -> str:
    """
    Сессия последней трассы строки — запасной путь, когда номер потерялся.

    Тот же приём и та же оговорка, что в `task_log._trace_last_session`: «последняя»
    верна лишь потому, что зовут её сразу после обрыва, пока строка заблокирована
    конвейером и новый прогон по ней не начался. Позже «последней» окажется уже
    следующий круг, и в замер уедет его копия.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT session_uuid FROM agent_workflow_trace "
            " WHERE variables_start LIKE %s ORDER BY id DESC LIMIT 1",
            (f'%"subtask_id": "{int(task_id)}"%',))
        row = await db.fetchone()

    return str((row or {}).get('session_uuid') or '')


async def _steps_measured(session_uuid: str) -> list[dict]:
    """
    Шаги прогона, ходившие к агенту, с разобранными токенами.

    Токены лежат внутри ответа инструмента, а тот записан в трассу как repr
    словаря. Разбираем `literal_eval`, а не регулярным выражением: внутри
    `response` живут кавычки и переносы живого текста, и регулярка на первом же
    из них цепляла бы не то. Не разобралось — берём шаг с нулевыми токенами:
    время всё равно ценно, а нули честно скажут, что замера не было.
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT s.step_title, s.status, s.duration_ms, s.output "
            "  FROM agent_workflow_trace_step s "
            "  JOIN agent_workflow_trace r ON r.id = s.run_id "
            " WHERE r.session_uuid = %s AND s.duration_ms >= %s "
            " ORDER BY s.exec_index", (session_uuid, TASK_METRIC_STEP_MIN_MS))
        rows = await db.fetchall() or []

    steps = []
    for row in rows:
        tokens = _tokens_parse(str(row.get('output') or ''))
        steps.append({**row, **tokens})

    return steps


def _tokens_parse(output: str) -> dict:
    """Токены из ответа инструмента. Не нашлись — нули."""
    empty = {'tokens_out': 0, 'tokens_prompt': 0, 'tokens_sec': 0.0}
    raw = output.strip()
    if not raw.startswith('{'):
        return empty

    for parse in (ast.literal_eval, json.loads):
        try:
            data = parse(raw)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            continue
        if isinstance(data, dict):
            return {'tokens_out': int(data.get('tokens_out') or 0),
                    'tokens_prompt': int(data.get('tokens_prompt') or 0),
                    'tokens_sec': float(data.get('tokens_sec') or 0.0)}

    return empty

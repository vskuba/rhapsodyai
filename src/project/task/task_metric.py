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
                              task_title: str = '', lines_changed: int = 0,
                              llm_name: str = '') -> int:
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

    `llm_name` — модель, которой шёл круг: её выдал пул проекта (`team_llm_pool`).
    Пишем копией, как и заголовок: пул меняют, модель из него убирают, а замер
    остаётся — и по нему потом читают, чего эта модель стоила. Пусто — круг шёл до
    появления пула или облачным бэкендом напрямую.

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
                 str(task_title or '')[:255], str(role or ''), str(llm_name or '')[:100],
                 str(step['step_title'] or '')[:190], int(attempt_no or 0),
                 int(context_lines or 0), int(lines_changed or 0) if number == last else 0,
                 int(step['duration_ms'] or 0),
                 step['tokens_out'], step['tokens_prompt'], step['tokens_sec'],
                 str(step['status'] or ''))
                for number, step in enumerate(steps)]

        async with mysql_get_db_async() as db:
            await db.executemany(
                "INSERT INTO project_task_metric "
                "  (task_id, parent_id, task_title, role, llm_name, step_title, attempt_no, "
                "   context_lines, lines_changed, duration_ms, tokens_output, "
                "   tokens_prompt, tokens_per_sec, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", rows)
            await db.connection.commit()
    except Exception as e:
        logger_info(f'task_metric: замеры строки {task_id} не записаны: {type(e).__name__}: {e}')
        return 0

    return len(rows)


async def task_metric_delete(task_id=None, parent_id=None, reset_all: bool = False) -> int:
    """
    Убрать замеры руками. Returns: сколько строк удалили.

    Пересчитывать после этого нечего: средние нигде не хранятся, их считает запрос
    по оставшимся строкам — удалили мусорный прогон, и следующая же сводка идёт
    без него. Хранимые агрегаты пришлось бы чинить отдельно, и они разошлись бы с
    сырыми данными при первом же сбое.

    `reset_all` — начать накопление с нуля. Отдельным флагом, а не «пустыми
    номерами»: обнулить всё случайным вызовом без аргументов нельзя, накопленное
    здесь не восстановить — оно копится кругами по сорок минут.

    Зачем такое вообще нужно. Сравнение моделей идёт по средним, а средние тянут за
    собой прошлое: сменили пул, поправили `max_tokens`, починили канал — и старые
    замеры смешиваются с новыми, показывая погоду позавчерашнего дня. Сброс делает
    ответ чистым: дальше видно ровно то, что происходит после правки.

    Без номеров и без флага не делаем ничего.
    """
    if not task_id and not parent_id and not reset_all:
        return 0

    if reset_all:
        where, params = ('1 = 1', [])
    else:
        where, params = ('task_id = %s', [int(task_id)]) if task_id else ('parent_id = %s', [int(parent_id)])

    async with mysql_get_db_async() as db:
        await db.execute(f'DELETE FROM project_task_metric WHERE {where}', params)
        removed = db.rowcount
        await db.connection.commit()

    scope = ('сброс всей статистики' if reset_all
             else ('строка ' + str(task_id) if task_id else 'дерево ' + str(parent_id)))
    logger_info(f'task_metric: удалено замеров {removed} ({scope})')

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


async def task_metric_by_llm(parent_id=None) -> list[dict]:
    """
    То же накопленное, но в разрезе моделей: чем работать выгоднее.

    Вопрос, на который отвечает таблица, сменился вместе с появлением пула. Пока
    модель у проекта была одна, спрашивали «сколько стоит круг этой роли». Теперь
    моделей несколько, круги идут на разных — и спрашивают, какая из них лучше
    справляется: быстрее отвечает, реже срывается, меньше тратит времени на тот же
    объём.

    Что отдаём и почему именно это:

    | Поле | Зачем |
    |---|---|
    | `runs`, `tasks` | сколько замеров и по скольким задачам — вес выводов |
    | `sec_avg`, `sec_max` | среднее и хвост: срываются длинные круги, не средние |
    | `speed_avg` | токенов в секунду — прямое сравнение моделей |
    | `tokens_avg` | сколько модель наговаривает: болтливая дороже при той же скорости |
    | `fail_share` | доля шагов не в статусе `success` — надёжность |
    | `sec_per_1k` | секунд на тысячу строк контекста: цена объёма |

    Доля сбоев считается по `status`, а не по отсутствию строк: сорвавшийся круг
    свои замеры **пишет** (см. `task_metric_collect` — трасса берётся и у оборванного
    прогона), и именно поэтому по ним видно, какая модель не доводит работу до конца.

    Замеры без модели в отдельной группе с пустым именем — страница подписывает её
    «не записана». Растворять их в чужих средних нельзя: это круги до появления пула,
    и они шли неизвестно чем.
    """
    where, params = ('WHERE parent_id = %s', [parent_id]) if parent_id else ('', [])

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT llm_name, COUNT(*) AS runs, COUNT(DISTINCT task_id) AS tasks, "
            "       ROUND(AVG(duration_ms) / 1000) AS sec_avg, "
            "       ROUND(MAX(duration_ms) / 1000) AS sec_max, "
            "       ROUND(SUM(duration_ms) / 1000) AS sec_total, "
            "       ROUND(AVG(tokens_output)) AS tokens_avg, "
            "       SUM(tokens_output) AS tokens_total, "
            "       ROUND(AVG(NULLIF(tokens_per_sec, 0)), 1) AS speed_avg, "
            "       ROUND(100 * SUM(status <> 'success') / COUNT(*)) AS fail_share, "
            "       ROUND(AVG(duration_ms) / 1000 / GREATEST(AVG(context_lines), 1) * 1000) AS sec_per_1k "
            f"  FROM project_task_metric {where} "
            # По числу замеров: сверху та модель, о которой мы знаем больше всего, —
            # её средним и стоит верить в первую очередь.
            " GROUP BY llm_name ORDER BY runs DESC", params)

        return [dict(row) for row in (await db.fetchall() or [])]


async def task_metric_by_llm_role(parent_id=None) -> list[dict]:
    """
    Модель против роли: одна и та же модель ведёт себя на разных ролях по-разному.

    Разведка менеджера и прогон QA — разная работа: первая читает проект и много
    рассуждает, вторая гоняет команды и ждёт. Средняя по модели их смешивает, и
    решение «эту модель — разработчику, ту — менеджеру» по ней не принять.

    Строк тут больше, поэтому пустые пересечения не выдумываем: пара «модель + роль»,
    которой не было, в таблице просто не появится.
    """
    where, params = ('WHERE parent_id = %s', [parent_id]) if parent_id else ('', [])

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT llm_name, role, COUNT(*) AS runs, "
            "       ROUND(AVG(duration_ms) / 1000) AS sec_avg, "
            "       ROUND(MAX(duration_ms) / 1000) AS sec_max, "
            "       ROUND(AVG(tokens_output)) AS tokens_avg, "
            "       ROUND(AVG(NULLIF(tokens_per_sec, 0)), 1) AS speed_avg, "
            "       ROUND(100 * SUM(status <> 'success') / COUNT(*)) AS fail_share "
            f"  FROM project_task_metric {where} "
            " GROUP BY llm_name, role ORDER BY llm_name, runs DESC", params)

        return [dict(row) for row in (await db.fetchall() or [])]


async def task_metric_task_summary(task_id: int) -> dict:
    """
    Что стоила одна задача: итог, разбивка по моделям и по ролям.

    Считаем по дереву целиком — сама строка плюс её подзадачи: человек на странице
    разбора смотрит на задачу как на одно целое, и «сколько это стоило» для него
    включает работу всех исполнителей, а не только менеджера.

    Три разреза, потому что вопроса три: сколько всего (`totals`), чем работали и
    почём (`by_llm`), кто сколько занял (`by_role`). Один общий список строк на них
    не отвечает — по нему пришлось бы считать глазами.

    Пусто — замеров нет: задача из тех, что заводились до появления таблицы, либо
    круг ещё не кончился. Это не ошибка, и страница показывает так и говорит.
    """
    task_id = int(task_id or 0)
    if not task_id:
        return {'totals': {}, 'by_llm': [], 'by_role': []}

    # Дерево: сама строка и её дети. Внуков в конвейере не бывает — подзадачи плоские,
    # — но условие писано по `parent_id`, и появись они, попадут сюда сами.
    where = '(task_id = %s OR parent_id = %s)'
    params = [task_id, task_id]

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT COUNT(*) AS runs, COUNT(DISTINCT task_id) AS tasks, '
            '       ROUND(SUM(duration_ms) / 1000) AS sec_total, '
            '       SUM(tokens_output) AS tokens_out, SUM(tokens_prompt) AS tokens_prompt, '
            '       SUM(lines_changed) AS lines_changed, '
            '       ROUND(AVG(NULLIF(tokens_per_sec, 0)), 1) AS speed_avg, '
            '       ROUND(100 * SUM(status <> \'success\') / GREATEST(COUNT(*), 1)) AS fail_share '
            f'  FROM project_task_metric WHERE {where}', tuple(params))
        totals = dict(await db.fetchone() or {})

        await db.execute(
            'SELECT llm_name, COUNT(*) AS runs, '
            '       ROUND(SUM(duration_ms) / 1000) AS sec_total, '
            '       ROUND(AVG(duration_ms) / 1000) AS sec_avg, '
            '       SUM(tokens_output) AS tokens_out, '
            '       ROUND(AVG(NULLIF(tokens_per_sec, 0)), 1) AS speed_avg, '
            '       ROUND(100 * SUM(status <> \'success\') / COUNT(*)) AS fail_share '
            f'  FROM project_task_metric WHERE {where} '
            ' GROUP BY llm_name ORDER BY sec_total DESC', tuple(params))
        by_llm = [dict(r) for r in await db.fetchall() or []]

        await db.execute(
            'SELECT role, COUNT(*) AS runs, COUNT(DISTINCT task_id) AS tasks, '
            '       ROUND(SUM(duration_ms) / 1000) AS sec_total, '
            '       SUM(tokens_output) AS tokens_out, '
            '       SUM(lines_changed) AS lines_changed, '
            '       ROUND(100 * SUM(status <> \'success\') / COUNT(*)) AS fail_share '
            f'  FROM project_task_metric WHERE {where} '
            ' GROUP BY role ORDER BY sec_total DESC', tuple(params))
        by_role = [dict(r) for r in await db.fetchall() or []]

    return {'totals': totals, 'by_llm': by_llm, 'by_role': by_role}


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

    Токенов две суммы, и они несъёмно разные: прочитанное (`tokens_prompt`) на
    порядок больше сгенерированного (`tokens_output`) — ход агента пересылает
    историю целиком. Одной цифрой их не показать, не соврав ни в том, ни в другом.

    Скорость усредняем по ненулевым (`NULLIF`): ноль означает «счётчики модели
    не читались», и в среднее он входить не должен — иначе каждый сбой замера
    занижал бы скорость модели.
    """
    where, params = ('WHERE parent_id = %s', [parent_id]) if parent_id else ('', [])

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT COUNT(*) AS runs, "
            "       COALESCE(SUM(duration_ms), 0) AS ms_total, "
            "       COALESCE(SUM(tokens_prompt), 0) AS tokens_prompt_total, "
            "       COALESCE(SUM(tokens_output), 0) AS tokens_output_total, "
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


async def task_metric_lines_advanced(task_id: int, lines_now: int,
                                     attempt_no: int = 0) -> bool:
    """
    Сдвинулась ли работа за этот круг: стало ли в ветке больше кода, чем было.

    Нужна там, где решают, дать ли подзадаче ещё один круг после исчерпанных
    попыток (`task_state_subtask_fail`). Голого «код в ветке есть» для этого мало:
    код остаётся от прошлых кругов, и строка, которая топчется на месте, получала бы
    попытки бесконечно.

    Сравниваем с последним замером, а не с нулём. Живьём у подзадачи #5219 это
    выглядело так: 79 строк четыре круга подряд — работа стояла, — а на пятом стало
    125, и вот он сдвинулся. Первый ответ — «нет, топчется», второй — «да, идёт».

    `attempt_no` — номер текущего круга, и его замеры из сравнения исключаются.
    Иначе сравнение идёт с самим собой: журнал круга (`_log_run`) пишется раньше,
    чем принимается решение о повторе, и «сейчас» уже лежит в таблице последней
    строкой. Ответ выходил бы всегда «нет», то есть проверка молча не работала бы.

    Замеров ещё нет — считаем сдвигом любой непустой код: первый круг сравнивать не
    с чем, а отказать ему значило бы наказать за то, что он первый.

    Ошибку глушим намеренно: это подсказка для решения о повторе, и упавший запрос
    к метрикам не должен ронять круг. Не смогли посчитать — отвечаем «нет», то есть
    ведём себя как до появления этой проверки.
    """
    lines_now = int(lines_now or 0)
    if lines_now <= 0:
        return False

    where = ['task_id = %s', 'lines_changed > 0']
    params = [int(task_id)]
    if attempt_no:
        where.append('attempt_no < %s')
        params.append(int(attempt_no))

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                'SELECT lines_changed FROM project_task_metric '
                f" WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 1",
                tuple(params))
            row = await db.fetchone()
    except Exception as error:
        logger_info(f'[task] метрики строк не прочитаны для #{task_id}: {error}')

        return False

    if not row:
        return True

    return lines_now > int(row.get('lines_changed') or 0)

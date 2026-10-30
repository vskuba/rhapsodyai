"""Доля выполненного у работающей роли: сколько шагов прогона уже пройдено.

Работу роли ведёт workflow, и единственный след того, где она сейчас, — трейс
(`agent_workflow_trace` и его шаги). Прогон привязывается к строке очереди не по
времени захвата, а по номеру задачи в стартовых переменных: у одной роли столько
одновременных прогонов, сколько проектов, и «ближайший по времени» ошибался бы
ровно тогда, когда работы много.

**Знаменатель — не число шагов в workflow.** В WF55 их 53, но полтора десятка —
ветки ошибок и тупики («Менеджер недоступен», «Цели недоступны»), в удачном
прогоне не исполняемые ни разу; зато шаги-циклы (судья, счётчик итераций)
исполняются по нескольку раз. Считать от определения значило бы показывать 26 %
в момент, когда менеджер уже вернул план. Поэтому за 100 % берётся медиана числа
исполненных шагов по прошлым **удачным** прогонам того же workflow — оценка по
факту, а не по схеме. Истории нет — только тогда берём число шагов определения.

Отсюда и потолок: оценка по медиане легко перешагивает свой знаменатель (цикл
судьи развернулся лишний раз), а работающий прогон не бывает завершён — процент
упирается в `TEAM_PROGRESS_MAX_PERCENT` и ждёт настоящего конца.

## ⚠ Знаменатель считается редко, а не на каждый опрос

Выдачу, ради которой этот модуль и зовут, опрашивают раз в 15 секунд две
страницы админки. Медиана при этом за 15 секунд не меняется — чтобы она
сдвинулась, нужны новые удачные прогоны того же workflow, — а стоила она на проде
406 мс: база сводила все удачные прогоны workflow разом. Поэтому значение живёт в
`_totals_cache` на `TEAM_PROGRESS_TOTAL_TTL`, а сам замер (`_totals_measure`)
берёт индексом только последний десяток прогонов, а не все.

⚠ Второй половиной той же экономии занимается вызывающий: `team_queue` не зовёт
`team_progress_running` вовсе, пока в очереди нет ни одной занятой строки.
Прогресс есть только у работающей роли, а конвейер стоит большую часть суток.

Здесь же считается срок текущего шага. Прогон обрывается не по своему потолку
(`timeout_manager_run` — больше часа), а по ожиданию ответа оболочки на отдельном
шаге: в WF55 это десять минут, и планирование гибнет именно на нём. Значение шага
лежит в его же метаданных литералом `_const_600`, поэтому читается из определения
workflow, а не из настроек; разбор литерала и правка с карточки команды — в
`task_setting_step.py`.
"""
import time

from json_.json_ import json_from_string
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_setting_step import task_setting_step_timeout_of
from src.project.task.task_setting_timeout import (TASK_SETTING_TIMEOUT_SHELL_CALL,
                                                   task_setting_timeout_get)

# Сколько прошлых удачных прогонов берём за образец длины.
TEAM_PROGRESS_SAMPLE_LIMIT = 10

# Насколько знаменатель считается свежим. Медиана по десяти последним удачным
# прогонам за пять минут не меняется: чтобы она сдвинулась, нужны новые удачные
# прогоны того же workflow, а идут они минутами. Правку самого workflow при этом
# видно на следующем окне — это и есть верхняя граница «через сколько доля
# перестроится под новый сценарий».
TEAM_PROGRESS_TOTAL_TTL = 300

# Работающий прогон не показывает 100 %: конец отмечает завершение, а не оценка.
TEAM_PROGRESS_MAX_PERCENT = 99


async def team_progress_running() -> dict[tuple[str, int], dict]:
    """Прогресс всех работающих прогонов.

    Returns:
        {('task'|'subtask', id): {'percent': int, 'step_index': int,
                                  'step_total': int, 'step_title': str,
                                  'step_left_seconds': int|None,
                                  'step_running_title': str}}
        Ключ — то, чем прогон занят: планирование адресуется задачей, круг
        Developer/QA — подзадачей. Прогонов без номера в переменных (запуск
        не из конвейера) в ответе нет.

        `step_left_seconds` — сколько осталось идущему сейчас шагу до его
        собственного таймаута, `step_running_title` — название этого шага. None,
        когда шаг ответа не ждёт (не ходит в оболочку) или когда идущий шаг не
        опознан: врать сроком хуже, чем промолчать.
    """
    runs = await _runs_running()
    if not runs:
        return {}

    last_steps    = await _steps_last([run['id'] for run in runs])
    totals        = await _totals_by_workflow({int(run['workflow_id'] or 0) for run in runs})
    defined       = await _steps_defined({int(run['workflow_id'] or 0) for run in runs})
    shell_default = await task_setting_timeout_get(TASK_SETTING_TIMEOUT_SHELL_CALL)
    # ⚠ Срок шага бывает задан переменной потока, а не литералом в его
    # метаданных: разбирает оба вида `task_setting_step_timeout_of`, но
    # значение переменной надо ему подать.
    flow_vars     = await _variables_defined({int(run['workflow_id'] or 0) for run in runs})

    progress: dict[tuple[str, int], dict] = {}
    for run in runs:
        step = last_steps.get(int(run['id']))
        if not step:
            # Прогон начался, первый шаг ещё не закрыт — считать нечего.
            continue
        key = _key_build(run)
        if key is None:
            continue
        total = max(1, int(totals.get(int(run['workflow_id'] or 0)) or 1))
        # `exec_index` считает с единицы, так что это уже «сколько шагов пройдено».
        index = int(step.get('exec_index') or 0)
        running = _step_running_find(defined.get(int(run['workflow_id'] or 0)) or [], step)
        timeout = _step_timeout_get(running, shell_default,
                                    flow_vars.get(int(run['workflow_id'] or 0)) or {})
        progress[key] = {
            'percent':    min(TEAM_PROGRESS_MAX_PERCENT, round(100 * index / total)),
            'step_index': index,
            'step_total': total,
            'step_title': str(step.get('step_title') or ''),
            'step_left_seconds': (max(0, timeout - int(step.get('since_seconds') or 0))
                                  if timeout else None),
            'step_running_title': str(running.get('title') or '') if timeout else '',
        }

    return progress


async def _runs_running() -> list[dict]:
    """Работающие прогоны с номерами задачи и подзадачи из стартовых переменных.

    ⚠ Номера берутся **колонками**, а не разбором JSON на лету. Раньше здесь
    стояли `JSON_VALID` и два `JSON_EXTRACT` по `variables_start`, и любое из них
    заставляло базу прочитать LONGTEXT у каждой строки таблицы: `type: ALL`,
    174 МБ, 81 мс на запрос — а запрос этот идёт по опросу страницы. Колонки
    `task_id`/`subtask_id` считаются из того же поля при вставке и покрыты
    индексом (`20260929123812`); `JSON_VALID` в условии не нужен вовсе — кривой
    JSON даёт в них `NULL`, и прогон отсеется дальше, в `_key_build`.
    """
    sql = (
        "SELECT id, workflow_id, task_id, subtask_id "
        "  FROM agent_workflow_trace "
        " WHERE status = 'running' "
        " ORDER BY id"
    )

    return await _rows_fetch(sql, ())


async def _steps_last(run_ids: list[int]) -> dict[int, dict]:
    """Последний записанный шаг каждого прогона.

    Порядок — по `id` записи, а не по `exec_index`: индекс на циклах повторяется,
    и «последний по индексу» вернул бы шаг из предыдущего витка.

    `since_seconds` — сколько прошло с этой записи. Шаг записывается по завершении,
    поэтому его момент — это начало следующего, идущего сейчас: другого отсчёта у
    работающего шага нет, в базе он появится только когда кончится.
    """
    marks = ', '.join(['%s'] * len(run_ids))
    sql = (
        "SELECT s.run_id, s.exec_index, s.step_id, s.step_title, s.transition, "
        "       TIMESTAMPDIFF(SECOND, s.created_at, NOW()) AS since_seconds "
        "  FROM agent_workflow_trace_step s "
        "  JOIN (SELECT run_id, MAX(id) AS id FROM agent_workflow_trace_step "
        f"         WHERE run_id IN ({marks}) GROUP BY run_id) last ON last.id = s.id"
    )
    rows = await _rows_fetch(sql, tuple(run_ids))

    return {int(row['run_id']): row for row in rows}


async def _steps_defined(workflow_ids: set[int]) -> dict[int, list[dict]]:
    """Шаги workflow в порядке исполнения по умолчанию — чтобы найти идущий сейчас."""
    ids = [wid for wid in workflow_ids if wid]
    if not ids:
        return {}

    marks = ', '.join(['%s'] * len(ids))
    sql = (f"SELECT id, workflow_id, title, metadata FROM agent_workflow_step "
           f" WHERE workflow_id IN ({marks}) ORDER BY workflow_id, position, id")

    steps: dict[int, list[dict]] = {}
    for row in await _rows_fetch(sql, tuple(ids)):
        steps.setdefault(int(row['workflow_id']), []).append(row)

    return steps


async def _variables_defined(workflow_ids: set[int]) -> dict[int, dict]:
    """Умолчания переменных потоков: `{поток: {имя: значение}}`.

    ⚠ Нужны затем, что срок шага бывает задан **ссылкой на переменную**, а не
    литералом в метаданных. Читатель у обоих видов один
    (`task_setting_step_timeout_of`), но значение переменной лежит не в шаге, и
    подать его обязан вызывающий.
    """
    ids = [wid for wid in workflow_ids if wid]
    if not ids:
        return {}

    marks = ', '.join(['%s'] * len(ids))
    sql = ('SELECT workflow_id, name, `default` FROM agent_workflow_variable'
           f' WHERE workflow_id IN ({marks})')

    got: dict[int, dict] = {}
    for row in await _rows_fetch(sql, tuple(ids)):
        got.setdefault(int(row['workflow_id']), {})[
            str(row['name'] or '').strip()] = row['default']

    return got


# Посчитанный знаменатель: `{workflow_id: (шагов, до какого момента годен)}`.
# Живёт в процессе, общего хранилища ему не нужно — значение одинаковое у всех, и
# посчитать его заново стоит один запрос.
_totals_cache: dict[int, tuple[int, float]] = {}


async def _totals_by_workflow(workflow_ids: set[int]) -> dict[int, int]:
    """Сколько шагов считать за 100 % — по медиане прошлых удачных прогонов.

    Значение кэшируется на `TEAM_PROGRESS_TOTAL_TTL`: см. шапку модуля, раздел
    про цену знаменателя.
    """
    ids = [wid for wid in workflow_ids if wid]
    if not ids:
        return {}

    now = time.monotonic()
    known: dict[int, int] = {}
    for wid in ids:
        value, until = _totals_cache.get(wid, (0, 0.0))
        if until > now:
            known[wid] = value

    stale = [wid for wid in ids if wid not in known]
    if not stale:
        return known

    fresh = await _totals_measure(stale)
    until = now + TEAM_PROGRESS_TOTAL_TTL
    for wid in stale:
        # В кэш кладём и промах: workflow без единого удачного прогона и без шагов
        # знаменателя не даёт, и переспрашивать о нём каждые 15 секунд — та же
        # работа, только впустую. Ноль вызывающий уже умеет читать как «молчим
        # про долю» (`max(1, ...)` на месте использования).
        _totals_cache[wid] = (int(fresh.get(wid) or 0), until)

    return {**known, **fresh}


async def _totals_measure(workflow_ids: list[int]) -> dict[int, int]:
    """Медиана числа исполненных шагов по последним удачным прогонам. Без кэша.

    ⚠ **Прогоны отбираются по одному workflow за раз, и это дешевле общего
    запроса.** Прежде брался один `IN (...)` с `GROUP BY r.workflow_id, r.id` и
    без предела: база сводила **все** удачные прогоны каждого workflow (на проде
    это 10 454 строки только по четырём номерам, плюс временная таблица), а
    питон дальше выбрасывал всё, кроме первого десятка. Замер — 406 мс, и уходили
    они на работу, результат которой не использовался.

    Здесь у каждого workflow свои `TEAM_PROGRESS_SAMPLE_LIMIT` последних удачных
    прогонов отбираются индексом, и шаги считаются только у них. Ответ тот же:
    прежний код брал ровно первый десяток того же порядка (`ORDER BY r.id DESC`).

    ⚠ Запросов столько, сколько workflow у идущих прогонов, — то есть единицы:
    ролей конвейера четыре. Это не «N+1»: N здесь не растёт ни с числом задач, ни
    с числом прогонов.

    ⚠ **`EXISTS` в отборе прогонов — не лишнее условие, а сохранение прежнего
    ответа.** Старый запрос сводил прогоны с шагами внутренним `JOIN`, то есть
    прогон без единого записанного шага в десяток образцов не попадал вовсе.
    Возьми мы просто «последние десять удачных», такой прогон занял бы место в
    выборке и выпал бы уже после — образцов стало бы меньше десяти, и медиана
    поехала бы. Сегодня на проде таких прогонов ноль из 25 775, но ноль этот
    держится на том, что запись шага может и не состояться: `trace_step` свои
    отказы глотает, чтобы не ронять workflow.
    """
    samples: dict[int, list[int]] = {}
    for wid in workflow_ids:
        rows = await _rows_fetch(
            "SELECT COUNT(s.id) AS execs "
            "  FROM (SELECT id FROM agent_workflow_trace r "
            "         WHERE r.workflow_id = %s AND r.status = 'success' "
            "           AND EXISTS (SELECT 1 FROM agent_workflow_trace_step e "
            "                        WHERE e.run_id = r.id) "
            "         ORDER BY r.id DESC LIMIT %s) r "
            "  JOIN agent_workflow_trace_step s ON s.run_id = r.id "
            " GROUP BY r.id",
            (wid, TEAM_PROGRESS_SAMPLE_LIMIT))
        values = [int(row['execs'] or 0) for row in rows]
        if values:
            samples[wid] = values

    totals = {wid: _median(values) for wid, values in samples.items() if _median(values)}
    missing = [wid for wid in workflow_ids if wid not in totals]

    return {**(await _totals_defined(missing)), **totals}


async def _totals_defined(workflow_ids: list[int]) -> dict[int, int]:
    """Запасной знаменатель — число шагов в определении workflow."""
    if not workflow_ids:
        return {}

    marks = ', '.join(['%s'] * len(workflow_ids))
    sql = (f"SELECT workflow_id, COUNT(*) AS steps FROM agent_workflow_step "
           f" WHERE workflow_id IN ({marks}) GROUP BY workflow_id")

    return {int(row['workflow_id']): int(row['steps'] or 0)
            for row in await _rows_fetch(sql, tuple(workflow_ids))}


async def _rows_fetch(sql: str, params: tuple) -> list[dict]:
    async with mysql_get_db_async() as db:
        await db.execute(sql, params)
        rows = await db.fetchall()

    return [dict(row) for row in (rows or [])]


def _key_build(run: dict) -> tuple[str, int] | None:
    """Чем занят прогон: подзадача важнее задачи.

    У Developer/QA в переменных лежат обе — задача нужна промпту для контекста,
    работой же считается подзадача, и очередь показывает именно её.
    """
    for kind in ('subtask', 'task'):
        value = str(run.get(f'{kind}_id') or '').strip()
        if value.isdigit() and int(value):
            return kind, int(value)

    return None


def _step_running_find(defined: list[dict], step: dict) -> dict:
    """Шаг, идущий сейчас, — тот, куда прогон ушёл с последнего записанного.

    Переход лежит в самой записи (`transition.to_step_id`), и в фазе `before` тоже:
    пропущенный шаг попадает в журнал с указанием, куда прыгнули. Перехода нет —
    движок берёт следующий по позиции, порядок здесь тот же, что у него.

    Пустой словарь, когда шага не нашлось: определение workflow могли поменять
    после старта прогона, и выдумывать срок по чужому шагу нельзя.
    """
    transition = json_from_string(step.get('transition'))
    target = int(transition.get('to_step_id') or 0)
    if target:
        return next((row for row in defined if int(row.get('id') or 0) == target), {})

    last_id = int(step.get('step_id') or 0)
    for index, row in enumerate(defined):
        if int(row.get('id') or 0) == last_id:
            return defined[index + 1] if index + 1 < len(defined) else {}

    return {}


def _step_timeout_get(step: dict, default: int, variables: dict = None) -> int:
    """Срок шага в секундах; 0 — шаг ничего не ждёт и срока у него нет.

    Args:
        variables: умолчания переменных потока — шаг может задавать срок
            ссылкой на переменную, а не литералом.

    Разбор — в `task_setting_step`: то же значение правится с карточки
    команды, и читать его двумя способами значит однажды разойтись. Ноль оттуда
    означает «шаг ждёт, но срока не задал», и тогда берётся настройка — ровно то,
    чем инструмент подменяет незаданный таймаут.
    """
    seconds = task_setting_step_timeout_of(json_from_string(step.get('metadata')),
                                           variables)

    return 0 if seconds is None else (seconds or int(default))


def _median(values: list[int]) -> int:
    """Медиана, а не среднее: один сорвавшийся долгий прогон не сдвигает оценку."""
    ordered = sorted(v for v in values if v > 0)
    if not ordered:
        return 0
    middle = len(ordered) // 2

    return (ordered[middle] if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) // 2)

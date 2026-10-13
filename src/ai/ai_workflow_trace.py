import json
import traceback

from config.config import config_get
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Максимальная длина всего JSON-значения при сохранении в журнал
TRACE_VALUE_MAX_LEN = 500_000
# Максимальная длина отдельного строкового значения внутри dict-метаданных
TRACE_STR_VALUE_MAX_LEN = 100_000

# Через сколько секунд молчания прогон считается брошенным (`ai_workflow_trace_runs_stale_close`).
#
# Порог обязан быть больше самого долгого шага. Шаг пишет строку трассы, только
# **завершившись**: пока «реализация» ждёт разработчика, журнал молчит, и живой прогон
# по этому признаку неотличим от мёртвого. Самый долгий шаг конвейера — 7200с
# (`_const_7200` у шага 436, WF56), отсюда 9000 с запасом.
#
# Прежние 3600 стояли с тех пор, когда реализация ждала 1800с. Дальше её подняли до
# 4800, потом до 7200, а порог остался — и уборка начала штамповать «Прерван рестартом
# сервера» работающим прогонам. Живьём: прогон 2470 подзадачи #5238 помечен брошенным
# в 04:44, а его шаг реализации закончился в 04:51 и записался как ни в чём не бывало.
# Гасить прогон пометка не гасит (движок пишет 'stopped' только сам, поймав отмену),
# поэтому цена — враньё в журнале, ровно то, ради ухода от которого писали функцию.
#
# Меняешь сроки шагов — сверься с этим числом. Проверка держит связь машинно:
# `TestTraceStaleThreshold` в `tests/test_task_pipeline.py` берёт максимум из живых
# workflow, а не из памяти о том, каким он был.
TRACE_RUN_STALE_SECONDS = 9000

# Сколько дней держим прогон. Столько же, сколько держали раньше, — менялось не
# «сколько», а «кто и когда убирает» (`ai_workflow_trace_trim`).
TRACE_KEEP_DAYS = 7

# Сколько прогонов сносим одним `DELETE`. Пачка нужна не ради скорости, а ради
# замков: каждый прогон тянет за собой каскадом свои шаги и свои sub-workflow, и
# один `DELETE` на месячный завал держал бы таблицу под замком минутами — ровно
# ту таблицу, в которую в этот момент пишутся живые прогоны.
TRACE_TRIM_BATCH = 200

# Потолок на один прогон уборки. Стоит не от недоверия к базе, а от расписания:
# крон ходит ежечасно, и уборке незачем разгребать за один раз то, что спокойно
# разойдётся по нескольким заходам.
TRACE_TRIM_MAX = 10000


def ai_workflow_trace_enabled() -> bool:
    return str(config_get('WORKFLOW_TRACE_ENABLED', '1')).lower() not in ('0', 'false', 'off')


async def ai_workflow_trace_run_start(run_uuid: str, workflow_id, agent_id, user_id,
                                   session_uuid: str, request_uuid: str,
                                   prompt_user, variables: dict,
                                   parent_run_id: int | None = None,
                                   parent_step_id: int | None = None,
                                   depth: int = 0,
                                   request_json=None) -> int | None:
    """Создает запись запуска workflow. Возвращает run_id либо None (трейс выключен/сбой) —
    сбой записи журнала никогда не должен ронять выполнение workflow.

    ⚠ `request_json` — контракт вызова, который сложил ЗОВУЩИЙ (ручка) и положил
    на модель. Движок переносит его сюда, не разбирая: что такое «тело запроса»,
    знает только тот, кто его объявил. Пишется здесь, а не вторым заходом в
    конце, затем что прогон читают и **пока он идёт** — у зависшего вопрос «чем
    его позвали» первый по порядку, а отвечать на него будет уже нечем.
    """
    if not ai_workflow_trace_enabled():
        return None
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                INSERT INTO agent_workflow_trace
                    (run_uuid, parent_run_id, parent_step_id, depth, workflow_id, agent_id,
                     user_id, session_uuid, request_uuid, prompt_user, variables_start,
                     request_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_uuid, parent_run_id, parent_step_id, depth, workflow_id, agent_id,
                 user_id, session_uuid, request_uuid, _workflow_trace_truncate(prompt_user),
                 _workflow_trace_json_dump(variables), _workflow_trace_json_dump(request_json))
            )
            return db.lastrowid
    except Exception as e:
        logger_info(f"⚠️ ai_workflow_trace_run_start не записан: {e}\n{traceback.format_exc()}")
        return None


async def ai_workflow_trace_run_finish(run_id: int | None, status: str,
                                    result=None, error: str | None = None,
                                    duration_ms: int | None = None) -> None:
    """Закрывает запись запуска: статус, результат/ошибка, длительность."""
    if run_id is None:
        return
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                UPDATE agent_workflow_trace
                SET status = %s, result = %s, error = %s,
                    finished_at = NOW(3), duration_ms = %s
                WHERE id = %s
                """,
                (status, _workflow_trace_truncate(result), _workflow_trace_truncate(error), duration_ms, run_id)
            )
    except Exception as e:
        logger_info(f"⚠️ ai_workflow_trace_run_finish не записан: {e}")


async def ai_workflow_trace_run_contract(run_id: int | None, request=None, response=None) -> None:
    """Записать контракт вызова: чем прогон начали и что ушло зовущему.

    ЗАПРОС и ОТВЕТ на странице — это `prompt_user` и `result`, то есть вход и
    выход **workflow**. Контракт — соседний вопрос: что пришло по HTTP и что
    по нему ответили. Из прогона он не восстанавливается: `variables` запроса
    растворены в снапшоте старта вперемешку с переменными агента и ноды, а
    `message_id` с `intentions` не хранились нигде.

    Args:
        run_id: номер прогона (`model.trace_run_id`); `None` — писать некуда.
        request: тело запроса. `None` — не трогать колонку.
        response: тело ответа или отказа. `None` — не трогать колонку.

    ⚠⚠ Зовёт **ручка**, а не движок: контракт принадлежит тому, кто его
    объявил. Движок про HTTP не знает, и у соседних входов (мини-приложение,
    блог) контракты свои.

    ⚠ Пишется двумя заходами — запрос в начале, ответ в конце, — поэтому
    `None` значит «про это поле мне сейчас нечего сказать», а не «пусто».
    Иначе второй заход затирал бы первый.

    ⚠ Сбой записи не роняет вызов: контракт — журнал, а не работа. То же
    правило, что у остальных функций модуля.
    """
    if run_id is None or (request is None and response is None):
        return

    fields, params = [], []
    if request is not None:
        fields.append('request_json = %s')
        params.append(_workflow_trace_json_dump(request))
    if response is not None:
        fields.append('response_json = %s')
        params.append(_workflow_trace_json_dump(response))

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                f"UPDATE agent_workflow_trace SET {', '.join(fields)} WHERE id = %s",
                (*params, run_id)
            )
    except Exception as e:
        logger_info(f"⚠️ ai_workflow_trace_run_contract не записан: {e}")


async def ai_workflow_trace_step(run_id: int | None, exec_index: int, step: dict,
                              metadata_rendered=None, variables_changed: dict | None = None,
                              output=None, transition: dict | None = None,
                              status: str = 'success', error: str | None = None,
                              duration_ms: int | None = None,
                              llm_id: int | None = None,
                              tokens_input: int | None = None,
                              tokens_output: int | None = None) -> None:
    """Записывает выполненный шаг: вход (metadata после рендера), выход (изменённые
    переменные), сырой output, сработавший переход, статус и длительность.
    llm_id — модель использованная в LLM-шаге (None для tool/text/variable шагов)."""
    if run_id is None:
        return
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                INSERT INTO agent_workflow_trace_step
                    (run_id, exec_index, step_id, step_title, step_type, llm_id,
                     metadata_rendered, variables_changed, output, transition, status, error, duration_ms,
                     tokens_input, tokens_output)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, exec_index, step.get('id'),
                 str(step.get('title', ''))[:100], str(step.get('step_type_name', ''))[:50],
                 llm_id,
                 _workflow_trace_json_dump(metadata_rendered), _workflow_trace_json_dump(variables_changed),
                 _workflow_trace_truncate(output), _workflow_trace_json_dump(transition),
                 status, _workflow_trace_truncate(error), duration_ms,
                 tokens_input, tokens_output)
            )
    except Exception as e:
        logger_info(f"⚠️ ai_workflow_trace_step не записан: {e}")


async def ai_workflow_trace_runs_stale_close() -> int:
    """На старте сервера закрывает записи, застрявшие в статусе 'running' —
    они остались после предыдущего рестарта (SIGKILL/crash), когда ai_workflow_trace_run_finish
    не успел выполниться. Возвращает кол-во закрытых записей.

    Закрываем не все running-записи, а только замолчавшие. Прогоны идут не только
    в uvicorn: воркеры конвейера задач (`src/worker/project/`) — отдельные контейнеры,
    их прогоны переживают рестарт сервера. А рестарт этот случается посреди чужой
    работы регулярно: промпт разработчика прямо велит ему перезапустить uvicorn после
    правки .py. Раньше такой рестарт штамповал живым прогонам 'Прерван рестартом
    сервера', журнал показывал остановку, а прогон продолжал идти и слать сообщения
    агенту — в логах пусто, а работа кипит.

    Признак брошенного — молчание: ни одного шага дольше `TRACE_RUN_STALE_SECONDS`
    (у прогона без шагов считаем от старта). Работающий прогон свои шаги пишет.
    """
    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                """
                UPDATE agent_workflow_trace r
                LEFT JOIN (
                    SELECT run_id, MAX(created_at) AS last_step_at
                      FROM agent_workflow_trace_step
                     GROUP BY run_id
                ) s ON s.run_id = r.id
                SET r.status = 'stopped',
                    r.error = 'Прерван рестартом сервера',
                    r.finished_at = NOW(3)
                WHERE r.status = 'running'
                  AND GREATEST(r.started_at, COALESCE(s.last_step_at, r.started_at))
                      < NOW(3) - INTERVAL %s SECOND
                """,
                (TRACE_RUN_STALE_SECONDS,)
            )
            count = db.rowcount
        if count:
            logger_info(f"🧹 ai_workflow_trace_runs_stale_close: закрыто {count} зависших running-записей")
        return count
    except Exception as e:
        logger_info(f"⚠️ ai_workflow_trace_runs_stale_close не выполнен: {e}")
        return 0


async def ai_workflow_trace_trim(keep_days: int = TRACE_KEEP_DAYS,
                                 batch: int = TRACE_TRIM_BATCH,
                                 limit: int = TRACE_TRIM_MAX) -> int:
    """Сносит прогоны старше срока. Пачками, по расписанию — не из запроса страницы.

    Args:
        keep_days: сколько дней держим прогон.
        batch: сколько прогонов сносим одним `DELETE`.
        limit: потолок на один заход уборки.

    Returns:
        int: сколько прогонов снесено (шаги и sub-workflow уходят каскадом, в счёт
        не попадают).

    ## ⚠ Почему это больше не живёт в ручке списка

    Раньше тот же `DELETE` стоял первой строкой в `/workflow_trace/run/list`, то
    есть шёл на **каждое** открытие страницы трасс — а страница зовёт список
    дважды при заходе и ещё раз на каждое переключение вкладки, отбора и
    страницы. Стоило это на проде 119 мс полного прохода по таблице в 174 МБ, и
    удаляло при этом **ноль строк**: 26 тысяч прогонов набегают меньше чем за
    неделю, и до порога не доживает никто.

    Хуже цены была блокировка. Условие шло без индекса, а уровень изоляции у базы
    `REPEATABLE-READ`: `DELETE` брал next-key-замок на каждую просмотренную
    строку, то есть открытие страницы трасс на сотню миллисекунд запирало запись
    трассы для всех идущих в этот момент workflow. Страницу трасс открывают
    именно тогда, когда что-то идёт.

    ⚠ **`depth = 0` в условии обязателен.** У дочерних прогонов (sub-workflow)
    свой `finished_at`, и он почти всегда раньше родительского: адресный снос
    по времени выдрал бы ветки из-под живого дерева. Дети уходят каскадом за
    родителем — так и задумано внешним ключом `fk_wr_run_parent`.

    ⚠ **`ORDER BY finished_at` не для красоты.** Без него MySQL выбирает, какие
    именно `batch` строк снести, на своё усмотрение, и пачки перемешиваются:
    уборка перестаёт быть «сначала самое старое» и на потолке `limit`
    останавливается посреди случайного места.
    """
    removed = 0
    try:
        async with mysql_get_db_async() as db:
            while removed < limit:
                await db.execute(
                    'DELETE FROM agent_workflow_trace'
                    ' WHERE depth = 0 AND finished_at < NOW() - INTERVAL %s DAY'
                    ' ORDER BY finished_at'
                    ' LIMIT %s',
                    (int(keep_days), min(int(batch), limit - removed)))
                count = int(db.rowcount or 0)
                removed += count
                if not count:
                    break
    except Exception as e:
        # Уборка — не работа, ради которой процесс живёт: недоступная база или
        # замок отменяют заход, а не роняют кронджоб. Следующий час разгребёт.
        logger_info(f'⚠️ ai_workflow_trace_trim не доделан ({removed} снесено): {e}')

    if removed:
        logger_info(f'🧹 ai_workflow_trace_trim: снесено прогонов {removed} '
                    f'(старше {keep_days} дн.)')

    return removed


def ai_workflow_trace_variables_diff(before: dict, after: dict) -> dict:
    """Изменённые и новые переменные шага (для поля variables_changed)."""
    return {
        key: value for key, value in after.items()
        if key not in before or before[key] != value
    }


def _workflow_trace_truncate(text: str | None) -> str | None:
    if text is None:
        return None
    text = str(text)
    if len(text) > TRACE_VALUE_MAX_LEN:
        return text[:TRACE_VALUE_MAX_LEN] + '...[truncated]'
    return text


def _workflow_trace_str_truncate(value: str) -> str:
    if len(value) > TRACE_STR_VALUE_MAX_LEN:
        return value[:TRACE_STR_VALUE_MAX_LEN] + '...[truncated]'
    return value


def _workflow_trace_dict_prepare(data):
    """Рекурсивно обрезает длинные строки внутри dict/list, сохраняя структуру JSON."""
    if isinstance(data, dict):
        return {k: _workflow_trace_dict_prepare(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_workflow_trace_dict_prepare(item) for item in data]
    if isinstance(data, str):
        return _workflow_trace_str_truncate(data)
    return data


def _workflow_trace_json_dump(data) -> str | None:
    if data is None:
        return None
    try:
        prepared = _workflow_trace_dict_prepare(data) if isinstance(data, (dict, list)) else data
        return _workflow_trace_truncate(json.dumps(prepared, ensure_ascii=False, default=str))
    except Exception:
        return _workflow_trace_truncate(str(data))

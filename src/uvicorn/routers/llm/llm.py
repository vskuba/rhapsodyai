import json
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException

from src.ai.ai_llm import ai_llm_provider
from config.config import config_get
from mysql_.mysql_ import mysql_get_db_async
from setting_.setting_ import setting_get, setting_set
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# Допустимые интервалы сброса ошибок и настройка по умолчанию
LLM_ERROR_RESET_SECONDS = (15, 45, 180, 300)
LLM_ERROR_RESET_DEFAULT = 300

# ⚠ Anthropic требует версию API заголовком на **каждом** запросе, включая
# справочный `GET /models`. Без него пинг возвращает 400 «anthropic-version:
# header is required», и живая модель показывается в панели мёртвой. Сам вызов
# модели идёт OpenAI-совместимой ручкой через pydantic-ai, и там заголовок
# ставит клиент — потому несоответствие и всплыло только на пинге.
LLM_PING_ANTHROPIC_VERSION = '2023-06-01'


@router.get("/llm/list")
async def llm_list(db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.LLM_VIEW]))):
    """Все LLM независимо от пользователя (справочник для админских страниц)."""
    async with db:
        await db.execute("SELECT * FROM `llm` ORDER BY `name` ASC")
        return {"result": await db.fetchall()}


@router.get("/llm/status")
async def llm_status(node_id: int | None = None, reset_seconds: int | None = None,
                     user=Depends(AuthChecker([AuthPermission.LLM_VIEW]))):
    """Очередь LLM выбранной ноды в порядке приоритета (position).

    Активная модель — та, которую выберет движок: первая по сортировке
    rate_limit_at ASC, position ASC (ошибки 429/413/402/503 двигают модель
    в конец очереди через rate_limit_at + code_error).

    Ошибки старше интервала reset_seconds сбрасываются в БД перед выборкой
    (rate_limit_at и code_error -> NULL) — модель возвращается на свою позицию.
    Переданный reset_seconds сохраняется как настройка страницы."""
    if reset_seconds is not None and reset_seconds not in LLM_ERROR_RESET_SECONDS:
        raise HTTPException(status_code=400, detail=f"reset_seconds: допустимые значения {LLM_ERROR_RESET_SECONDS}")

    if reset_seconds is not None:
        await setting_set('llm_error_reset_seconds', reset_seconds)
        seconds = reset_seconds
    else:
        stored = str(await setting_get('llm_error_reset_seconds'))
        seconds = int(stored) if stored and stored.isdigit() else LLM_ERROR_RESET_DEFAULT

    async with mysql_get_db_async() as db:
        # Сброс просроченных ошибок: модель снова участвует в очереди по своей позиции.
        #
        # ⚠⚠ Сначала спрашиваем, есть ли что сбрасывать, и только потом пишем.
        # Лишний `SELECT` здесь дешевле `UPDATE` вхолостую, и вот почему:
        # индекса по `rate_limit_at` нет, `EXPLAIN` на этот `UPDATE` даёт
        # `rows: 41` — то есть просматриваются все строки таблицы, — а при
        # `REPEATABLE-READ` просмотренное запирается next-key-замками. Замок на
        # всю `node_llm` берётся, даже когда обновлять нечего, а нечего почти
        # всегда: модели в ошибке — исключение, а не норма.
        #
        # Цена этого выяснилась на проде 2026-09-29. Страница `/admin/llm`
        # опрашивает эту ручку **раз в секунду**, запросы наложились друг на
        # друга и встали в очередь за замком (`innodb_lock_wait_timeout` — 50 с).
        # Десять таких запросов заняли весь пул соединений, и вместе с ними встало
        # всё, что ходит в базу: вход в панель, вызовы LLM, работа соседнего
        # проекта. В логах при этом ни одной ошибки — исчерпанный пул не роняет
        # запрос, а ждёт.
        #
        # `SELECT` замков не берёт вовсе, и в обычном случае ручка теперь не
        # пишет ничего.
        await db.execute(
            "SELECT COUNT(*) AS qty FROM node_llm"
            " WHERE rate_limit_at IS NOT NULL AND rate_limit_at < NOW() - INTERVAL %s SECOND",
            (seconds,)
        )
        if int((await db.fetchone() or {}).get('qty') or 0):
            await db.execute(
                """
                UPDATE node_llm SET rate_limit_at = NULL, code_error = NULL
                WHERE rate_limit_at IS NOT NULL AND rate_limit_at < NOW() - INTERVAL %s SECOND
                """,
                (seconds,)
            )

        await db.execute("SELECT id, name FROM `node` ORDER BY name ASC")
        nodes = await db.fetchall()

        if not nodes:
            return {"result": {"nodes": [], "node_id": None, "reset_seconds": seconds, "llms": []}}

        # По умолчанию — нода последнего LLM-запроса (а не первая по алфавиту)
        selected_node_id = node_id if node_id in {n['id'] for n in nodes} else await _llm_node_last_used_get(db, nodes)

        # Порядок отображения — приоритет (position), как настроено в node_llm
        await db.execute(
            """
            SELECT l.id, l.name, l.input_type, l.output_type, l.reasoning_disable,
                   nl.position, nl.rate_limit_at, nl.code_error
            FROM node_llm nl
            JOIN llm l ON l.id = nl.llm_id
            WHERE nl.node_id = %s
            ORDER BY nl.position ASC, l.id ASC
            """,
            (selected_node_id,)
        )
        rows = await db.fetchall()

        # ⚠⚠ Пинги читаются ОДНИМ запросом, и это не про скорость, а про пул.
        #
        # Раньше здесь стоял `{row['id']: await _ping_get(row['id']) for row in rows}`.
        # Каждый `_ping_get` зовёт `setting_get`, а тот берёт СВОЁ соединение из
        # пула — внутри блока `async with mysql_get_db_async() as db`, который
        # своё соединение уже держит. То есть на каждую модель ноды бралось
        # второе соединение, не отпустив первое.
        #
        # Пока запросы идут по одному, это лишь расточительно. Но стоит десяти
        # прийти разом (страница опрашивала ручку раз в секунду) — и каждый
        # держит одно соединение, ожидая второго, которого в пуле уже нет. Все
        # десять ждут друг друга навсегда: классический тупик на исчерпании пула.
        # Ни одной ошибки при этом не возникает, запросы просто висят.
        #
        # Живьём 2026-09-29: `used=10 free=0`, сервер отвечал только там, где не
        # ходил в базу; вход в панель, LLM и соседний проект встали. В MySQL те же
        # соединения видны обычными `Sleep` — база их не держит, держит наш
        # счётчик занятых.
        #
        # ⚠ Правило общее: **внутри блока `async with mysql_get_db_async()`
        # нельзя звать функции, которые берут соединение сами.** Либо читать
        # тем же курсором (как здесь), либо выносить вызов за пределы блока.
        ping_keys = [f'llm_ping_{row["id"]}' for row in rows]
        pings = {}
        if ping_keys:
            marks = ', '.join(['%s'] * len(ping_keys))
            await db.execute(
                f'SELECT `key`, value FROM setting'
                f' WHERE `key` IN ({marks}) AND user_id IS NULL AND node_id IS NULL',
                ping_keys)
            saved = {row['key']: row['value'] for row in (await db.fetchall() or [])}
            pings = {row['id']: _ping_parse(saved.get(f'llm_ping_{row["id"]}'))
                     for row in rows}

        # Счетчики запросов по окнам (журнал llm_request хранится 7 дней).
        # Фильтр по node_id самого запроса (не по текущему списку моделей ноды) -
        # node_llm может делить одну модель между нодами
        await db.execute(
            """
            SELECT llm_id,
                   SUM(created_at >= NOW() - INTERVAL 1 MINUTE)  AS m1,
                   SUM(created_at >= NOW() - INTERVAL 5 MINUTE)  AS m5,
                   SUM(created_at >= NOW() - INTERVAL 10 MINUTE) AS m10,
                   COUNT(*)                                      AS d7,
                   SUM(status_code >= 400)                       AS d7_errors,
                   AVG(CASE WHEN status_code < 400 THEN duration_ms END) AS avg_ms
            FROM llm_request
            WHERE node_id = %s
            GROUP BY llm_id
            """,
            (selected_node_id,)
        )
        counters = {r['llm_id']: r for r in await db.fetchall()}
        for c in counters.values():
            # AVG возвращает Decimal | None — приводим к int для JSON
            c['avg_ms'] = int(c['avg_ms']) if c['avg_ms'] is not None else None

        # Спарклайн: последний час 12 корзинами по 5 минут (0 — самая свежая)
        await db.execute(
            """
            SELECT llm_id,
                   FLOOR(TIMESTAMPDIFF(SECOND, created_at, NOW()) / 300) AS bucket,
                   COUNT(*)                AS qty,
                   SUM(status_code >= 400) AS errors
            FROM llm_request
            WHERE created_at >= NOW() - INTERVAL 60 MINUTE AND node_id = %s
            GROUP BY llm_id, bucket
            """,
            (selected_node_id,)
        )
        spark_rows = await db.fetchall()

    sparklines = {}
    for r in spark_rows:
        bucket = int(r['bucket'])
        if 0 <= bucket <= 11:
            buckets = sparklines.setdefault(r['llm_id'], [{'qty': 0, 'errors': 0} for _ in range(12)])
            buckets[bucket] = {'qty': int(r['qty']), 'errors': int(r['errors'] or 0)}

    # Активная модель — первая по порядку выбора движка:
    # rate_limit_at ASC (NULL раньше любых ошибок), затем position ASC
    active_id = None
    if rows:
        active_id = min(rows, key=lambda r: (
            r['rate_limit_at'] is not None,
            r['rate_limit_at'] or datetime.min,
            r['position'] or 0,
        ))['id']

    return {"result": {
        "nodes": nodes,
        "node_id": selected_node_id,
        "reset_seconds": seconds,
        "llms": [
            {
                'id': row['id'],
                'name': row['name'],
                'provider': ai_llm_provider(row['name']),
                'input_type': row['input_type'],
                'output_type': row['output_type'],
                # Мониторинг помечает такие модели чипсом: размышления влияют и на
                # время ответа, и на расход токенов, а обе эти цифры тут же рядом.
                'reasoning_disable': int(row['reasoning_disable'] or 0),
                'position': row['position'],
                'rate_limit_at': str(row['rate_limit_at']) if row['rate_limit_at'] else None,
                'code_error': row['code_error'],
                'active': row['id'] == active_id,
                'ping': pings.get(row['id']),
                'requests': {
                    'm1': int((counters.get(row['id']) or {}).get('m1') or 0),
                    'm5': int((counters.get(row['id']) or {}).get('m5') or 0),
                    'm10': int((counters.get(row['id']) or {}).get('m10') or 0),
                    'd7': int((counters.get(row['id']) or {}).get('d7') or 0),
                    'd7_errors': int((counters.get(row['id']) or {}).get('d7_errors') or 0),
                    # Среднее время успешного ответа за 7 дней, мс (None — нет данных)
                    'avg_ms': (counters.get(row['id']) or {}).get('avg_ms'),
                    'sparkline': sparklines.get(row['id']) or [],
                },
            }
            for row in rows
        ],
    }}


@router.post("/llm/queue/reorder")
async def llm_queue_reorder(data: dict, user=Depends(AuthChecker([AuthPermission.LLM_UPDATE]))):
    """Сохраняет новый порядок очереди LLM ноды (node_llm.position).
    Ожидает {node_id, positions: [{llm_id, position}, ...]}."""
    reorder_node_id = data.get('node_id')
    positions = data.get('positions') or []

    if not reorder_node_id or not positions:
        raise HTTPException(status_code=400, detail="node_id и positions обязательны")

    async with mysql_get_db_async() as db:
        for item in positions:
            llm_id = item.get('llm_id')
            position = item.get('position')
            if llm_id is None or position is None:
                continue
            await db.execute(
                "UPDATE node_llm SET position = %s WHERE node_id = %s AND llm_id = %s",
                (int(position), int(reorder_node_id), int(llm_id))
            )

    return {"result": "success"}


@router.post("/llm/errors/reset")
async def llm_errors_reset(data: dict, user=Depends(AuthChecker([AuthPermission.LLM_UPDATE]))):
    """Немедленно очищает время и код ошибки моделей (rate_limit_at, code_error):
    все модели возвращаются на свои позиции в очереди. С node_id — только для
    одной ноды, без — для всех."""
    reset_node_id = data.get('node_id')

    async with mysql_get_db_async() as db:
        if reset_node_id:
            await db.execute(
                "UPDATE node_llm SET rate_limit_at = NULL, code_error = NULL WHERE node_id = %s",
                (int(reset_node_id),)
            )
        else:
            await db.execute("UPDATE node_llm SET rate_limit_at = NULL, code_error = NULL")
        reset_qty = db.rowcount

    return {"result": {"reset_qty": reset_qty}}


@router.get("/llm/usage/stats")
async def llm_usage_stats(node_id: int | None = None, node: str = "", days: int = 7,
                          user=Depends(AuthChecker([AuthPermission.LLM_VIEW]))):
    """Статистика использования LLM по пользователям за последние `days` дней
    (клампится до 7 - дальше llm_request не хранит записи, см. миграцию).
    Фильтр по node_id - это node_id самого запроса (llm_request.node_id),
    а не текущий список моделей ноды: node_llm может делить одну модель
    между нодами, так что "модель числится за нодой" не значит "запрос был
    сделан под этой нодой".

    ⚠ **Ноду можно назвать именем** (`node=Dating`), а не только номером.
    Заведено для соседних проектов: DatingAi адресует ноды **по имени** везде, где
    к нам обращается (`POST /agent/create` принимает `node`), и номер ему взять
    негде — читать список нод его служебной учётке не положено, а зашить `2` в
    чужой код значило бы сломать его при первом переносе базы.

    Имя разрешается здесь, где список нод и так под рукой. Незнакомое имя даёт
    пустую статистику, а не отказ: «такой ноды нет» и «за неделю ничего не
    считалось» для читающего одно и то же, а 404 заставил бы страницу отличать их
    без надобности."""
    days = max(1, min(int(days), 7))

    async with mysql_get_db_async() as db:
        # Имя в номер — до основного запроса: дальше фильтр всё равно по
        # `llm_request.node_id`, и вторая ветка SQL под имя означала бы два
        # похожих запроса, которые однажды разойдутся.
        if node and not node_id:
            await db.execute("SELECT id FROM node WHERE name = %s", (str(node),))
            found = await db.fetchone()
            if not found:
                return {"result": {"days": days, "node_id": None, "node": node,
                                   "rows": []}}
            node_id = int(found["id"])

    node_filter = "AND r.node_id = %s" if node_id else ""
    params = (days, node_id) if node_id else (days,)

    async with mysql_get_db_async() as db:
        await db.execute(
            f"""
            SELECT u.id AS user_id, u.username, r.llm_id, l.name AS llm_name,
                   COUNT(*) AS requests, SUM(r.status_code >= 400) AS errors,
                   SUM(r.tokens_input) AS tokens_input, SUM(r.tokens_output) AS tokens_output
            FROM llm_request r
            JOIN llm l ON l.id = r.llm_id
            LEFT JOIN `user` u ON u.id = r.user_id
            WHERE r.created_at >= NOW() - INTERVAL %s DAY
            {node_filter}
            GROUP BY u.id, r.llm_id
            ORDER BY requests DESC
            """,
            params
        )
        rows = await db.fetchall()
        for row in rows:
            row['requests'] = int(row['requests'])
            row['errors'] = int(row['errors'] or 0)
            row['tokens_input'] = int(row['tokens_input'] or 0)
            row['tokens_output'] = int(row['tokens_output'] or 0)

    return {"result": {"days": days, "node_id": node_id, "node": node,
                       "rows": rows}}


@router.delete("/llm/usage/stats")
async def llm_usage_stats_delete(user=Depends(AuthChecker([AuthPermission.LLM_DELETE]))):
    """Очищает всю таблицу llm_request."""
    async with mysql_get_db_async() as db:
        await db.execute("DELETE FROM llm_request")
        if hasattr(db, 'connection') and db.connection:
            await db.connection.commit()
    return {"result": "ok"}


@router.put("/llm/{llm_id}")
async def llm_update(llm_id: int, data: dict, user=Depends(AuthChecker([AuthPermission.LLM_UPDATE]))):
    """Обновляет поля LLM-модели. Обновляются только переданные поля:
    name, input_type, output_type, reasoning_disable, chunk_size (JSON),
    chunk_size_refresh_at."""
    allowed_keys = ("name", "input_type", "output_type", "reasoning_disable",
                    "chunk_size", "chunk_size_refresh_at")
    update_data = {key: data[key] for key in allowed_keys if key in data}
    # Чекбокс приезжает булевым, а колонка — TINYINT(1). Приводим здесь, а не
    # полагаемся на драйвер: строка «false» из чужого клиента дошла бы до базы
    # непустой и легла бы единицей, то есть запретом вместо разрешения.
    if 'reasoning_disable' in update_data:
        update_data['reasoning_disable'] = 1 if _flag_true(update_data['reasoning_disable']) else 0

    if not update_data:
        raise HTTPException(status_code=400, detail="Нет полей для обновления")

    async with mysql_get_db_async() as db:
        # Проверим что LLM существует и получим текущее имя (для логирования провайдера)
        await db.execute("SELECT id, name FROM llm WHERE id = %s", (llm_id,))
        llm = await db.fetchone()
    if not llm:
        raise HTTPException(status_code=404, detail="LLM не найдена")

    async with mysql_get_db_async() as db:
        set_clauses, params = [], []
        for key, value in update_data.items():
            set_clauses.append(f"`{key}` = %s")
            # JSON-кодируем chunk_size, даты оставляем как есть
            if key == 'chunk_size' and value is not None:
                params.append(json.dumps(value, ensure_ascii=False))
            else:
                params.append(value)
        params.append(llm_id)
        await db.execute(
            f"UPDATE llm SET {', '.join(set_clauses)} WHERE id = %s",
            params,
        )

    return {"result": "success"}


@router.post("/llm/ping/{llm_id}")
async def llm_ping(llm_id: int, user=Depends(AuthChecker([AuthPermission.LLM_UPDATE]))):
    """Пингует провайдера модели дешевым запросом GET /models (без токенов),
    результат сохраняется в setting (llm_ping_{id}) как последний пинг."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT id, name FROM llm WHERE id = %s", (llm_id,))
        llm = await db.fetchone()
    if not llm:
        raise HTTPException(status_code=404, detail="LLM не найдена")

    ping = {
        'status': 'error',
        'http_status': None,
        'ms': None,
        'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'error': None,
    }

    provider = ai_llm_provider(llm['name'])
    env_suffix = '_API_URL'

    if provider == 'gx10':
        model_name = llm['name'].split('/')[-1]
        model_size = model_name.split('-')[-1].upper()
        env_suffix = f'_{model_size}{env_suffix}'
        base_url = config_get(provider.upper() + env_suffix) if provider else ''
    else:
        base_url = config_get(provider.upper() + env_suffix) if provider else ''

    api_key = config_get(provider.upper() + '_API_KEY') if provider else ''

    if not provider:
        ping['error'] = 'Провайдер не определен по имени модели'
    elif not base_url:
        ping['error'] = f'В .env нет {provider.upper()}{env_suffix}'
    else:
        url = base_url.rstrip('/') + '/models'
        headers, params = {}, {}

        if provider == 'gemini':
            url = base_url.rstrip('/') + '/v1/models'
            params['key'] = api_key  # Google API авторизуется query-параметром
        elif api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        if provider == 'claude':
            headers['anthropic-version'] = LLM_PING_ANTHROPIC_VERSION

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                response = await client.get(url, headers=headers, params=params)
            ping['ms'] = int((time.monotonic() - started) * 1000)
            ping['http_status'] = str(response.status_code)
            if response.is_success:
                ping['status'] = 'ok'
            else:
                ping['error'] = response.text[:300]
        except Exception as e:
            ping['ms'] = int((time.monotonic() - started) * 1000)
            ping['error'] = f'{type(e).__name__}: {e}'

    await setting_set(f'llm_ping_{llm_id}', json.dumps(ping, ensure_ascii=False), dynamic=1)
    return {"result": ping}


async def _ping_get(llm_id: int) -> dict | None:
    """Последний пинг модели из настроек. Своё соединение, вне блока с базой.

    ⚠ Внутри `async with mysql_get_db_async()` звать НЕЛЬЗЯ: возьмёт второе
    соединение, не отпустив первое, и на нагрузке это кладёт пул (см. комментарий
    в `llm_status`). Там, где пинги нужны сразу для нескольких моделей, читать их
    одним запросом и разбирать `_ping_parse`.
    """
    return _ping_parse(await setting_get(f'llm_ping_{llm_id}'))


def _ping_parse(value) -> dict | None:
    """Разбор сохранённого пинга. Мусор в настройке — это `None`, а не отказ."""
    text = str(value or '')
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


async def _llm_node_last_used_get(db, nodes: list[dict]) -> int:
    """Нода последнего LLM-запроса (llm_request.node_id) — фоллбэк, если node_id не передан.
    Если запросов еще не было, откатываемся на первую ноду по алфавиту."""
    await db.execute(
        "SELECT node_id FROM llm_request WHERE node_id IS NOT NULL ORDER BY created_at DESC LIMIT 1"
    )
    row = await db.fetchone()
    node_ids = {n['id'] for n in nodes}
    if row and row['node_id'] in node_ids:
        return row['node_id']
    return nodes[0]['id']


def _flag_true(value) -> bool:
    """
    Значение флажка из тела запроса — в булево.

    Чекбокс со страницы приезжает настоящим `true`/`false`, но тело ручки — это
    свободный `dict`, и тот же вызов делают из curl и из соседних сервисов.
    Оттуда флаг приходит строкой, и `bool('false')` дал бы истину: модель молча
    получила бы запрет вместо разрешения, а по журналу это выглядело бы как
    «модель перестала думать сама по себе».
    """
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes', 'on', 'да')

    return bool(value)

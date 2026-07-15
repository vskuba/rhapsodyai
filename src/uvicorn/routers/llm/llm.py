import json
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ai.ai_llm import ai_llm_provider
from config.config import config_get
from mysql_.mysql_ import mysql_get_db_async
from setting_.setting_ import setting_get, setting_set
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# Допустимые интервалы сброса ошибок и настройка по умолчанию
LLM_ERROR_RESET_HOURS = (1, 6, 12, 24, 48)
LLM_ERROR_RESET_DEFAULT = 24


@router.get("/llm/list")
async def llm_list(db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.LLM_VIEW]))):
    """Все LLM независимо от пользователя (справочник для админских страниц)."""
    async with db:
        await db.execute("SELECT * FROM `llm` ORDER BY `name` ASC")
        return {"result": await db.fetchall()}


@router.get("/llm/user/list")
async def llm_user_list(db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.LLM_VIEW]))):
    """LLM, привязанные к текущему пользователю, в порядке очереди выбора движка."""
    async with db:
        sql = """
            SELECT l.*
            FROM `llm` l
            JOIN `user_llm` ul ON l.id = ul.llm_id
            WHERE ul.user_id = %s
            ORDER BY ul.rate_limit_at ASC, ul.position ASC
        """
        await db.execute(sql, (user.user_id,))
        return {"result": await db.fetchall()}


@router.get("/llm/status")
async def llm_status(user_id: int | None = None, reset_hours: int | None = None,
                     user=Depends(AuthChecker([AuthPermission.LLM_VIEW]))):
    """Очередь LLM выбранного пользователя в порядке приоритета (position).

    Активная модель — та, которую выберет движок: первая по сортировке
    rate_limit_at ASC, position ASC (ошибки 429/413/402/503 двигают модель
    в конец очереди через rate_limit_at + code_error).

    Ошибки старше интервала reset_hours сбрасываются в БД перед выборкой
    (rate_limit_at и code_error -> NULL) — модель возвращается на свою позицию.
    Переданный reset_hours сохраняется как настройка страницы."""
    if reset_hours is not None and reset_hours not in LLM_ERROR_RESET_HOURS:
        raise HTTPException(status_code=400, detail=f"reset_hours: допустимые значения {LLM_ERROR_RESET_HOURS}")

    if reset_hours is not None:
        await setting_set('llm_error_reset_hours', reset_hours)
        hours = reset_hours
    else:
        stored = str(await setting_get('llm_error_reset_hours'))
        hours = int(stored) if stored and stored.isdigit() else LLM_ERROR_RESET_DEFAULT

    async with mysql_get_db_async() as db:
        # Сброс просроченных ошибок: модель снова участвует в очереди по своей позиции
        await db.execute(
            """
            UPDATE user_llm SET rate_limit_at = NULL, code_error = NULL
            WHERE rate_limit_at IS NOT NULL AND rate_limit_at < NOW() - INTERVAL %s HOUR
            """,
            (hours,)
        )

        await db.execute(
            """
            SELECT DISTINCT u.id, u.username
            FROM `user` u
            JOIN user_llm ul ON ul.user_id = u.id
            ORDER BY u.id
            """
        )
        users = await db.fetchall()

        if not users:
            return {"result": {"users": [], "user_id": None, "reset_hours": hours, "llms": []}}

        # По умолчанию — первый пользователь
        selected_user_id = user_id if user_id in {u['id'] for u in users} else users[0]['id']

        # Порядок отображения — приоритет (position), как настроено в user_llm
        await db.execute(
            """
            SELECT l.id, l.name, ul.position, ul.rate_limit_at, ul.code_error
            FROM user_llm ul
            JOIN llm l ON l.id = ul.llm_id
            WHERE ul.user_id = %s
            ORDER BY ul.position ASC, l.id ASC
            """,
            (selected_user_id,)
        )
        rows = await db.fetchall()

        pings = {row['id']: await _ping_get(row['id']) for row in rows}

        # Счетчики запросов по окнам (журнал llm_request хранится 7 дней)
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
            GROUP BY llm_id
            """
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
            WHERE created_at >= NOW() - INTERVAL 60 MINUTE
            GROUP BY llm_id, bucket
            """
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
        "users": users,
        "user_id": selected_user_id,
        "reset_hours": hours,
        "llms": [
            {
                'id': row['id'],
                'name': row['name'],
                'provider': ai_llm_provider(row['name']),
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
    """Сохраняет новый порядок очереди LLM пользователя (user_llm.position).
    Ожидает {user_id, positions: [{llm_id, position}, ...]}."""
    reorder_user_id = data.get('user_id')
    positions = data.get('positions') or []

    if not reorder_user_id or not positions:
        raise HTTPException(status_code=400, detail="user_id и positions обязательны")

    async with mysql_get_db_async() as db:
        for item in positions:
            llm_id = item.get('llm_id')
            position = item.get('position')
            if llm_id is None or position is None:
                continue
            await db.execute(
                "UPDATE user_llm SET position = %s WHERE user_id = %s AND llm_id = %s",
                (int(position), int(reorder_user_id), int(llm_id))
            )

    return {"result": "success"}


@router.post("/llm/errors/reset")
async def llm_errors_reset(data: dict, user=Depends(AuthChecker([AuthPermission.LLM_UPDATE]))):
    """Немедленно очищает время и код ошибки моделей (rate_limit_at, code_error):
    все модели возвращаются на свои позиции в очереди. С user_id — только для
    одного пользователя, без — для всех."""
    reset_user_id = data.get('user_id')

    async with mysql_get_db_async() as db:
        if reset_user_id:
            await db.execute(
                "UPDATE user_llm SET rate_limit_at = NULL, code_error = NULL WHERE user_id = %s",
                (int(reset_user_id),)
            )
        else:
            await db.execute("UPDATE user_llm SET rate_limit_at = NULL, code_error = NULL")
        reset_qty = db.rowcount

    return {"result": {"reset_qty": reset_qty}}


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
    base_url = config_get(provider.upper() + '_API_URL') if provider else ''
    api_key = config_get(provider.upper() + '_API_KEY') if provider else ''

    if not provider:
        ping['error'] = 'Провайдер не определен по имени модели'
    elif not base_url:
        ping['error'] = f'В .env нет {provider.upper()}_API_URL'
    else:
        url = base_url.rstrip('/') + '/models'
        headers, params = {}, {}

        if provider == 'gemini':
            url = base_url.rstrip('/') + '/v1/models'
            params['key'] = api_key  # Google API авторизуется query-параметром
        elif api_key:
            headers['Authorization'] = f'Bearer {api_key}'

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

    await setting_set(f'llm_ping_{llm_id}', json.dumps(ping, ensure_ascii=False))
    return {"result": ping}


async def _ping_get(llm_id: int) -> dict | None:
    value = str(await setting_get(f'llm_ping_{llm_id}'))
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None

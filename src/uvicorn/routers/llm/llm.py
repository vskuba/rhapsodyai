import json
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ai.ai_llm import ai_llm_provider
from config.config import config_get
from mysql_.mysql_ import mysql_get_db_async
from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter()

# Допустимые интервалы сброса ошибок и настройка по умолчанию
LLM_ERROR_RESET_HOURS = (6, 12, 24, 48)
LLM_ERROR_RESET_DEFAULT = 24


@router.get("/llm/list")
async def llm_list(db=Depends(mysql_get_db_async), user=Depends(AuthChecker([AuthPermission.LLM_VIEW]))):
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

    async with mysql_get_db_async() as db:
        if reset_hours is not None:
            await _global_setting_set(db, 'llm_error_reset_hours', str(reset_hours))
            hours = reset_hours
        else:
            stored = await _global_setting_get(db, 'llm_error_reset_hours')
            hours = int(stored) if stored and stored.isdigit() else LLM_ERROR_RESET_DEFAULT

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

        pings = {row['id']: await _ping_get(db, row['id']) for row in rows}

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
            }
            for row in rows
        ],
    }}


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
            ping['http_status'] = response.status_code
            if response.is_success:
                ping['status'] = 'ok'
            else:
                ping['error'] = response.text[:300]
        except Exception as e:
            ping['ms'] = int((time.monotonic() - started) * 1000)
            ping['error'] = f'{type(e).__name__}: {e}'

    async with mysql_get_db_async() as db:
        await _global_setting_set(db, f'llm_ping_{llm_id}', json.dumps(ping, ensure_ascii=False))
    return {"result": ping}


async def _ping_get(db, llm_id: int) -> dict | None:
    value = await _global_setting_get(db, f'llm_ping_{llm_id}')
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


async def _global_setting_get(db, key: str) -> str | None:
    await db.execute(
        "SELECT value FROM setting WHERE `key` = %s AND user_id IS NULL",
        (key,)
    )
    row = await db.fetchone()
    return row['value'] if row else None


async def _global_setting_set(db, key: str, value: str):
    # Свой upsert: уникальный индекс (key, user_id) не ловит дубли при user_id NULL
    await db.execute(
        "UPDATE setting SET value = %s WHERE `key` = %s AND user_id IS NULL",
        (value, key)
    )
    if not db.rowcount:
        await db.execute(
            "SELECT id FROM setting WHERE `key` = %s AND user_id IS NULL", (key,)
        )
        if not await db.fetchone():
            await db.execute(
                "INSERT INTO setting (`key`, value, user_id) VALUES (%s, %s, NULL)",
                (key, value)
            )

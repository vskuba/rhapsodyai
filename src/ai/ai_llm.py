import base64
import json
from datetime import datetime

import httpx

from config.config import config_get
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

LLM_PROVIDERS = ('openrouter', 'claude', 'ollama', 'gemini', 'groq', 'mistral', 'huggingface', 'cerebras', 'openai',
                 'gx10')

# Журнал запросов держим неделю: этого хватает для метрик от 1 минуты до 7 дней
LLM_REQUEST_TTL_DAYS = 7


def ai_llm_provider(model_name: str) -> str | None:
    for provider in LLM_PROVIDERS:
        if (model_name or '').lower().startswith(provider + '/'):
            return provider
    return None


async def ai_llm_node_get(
        node_id: int | None,
        input_type: str | None = None,
        output_type: str | None = None,
) -> list[dict]:
    """Список LLM ноды (с фоллбэком на catchall-ноду для агентов без своей ноды).

    input_type / output_type — если указаны, возвращает только LLM у которых
    соответствующий тип входит в список через запятую (например, input_type='image'
    вернёт только LLM с 'image' в колонке input_type).
    """
    effective_node_id = node_id or await ai_llm_node_id_default_get()

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT l.* FROM `llm` l
            JOIN `node_llm` nl ON l.id = nl.llm_id
            WHERE nl.node_id = %s
            ORDER BY nl.rate_limit_at ASC, nl.position ASC
            """,
            (effective_node_id,)
        )
        rows = await db.fetchall()

    if input_type:
        rows = [r for r in rows if input_type in (r.get('input_type') or 'text').split(',')]
    if output_type:
        rows = [r for r in rows if output_type in (r.get('output_type') or 'text').split(',')]
    return rows


async def ai_llm_image_generate(
        llm: dict,
        prompt: str,
        size: str = '1024x1024',
        quality: str = 'auto',
        style: str = '',
) -> tuple[bytes, dict]:
    """Генерирует изображение через LLM-провайдера.

    Возвращает (PNG bytes, usage dict) где usage содержит tokens_input/tokens_output если API их вернул.
    Провайдеры: openai, openrouter — OpenAI Images API.
                gx10 — ComfyUI (Flux.1 Dev) на 192.168.1.2:8188.
    """
    import asyncio as _asyncio
    import uuid as _uuid
    import random as _random

    model_name: str = llm.get('name', '')
    provider = ai_llm_provider(model_name)
    if not provider:
        raise ValueError(f'Неизвестный провайдер для LLM: {model_name}')

    if provider == 'gx10':
        img_bytes = await _ai_llm_image_generate_gx10(prompt, size)
        return img_bytes, {}

    base_url = (config_get(provider.upper() + '_API_URL') or '').rstrip('/')
    api_key = config_get(provider.upper() + '_API_KEY') or ''

    # OpenAI images endpoint
    url = base_url + '/images/generations'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    body = {
        'model': model_name[len(provider) + 1:],
        'prompt': prompt,
        'n': 1,
        'size': size,
        'quality': quality,
        'response_format': 'b64_json',
    }
    if style:
        body['style'] = style

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code != 200:
        raise ValueError(f'Image API error {resp.status_code}: {resp.text[:300]}')

    data = resp.json()
    b64 = data['data'][0].get('b64_json') or ''
    if not b64:
        raise ValueError('Image API вернул пустой b64_json')

    usage_raw = data.get('usage') or {}
    usage = {
        'tokens_input': usage_raw.get('input_tokens') or usage_raw.get('prompt_tokens'),
        'tokens_output': usage_raw.get('output_tokens') or usage_raw.get('completion_tokens'),
    }

    return base64.b64decode(b64), usage


def _ai_llm_comfyui_workflow(prompt: str, seed: int, width: int, height: int) -> dict:
    unet  = config_get('GX10_COMFYUI_UNET')  or 'flux1-dev-fp8.safetensors'
    clip1 = config_get('GX10_COMFYUI_CLIP1') or 'clip_l.safetensors'
    clip2 = config_get('GX10_COMFYUI_CLIP2') or 't5xxl_fp8_e4m3fn.safetensors'
    vae   = config_get('GX10_COMFYUI_VAE')   or 'ae.safetensors'
    return {
        "1": {"class_type": "UNETLoader",        "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader",    "inputs": {"clip_name1": clip1, "clip_name2": clip2, "type": "flux"}},
        "3": {"class_type": "VAELoader",         "inputs": {"vae_name": vae}},
        "4": {"class_type": "CLIPTextEncode",    "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "KSampler",          "inputs": {"seed": seed, "steps": 20, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0, "model": ["1", 0], "positive": ["4", 0], "negative": ["4", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode",         "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage",         "inputs": {"filename_prefix": "rhapsody_gen", "images": ["7", 0]}},
    }


async def _ai_llm_image_generate_gx10(prompt: str, size: str = '1024x1024', timeout: float = 300.0) -> bytes:
    import random as _random, uuid as _uuid, asyncio as _asyncio
    parts = size.split('x')
    width  = int(parts[0]) if len(parts) == 2 else 1024
    height = int(parts[1]) if len(parts) == 2 else 1024
    seed = _random.randint(0, 2 ** 32 - 1)
    client_id = str(_uuid.uuid4())
    workflow = _ai_llm_comfyui_workflow(prompt, seed, width, height)

    comfyui_base = (config_get('GX10_COMFYUI_URL') or 'http://192.168.1.2:8188').rstrip('/')

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
        resp = await client.post(f"{comfyui_base}/prompt", json={"prompt": workflow, "client_id": client_id})
        if resp.status_code != 200:
            raise ValueError(f'ComfyUI /prompt error {resp.status_code}: {resp.text[:200]}')
        prompt_id = resp.json()['prompt_id']

        elapsed = 0.0
        poll_interval = 2.0
        while elapsed < timeout:
            hist = await client.get(f"{comfyui_base}/history/{prompt_id}")
            history = hist.json()
            if prompt_id in history:
                outputs = history[prompt_id].get('outputs', {})
                images = outputs.get('8', {}).get('images', [])
                if images:
                    img = images[0]
                    view = await client.get(f"{comfyui_base}/view", params={
                        'filename': img['filename'],
                        'subfolder': img.get('subfolder', ''),
                        'type': img.get('type', 'output'),
                    })
                    return view.content
                break
            await _asyncio.sleep(poll_interval)
            elapsed += poll_interval

    raise TimeoutError(f'ComfyUI генерация не завершилась за {timeout:.0f}с')


def ai_llm_filter_by_type(
        llm_list: list[dict],
        input_type: str | None = None,
        output_type: str | None = None,
) -> list[dict]:
    """Фильтрует список LLM по поддерживаемым типам входа/выхода."""
    result = llm_list
    if input_type:
        result = [r for r in result if input_type in (r.get('input_type') or 'text').split(',')]
    if output_type:
        result = [r for r in result if output_type in (r.get('output_type') or 'text').split(',')]
    return result


async def ai_llm_node_id_default_get() -> int:
    """Нода-фоллбэк (node.is_catchall=1) для агентов без своей ноды (node_id IS NULL)."""
    async with mysql_get_db_async() as db:
        await db.execute("SELECT id FROM `node` WHERE is_catchall = 1 LIMIT 1")
        row = await db.fetchone()
        return row['id'] if row else None


async def ai_llm_parallel_per_agent_max_get(node_id: int | None) -> int:
    """llm_parallel_per_agent_max для ноды (1 если не задано)."""
    effective_node_id = node_id or await ai_llm_node_id_default_get()
    if not effective_node_id:
        return 1
    async with mysql_get_db_async() as db:
        await db.execute("SELECT llm_parallel_per_agent_max FROM `node` WHERE id = %s", (effective_node_id,))
        row = await db.fetchone()
        return int(row['llm_parallel_per_agent_max']) if row and row.get('llm_parallel_per_agent_max') else 1


CHUNK_SIZE_REFRESH_MINUTES = 15
CHUNK_SIZE_TARGET_SECONDS = 10


async def ai_llm_speed_get(llm_id: int | None, target_seconds: int = CHUNK_SIZE_TARGET_SECONDS) -> dict:
    """Returns LLM speed metrics with cached chunk_size.

    chunk_size кешируется в llm.chunk_size (JSON) на CHUNK_SIZE_REFRESH_MINUTES минут.
    Формат: {"10": 15000, "avg_ms": 32000, "chars_per_ms": 1.5, "n": 117}
    Ключ = target_seconds (строка). При истечении кеша или chunk_size_refresh_at=NULL — пересчёт.

    Returns: {'chars_per_ms', 'avg_ms', 'chunk_size', 'n'}
    """
    _default = _ai_llm_speed_default(target_seconds)

    if not llm_id:
        return _default

    # Читаем кеш из llm
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT chunk_size, chunk_size_refresh_at FROM llm WHERE id = %s",
            (llm_id,)
        )
        llm_row = await db.fetchone()

    if llm_row:
        refresh_at = llm_row.get('chunk_size_refresh_at')
        raw = llm_row.get('chunk_size')
        if refresh_at and raw:
            now = datetime.utcnow()
            if isinstance(refresh_at, str):
                try:
                    refresh_at = datetime.fromisoformat(refresh_at)
                except Exception:
                    refresh_at = None
            if refresh_at and now < refresh_at:
                try:
                    cached = json.loads(raw) if isinstance(raw, str) else raw
                    key = str(target_seconds)
                    if key in cached:
                        return {
                            'chars_per_ms': float(cached.get('chars_per_ms') or 1.5),
                            'avg_ms': float(cached.get('avg_ms') or 10000),
                            'chunk_size': int(cached[key]),
                            'n': int(cached.get('n') or 0),
                        }
                except Exception:
                    pass

    # Кеш устарел или отсутствует — пересчитываем
    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT
                SUM(CASE WHEN prompt_length > 0 THEN prompt_length ELSE NULL END) /
                    NULLIF(SUM(CASE WHEN prompt_length > 0 THEN duration_ms ELSE NULL END), 0) AS chars_per_ms,
                AVG(duration_ms) AS avg_ms,
                COUNT(*) AS n
            FROM llm_request
            WHERE llm_id = %s AND status_code = 200 AND duration_ms > 0
              AND created_at >= NOW() - INTERVAL 7 DAY
            """,
            (llm_id,)
        )
        row = await db.fetchone()

    avg_ms = float((row or {}).get('avg_ms') or 10000)
    n = int((row or {}).get('n') or 0)
    chars_per_ms_raw = (row or {}).get('chars_per_ms')
    chars_per_ms = float(chars_per_ms_raw) if chars_per_ms_raw else 15000.0 / max(avg_ms, 1)

    chunk_size = max(5000, int(chars_per_ms * target_seconds * 1000 * 0.7))

    # Сохраняем в кеш: мерджим с существующими ключами других target_seconds
    try:
        existing: dict = {}
        if llm_row and llm_row.get('chunk_size'):
            try:
                existing = json.loads(llm_row['chunk_size']) if isinstance(llm_row['chunk_size'], str) else dict(
                    llm_row['chunk_size'])
            except Exception:
                pass
        existing.update({
            str(target_seconds): chunk_size,
            'avg_ms': avg_ms,
            'chars_per_ms': chars_per_ms,
            'n': n,
        })
        async with mysql_get_db_async() as db:
            await db.execute(
                "UPDATE llm SET chunk_size = %s, chunk_size_refresh_at = DATE_ADD(NOW(), INTERVAL %s MINUTE) WHERE id = %s",
                (json.dumps(existing), CHUNK_SIZE_REFRESH_MINUTES, llm_id)
            )
            await db.connection.commit()
    except Exception as e:
        logger_info(f"⚠️ Не удалось обновить chunk_size кеш для llm_id={llm_id}: {e}")

    logger_info(
        f'📐 chunk_size пересчитан: llm_id={llm_id}, target={target_seconds}s → {chunk_size} симв. (chars/ms={chars_per_ms:.3f}, avg_ms={avg_ms:.0f})')
    return {'chars_per_ms': chars_per_ms, 'avg_ms': avg_ms, 'chunk_size': chunk_size, 'n': n}


def _ai_llm_speed_default(target_seconds: int = CHUNK_SIZE_TARGET_SECONDS) -> dict:
    chunk_size = max(5000, int(1.5 * target_seconds * 1000 * 0.7))
    return {'chars_per_ms': 1.5, 'avg_ms': 10000.0, 'chunk_size': chunk_size, 'n': 0}


async def ai_llm_request_log(
        llm_id: int | None,
        user_id: int | None,
        node_id: int | None = None,
        status_code: int = 200, error: str | None = None,
        duration_ms: int | None = None,
        prompt_length: int | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
):
    """Пишет запрос к LLM в журнал llm_request (метрики страницы /admin/llm).

    node_id — нода, под которой реально шел запрос: node_llm может делить одну
    модель между несколькими нодами, поэтому фильтр статистики по ноде нужно
    строить по факту запроса, а не по текущему списку моделей ноды.

    Заодно оппортунистически удаляет записи старше LLM_REQUEST_TTL_DAYS
    (порциями, чтобы не блокировать таблицу). Сбой журнала не должен
    ломать сам запрос — только warning в лог."""
    if not llm_id:
        return

    try:
        async with mysql_get_db_async() as db:
            await db.execute(
                "INSERT INTO llm_request (llm_id, user_id, node_id, status_code, duration_ms, prompt_length, error, tokens_input, tokens_output) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (llm_id, user_id or None, node_id or None, status_code, duration_ms,
                 prompt_length or None, (error or None) and str(error)[:255],
                 tokens_input or None, tokens_output or None)
            )
            await db.execute(
                "DELETE FROM llm_request WHERE created_at < NOW() - INTERVAL %s DAY LIMIT 500",
                (LLM_REQUEST_TTL_DAYS,)
            )
    except Exception as e:
        logger_info(f"⚠️ Не удалось записать llm_request (llm_id={llm_id}): {e}")

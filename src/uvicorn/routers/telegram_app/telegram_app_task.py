"""Вопросы и ответы задач мини-приложения Telegram.

Эндпоинты чтения вопросов задачи (GET) и отправки ответа (POST).
Геймим по telegram_owner_id через _require_telegram_owner.
Парсим action для автовопроса (goals_split / goals_drop / goals_keep / goals_replan),
разбираем indexes как строку JSON или массив, применяем scope.
Опираемся на существующие task_question.py + task_goal_scope.py.
"""
import json

from fastapi import APIRouter, Request, HTTPException

from datetime_.datetime_ import datetime_utc_now
from mysql_.mysql_ import mysql_get_db_async
from src.project.task.task_goal_scope import (
    task_goal_scope_drop,
    task_goal_scope_split,
)
from src.project.task.task_metadata import task_metadata_parse, task_metadata_row_apply, task_metadata_update
from src.project.task.task_question import (
    TASK_QUESTION_ACTION_DROP,
    TASK_QUESTION_ACTION_PLAN,
    TASK_QUESTION_ACTION_RETRY,
    TASK_QUESTION_ACTION_SPLIT,
    TASK_QUESTION_ANSWER_MAX,
    TASK_QUESTION_DECISIONS_MAX,
    TASK_QUESTION_KEY_DECISIONS,
    TASK_QUESTION_KEY_QUEUE,
    TASK_QUESTION_KEY as TASK_QUESTION_KEY_Q,
    task_question_auto,
    task_question_decisions,
    task_question_get,
)
from src.uvicorn.routers.telegram_app.telegram_app_common import _require_telegram_owner

router = APIRouter()


def _now() -> str:
    """UTC метка времени решения."""
    return datetime_utc_now().strftime('%Y-%m-%d %H:%M:%S')


# ===================================================================
# GET /telegram-app/task/{id}/question
# ===================================================================

@router.get('/telegram-app/task/{task_id}/question')
async def telegram_app_task_question_get(request: Request, task_id: int):
    """Вернуть вопрос задачи: одиночный от роли, пачку разведки, автовопрос и решения."""
    _require_telegram_owner(request)

    subtask = await _get_subtask(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='Task not found')

    # Одиночный вопрос роли.
    role_question = task_question_get(subtask)

    # Пачка вопросов разведки с черновиками ответов.
    batch = [q for q in subtask.get('_batch') or [] if isinstance(q, dict)]

    # Решения, уже принятые по задаче.
    decisions = task_question_decisions(subtask)

    # Автовопрос конвейера — если задача встала, но агент не спросил.
    attempt_list = _read_attempts(subtask)
    auto_q = task_question_auto(subtask, attempt_list)

    return {
        'result': {
            'id':             subtask['id'],
            'title':          subtask.get('title'),
            'status':         subtask.get('status'),
            'pipeline_state': subtask.get('pipeline_state'),
            'role_question':  role_question,
            'batch':          batch,
            'decisions':      decisions,
            'auto_question':  auto_q,
        },
    }


# ===================================================================
# POST /telegram-app/task/{id}/question/answer
# ===================================================================

@router.post('/telegram-app/task/{task_id}/question/answer')
async def telegram_app_task_question_answer(request: Request, task_id: int, data: dict):
    """Ответить на вопрос задачи: одиночный, пачку или действие над охватом."""
    _require_telegram_owner(request)

    action = str(data.get('action') or '').strip()

    # --- Автодействие над целями ---
    if action == TASK_QUESTION_ACTION_SPLIT:
        return await _handle_split(task_id, data)
    if action == TASK_QUESTION_ACTION_DROP:
        return await _handle_drop(task_id, data)
    if action == TASK_QUESTION_ACTION_RETRY:
        return await _handle_retry(task_id)
    if action == TASK_QUESTION_ACTION_PLAN:
        return await _handle_replan(task_id)

    # Есть batch_index → пачка разведки.
    if 'batch_index' in data:
        return await _handle_batch(task_id, data)

    # Иначе — одиночный ответ.
    return await _handle_single(task_id, data)


# ===================================================================
# Helpers — чтение данных
# ===================================================================

async def _get_subtask(task_id: int) -> dict | None:
    """Прочитать задачу из БД + разобрать metadata (включая _batch)."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, parent_id, title, status, pipeline_state, pipeline_plan, "
            "       pipeline_error, goals, metadata, project_id, task_type_id "
            "FROM project_task WHERE id = %s",
            (task_id,),
        )
        row = await db.fetchone()
    if not row:
        return None
    subtask = task_metadata_row_apply(row)
    meta = subtask.get('metadata') or {}
    queue = meta.get(TASK_QUESTION_KEY_QUEUE) or []
    if not isinstance(queue, list):
        queue = []
    subtask['_batch'] = queue
    return subtask


async def _get_task_for_scope(task_id: int) -> dict | None:
    """Задача с целями — нужно для goal scope операций."""
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT id, parent_id, goals, metadata FROM project_task WHERE id = %s",
            (task_id,),
        )
        row = await db.fetchone()
    if not row:
        return None
    subtask = task_metadata_row_apply(row)
    meta = subtask.get('metadata') or {}
    queue = meta.get(TASK_QUESTION_KEY_QUEUE) or []
    if not isinstance(queue, list):
        queue = []
    subtask['_batch'] = queue
    return subtask


def _read_attempts(subtask: dict) -> list:
    """Извлечь журнал попыток (attempts). Формат зависит от записи — пытаемся оба варианта."""
    err = subtask.get('pipeline_error') or ''
    if isinstance(err, list):
        return [a for a in err if isinstance(a, dict)]
    try:
        parsed = json.loads(str(err))
        if isinstance(parsed, list):
            return [a for a in parsed if isinstance(a, dict)]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


# ===================================================================
# Single answer — ответить на одиночный вопрос роли или автовопрос
# ===================================================================

async def _handle_single(task_id: int, data: dict) -> dict:
    answers_raw = data.get('answers') or data.get('options') or []
    note = str(data.get('note') or data.get('text') or '').strip()[:TASK_QUESTION_ANSWER_MAX]

    subtask = await _get_subtask(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='Task not found')

    answers = _normalize_answers(answers_raw)
    labels = _build_labels(subtask, answers)
    text = '; '.join([*labels, note]) if note else labels

    if not text:
        return {'error': 'Решение пустое — проверьте ответы'}

    question = task_question_get(subtask)

    decision = {
        'at':   _now(),
        'question': str(question.get('text') or '').strip(),
        'answer': text,
        'by':   '',
    }
    decisions = [*task_question_decisions(subtask), decision][-TASK_QUESTION_DECISIONS_MAX:]
    await task_metadata_update(task_id, {
        TASK_QUESTION_KEY_Q: None,
        TASK_QUESTION_KEY_DECISIONS: decisions,
    })

    return {'result': {'decision': decision}}


# ===================================================================
# Batch answer — ответить на один вопрос пачки разведки
# ===================================================================

async def _handle_batch(task_id: int, data: dict) -> dict:
    index = int(data.get('batch_index', -1))
    answers_raw = data.get('answers') or []
    note = str(data.get('note') or '').strip()[:TASK_QUESTION_ANSWER_MAX]

    subtask = await _get_subtask(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='Task not found')

    answers = _normalize_answers(answers_raw)

    result = await _batch_answer(task_id, subtask, index, answers, note)
    if not result:
        return {'error': 'Вопрос с таким индексом не найден'}

    return {
        'result': {
            'left':     result.get('left', -1),
            'done':     bool(result.get('done')),
            'decisions': result.get('decisions', []),
        },
    }


async def _batch_answer(subtask_id: int, subtask: dict, index: int,
                        answers: list, note: str) -> dict:
    """Ответ на один вопрос пачки — черновиком. Отвечены все — пачка в решения."""
    batch = subtask.get('_batch') or []
    if not batch or not 0 <= int(index) < len(batch):
        return {}

    question = batch[int(index)]
    labels = _batch_answer_labels(question, answers)
    free = note.strip()[:TASK_QUESTION_ANSWER_MAX]
    text = '; '.join([*labels, free] if free else labels)
    if not text:
        return {}

    batch[int(index)] = {**question, 'answer': {
        'text': text,
        'keys': [str(a) for a in answers],
        'note': free,
        'at': _now(),
    }}

    left = sum(1 for q in batch if not (q.get('answer') or {}).get('text'))

    if left:
        await task_metadata_update(int(subtask_id), {TASK_QUESTION_KEY_QUEUE: batch})
        return {'left': left, 'done': False, 'decisions': []}

    # Пачка закрылась — черновики становятся решениями разом.
    fresh = [{'at': q['answer']['at'],
              'question': str(q.get('text') or '').strip(),
              'answer': q['answer']['text']}
             for q in batch]
    decisions = [*task_question_decisions(subtask), *fresh][-TASK_QUESTION_DECISIONS_MAX:]
    await task_metadata_update(int(subtask_id), {
        TASK_QUESTION_KEY_QUEUE: None,
        TASK_QUESTION_KEY_DECISIONS: decisions,
    })

    return {'left': 0, 'done': True, 'decisions': fresh}


def _batch_answer_labels(question: dict, answers: list) -> list:
    """Ключи выбранных вариантов → их подписи для черновика пачки."""
    if not answers:
        return []
    by_key = {str(o.get('key')): str(o.get('label') or '')
              for o in question.get('options') or []}
    return [by_key[key] for key in (str(a) for a in answers) if by_key.get(key)]


# ===================================================================
# Auto-actions — раздробить / сократить / перезапустить / спланировать
# ===================================================================

async def _handle_split(task_id: int, data: dict) -> dict:
    subtask = await _get_task_for_scope(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='Task not found')

    indexes = _parse_indexes(data.get('indexes'))
    result = await task_goal_scope_split(subtask, indexes)
    if not result.get('ok'):
        return {'error': result.get('error', 'Не удалось раздробить')}

    # Записать решение в decisions.
    decision = {
        'at': _now(),
        'question': 'Раздробить цели',
        'answer': _ACTION_LABELS[TASK_QUESTION_ACTION_SPLIT],
        'by': '',
    }
    decisions = [*task_question_decisions(subtask), decision][-TASK_QUESTION_DECISIONS_MAX:]
    await task_metadata_update(task_id, {
        TASK_QUESTION_KEY_DECISIONS: decisions,
    })

    return {'result': result}


async def _handle_drop(task_id: int, data: dict) -> dict:
    subtask = await _get_task_for_scope(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='Task not found')

    indexes = _parse_indexes(data.get('indexes'))
    result = await task_goal_scope_drop(subtask, indexes)
    if not result.get('ok'):
        return {'error': result.get('error', 'Не удалось сократить')}

    decision = {
        'at': _now(),
        'question': 'Сократить цели',
        'answer': _ACTION_LABELS[TASK_QUESTION_ACTION_DROP],
        'by': '',
    }
    decisions = [*task_question_decisions(subtask), decision][-TASK_QUESTION_DECISIONS_MAX:]
    await task_metadata_update(task_id, {
        TASK_QUESTION_KEY_DECISIONS: decisions,
    })

    return {'result': result}


async def _handle_retry(task_id: int) -> dict:
    """Перезапустить как есть."""
    subtask = await _get_subtask(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='Task not found')

    decision = {
        'at': _now(),
        'question': 'Перезапустить как есть',
        'answer': _ACTION_LABELS[TASK_QUESTION_ACTION_RETRY],
        'by': '',
    }
    decisions = [*task_question_decisions(subtask), decision][-TASK_QUESTION_DECISIONS_MAX:]
    await task_metadata_update(task_id, {
        TASK_QUESTION_KEY_DECISIONS: decisions,
    })

    return {'result': {'ok': True}}


async def _handle_replan(task_id: int) -> dict:
    """Вернуть задачу менеджеру на разбиение."""
    subtask = await _get_subtask(task_id)
    if not subtask:
        raise HTTPException(status_code=404, detail='Task not found')

    decision = {
        'at': _now(),
        'question': 'Отправить на планирование',
        'answer': _ACTION_LABELS[TASK_QUESTION_ACTION_PLAN],
        'by': '',
    }
    decisions = [*task_question_decisions(subtask), decision][-TASK_QUESTION_DECISIONS_MAX:]
    await task_metadata_update(task_id, {
        TASK_QUESTION_KEY_DECISIONS: decisions,
        'replanned': True,
    })

    return {'result': {'ok': True}}


# ===================================================================
# Utility helpers
# ===================================================================

def _parse_indexes(raw) -> list:
    """Парсим indexes: список чисел или JSON-строка '[0,2]'."""
    if isinstance(raw, list):
        return [int(i) for i in raw if str(i).lstrip('-').isdigit()]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [int(i) for i in parsed if str(i).lstrip('-').isdigit()]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _normalize_answers(raw) -> list:
    """Преобразуем answers [] -> список строк-ключей."""
    result = []
    for item in (raw or []):
        if isinstance(item, dict):
            result.append(str(item.get('key', '')))
        elif isinstance(item, (str, int)):
            result.append(str(item))
    return result


def _build_labels(subtask: dict, answers: list) -> list:
    """Для одиночного ответа: ключи вариантов -> их подписи."""
    pending = task_question_get(subtask) or {}
    by_key = {str(o.get('key')): str(o.get('label') or '')
              for o in pending.get('options') or []}
    return [by_key[key] for key in (str(a) for a in answers) if by_key.get(key)]


_ACTION_LABELS = {
    TASK_QUESTION_ACTION_SPLIT: 'Раздробить: цель(ли) вынесены в новую подзадачу',
    TASK_QUESTION_ACTION_DROP: 'Сократить: цель(ли) убраны из охвата',
    TASK_QUESTION_ACTION_RETRY: 'Перезапустить как есть',
    TASK_QUESTION_ACTION_PLAN: 'Отправить на планирование: разложить на подзадачи',
}

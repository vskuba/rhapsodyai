"""Ручки страницы «Настройки → Cronicle»: расписание, включатель, прогоны.

Планировщик ходит к нам (`POST /cronjob`), а эта страница — обратная сторона:
посмотреть, что запланировано, выключить событие на время и увидеть, что за
сегодня отработало удачно. Раньше для этого открывали панель самого Cronicle —
другой порт, другой вход и полный доступ ко всему расписанию заодно.

Сам разговор с Cronicle — в слое (`py_modules/cronicle_/cronicle_api.py`): он
одинаков у всех установок. Здесь — права, пояс показа и сборка ответа под эту
страницу.

⚠ Ключа может не быть, и это **не ошибка сервера**: установка живёт без ключа
ровно до тех пор, пока его не завели в панели Cronicle. Поэтому список отдаётся
с полем `ready: false` и текстом, что сделать, — а не пятисоткой, которая
уедет в журнал ошибок и будет там мозолить глаза каждую минуту опроса.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cronicle_.cronicle_api import (cronicle_api_enable, cronicle_api_history,
                                    cronicle_api_key, cronicle_api_last_ok_today,
                                    cronicle_api_schedule)
from panel_.panel_setting_api import panel_setting_timezone_hours

from src.auth.auth import AuthChecker
from src.auth.auth_permission import AuthPermission

router = APIRouter(prefix='/api/cronicle', tags=['cronicle'])


class CronicleEnableIn(BaseModel):
    """Тело переключателя события."""
    enabled: bool


@router.get('/event', include_in_schema=False)
async def cronicle_event_list(user=Depends(AuthChecker([AuthPermission.CRONICLE_VIEW]))):
    """Расписание с состоянием включателя и последним удачным прогоном за сегодня.

    Returns:
        dict: `result` — `ready` (есть ли ключ), `reason` (чего не хватает),
        `events` — список событий: `id`, `title`, `enabled`, `timing`,
        `category`, `target`, `last_ok` (прогон или None).
    """
    if not cronicle_api_key():
        return {'result': {'ready': False, 'events': [],
                           'reason': 'Ключ Cronicle не задан. Заведите его в панели '
                                     'Cronicle (Admin → API Keys), отметьте '
                                     '«Edit Events» — без неё переключатель будет '
                                     'отказывать, — и положите ключ в .env как '
                                     'CRONICLE_API_KEY.'}}

    try:
        events = await cronicle_api_schedule()
        history = await cronicle_api_history()
    except RuntimeError as err:
        # Планировщик лежит или ключ не тот — это состояние страницы, а не сбой
        # нашего сервера: показываем причину словами, 502 ничего не объяснит.
        return {'result': {'ready': False, 'events': [], 'reason': str(err)}}

    offset = await panel_setting_timezone_hours() * 60
    last_ok = cronicle_api_last_ok_today(history, offset_minutes=offset)

    return {'result': {'ready': True, 'reason': '',
                       'events': [_cronicle_event_card(one, last_ok) for one in events]}}


@router.put('/event/{event_id}/enabled', include_in_schema=False)
async def cronicle_event_enable(event_id: str, body: CronicleEnableIn,
                                user=Depends(AuthChecker([AuthPermission.CRONICLE_UPDATE]))):
    """Включить или выключить событие планировщика.

    ⚠ Это пауза, а не удаление: событие остаётся в расписании. Идущий сейчас
    прогон выключатель не останавливает — у Cronicle это другая операция.
    """
    try:
        await cronicle_api_enable(event_id, body.enabled)
    except RuntimeError as err:
        raise HTTPException(status_code=502, detail=str(err))

    return {'result': {'id': event_id, 'enabled': body.enabled}}


def _cronicle_event_card(event: dict, last_ok: dict) -> dict:
    """Событие Cronicle → то, что читает страница.

    Из полной записи берём семь полей: остальное — внутренности планировщика
    (цепочки, веб-хуки, ограничения параллельности), и на странице обзора они
    только мешают. Кому нужно всё — тот идёт в саму панель Cronicle.

    ⚠⚠ `params` сюда не попадает **намеренно**, и это не экономия полей. У
    событий-веб-хуков там лежат заголовки запроса целиком, вместе с чужим
    `X-API-Key`: отдай мы их странице — ключи соседних установок уехали бы в
    браузер каждому, у кого есть `cronicle:view`.

    `notes` — наоборот, самое ценное поле: по именам вроде `dating_chat` или
    `planning_fallback` не догадаться, что событие делает, и за ответом
    приходилось идти в чужую панель.
    """
    run = last_ok.get(str(event.get('id') or ''))
    return {
        'id': event.get('id'),
        'title': event.get('title') or '—',
        'enabled': bool(event.get('enabled')),
        'category': event.get('category') or '',
        'timing': event.get('timing') or {},
        'target': event.get('target') or '',
        'notes': str(event.get('notes') or '').strip(),
        'last_ok': {
            'time_start': run.get('time_start'),
            'elapsed': run.get('elapsed'),
            'description': run.get('description') or '',
        } if run else None,
    }

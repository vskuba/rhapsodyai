"""
Добавочные карточки роли Harness: «плюс» рядом с выключателем и крестик на карточке.

Карточки одной роли не равны между собой. Первая — **базовая**: ею распоряжается
выключатель (`team_dsh_switch`), и она же отвечает на вопрос «работает ли роль». Вторая
и следующие — **добавочные**: роль берёт больше кругов сразу, и заводят их отдельно,
кнопкой «+». Убирают добавочную крестиком на самой карточке — базовую крестик не
показывает, потому что убрать её значит выключить роль, а на это есть выключатель.

Своей логики здесь нет: обе ручки — перевод нажатия в вызов пульта (`/roles/add`,
`/roles/drop`), а решает всё сторона оболочки. Отдельным файлом от `team_dsh.py`, потому
что там выключатель и сбор состояния — другая ответственность и другой размер ответа.
"""
from src.project.team.team_dsh import team_dsh_owner_url, team_dsh_path_norm
from src.project.team.team_dsh_panel import (TeamDshError, team_dsh_panel_index,
                                             team_dsh_panel_request)


async def team_dsh_card_add(project: str, role: str) -> dict:
    """
    Завести роли ещё одну карточку — с первым свободным номером.

    Returns: `{'project', 'role', 'card_id', 'index', 'cards'}`, где `cards` — все живые
    карточки роли после добавления, по порядку номеров.

    Номер выбирает пульт, а не страница: между показом блока и нажатием кнопки карточки
    могли завестись и уйти в архив, и присланный номер уже ничего бы не значил.

    Raises: `TeamDshError` — пульт не найден, не ответил либо отказал (422 — не тот
    проект или роль, 502 — та сторона).
    """
    project, role = _asked(project, role)

    url = await team_dsh_owner_url(project)
    result = await team_dsh_panel_request(url, 'POST', '/roles/add',
                                          {'project': project, 'role': role})

    return _result(project, role, result)


async def team_dsh_card_drop(project: str, role: str, card_id: str) -> dict:
    """
    Убрать названную добавочную карточку роли: пульт отправит её в архив.

    Returns: `{'project', 'role', 'card_id', 'index', 'cards'}` — `cards` те, что
    остались живыми.

    Карточку называем по `card_id`, а не по номеру: перезавод поколения меняет id
    (`…-2` → `…-2-g2`), а страница показывает состояние прошлой сверки. Пульт разберёт
    присланный id целиком — проект, роль, номер, поколение, — так что промах кнопкой по
    чужой карточке станет отказом, а не архивом не той сессии.

    Raises: `TeamDshError`; 422 — карточка не названа, не та роль или базовый номер
    (базовую не убирают, а выключают), 502 — пульт не ответил.
    """
    project, role = _asked(project, role)
    card_id = str(card_id or '').strip()
    if not card_id:
        raise TeamDshError('card_id обязателен: карточку убирают по имени, а не по номеру', 422)

    url = await team_dsh_owner_url(project)
    result = await team_dsh_panel_request(url, 'POST', '/roles/drop',
                                          {'project': project, 'role': role,
                                           'card_id': card_id})

    return _result(project, role, result, card_id)


def _asked(project: str, role: str) -> tuple:
    """Проект и роль в сравнимом виде. Пустые — 422: пультов несколько, роли одноимённые."""
    project = team_dsh_path_norm(project)
    role = str(role or '').strip()
    if not project:
        raise TeamDshError('project обязателен: пультов несколько, роли у них одноимённые', 422)
    if not role:
        raise TeamDshError('role обязателен', 422)

    return project, role


def _result(project: str, role: str, result: dict, card_id: str = '') -> dict:
    """Ответ пульта в вид страницы. Своё имя карточки — запасное на случай пустого ответа."""
    return {
        'project': project,
        'role': str(result.get('role') or role),
        'card_id': str(result.get('card_id') or card_id),
        'index': team_dsh_panel_index(result.get('index')),
        'cards': [str(item) for item in (result.get('cards') or [])],
        'changed': bool(result.get('changed')),
    }

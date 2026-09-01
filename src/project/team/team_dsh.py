"""
Включатель ролей DeepSeek Harness: сторона страницы команды.

Что включается. Роль в Harness — это карточка сессии на его хосте, и она же
единственное состояние: живая карточка значит «роль работает», карточка в архиве —
«не работает». Отдельного флага нет ни здесь, ни там намеренно: два состояния на одну
сущность разошлись бы на первом же перезапуске сервиса.

Пульт (`ds-shell --service`) обслуживает несколько проектов сразу, но пульт на странице
может быть не один — на разных машинах, — поэтому состояние собираем со всех разом и
раскладываем **по корню проекта**. Имена ролей у всех проектов одинаковые, так что без
этого ключа кнопки встали бы на чужие карточки. Устройство одного пульта — в
`team_dsh_panel.py`, подключение проектов к нему — в `team_dsh_project.py`.

Состояние и переключение отвечают на отказ по-разному. `team_dsh_state` возвращает
причину текстом (`problem`) — она зовётся при каждом обновлении страницы, и ронять её
из-за выключенного ноутбука незачем; молчание одного пульта не отменяет кнопок у
остальных. `team_dsh_switch` бросает: за ним стоит нажатая кнопка, и молчаливое «ничего
не произошло» человек прочтёт как сделанное.
"""
import asyncio

from logging_.logging_ import logger_info
from src.project.team.team_dsh_panel import (TEAM_DSH_PANEL_HARNESS_URL, TeamDshError,
                                             team_dsh_panel_projects, team_dsh_panel_request,
                                             team_dsh_panel_roles, team_dsh_panel_sessions,
                                             team_dsh_panel_urls)


async def team_dsh_state() -> dict:
    """
    Состояние ролей Harness по всем пультам сразу.

    Returns: `{'harness_url': адрес, 'alive': bool, 'problem': '', 'panels': [...],
    'projects': {корень проекта: {'url', 'alive', 'harness_url', 'label', 'home',
    'roles', 'sessions'}}}`, где `roles` — словарь `роль → {title, enabled, cards}`, а
    `sessions` — словарь `сессия реестра → {card_id, role, index}`.

    Ключ проектов — корень каталога: другого общего признака у страницы и пульта нет,
    номера проекта пульт не знает. Роли отдаём словарём, а не списком: страница ищет в
    нём по имени роли, а порядок задаёт свой — тот, в котором стоят карточки блока.

    `sessions` нужен карточкам поимённо: по нему страница узнаёт, какая карточка блока
    базовая (номер 1 — на ней выключатель роли), а какая добавочная (номер 2 и дальше —
    на ней крестик), и какой `card_id` называть при удалении.

    `panels` — сами пульты: адрес, жив ли, причина молчания и его домашний проект. Нужен
    он блокам, чьего проекта в `projects` нет вовсе: там стоит кнопка «подключить», и без
    списка пультов страница не отличила бы «проект не подключён» от «пульта нет совсем».

    `alive` наверху — про сам Harness: хост у всех проектов и всех ролей один, и живым
    его считаем, если так сказал хоть кто-то из пультов.

    Причину неудачи возвращаем текстом. Пульт живёт на ноутбуке разработчика, и его
    отсутствие — обычное состояние установки, а не поломка страницы команды.
    """
    projects, panels, problems, harness_url, alive = {}, [], [], '', False

    for url, state, problem in await team_dsh_panels():
        served = team_dsh_panel_projects(state)
        if not problem and not served:
            problem = (f'пульт {url} не назвал проектов — кнопки поставить некуда '
                       f'(старый ds-shell? перезапустите сервис)')

        harness = str(state.get('harness_url') or TEAM_DSH_PANEL_HARNESS_URL)
        harness_url = harness_url or harness
        alive = alive or bool(state.get('alive'))
        panels.append({'url': url,
                       'alive': bool(state.get('alive')),
                       'home': team_dsh_path_norm(state.get('project')),
                       'problem': problem})
        if problem:
            problems.append(problem)
            continue

        for item in served:
            projects[team_dsh_path_norm(item['project'])] = {
                'url': url,
                'alive': bool(state.get('alive')),
                'harness_url': harness,
                'label': item['label'],
                'home': item['home'],
                'roles': team_dsh_panel_roles(item['roles']),
                'sessions': team_dsh_panel_sessions(item['attached'])}

    return {'harness_url': harness_url or TEAM_DSH_PANEL_HARNESS_URL,
            'alive': alive,
            'panels': panels,
            'projects': projects,
            'problem': '; '.join(problems)}


async def team_dsh_switch(project: str, role: str, enabled: bool) -> dict:
    """
    Включить или выключить роль проекта: завести карточку в Harness либо в архив.

    Returns: `{'project', 'role', 'enabled', 'changed', 'cards', 'card_id'}`. `changed`
    ложно, когда роль уже была в нужном состоянии, — обе ручки пульта идемпотентны, и
    повтор нажатия ничего не ломает.

    Пульт ищет `team_dsh_owner_url` — по корню проекта, а не по адресу из запроса. Корень
    уходит и в тело: проектов у пульта несколько, а роли у них одноимённые, и без него
    пульт взялся бы за свой домашний.

    Raises: `TeamDshError` — пульт не найден, не ответил либо отказал; `status` уже
    пригоден для ответа наружу (422 — не тот проект или роль, 502 — та сторона).
    """
    project = team_dsh_path_norm(project)
    role = str(role or '').strip()
    if not project:
        raise TeamDshError('project обязателен: пультов несколько, роли у них одноимённые', 422)
    if not role:
        raise TeamDshError('role обязателен', 422)

    url = await team_dsh_owner_url(project)
    result = await team_dsh_panel_request(url, 'POST', '/roles/on' if enabled else '/roles/off',
                                          {'project': project, 'role': role})

    return {
        'project': project,
        'role': str(result.get('role') or role),
        'enabled': enabled,
        'changed': bool(result.get('changed')),
        'cards': [str(item) for item in (result.get('cards') or [])],
        'card_id': str(result.get('card_id') or ''),
    }


async def team_dsh_owner_url(project: str) -> str:
    """
    Адрес пульта, который обслуживает этот проект. Не нашли — `TeamDshError`.

    Адрес пульта от страницы не принимаем нигде и никогда: он в запросе означал бы, что
    браузер выбирает, к кому сервер сходит в сети. Поэтому владельца ищем сами — по
    корню проекта среди тех пультов, что ответили.

    Ищем по всему списку проектов пульта, а не по его домашнему: домашний — лишь тот, в
    чьём каталоге сервис подняли, а обслуживает он и подключённые кнопкой.

    Raises: `TeamDshError` (502 — нужный пульт мог оказаться среди молчащих, 422 — все
    ответили, и проекта среди них нет).
    """
    silent = []
    for url, state, problem in await team_dsh_panels():
        if problem:
            silent.append(problem)
            continue
        for item in team_dsh_panel_projects(state):
            if team_dsh_path_norm(item['project']) == project:
                return url

    # Молчащий пульт мог быть как раз нужным, поэтому вина на той стороне (502). Все
    # ответили, а проекта среди них нет — значит его к пульту не подключали (422).
    if silent:
        raise TeamDshError(f'пульт проекта {project} не отвечает: ' + '; '.join(silent))

    raise TeamDshError(f'проект {project} не подключён ни к одному пульту: '
                       f'подключите его кнопкой в шапке блока', 422)


def team_dsh_path_norm(path) -> str:
    """Корень проекта в сравнимом виде: без пробелов по краям и хвостовых слэшей."""
    return str(path or '').strip().rstrip('/')


async def team_dsh_panels() -> list:
    """
    Опрос всех пультов разом: `[(адрес, состояние, причина неудачи)]`.

    Параллельно, а не подряд: пультов столько же, сколько машин с оболочкой, и каждый
    может молчать до таймаута дозвона — последовательный обход умножил бы это ожидание
    на число пультов прямо в обновлении страницы.
    """
    return list(await asyncio.gather(*[_panel_state(url) for url in team_dsh_panel_urls()]))


async def _panel_state(url: str) -> tuple:
    """Состояние одного пульта; неудача возвращается, а не бросается."""
    try:
        return url, await team_dsh_panel_request(url, 'GET', '/roles'), ''
    except TeamDshError as error:
        logger_info(f'[team] пульт ролей dsh не ответил: {error}')
        return url, {}, str(error)

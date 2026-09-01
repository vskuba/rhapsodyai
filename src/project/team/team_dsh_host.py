"""
Перезапуск хоста DeepSeek Harness: кнопка наверху страницы команды.

Зачем кнопка вообще. Хост (`dsh --profile web` на петле машины) сам собой не
перезапускается никогда, и это осознанно: он один на все проекты и все роли, так что
перезапуск ради одной роли оборвал бы круги всех прочих. Но случаи, когда его надо
поднять заново, есть, и чинить их некому: пока хост молчит, сервис лишь пропускает
сверку карточек, и включённые кнопкой роли не поднимутся ни через минуту, ни через час.
Раньше это лечилось походом на машину; теперь — нажатием.

Кому адресован запрос. Всем ответившим пультам разом, а не одному: пульт — это машина,
хост у машины свой, и точка «жив» наверху страницы горит по тому же правилу — жив хоть
у кого-то. Выбирать машину человеку было бы нечем: адреса пультов страница не видит и
видеть не должна.

Проекта у перезапуска нет. Хост общий, адресовать нечего — потому и ручка пульта
(`/host/restart`) единственная, у которой тело пустое.
"""
import asyncio

from logging_.logging_ import logger_info
from src.project.team.team_dsh import team_dsh_panels
from src.project.team.team_dsh_panel import TeamDshError, team_dsh_panel_request

# Потолок ожидания перезапуска. Складывается из остановки хоста (до 10 с), ожидания
# освобождения порта (до 5 с) и подъёма нового (до 45 с) — плюс запас на сверку карточек
# по всем проектам пульта. Общий потолок пульта (25 с) оборвал бы это на середине.
TEAM_DSH_HOST_TIMEOUT = 90.0

TEAM_DSH_HOST_PATH = '/host/restart'


async def team_dsh_host_restart() -> dict:
    """
    Перезапустить хост Harness на всех ответивших пультах.

    Returns: `{'panels': [{'url', 'restarted', 'pid', 'problem'}], 'restarted': сколько
    поднялось, 'total': сколько пультов отвечало, 'problem': причины неудач одной строкой}`.

    Молчащий пульт в `total` не идёт: он не машина с лежачим хостом, а машина, до которой
    мы не дозвонились, — про её хост нам вообще ничего не известно. Его молчание уходит в
    `problem`, чтобы человек не считал перезапуск полным.

    Неудача одного пульта не отменяет остальных: машины независимы, и «на одной не
    получилось» — это не повод не чинить вторую.

    Raises: `TeamDshError` — 502, если не перезапустился ни один; 422, если пультов нет
    вовсе. Молчаливое «готово» при нуле поднятых человек прочтёт как сделанное.
    """
    panels = await team_dsh_panels()
    if not panels:
        raise TeamDshError('пультов нет вовсе: задайте DSH_CONTROL_URL и поднимите '
                           'ds-shell --service на машине с проектом', 422)

    silent = [problem for _url, _state, problem in panels if problem]
    alive = [url for url, _state, problem in panels if not problem]

    results = list(await asyncio.gather(*[_restart(url) for url in alive]))

    problems = silent + [item['problem'] for item in results if item['problem']]
    restarted = [item for item in results if item['restarted']]
    if not restarted:
        raise TeamDshError('хост Harness не перезапущен: ' + ('; '.join(problems)
                                                              or 'пульты не отозвались'))

    return {'panels': results,
            'restarted': len(restarted),
            'total': len(results),
            'problem': '; '.join(problems)}


async def _restart(url: str) -> dict:
    """Перезапуск на одном пульте; неудача возвращается, а не бросается."""
    try:
        result = await team_dsh_panel_request(url, 'POST', TEAM_DSH_HOST_PATH,
                                              timeout=TEAM_DSH_HOST_TIMEOUT)
    except TeamDshError as error:
        logger_info(f'[team] пульт {url} не перезапустил хост Harness: {error}')
        return {'url': url, 'restarted': False, 'pid': 0, 'problem': f'{url}: {error}'}

    logger_info(f'[team] хост Harness перезапущен пультом {url}: pid {result.get("pid")}')

    return {'url': url,
            'restarted': True,
            'pid': _pid(result.get('pid')),
            'problem': ''}


def _pid(value) -> int:
    """Номер процесса числом. Пульт — чужой процесс, и его ответ для нас входные данные."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

"""Прогон случаев этой установки: каркас слоя → строки в `test_e2e`.

Здесь сходятся две половины. Общая — `py_modules/tests_e2e/`: она открывает
копию страницы, снимает кадр, меряет области и проверяет содержимое, ничего не
зная ни про базу, ни про страницу результатов. Проектная — эта: где лежат
случаи, куда класть кадры, в какую таблицу писать.

⚠⚠ Работа браузера идёт в **отдельном потоке** (`asyncio.to_thread`). Прогон
синхронный: внутри три запуска Chrome подряд через `subprocess`, каждый держит
поток секундами. Позови его прямо — и встанет цикл событий того, кто позвал:
у кронджоба это его собственные задачи, у ручки панели — весь сервер.

⚠ Один сорвавшийся случай не уносит остальные: каркас возвращает `error`-строку
вместо исключения, а эта функция пишет её и идёт дальше. Иначе мёртвый селектор
в одном случае оставлял бы страницу результатов вчерашней целиком.
"""

import asyncio
import os

from config.config import config_get
from logging_.logging_ import logger_exception, logger_info
from tests_e2e.tests_e2e_case import tests_e2e_case_list
from tests_e2e.tests_e2e_run import tests_e2e_run_case

from src.e2e.e2e import e2e_row_write, e2e_run_uuid, e2e_trim
from src.e2e.e2e_shot import E2E_SHOT_DIR, e2e_shot_dir, e2e_shot_name

# Где лежат случаи. Рядом с `tests/`, `tests_browser/` и `tests_llm/`: те же
# проверки, только предмет другой.
E2E_CASE_DIR = '/app/tests_e2e' if os.path.isdir('/app/tests_e2e') else 'tests_e2e'

# Адрес панели, у которой прогон берёт копии страниц.
#
# ⚠⚠ Имя сервиса, а не `localhost`. Прогон идёт из ДВУХ разных контейнеров: из
# кронджоба (`uvicorn`) и из очереди по кнопке (`worker_task`). В первом
# `localhost:8000` — это панель, во втором — сам воркер, и прогон по кнопке
# падал `ConnectError: All connection attempts failed`, записывая `error` в
# каждую строку. Имя сервиса разрешается из обоих.
#
# ⚠⚠ На проде с Blue-Green нужен ПУБЛИЧНЫЙ адрес установки
# (`https://<домен>`), а не имя контейнера: имя указывает на один слот, и после
# выкладки в зелёный проверялся бы синий — то есть не то, что видит человек.
# Задаётся переменной `E2E_PANEL_URL`.
#
# ⚠⚠ `http://caddy:8090` для этого НЕ годится, хотя туда ходят кронджобы. Тот
# порт намеренно отвечает только на `/cronjob`, а на всё прочее — 404
# (`docker/caddy/Caddyfile`): с ним каждый случай писал бы `error`. Проверено на
# проде до того, как это успело сработать.
E2E_PANEL_BASE = 'http://uvicorn:8000'


async def e2e_runner_all(folder: str = '', base: str = '') -> dict:
    """Прогнать все случаи и записать результат.

    Args:
        folder: каталог случаев; пусто — `E2E_CASE_DIR`.
        base: адрес панели; пусто — `E2E_PANEL_URL` из окружения, а за ним
            `E2E_PANEL_BASE`.

    Returns:
        dict: `run_uuid`, `tests`, `failed`, `errored`.
    """
    base = base or config_get('E2E_PANEL_URL') or E2E_PANEL_BASE
    # ⚠⚠ Учётка своя, а не `ADMIN_*`. Та — личность загрузочного администратора
    # (`panel_user.py` заводит его на пустой таблице), и занимать её автоматикой
    # нельзя. Пусто — останется прежнее поведение: вход под `ADMIN_*`, как на
    # машине разработчика, где служебной учётки заводить незачем.
    user = config_get('E2E_PANEL_USER', '')
    password = config_get('E2E_PANEL_PASSWORD', '')
    cases = tests_e2e_case_list(folder or E2E_CASE_DIR)
    run_uuid = e2e_run_uuid()
    shots = e2e_shot_dir(run_uuid)
    logger_info(f'🧪 E2E прогон {run_uuid}: случаев {len(cases)}')

    tests = failed = errored = 0
    for case in cases:
        for width in case['widths']:
            result = await e2e_runner_one(case, width, shots, base,
                                          user=user, password=password)
            await e2e_runner_write(run_uuid, result)

            tests += 1
            failed += result['status'] == 'fail'
            errored += result['status'] == 'error'

    await e2e_trim()
    logger_info(f'🧪 E2E прогон {run_uuid}: тестов {tests}, '
                f'провалов {failed}, сорвалось {errored}')
    return {'run_uuid': run_uuid, 'tests': tests,
            'failed': failed, 'errored': errored}


async def e2e_runner_one(case: dict, width: int, shots: str, base: str,
                         user: str = '', password: str = '') -> dict:
    """Один случай в одной ширине — в отдельном потоке; см. шапку модуля."""
    names = (e2e_shot_name(case['name'], width, marked=False),
             e2e_shot_name(case['name'], width, marked=True))
    try:
        return await asyncio.to_thread(tests_e2e_run_case, case, width,
                                       shots, base, names, '', user, password)
    except Exception as err:
        # Сюда прилетает только то, что каркас не поймал сам: сбой потока,
        # отмена. Строку всё равно пишем — молчащий тест хуже красного.
        logger_exception(f'E2E: случай «{case["name"]}» {width}px сорвался: {err}')
        return {'name': case['name'], 'description': case['description'],
                'page': case['page'], 'width': width, 'status': 'error',
                'areas': [], 'console': [],
                'error': f'{type(err).__name__}: {err}', 'duration_ms': 0}


async def e2e_runner_write(run_uuid: str, result: dict) -> int:
    """Записать результат, переведя пути кадров в относительные.

    В колонке лежит путь **от корня кадров**, а не абсолютный: каталог данных у
    контейнера и у хоста разный, и абсолютный путь из базы сломался бы при
    первом же переносе установки.
    """
    row = dict(result)
    for key in ('shot_path', 'shot_plain_path'):
        value = row.get(key)
        row[key] = os.path.relpath(value, E2E_SHOT_DIR) if value else ''
    return await e2e_row_write(run_uuid, row)

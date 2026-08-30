"""
Проверка живости моделей пула и вывод мёртвых из выдачи.

Зачем. Модель пула может отвалиться на стороне провайдера, ничего об этом не сказав:
`qwen/qwen3.7-flash` перестала отвечать, а конвейер продолжал выдавать её ролям —
каждый тик уходил в круг, круг падал, попытка тратилась. Со стороны это выглядит как
неисправный конвейер, хотя ломается один поставщик из четырёх.

Пул оболочки — не справочник `llm`. Там модели, которые вызывает сам проект по нодам;
здесь — те, под которые `claude-shell` поднимает LiteLLM (`llm_models.yaml`). Списки
разные, поэтому и пинг свой, хотя устроен он по образцу `/admin/llm`
(`llm_ping`): дешёвый запрос, результат в `setting`, показ последнего значения.

**Пингуем не провайдера, а модель.** `GET /models` сказал бы лишь, что жив
маршрутизатор: список моделей OpenRouter отдаёт и тогда, когда конкретная снята с
раздачи. Поэтому шлём настоящий `chat/completions` в один токен — ровно тот путь,
которым пойдёт круг роли.

**Мёртвая модель уходит из выдачи, но остаётся в пуле.** Настройку пула не трогаем:
её правит человек, и стереть его выбор из-за минутной недоступности значило бы
заставить его набирать пул заново. Вместо этого захват модели
(`team_llm_pool_acquire`) пропускает те, чей последний пинг неудачен, а страница
показывает их отдельным состоянием. Провайдер ожил — следующий пинг вернёт модель в
работу сам, без единого действия человека.

**«Не отвечает» и «проверить не смогли» — разные состояния** (`error` и `unknown`), и
из выдачи выводит только первое. Второе — про эту установку, а не про модель: круг
роли идёт через LiteLLM оболочки с её собственным `.env`, и наша неспособность
достучаться ничего не говорит о том, работает ли модель там.
"""
import json
import time

import httpx

from config.config import config_get
from datetime_.datetime_ import datetime_utc_now
from logging_.logging_ import logger_info
from setting_.setting_ import setting_get, setting_set
from src.project.team.team_llm_catalog import team_llm_catalog_entry
from src.project.team.team_llm_pool import team_llm_pool_all

# Ключ настройки на модель. Имя модели содержит слэш (`gx10/qwen-large`) — это
# нормально: колонка `key` строковая, а искать по ней мы будем префиксом.
TEAM_LLM_PING_KEY_PREFIX = 'team_llm_ping_'

# Состояние «проверить не смогли»: каталог оболочки не смонтирован, адрес или ключ
# провайдера не назван. Из выдачи такую модель не выводим — см. `team_llm_ping_one`.
TEAM_LLM_PING_UNKNOWN = 'unknown'

# Сколько ждём ответа. Значение определила самая медленная модель, а не самая
# быстрая: локальный `gx10/qwen-large` отвечает на пустой запрос ~10 секунд (модель
# считает на своей машине), а под нагрузкой круга встаёт в очередь за ним. С прежними
# 20 секундами живая модель регулярно выпадала бы в «не отвечает» — а это ровно тот
# исход, ради предотвращения которого пинг и заведён.
#
# Расплата за щедрость — длительность опроса: моделей единицы, идут они по очереди, и
# полностью мёртвый пул займёт минуты. Опрос идёт в воркере (`_run_llm_ping`), ничего
# не держит, и ждать ему не жалко.
TEAM_LLM_PING_TIMEOUT = 45.0


async def team_llm_ping_one(name: str) -> dict:
    """
    Постучаться в модель и записать результат. Returns: `{status, ms, at, error}`.

    `status` — одно из трёх, и разница между двумя последними существенна:

    - `ok` — ответила;
    - `error` — постучались и не получили успеха. Только это выводит модель из выдачи;
    - `unknown` — постучаться не смогли: каталог оболочки не смонтирован, адрес или
      ключ провайдера не назван в `.env` этой установки.

    Почему `unknown` не считается отказом. Круг роли идёт не отсюда, а через LiteLLM
    оболочки, у которой свой `.env` и свой каталог, — наша неспособность проверить
    модель ничего не говорит о её работоспособности. Смешай мы эти случаи, забытое
    монтирование каталога объявило бы мёртвым весь пул разом и остановило бы конвейер
    целиком. Так и вышло на первом же прогоне: `worker_task` каталог не видел.

    Исключения наружу не выпускаем вовсе: пинг зовут из воркера конвейера, и упасть
    он там не имеет права — недоступная модель это его штатный исход, а не сбой.
    """
    name = str(name or '').strip()
    ping = {'status': 'error', 'http_status': None, 'ms': None,
            'at': datetime_utc_now().strftime('%Y-%m-%d %H:%M:%S'), 'error': None}

    entry = await team_llm_catalog_entry(name)
    if not entry:
        ping['status'] = TEAM_LLM_PING_UNKNOWN
        ping['error'] = 'модели нет в каталоге оболочки'

        return await _ping_save(name, ping)

    url, headers, problem = _endpoint(entry)
    if problem:
        ping['status'] = TEAM_LLM_PING_UNKNOWN
        ping['error'] = problem

        return await _ping_save(name, ping)

    # Модель для провайдера — из `target`, а не из имени записи: имена в каталоге
    # различают две записи на одну модель (`...-1`, `...-2`), и провайдер такого
    # имени не знает. Префикс маршрутизатора (`openrouter/`, `openai/`) добавляет
    # LiteLLM, а мы идём к провайдеру напрямую — здесь он лишний.
    model = entry['target'].split('/', 1)[-1] if entry['target'].count('/') > 1 \
        else entry['target'].removeprefix('openai/').removeprefix('openrouter/')

    payload = {'model': model, 'max_tokens': 1,
               'messages': [{'role': 'user', 'content': 'ping'}]}

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(TEAM_LLM_PING_TIMEOUT, connect=5.0)) as client:
            response = await client.post(url, headers=headers, json=payload)
        ping['ms'] = int((time.monotonic() - started) * 1000)
        ping['http_status'] = str(response.status_code)
        if response.is_success:
            ping['status'] = 'ok'
        else:
            ping['error'] = response.text[:300]
    except Exception as error:
        ping['ms'] = int((time.monotonic() - started) * 1000)
        ping['error'] = f'{type(error).__name__}: {error}'

    return await _ping_save(name, ping)


async def team_llm_ping_all(names: list = None) -> dict:
    """
    Пропинговать модели: названные либо все, что стоят в пулах проектов.

    Все пулы разом, а не пул одного проекта: моделей на машину единицы, а вызывающих
    у пинга двое — страница команды и тик оркестратора, который про проект ничего не
    знает. Returns: `{модель: результат}`.
    """
    wanted = [str(n).strip() for n in (names or []) if str(n).strip()]
    if not wanted:
        wanted = sorted({item['name'] for items in (await team_llm_pool_all()).values()
                         for item in items})

    out = {}
    for name in wanted:
        out[name] = await team_llm_ping_one(name)

    dead = [name for name, ping in out.items() if ping.get('status') == 'error']
    unknown = [name for name, ping in out.items()
               if ping.get('status') == TEAM_LLM_PING_UNKNOWN]
    if dead:
        logger_info(f"[team] пинг пула: не отвечают {', '.join(dead)}")
    if unknown:
        # Отдельной строкой: это не про модели, а про установку — и чинится она не
        # там, где чинят провайдера.
        logger_info(f"[team] пинг пула: не смогли проверить {', '.join(unknown)} "
                    f"— {out[unknown[0]].get('error')}")

    return out


async def team_llm_ping_get(name: str) -> dict:
    """Последний пинг модели. Пусто — не пинговали ни разу."""
    value = str(await setting_get(f'{TEAM_LLM_PING_KEY_PREFIX}{name}', ''))
    if not value:
        return {}
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return {}


async def team_llm_ping_map(names: list) -> dict[str, dict]:
    """Последние пинги нескольких моделей: `{модель: пинг}`."""

    return {str(name): await team_llm_ping_get(str(name)) for name in (names or [])}


async def team_llm_ping_dead(names: list) -> set[str]:
    """
    Какие из моделей выведены из выдачи по неудачному пингу.

    Выводит только `error` — «постучались и не получили успеха». Ни отсутствие пинга,
    ни `unknown` («проверить не смогли») моделью не считаются мёртвыми: на свежей
    установке не пинговали ещё никого, а без смонтированного каталога оболочки не
    проверить вовсе — и трактовать это как «всё мертво» значило бы остановить конвейер
    тем самым механизмом, который заведён его чинить.

    Протухший пинг тоже не выводит — по той же причине: не опрашивали (воркер стоял,
    контейнер поднимался) — это про опрос, а не про модель.
    """
    dead = set()
    for name in (names or []):
        ping = await team_llm_ping_get(str(name))
        if not ping or not ping.get('at'):
            continue
        if ping.get('status') == 'error':
            dead.add(str(name))

    return dead


async def _ping_save(name: str, ping: dict) -> dict:
    await setting_set(f'{TEAM_LLM_PING_KEY_PREFIX}{name}',
                      json.dumps(ping, ensure_ascii=False), dynamic=1)

    return ping


def _endpoint(entry: dict) -> tuple:
    """
    Куда и с каким ключом стучаться: `(url, headers, проблема)`.

    Адрес и ключ названы самой записью каталога (`url_env`/`key_env`) — тем же
    соглашением, по которому их читает LiteLLM.

    Но `.env` оболочки и `.env` этой установки — разные файлы, и имена в них
    разошлись: каталог зовёт адрес gx10 `GX10_URL`, а здесь он лежит под
    `GX10_LARGE_API_URL` — по размеру модели, как читает его `/admin/llm`. Поэтому
    имя из каталога пробуем первым, а не единственным: не нашлось — ищем по
    соглашению этой установки. Иначе пинг сообщал бы «в .env нет адреса» про
    прекрасно работающую модель.
    """
    key_env = entry.get('key_env') or ''
    url_env = entry.get('url_env') or ''
    base = str(config_get(url_env) if url_env else '').strip()
    if not base:
        for name in _url_env_guesses(entry, key_env):
            base = str(config_get(name) or '').strip()
            if base:
                break

    api_key = str(config_get(key_env) if key_env else '').strip()

    if not base:
        return '', {}, f'в .env нет адреса провайдера ({url_env or key_env or "не назван"})'
    if key_env and not api_key:
        return '', {}, f'в .env нет {key_env}'

    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}

    return base.rstrip('/') + '/chat/completions', headers, ''


def _url_env_guesses(entry: dict, key_env: str) -> list[str]:
    """
    Имена переменных с адресом провайдера по соглашению этой установки.

    Порядок от частного к общему: у gx10 адрес свой на каждый размер модели
    (`GX10_LARGE_API_URL` — размер берётся из хвоста имени, как в `/admin/llm`), у
    остальных один на провайдера (`OPENROUTER_API_URL`). Провайдера берём из ключа, а
    не из имени модели: у записей вида `deepseek-v4-flash-0731-2` префикса провайдера
    в имени нет вовсе.
    """
    provider = key_env.removesuffix('_API_KEY') if key_env.endswith('_API_KEY') else ''
    if not provider:
        return []

    names = []
    size = entry['name'].split('/')[-1].split('-')[-1].upper()
    if size:
        names.append(f'{provider}_{size}_API_URL')
    names.append(f'{provider}_API_URL')

    return names

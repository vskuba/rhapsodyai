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
которым пойдёт круг роли. Это полноценный платный запрос, и период опроса выбран с
оглядкой на это.

**Особенности сервисов знает стратегия провайдера** (`ai_provider_registry_get`), а
не этот файл: адрес с ключом даёт `raw_endpoint`, поля против размышлений —
`raw_body_no_thinking`. Разбирай мы `.env` и способы гасить размышления здесь, у
проекта появилось бы второе место, знающее про сервисы, — и разошлось бы оно на
первой же новой модели.

**Размышления обязательно выключаем.** Модель, ушедшая в рассуждение, тратит на него
весь бюджет ответа: `qwen3.7-flash` с `max_tokens: 1` не уложился и в 45 секунд и
вернул `content: null` при полном `reasoning`. Проверка объявила бы мёртвой
прекрасно работающую модель — и тем самым отобрала бы её у конвейера.

**Локальные не пингуем вовсе.** У модели на нашем железе одна карта на все роли, и
запрос проверки встаёт в общую очередь с настоящей работой: `gx10/qwen-large` отвечает
на пустой пинг десять секунд свободной и не отвечает вовсе, пока идёт круг. Проверка
живости стоила бы ровно того, ради чего затевалась, — времени модели. Локальность
объявляет сама стратегия провайдера (`AiProvider.local`), а не список имён здесь.

**Занятую кругом тоже не пингуем.** Она считает работу роли, и пинг встанет в очередь
за ней. Занятость сама по себе свидетельство надёжнее пинга: захват выдан, круг идёт.

**Мёртвая модель уходит из выдачи, но остаётся в пуле.** Настройку пула не трогаем:
её правит человек, и стереть его выбор из-за минутной недоступности значило бы
заставить его набирать пул заново. Вместо этого захват модели
(`team_llm_pool_acquire`) пропускает те, чей последний пинг неудачен, а страница
показывает их отдельным состоянием. Провайдер ожил — следующий пинг вернёт модель в
работу сам, без единого действия человека.

**«Не отвечает» и «проверить не смогли» — разные состояния** (`error` и `unknown`), и
из выдачи выводит только первое. Второе — про эту установку, а не про модель: круг
роли идёт через LiteLLM оболочки с её собственным `.env` и своей сетью, и наша
неспособность достучаться ничего не говорит о том, работает ли модель там.

Граница проходит по соединению. Не дозвонились (`ConnectError`, `ConnectTimeout`) —
`unknown`: пропади у нас интернет, приговор получили бы разом все сетевые модели, и
конвейер остался бы без работы по причине, к ним не относящейся. Дозвонились, а
ответа нет (`ReadTimeout`, код не из 2xx) — `error`: запрос принят, справиться не
удалось, и это уже про модель.
"""
import json
import time
from datetime import datetime

import httpx

from ai.provider.ai_provider_registry import ai_provider_registry_get
from datetime_.datetime_ import datetime_utc_now
from logging_.logging_ import logger_info
from setting_.setting_ import setting_get, setting_set
from src.project.team.team_llm_catalog import team_llm_catalog_entry
from src.project.team.team_llm_pool import team_llm_pool_all, team_llm_pool_locks

# Ключ настройки на модель. Имя модели содержит слэш (`gx10/qwen-large`) — это
# нормально: колонка `key` строковая, а искать по ней мы будем префиксом.
TEAM_LLM_PING_KEY_PREFIX = 'team_llm_ping_'

# Состояние «проверить не смогли»: каталог оболочки не смонтирован, адрес или ключ
# провайдера не назван. Из выдачи такую модель не выводим — см. `team_llm_ping_one`.
TEAM_LLM_PING_UNKNOWN = 'unknown'

# Состояние «не проверяем намеренно»: локальная модель. Отличается от `unknown` тем,
# что это наше решение, а не неудача, — см. `team_llm_ping_skipped`.
TEAM_LLM_PING_SKIPPED = 'skipped'

# Сколько отказ остаётся приговором. Модель, занятая длинным кругом, не опрашивается
# вовсе, и её последняя запись может быть какой угодно давности: пока она работала,
# проверить её было нельзя. Держи мы старый отказ бессрочно — освободившаяся модель
# не получила бы ни одного круга, хотя никто её больше не проверял.
#
# Три периода опроса: один пропущенный тик (воркер перезапускали) не должен возвращать
# в работу модель, которая только что не ответила.
TEAM_LLM_PING_DEAD_SECONDS = 900

# Сколько ждём ответа. Пингуем только сетевые модели, а они отвечают за секунду
# (`qwen3.7-flash` — 764 мс, `deepseek-v4-flash` — 726 мс с выключенными
# размышлениями), так что пятнадцати хватает с запасом на худший день провайдера.
#
# Раньше здесь стояло 45 секунд — ради локальной, которой на пустой запрос нужно было
# десять. Её мы больше не пингуем, и держать общий срок по самой медленной незачем:
# длинный таймаут только оттягивает момент, когда отвалившаяся модель перестанет
# получать круги.
TEAM_LLM_PING_TIMEOUT = 15.0


async def team_llm_ping_one(name: str) -> dict:
    """
    Постучаться в модель и записать результат. Returns: `{status, ms, at, error}`.

    `status` — одно из четырёх, и выводит из выдачи только второе:

    - `ok` — ответила;
    - `error` — постучались и не получили успеха;
    - `unknown` — постучаться не смогли: каталог оболочки не смонтирован, адрес или
      ключ провайдера не назван в `.env`, до сервиса не дозвонились;
    - `skipped` — не проверяли намеренно: модель локальная (`AiProvider.local`), и
      пинг отнимал бы у неё ту самую карту, на которой она считает работу ролей.

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

    if team_llm_ping_skipped(entry):
        ping['status'] = TEAM_LLM_PING_SKIPPED
        ping['error'] = 'локальная модель — не пингуем, чтобы не отнимать её время'

        return await _ping_save(name, ping)

    # Кто обслуживает модель — решает стратегия провайдера, а не разбор имени здесь.
    #
    # Имя записи пробуем первым, `target` — вторым, и порядок этот не случаен. В
    # `target` стоит строка для LiteLLM, и её первый сегмент — **протокол**, а не
    # сервис: у локальной модели там `openai/qwen3.6`, потому что llama.cpp говорит
    # по протоколу OpenAI. Спроси мы сначала `target` — пинг локальной модели ушёл
    # бы в настоящий OpenAI. У записей без префикса (`deepseek-v4-flash-0731-2`,
    # где суффикс различает два порта на одну модель) сервис виден только в
    # `target` — для них и нужен второй заход.
    provider = (ai_provider_registry_get(entry['name'])
                or ai_provider_registry_get(entry['target']))
    if not provider:
        ping['status'] = TEAM_LLM_PING_UNKNOWN
        ping['error'] = f"сервис модели не опознан: {entry['name']} → {entry['target']}"

        return await _ping_save(name, ping)

    # Два разных имени, и путать их нельзя. В теле запроса — то, как модель зовут у
    # сервиса (`target` без протокола: `qwen3.6`, `deepseek/deepseek-v4-flash-0731`).
    # В выборе адреса — то, как она зовётся у нас (`qwen-large`): у gx10 адрес свой
    # на каждый размер, и размер читается из нашего имени, а не из чужого.
    model = entry['target'].partition('/')[2] or entry['target']
    local_name = entry['name'].partition('/')[2] or entry['name']

    base, api_key = provider.raw_endpoint(local_name)
    if not base:
        ping['status'] = TEAM_LLM_PING_UNKNOWN
        ping['error'] = f'в .env нет адреса сервиса {provider.name}'

        return await _ping_save(name, ping)

    url = base.rstrip('/') + '/chat/completions'
    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}

    # Размышления гасит сам провайдер: как именно — его дело, а не наше. Без этого
    # модель тратит на внутренний монолог весь бюджет ответа и возвращает пустой
    # `content`; `qwen3.7-flash` так не уложился и в 45 секунд, хотя работал.
    payload = {'model': model, 'max_tokens': 1,
               'messages': [{'role': 'user', 'content': 'ping'}],
               **provider.raw_body_no_thinking()}

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
    except (httpx.ConnectError, httpx.ConnectTimeout) as error:
        # До сервиса не дозвонились вовсе. Это про нашу сеть, а не про модель: круг
        # роли идёт через LiteLLM оболочки, у которой и сеть, и прокси свои. Пропади
        # у нас интернет — пометив модели мёртвыми, мы отобрали бы у конвейера сразу
        # все сетевые, оставив его без работы по причине, к ним не относящейся.
        # Поймано живьём: три модели разом дали `ConnectTimeout` ровно за 5 секунд —
        # столько стоит `connect`, и совпадение до миллисекунд выдало общую причину.
        ping['status'] = TEAM_LLM_PING_UNKNOWN
        ping['ms'] = int((time.monotonic() - started) * 1000)
        ping['error'] = f'до сервиса не дозвонились: {type(error).__name__}'
    except Exception as error:
        # Соединение установилось, а ответа нет — вот это уже про модель: она приняла
        # запрос и не справилась. Сюда же попадает `ReadTimeout`.
        ping['ms'] = int((time.monotonic() - started) * 1000)
        ping['error'] = f'{type(error).__name__}: {error}'

    return await _ping_save(name, ping)


def team_llm_ping_skipped(entry: dict) -> bool:
    """
    Модель, которую не проверяем намеренно: локальная.

    Спрашиваем стратегию провайдера, а не имя: список локальных сервисов должен жить
    в одном месте с остальными их особенностями, иначе новая локальная модель
    молча попадёт под пинг и начнёт делиться картой с проверкой.

    Стратегия не опознана — не пропускаем: неизвестный сервис скорее сетевой, а
    ошибиться здесь безопаснее в сторону лишнего запроса, чем непроверенной модели.
    """
    provider = (ai_provider_registry_get(str(entry.get('name') or ''))
                or ai_provider_registry_get(str(entry.get('target') or '')))

    return bool(provider and provider.local)


async def team_llm_ping_all(names: list = None) -> dict:
    """
    Пропинговать модели: названные либо все, что стоят в пулах проектов.

    Все пулы разом, а не пул одного проекта: моделей на машину единицы, а вызывающих
    у пинга двое — страница команды и тик оркестратора, который про проект ничего не
    знает. Returns: `{модель: результат}`.

    **Занятые кругом не трогаем.** Модель, которую держит захват, сейчас считает
    работу роли, и пинг встанет в очередь за ней: локальная `gx10/qwen-large`,
    занятая кругом QA, не ответила на пинг и за 100 секунд — при том, что прекрасно
    работала. Пометь мы её «не отвечает», проверка отобрала бы у конвейера ровно ту
    модель, которая в этот момент делает работу.

    Занятость — свидетельство надёжнее пинга: захват выдан, круг идёт. Прежний
    результат такой модели остаётся как есть, и следующий опрос проверит её, когда
    она освободится.
    """
    wanted = [str(n).strip() for n in (names or []) if str(n).strip()]
    if not wanted:
        wanted = sorted({item['name'] for items in (await team_llm_pool_all()).values()
                         for item in items})

    busy = {str(lock['llm_name']) for lock in await team_llm_pool_locks()}

    out = {}
    for name in wanted:
        if name in busy:
            logger_info(f'[team] пинг пула: {name} занята кругом, проверку пропускаем')
            continue
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

    **Отказ протухает** (`TEAM_LLM_PING_DEAD_SECONDS`). Занятую кругом модель не
    опрашивают вовсе, и её последняя запись может быть какой угодно давности — пока
    она работала, проверить её было нельзя. Держи мы старый отказ бессрочно,
    освободившаяся модель не получила бы ни одного круга, хотя никто её больше не
    проверял; поймано живьём на `gx10/qwen-large`, чей таймаут пережил круг
    разработчика и остался висеть красным.
    """
    dead = set()
    for name in (names or []):
        ping = await team_llm_ping_get(str(name))
        if not ping or ping.get('status') != 'error':
            continue
        if _ping_age(ping) <= TEAM_LLM_PING_DEAD_SECONDS:
            dead.add(str(name))

    return dead


async def _ping_save(name: str, ping: dict) -> dict:
    await setting_set(f'{TEAM_LLM_PING_KEY_PREFIX}{name}',
                      json.dumps(ping, ensure_ascii=False), dynamic=1)

    return ping


def _ping_age(ping: dict) -> float:
    """
    Сколько секунд назад сделана запись пинга.

    Неразобранная отметка — «бесконечно давно»: считать её свежей значило бы держать
    модель выведенной из выдачи по записи, о которой мы ничего не знаем.
    """
    try:
        at = datetime.strptime(str(ping.get('at') or ''), '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return float('inf')

    return (datetime_utc_now() - at).total_seconds()

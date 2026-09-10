"""Автор сценария: LLM пишет шаги, глядя на снимки живой страницы.

Работает на стороне `uvicorn`, а не в контейнере-браузере: здесь LLM, база и
журнал, а там — только страницы. Поэтому правка этого файла требует рестарта
`uvicorn`, но не `browser`: живые сессии переживают её.

Виток цикла всегда один и тот же: снимок страницы → LLM предлагает следующие
шаги → шаги проходят схему `BrowserScenario` → выполняются в живой сессии →
снимок новой страницы. Автор пишет по тому, что видит, а не по тому, что помнит
о вёрстке: между витками страница меняется, и следующий шаг выбирается уже по
новому состоянию.

Витки ограничены и по числу, и по времени. Модель, которая не понимает страницу,
иначе крутила бы цикл до конца квоты, каждый раз предлагая тот же не работающий
клик.

Готовый сценарий проверяется ещё раз — с нуля, в чистой сессии. Сценарий, который
работает только там, где вход уже выполнен и нужный раздел уже открыт, завтра не
воспроизведётся; такой сохраняется как `draft`, а прошедший проверку — `active`.

Секретов LLM не видит: в запрос уходят только имена (`password`), значения живут
в памяти запроса и подставляются контейнером на прогоне.
"""

import asyncio
import json
import time

from pydantic import BaseModel, Field

from browser_.browser_scenario import (
    BROWSER_SCENARIO_ACTIONS,
    BrowserScenario,
    BrowserScenarioStep,
    browser_scenario_step_target,
)
from logging_.logging_ import logger_info
from json_.json_ import json_from_string
from queue_.queue_ import queue_get

from src.ai.ai_llm import ai_llm_node_get
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.browser.scenario_repository import BrowserScenarioRepository
from src.mysql_.repository.browser.scenario_run_repository import BrowserScenarioRunRepository
from src.uvicorn.routers.browser.browser_upstream import (
    BROWSER_UPSTREAM_SCENARIO_TIMEOUT,
    browser_upstream_request,
)

# Витков цикла. Каждый — это снимок, вызов LLM и прогон шагов; восьми хватает на
# вход и три-четыре перехода, а дальше цель почти всегда сформулирована слишком
# широко, и продолжать дешевле после правки формулировки, чем ещё десятью витками.
BROWSER_AUTHOR_ITERATION_LIMIT = 8

# Общий бюджет времени. Считается по всему циклу, а не по витку: один залипший
# ответ модели не должен съесть всё, но и восемь честных витков по минуте — уже
# перебор для запроса, который кто-то ждёт в браузере.
BROWSER_AUTHOR_BUDGET_SECONDS = 600

# Ждать ответа дольше, чем ждёт сама LLM (180 с на запрос): у ноды несколько
# моделей, и первая может быть выключена. Урезать это ожидание значит обрывать
# цепочку фоллбэка на первой же недоступной модели — а она в списке первая.
BROWSER_AUTHOR_LLM_TIMEOUT = 420.0

# Сколько символов снимка уходит в запрос. Предел снимка (20000) в промпт класть
# накладно: дерево идёт в порядке документа, и нужное почти всегда в начале.
BROWSER_AUTHOR_SNAPSHOT_LIMIT = 6000

# Шагов за один ответ. Чем длиннее пачка, тем дальше модель уходит от того, что
# видела на снимке: после первой же навигации остальные селекторы выдуманы.
BROWSER_AUTHOR_BATCH_LIMIT = 8

BROWSER_AUTHOR_AGENT_NAME = 'browser_author'


class BrowserAuthorRequest(BaseModel):
    """Задание автору: чего добиться и с какой страницы начать."""

    name: str = Field(..., min_length=1, max_length=100, description='Имя будущего сценария, уникальное')
    goal: str = Field(..., min_length=1, max_length=255, description='Цель словами — по ней сценарий перепишут потом')
    start_url: str = Field(..., min_length=1, max_length=500)
    variables: dict[str, str] = Field(default_factory=dict, description='Подстановки; попадут в базу и журнал')
    secrets: dict[str, str] = Field(default_factory=dict, description='Пароли и токены; ни в базу, ни в промпт')
    session_id: str = Field('', description='Писать в этой сессии; пусто — завести свою и погасить в конце')
    node_id: int | None = Field(None, description='LLM-нода; пусто — catchall')
    save: bool = Field(True, description='Сохранить результат в браузерные сценарии')


async def browser_author_run_browser_author_run(data: BrowserAuthorRequest, user_id: int = 0) -> dict:
    """Пишет сценарий под цель и возвращает его вместе с историей витков.

    Возвращает результат, а не бросает исключение на недостигнутой цели: неудачный
    заход всё равно ценен — по журналу видно, на каком шаге модель застряла, а
    написанные до срыва шаги ложатся в черновик и правятся руками.
    """
    started = time.monotonic()
    journal: list[dict] = []
    steps_ok: list[BrowserScenarioStep] = []
    session_id = data.session_id
    session_own = False
    reason = ''
    done = False

    try:
        if not session_id:
            created = await browser_upstream_request('POST', '/browser/session',
                                                     {'name': f'автор: {data.name}'[:100]})
            session_id = str(created.get('session', {}).get('session_id', ''))
            session_own = True

        # Первый шаг автор не придумывает: стартовый адрес задан заданием, а
        # смотреть на страницу нужно уже после перехода на неё.
        opening = BrowserScenarioStep(action='goto', url=data.start_url)
        run = await _steps_run([opening], session_id, data)
        if run.get('status') == 'error':
            return _result('error', f'стартовая страница не открылась: {run.get("error", "")}',
                           steps_ok, journal, None, None, session_id)
        steps_ok.append(opening)

        error_last = ''

        for number in range(1, BROWSER_AUTHOR_ITERATION_LIMIT + 1):
            if time.monotonic() - started > BROWSER_AUTHOR_BUDGET_SECONDS:
                reason = 'кончился бюджет времени'
                break

            snapshot = await _snapshot(session_id)
            entry = {'no': number, 'url': snapshot.get('url', ''), 'comment': '',
                     'steps': [], 'drop': 0, 'done': False, 'error': ''}
            journal.append(entry)

            try:
                answer = await _llm_ask(data, snapshot, steps_ok, error_last, number, user_id)
            except Exception as e:
                entry['error'] = f'LLM не ответила: {_exception_describe(e)}'
                reason = entry['error']
                break

            entry['comment'] = str(answer.get('comment', ''))[:500]
            entry['done'] = bool(answer.get('done'))

            # Тупик, в который автор зашёл (открыл несуществующий раздел, кликнул
            # не ту вкладку), технически выполняется без ошибки и потому оседает в
            # сценарии навсегда. `drop` — способ его вычеркнуть; страница при этом
            # остаётся где была, и следующие шаги пишутся от неё, а сойдётся ли
            # укороченный путь с нуля, покажет проверочный прогон.
            entry['drop'] = _drop_apply(answer.get('drop'), steps_ok)

            try:
                steps_new = _steps_parse(answer.get('steps'))
            except ValueError as e:
                # Схему не прошли — на страницу ничего не пошло. Ошибка уедет в
                # следующий запрос: модель чаще всего исправляется с первой подсказки.
                error_last = str(e)
                entry['error'] = error_last
                continue

            entry['steps'] = [step.model_dump() for step in steps_new]

            if not steps_new:
                if entry['done']:
                    done = True
                    break
                error_last = 'ответ без шагов: либо предложи шаги, либо поставь done'
                entry['error'] = error_last
                continue

            run = await _steps_run(steps_new, session_id, data)

            if run.get('status') == 'error':
                # Шаги до упавшего уже применились к странице — они часть сценария.
                # Выбросить их значило бы описать состояние, которого нет: следующий
                # виток смотрит на снимок, сделанный уже после них.
                failed = int(run.get('step_no', 0) or 0)
                steps_ok.extend(steps_new[:max(0, failed - 1)])
                error_last = _error_describe(steps_new, failed, str(run.get('error', '')))
                entry['error'] = error_last
                continue

            steps_ok.extend(steps_new)
            error_last = ''

            if entry['done']:
                done = True
                break
        else:
            reason = 'кончились витки, цель не достигнута'

        if not done:
            reason = reason or 'автор не признал цель достигнутой'

        scenario = BrowserScenario(name=data.name, goal=data.goal, steps=steps_ok)
        verify = await _verify(scenario, data)

        # `active` — только у сценария, который и цель взял, и прошёл проверку.
        # Оборванный на первом витке содержит один переход на стартовый адрес, и
        # проверка его пропускает: перейти по адресу всегда получается. Пометить
        # такой рабочим значит подсунуть его в дело вместо настоящего.
        status = 'active' if done and verify.get('status') != 'error' else 'draft'

        scenario_id = await _scenario_save(scenario, data, status, verify) if data.save else None

        if verify.get('status') == 'error':
            reason = reason or f'проверка с нуля не прошла: {verify.get("error", "")}'

        logger_info(f'[browser] автор «{data.name}»: витков {len(journal)}, шагов {len(steps_ok)}, '
                    f'проверка {verify.get("status", "?")}, статус {status}')

        return _result('ok' if done and status == 'active' else 'error', reason,
                       steps_ok, journal, verify, scenario_id, session_id, status)
    finally:
        if session_own and session_id:
            # Свою сессию гасим всегда, чужую — никогда: её мог открыть человек и
            # смотреть прямо сейчас в /admin/browser.
            try:
                await browser_upstream_request('DELETE', f'/browser/session/{session_id}')
            except Exception as e:
                logger_info(f'[browser] сессию автора {session_id} не удалось погасить: {e}')


def _actions_describe() -> str:
    """Справка по действиям — из самой схемы, чтобы промпт не разошёлся с ней."""
    return '\n'.join(
        f'- {action}: обязательны {", ".join(fields)}'
        for action, fields in sorted(BROWSER_SCENARIO_ACTIONS.items())
    )


def _drop_apply(value, steps_ok: list[BrowserScenarioStep]) -> int:
    """Выкидывает из написанного столько последних шагов, сколько просит модель.

    Первый шаг не трогает: переход на стартовый адрес задан заданием, а не автором,
    и сценарий без него начинался бы с пустой вкладки.
    """
    try:
        drop = int(value or 0)
    except (TypeError, ValueError):
        return 0

    drop = min(max(drop, 0), max(0, len(steps_ok) - 1))
    if drop:
        del steps_ok[len(steps_ok) - drop:]

    return drop


def _error_describe(steps: list[BrowserScenarioStep], failed: int, error: str) -> str:
    """Что именно не сработало — номером шага модели не объяснить, нужен сам шаг."""
    if 1 <= failed <= len(steps):
        step = steps[failed - 1]
        return f'шаг {failed} ({step.action} {browser_scenario_step_target(step)}) не выполнился: {error}'

    return f'прогон не прошёл: {error}'


def _exception_describe(e: Exception) -> str:
    """Текст исключения с гарантией, что он непустой.

    `asyncio.TimeoutError` печатается пустой строкой, и причина остановки в
    журнале выглядела бы как «LLM не ответила: » — по такой записи не отличить
    таймаут от отказа провайдера.
    """
    return str(e) or type(e).__name__


async def _llm_ask(data: BrowserAuthorRequest, snapshot: dict, steps_ok: list[BrowserScenarioStep],
                   error_last: str, number: int, user_id: int) -> dict:
    """Один вопрос модели. Ответ — объект с полями `comment`, `steps`, `done`."""
    entities_llm = await ai_llm_node_get(data.node_id)
    if not entities_llm:
        raise RuntimeError(f'нет доступной LLM: у ноды {data.node_id or "catchall"} пустой список')

    entity_agent = {
        'name': BROWSER_AUTHOR_AGENT_NAME,
        'title': 'Автор браузерных сценариев',
        'prompt_system': _prompt_system(),
    }
    if data.node_id:
        entity_agent['node_id'] = data.node_id

    framework_model = await AiFrameworkAgentManager().framework_model_create({
        'entity_agent': entity_agent,
        'entities_llm': entities_llm,
        'user_id': user_id,
        # None, а не 0 по умолчанию: у `agent_session.companion_id` внешний ключ на
        # `companion`, и нулём переписка автора в журнал не запишется — вызов упадёт
        # уже после ответа модели, потратив его впустую.
        'companion_id': None,
    })
    framework_model.prompt_user = _prompt_user(data, snapshot, steps_ok, error_last, number)
    framework_model.is_gui_mode = False

    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def on_complete(text: str, exception: Exception | None = None):
        # Замыкание, а не functools.partial: очередь делает deepcopy модели, и
        # partial с future внутри скопировался бы вместе с ним — ответ пришёл бы
        # в чужую копию, а этот вызов висел бы до таймаута.
        if future.done():
            return
        if exception:
            future.set_exception(exception)
        else:
            future.set_result(text)

    framework_model.on_complete = on_complete
    queue_get('ai_framework_model').put(framework_model)

    text = await asyncio.wait_for(future, BROWSER_AUTHOR_LLM_TIMEOUT)
    answer = json_from_string(text)

    if not isinstance(answer, dict):
        raise ValueError('ответ не разобрался как JSON-объект')

    return answer


def _prompt_system() -> str:
    """Правила автора. Живут в коде, а не в базе: они про схему шагов, и меняются
    вместе с ней."""
    return f"""Ты пишешь сценарий действий в браузере — детерминированную последовательность шагов.

Тебе дают цель и снимок страницы: дерево доступности, где у каждого элемента есть
роль, подпись и селектор sel="...". Ты предлагаешь следующие шаги, их выполняют в
живом браузере, и ты получаешь снимок того, что получилось.

Действия и обязательные для них поля:
{_actions_describe()}

Правила:
1. Селектор для click, fill и wait_for бери только из sel="..." снимка. Не
   выдумывай их и никогда не используй ref=eNN — эти ссылки живут до ближайшего
   перехода. Для extract selector можно составить самому: он должен совпадать со
   всеми элементами списка сразу (`tbody tr`, `[role="row"]`, `.card`), и sel из
   снимка для этого не годится — он рассчитан на одну строку из многих.
2. За один ответ не больше {BROWSER_AUTHOR_BATCH_LIMIT} шагов, и лучше меньше: после перехода на другую
   страницу селекторы из текущего снимка уже не годятся. Дойди до нового состояния
   и остановись — следующий снимок покажет, что делать дальше.
3. Пароли и логины подставляй как {{{{имя}}}} из списка секретов. Значений тебе не
   дают, и придумывать их не надо.
4. Данные, которые нужно вернуть, забирай действием extract с полем name. Оно
   собирает текст всех элементов, подходящих под селектор: под список бери
   селектор строки или карточки, а не одной ячейки и не счётчика рядом со списком.
5. done=true ставь, только если цель уже достигнута на текущем снимке — либо
   вместе с последними шагами, которые её достигают.
6. Если предыдущие шаги упали, разберись по снимку, что на странице на самом
   деле, и предложи другой путь, а не тот же шаг ещё раз.
7. Адреса не угадывай. goto — только на стартовый адрес или на адрес, который
   виден в снимке ссылкой. До остальных разделов доходи кликами по ссылкам.
8. В снимке только то, что видно сейчас. Пункт подменю, вкладка другой группы,
   содержимое свёрнутого блока в него не попадают — сначала раскрой их кликом по
   родительскому пункту, а потом смотри новый снимок.
9. Если предыдущий путь оказался тупиком, поставь drop: N — столько последних
   написанных шагов вычеркнут из сценария. Страница при этом останется где была.
10. Сценарий потом проигрывают с нуля: чистый браузер, вход не выполнен, открыта
   пустая вкладка. Шаги входа и переходы нужны даже тогда, когда прямо сейчас
   нужная страница уже открыта — без них с нуля не повторится. Вычёркивай через
   drop только то, что действительно оказалось лишним шагом в сторону.

Отвечай ТОЛЬКО JSON-объектом, без пояснений вокруг:
{{"comment": "что делаешь и почему", "steps": [{{"action": "click", "selector": "#loginBtn"}}], "drop": 0, "done": false}}"""


def _prompt_user(data: BrowserAuthorRequest, snapshot: dict, steps_ok: list[BrowserScenarioStep],
                 error_last: str, number: int) -> str:
    """Состояние дела на этот виток: цель, что уже написано, что видно, что упало."""
    variables = ', '.join(f'{{{{{name}}}}} = {value}' for name, value in data.variables.items()) or '—'
    secrets = ', '.join(f'{{{{{name}}}}}' for name in data.secrets) or '—'
    written = json.dumps([step.model_dump(exclude_defaults=True) for step in steps_ok], ensure_ascii=False)

    parts = [
        f'Цель: {data.goal}',
        f'Стартовый адрес: {data.start_url}',
        f'Виток {number} из {BROWSER_AUTHOR_ITERATION_LIMIT}.',
        f'Переменные: {variables}',
        f'Секреты (только имена): {secrets}',
        f'Уже написанные шаги: {written}',
    ]

    if error_last:
        parts.append(f'Предыдущая попытка не удалась: {error_last}')

    parts.append(f'Текущий адрес: {snapshot.get("url", "")} — {snapshot.get("title", "")}')
    parts.append('Снимок страницы:\n' + str(snapshot.get('snapshot', ''))[:BROWSER_AUTHOR_SNAPSHOT_LIMIT])

    return '\n\n'.join(parts)


def _result(status: str, reason: str, steps: list[BrowserScenarioStep], journal: list[dict],
            verify: dict | None, scenario_id: int | None, session_id: str,
            scenario_status: str = '') -> dict:
    """Ответ автора: сценарий, его судьба и вся история витков.

    Журнал отдаётся всегда, в том числе на удаче: по нему видно, сколько раз модель
    промахнулась селектором, — а это первый признак, что снимок надо чинить, а не
    промпт.
    """
    return {
        'status': status,
        'reason': reason,
        'scenario_id': scenario_id,
        'scenario_status': scenario_status,
        'steps': [step.model_dump() for step in steps],
        'iterations': journal,
        'verify': verify,
        'extract': (verify or {}).get('extract', {}),
        'session_id': session_id,
    }


async def _scenario_save(scenario: BrowserScenario, data: BrowserAuthorRequest, status: str,
                         verify: dict) -> int | None:
    """Кладёт сценарий и трассу проверочного прогона. Секретов в них нет."""
    try:
        scenario_id = await BrowserScenarioRepository().add({
            'name': data.name,
            'goal': data.goal,
            'start_url': data.start_url,
            'steps': json.dumps([step.model_dump() for step in scenario.steps], ensure_ascii=False),
            'variables': json.dumps(data.variables, ensure_ascii=False),
            'status': status,
        })
    except Exception as e:
        # Имя занято или база недоступна: терять из-за этого написанный сценарий
        # незачем — он вернётся ответом, и его сохранят руками.
        logger_info(f'[browser] сценарий автора «{data.name}» не сохранился: {e}')
        return None

    await BrowserScenarioRunRepository().add({
        'scenario_id': scenario_id,
        'session_id': str(verify.get('session_id', ''))[:32],
        'status': 'error' if verify.get('status') == 'error' else 'ok',
        'step_no': int(verify.get('step_no', 0) or 0),
        'error': str(verify.get('error', '')),
        'trace': json.dumps(verify.get('steps', []), ensure_ascii=False),
        'extract': json.dumps(verify.get('extract', {}), ensure_ascii=False),
        'duration_ms': int(verify.get('duration_ms', 0) or 0),
    })

    return scenario_id


async def _snapshot(session_id: str) -> dict:
    """Снимок текущей страницы сессии — без перехода, автор смотрит на то, что есть."""
    return await browser_upstream_request('POST', '/browser/snapshot', {'session_id': session_id})


async def _steps_run(steps: list[BrowserScenarioStep], session_id: str, data: BrowserAuthorRequest) -> dict:
    """Гонит пачку шагов в рабочей сессии автора, не гася её."""
    scenario = BrowserScenario(name=f'автор: {data.name}'[:100], goal=data.goal, steps=steps)

    return await browser_upstream_request('POST', '/browser/scenario/run', {
        'scenario': scenario.model_dump(),
        'session_id': session_id,
        'variables': data.variables,
        'secrets': data.secrets,
        'keep_session': True,
    }, timeout=BROWSER_UPSTREAM_SCENARIO_TIMEOUT)


def _steps_parse(value) -> list[BrowserScenarioStep]:
    """Шаги из ответа модели через ту же схему, что и на сохранении.

    Ошибка здесь — нормальный ход событий, а не сбой: она уходит обратно в промпт
    текстом, и следующий ответ обычно уже проходит.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError('steps должен быть массивом')
    if len(value) > BROWSER_AUTHOR_BATCH_LIMIT:
        raise ValueError(f'шагов за раз не больше {BROWSER_AUTHOR_BATCH_LIMIT}')

    steps: list[BrowserScenarioStep] = []

    for number, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f'шаг {number}: ожидается объект')
        try:
            steps.append(BrowserScenarioStep(**item))
        except Exception as e:
            raise ValueError(f'шаг {number} не прошёл проверку: {str(e).splitlines()[0]}')

    return steps


async def _verify(scenario: BrowserScenario, data: BrowserAuthorRequest) -> dict:
    """Проверочный прогон с нуля, в чистой сессии.

    Именно он решает, `active` сценарий или `draft`: в рабочей сессии автора уже
    выполнен вход и открыт нужный раздел, и сценарий, который молча на это
    опирается, здесь падает на первом же шаге.
    """
    return await browser_upstream_request('POST', '/browser/scenario/run', {
        'scenario': scenario.model_dump(),
        'session_id': '',
        'variables': data.variables,
        'secrets': data.secrets,
        'keep_session': False,
    }, timeout=BROWSER_UPSTREAM_SCENARIO_TIMEOUT)

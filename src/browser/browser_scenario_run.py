"""Прогон сценария: шаги выполняются здесь, в контейнере, где живут страницы.

Контейнер сценариев не хранит и в журнал не пишет — он отвечает трассой прогона
тому, кто попросил. Хранением и журналом занимается `uvicorn`, у которого уже есть
пул MySQL: второй потребитель базы дал бы контейнеру связность там, где он её
специально не имеет — упавшая база не должна ронять живые сессии.

Трасса возвращается **всегда**, и на ошибке тоже: без неё ответ «не сработало»
бесполезен, а с ней видно, на каком шаге и с чем встали — из этого агент этапа 7
и напишет задачу на переписывание сценария.
"""

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from logging_.logging_ import logger_info

from src.browser.browser_api import browser_api_auth
from src.browser.browser_pool import (
    browser_pool_session_close,
    browser_pool_session_get,
    browser_pool_session_open,
)
from src.browser.browser_scenario import (
    BrowserScenario,
    BrowserScenarioStep,
    browser_scenario_mask,
    browser_scenario_render,
    browser_scenario_step_target,
    browser_scenario_variables_missing,
)

router = APIRouter()

# Текст ошибки шага в трассе. Сообщения Playwright многострочные и с «call log»
# на полсотни строк — в журнале от него пользы нет, причина всегда в первых строках.
BROWSER_SCENARIO_RUN_ERROR_LIMIT = 500

# Набор текста посимвольно: 20 мс между клавишами. Мгновенный ввод не замечают
# поля с обработчиком на каждое нажатие — автодополнение, маска телефона.
BROWSER_SCENARIO_RUN_TYPE_DELAY_MS = 20


class BrowserScenarioRunRequest(BaseModel):
    """Что нужно для прогона: сам сценарий, где его крутить и с какими значениями."""

    scenario: BrowserScenario
    session_id: str = Field('', description='Пусто — завести временную сессию под прогон')
    variables: dict[str, str] = Field(default_factory=dict, description='Значения; попадают в журнал')
    secrets: dict[str, str] = Field(default_factory=dict, description='Значения; в журнал не попадают')
    keep_session: bool = Field(False, description='Не гасить временную сессию после прогона')


@router.post('/browser/scenario/run', dependencies=browser_api_auth)
async def browser_scenario_run_post(data: BrowserScenarioRunRequest):
    """Прогоняет сценарий и отвечает трассой.

    Код ответа — про сам запрос, а не про результат сценария: не тот `session_id`
    это 404, нехватка переменной — 422, а упавший на третьем шаге сценарий — 200
    со `status: error`. Иначе журнал прогонов пришлось бы собирать из кодов HTTP.
    """
    try:
        return await browser_scenario_run(
            data.scenario,
            session_id=data.session_id,
            variables=data.variables,
            secrets=data.secrets,
            keep_session=data.keep_session,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail='сессия не найдена')
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


async def browser_scenario_run(scenario: BrowserScenario, session_id: str = '',
                               variables: dict | None = None, secrets: dict | None = None,
                               keep_session: bool = False) -> dict:
    """Выполняет шаги по порядку и возвращает трассу прогона.

    Первый упавший шаг останавливает прогон: следующие шаги рассчитывают на то,
    что предыдущий сработал, и продолжать значило бы получить лавину ошибок вместо
    одной настоящей. Исключение — шаги с `optional`: баннер согласия может и не
    появиться, и его отсутствие не сбой.
    """
    variables = variables or {}
    secrets = secrets or {}
    values = {**variables, **secrets}

    missing = browser_scenario_variables_missing(scenario, values)
    if missing:
        raise ValueError(f'не переданы переменные: {", ".join(missing)}')

    entry, own_session = await _session_take(session_id, scenario.name)
    page = entry['page']
    started = time.monotonic()
    steps: list[dict] = []
    extract: dict[str, str] = {}
    status = 'ok'
    error = ''
    failed_no = 0
    final_url = ''

    try:
        for index, step in enumerate(scenario.steps, start=1):
            record = await _step_run(page, step, index, values, secrets)
            steps.append(record)

            if record['name'] and record['ok']:
                extract[record['name']] = record['value']

            if not record['ok']:
                status = 'error'
                error = record['error']
                failed_no = index
                break

        # Адрес снимается до закрытия сессии: у закрытой страницы его уже не спросить,
        # а «где мы оказались» — половина ответа на вопрос, сработал ли сценарий.
        final_url = page.url
        entry['used_at'] = time.time()
    finally:
        if own_session and not keep_session:
            await browser_pool_session_close(entry['session_id'])

    logger_info(f'[browser] сценарий «{scenario.name}»: {status}, шагов {len(steps)} из {len(scenario.steps)}')

    return {
        'status': status,
        'session_id': entry['session_id'],
        'session_kept': not own_session or keep_session,
        'url': final_url,
        'step_no': failed_no,
        'error': error,
        'steps': steps,
        'extract': extract,
        'duration_ms': round((time.monotonic() - started) * 1000),
    }


async def _session_take(session_id: str, name: str) -> tuple[dict, bool]:
    """Сессия прогона и признак «завели её мы».

    Свою сессию гасим после прогона, чужую — никогда: сценарий часто крутят на
    странице, которую человек в этот момент смотрит в `/admin/browser`.
    """
    if session_id:
        entry = browser_pool_session_get(session_id)
        if entry is None:
            raise KeyError(session_id)
        if entry['page'].is_closed():
            raise RuntimeError('страница сессии закрыта')
        return entry, False

    session = await browser_pool_session_open(name=f'сценарий: {name}'[:100])
    return browser_pool_session_get(session['session_id']), True


async def _step_run(page, step: BrowserScenarioStep, index: int, values: dict, secrets: dict) -> dict:
    """Один шаг с замером и разбором ошибки. Исключения наружу не выпускает:
    упавший шаг — это строка трассы, а не сбой прогона."""
    started = time.monotonic()
    value = ''
    ok = True
    error = ''

    try:
        value = await _step_apply(page, step, values)
    except Exception as e:
        ok = bool(step.optional)
        error = browser_scenario_mask(str(e), secrets).strip()[:BROWSER_SCENARIO_RUN_ERROR_LIMIT]

    return {
        'index': index,
        'action': step.action,
        # Цель — до подстановки: в журнале должно остаться `{{password}}`, а не пароль.
        'target': browser_scenario_step_target(step),
        'name': step.name,
        'ok': ok,
        'optional': step.optional,
        'error': error,
        'value': browser_scenario_mask(value, secrets),
        'ms': round((time.monotonic() - started) * 1000),
    }


async def _step_apply(page, step: BrowserScenarioStep, values: dict) -> str:
    """Действие шага. Возвращает то, что стоит показать в трассе.

    Всё идёт через `page.locator`: он сам ждёт появления элемента до таймаута,
    поэтому отдельный `wait_for` перед кликом не нужен. Строгость локатора —
    «два совпадения это ошибка» — оставлена действиям над одним элементом: клик по
    двум кнопкам сразу и правда бессмыслен. Действиям над списком (`wait_for`,
    `extract`) она мешает, и там берётся `.first` или все совпадения разом.
    """
    action = step.action
    timeout = step.timeout_ms
    selector = browser_scenario_render(step.selector, values)
    value = browser_scenario_render(step.value, values)

    if action == 'goto':
        await page.goto(browser_scenario_render(step.url, values),
                        wait_until='domcontentloaded', timeout=timeout)
        return page.url

    if action == 'click':
        await page.locator(selector).click(timeout=timeout)
        return ''

    if action == 'fill':
        await page.locator(selector).fill(value, timeout=timeout)
        return ''

    if action == 'type':
        locator = page.locator(selector)
        await locator.click(timeout=timeout)
        await locator.press_sequentially(value, delay=BROWSER_SCENARIO_RUN_TYPE_DELAY_MS, timeout=timeout)
        return ''

    if action == 'press':
        key = browser_scenario_render(step.key, values)
        if selector:
            await page.locator(selector).press(key, timeout=timeout)
        else:
            await page.keyboard.press(key)
        return ''

    if action == 'select':
        chosen = await page.locator(selector).select_option(value, timeout=timeout)
        return ', '.join(chosen)

    if action == 'wait_for':
        # `.first` по той же причине, что и в extract: ждут обычно появления списка,
        # а селектор списка совпадает со всеми его строками сразу. Строгий режим
        # Playwright счёл бы это ошибкой — «resolved to 70 elements» вместо ожидания.
        await page.locator(selector).first.wait_for(state='visible', timeout=timeout)
        return ''

    if action == 'wait_url':
        # Шаблон в стиле glob: `**/admin` совпадёт с любым хостом и портом.
        await page.wait_for_url(browser_scenario_render(step.url, values), timeout=timeout)
        return page.url

    if action == 'wait_ms':
        await page.wait_for_timeout(min(int(value), timeout))
        return ''

    if action == 'scroll':
        await page.mouse.wheel(0, int(value))
        return ''

    if action == 'extract':
        # Все совпадения, а не первое: собирают обычно список — строки таблицы,
        # пункты меню, карточки. По одному селектору строк несколько, и `inner_text`
        # на них падает строгим режимом Playwright вместо того, чтобы отдать список.
        # Ждать приходится отдельно: `all_inner_texts` не ждёт ничего и на ещё не
        # отрисованном списке молча вернул бы пусто.
        await page.locator(selector).first.wait_for(timeout=timeout)
        texts = [text.strip() for text in await page.locator(selector).all_inner_texts()]

        return '\n'.join(text for text in texts if text)

    if action == 'assert_text':
        text = (await page.locator(selector).inner_text(timeout=timeout)).strip()
        if value not in text:
            raise AssertionError(f'ожидалось «{value}», на странице «{text[:200]}»')
        return text

    raise ValueError(f'неизвестное действие: {action}')

"""Карта выходов подпотока на `/admin/workflow`: вкладки, правка, доезд до базы.

Проверять это можно только браузером: блок рисует JS уже после загрузки
(`subflow-maps.js`), в разметке шаблона его нет — `curl` увидит пустой
`#dynamicStepFieldsContainer`.

## ⚠⚠⚠ Что здесь главное

Не вкладки, а то, что правка **доезжает до метаданных шага**. Блок заведён
ровно потому, что `outputs_map` правилась только через базу, и беда была
молчаливой: карта есть, посмотреть нельзя, поправить нельзя.

⚠⚠ **Снос пары приходит кнопкой, а не полем.** Автосохранение страницы висит на
`change` и `focusout` колонки (`steps.js`), и клик по кнопке не даёт ни того, ни
другого. Поймано живым прогоном до этого теста: снос не доезжал до базы вовсе —
он появлялся там попутно, при следующем выборе в селекте. Чинит это событие
`workflow:step-dirty`, и вот тест, который держит его на месте.

## ⚠ Карта возвращается на место

Тест правит живой шаг живого workflow: другого способа проверить сохранение нет.
Исходная карта снимается до правки и возвращается `finally` — иначе упавший на
середине тест оставил бы ветку «письма и фото» без правки судьи.

## ⚠ Почему своя оснастка, а не общий слой

Застава предлагает `web_drive_page`, `web_unit_run`, `web_watch` — и этот разбор
для **этой же страницы** уже сделан в `test_workflow_prompt_modal.py`: первый
вынимает *встроенный* в страницу ES-модуль, а у `/admin/workflow` он внешний
(`/static/js/workflow/main.js`); второй гоняет тесты на инлайн-скрипте, третий
смотрит перемены разметки. Здесь к тому же нужен путь в два щелчка по спискам,
которые наполняет сервер, и проверка записи **в базе** после клика по кнопке.

## ⚠⚠ Сам этот тест не запускается в общем прогоне

Папки нет в `testpaths`, и правило проекта прямое: правишь страницу панели —
**предложи прогон и дождись ответа** (`tests_browser/conftest.py`).
"""

import json
import os

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Browser, Page, sync_playwright

from mysql_.mysql_query import mysql_query_run
from tests.constants import TEST_AUTH

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Шаг, на котором проверяем: вызов подпотока с непустой картой выходов.
#
# ⚠⚠ Берётся **по названию workflow и заголовку шага**, а номер вычисляется:
# номера у баз свои, и зашитый указал бы на чужой шаг. По тексту в списке шагов
# искать нельзя — `has_text` ловит и соседей, которые на этот шаг только
# ссылаются условием перехода (проверено: открывался не тот шаг).
WORKFLOW_NAME = 'dating_talk'
STEP_TITLE = 'Ветка: письма и фото'

# Автосохранение идёт с дебаунсом 400 мс (`stepAutoSaveFlush`); ждём с запасом.
SAVE_WAIT_MS = 2000


@pytest.fixture(scope='module')
def step_id() -> int:
    """Номер шага на этой установке. Нет такого — проверять нечего."""
    got = mysql_query_run(
        'SELECT ws.id FROM agent_workflow_step ws'
        ' JOIN agent_workflow w ON w.id = ws.workflow_id'
        ' WHERE w.name = %s AND ws.title = %s LIMIT 1',
        (WORKFLOW_NAME, STEP_TITLE))
    rows = got.get('rows') or []

    if not rows:
        pytest.skip(f'на установке нет шага «{STEP_TITLE}» у {WORKFLOW_NAME}')

    return int(rows[0]['id'])


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture(scope='module')
def page(browser: Browser):
    """Одна авторизованная вкладка на весь модуль: логин небыстрый."""
    context = browser.new_context(viewport={'width': 1700, 'height': 1100})
    tab = context.new_page()
    _login(tab)
    yield tab
    context.close()


@pytest.fixture
def maps(page: Page, step_id: int):
    """Открытый шаг с блоком карт. Карты возвращаются на место."""
    was = _maps_in_db(step_id)
    _open_step(page, step_id)

    try:
        yield page
    finally:
        _maps_to_db(step_id, was)


class TestTheBlockHasTwoTabs:
    """⚠ Две стороны договора с подпотоком — две вкладки одного блока."""

    def test_both_tabs_are_there(self, maps: Page):
        tabs = maps.locator('.subflow-tab')

        assert tabs.count() == 2, f'вкладок {tabs.count()}, ждали две'

    def test_the_tabs_count_what_is_set(self, maps: Page):
        """⚠⚠ Числа на вкладках: настроенная карта видна **с закрытой** вкладки.

        Без них человек не знает, что на соседней вкладке что-то есть, — а
        прежде её не было видно и с открытой.
        """
        tabs = maps.locator('.subflow-tab')

        assert '(' in tabs.nth(0).text_content(), 'на вкладке входящих нет счёта'
        assert '(' in tabs.nth(1).text_content(), 'на вкладке исходящих нет счёта'

    def test_inputs_show_first(self, maps: Page):
        """⚠ Открыт блок на входящих: так было до вкладок, и так привычнее."""
        assert maps.locator('.subflow-input-row').first.is_visible(), \
            'вкладка входящих закрыта при открытии'


class TestTheOutputMapIsShown:
    """⚠⚠ То, чего в UI не было вовсе: пары `outputs_map` живого шага."""

    def test_every_saved_pair_has_its_row(self, maps: Page, step_id: int):
        _outputs_tab(maps)
        saved = _maps_in_db(step_id)[1]
        shown = _rows_shown(maps)

        assert shown == saved, \
            f'на странице не та карта, что в базе: {shown} против {saved}'

    def test_the_always_there_result_is_shown_too(self, maps: Page):
        """⚠ Строка автоимени `%…_result_str%` — не карта, а то, что движок
        кладёт всегда. Стоит там, где человек ищет выходы шага.

        ⚠⚠ Искать надо **внутри колонки шага**: тот же класс `.variable-name`
        носят имена в списке переменных слева, и по всей странице их четырнадцать.
        """
        _outputs_tab(maps)
        inside = maps.locator('#dynamicStepFieldsContainer .variable-name')

        assert inside.filter(has_text='_result_str').count() == 1, \
            'строки автоимени результата в блоке карт нет'


class TestTheEditReachesTheDatabase:
    """⚠⚠⚠ Главное: правка доезжает до метаданных, а не только рисуется."""

    def test_dropping_a_pair_is_saved(self, maps: Page, step_id: int):
        """⚠⚠⚠ Снос приходит **кнопкой**, у которой нет события формы.

        Автосохранение слушает `change` и `focusout`; клик не даёт ни того, ни
        другого. До правки снос не доезжал до базы вовсе — появлялся там
        попутно, при следующем выборе в селекте. Держит это
        `workflow:step-dirty`.
        """
        _outputs_tab(maps)
        was = _maps_in_db(step_id)[1]

        if len(was) < 2:
            pytest.skip('в карте меньше двух пар — сносить нечего')

        gone = maps.locator('.subflow-output-row').first.locator(
            '.map-child-select').input_value()
        maps.locator('.subflow-output-row').first.locator('button').click()
        maps.wait_for_timeout(SAVE_WAIT_MS)

        became = _maps_in_db(step_id)[1]

        assert gone not in became, \
            f'снесённая пара `{gone}` осталась в метаданных: {became}'
        assert len(became) == len(was) - 1, f'снеслось не одно: {was} → {became}'

    def test_adding_a_pair_is_saved(self, maps: Page, step_id: int):
        """⚠ Новая пара: имя подпотока вписывается, переменная выбирается."""
        _outputs_tab(maps)
        picked = _some_parent_variable(maps)

        maps.locator('button:has-text("+ Переменная наружу")').click()
        maps.wait_for_timeout(300)

        fresh = maps.locator('.subflow-output-row').last
        fresh.locator('.map-child-select').fill('pytest_child_var')
        fresh.locator('.map-parent-select').select_option(picked)
        maps.wait_for_timeout(SAVE_WAIT_MS)

        became = _maps_in_db(step_id)[1]

        assert became.get('pytest_child_var') == picked, \
            f'новая пара не доехала до метаданных: {became}'

    def test_a_half_filled_row_stays_out(self, maps: Page, step_id: int):
        """⚠⚠ Нажал «добавить» и отвлёкся — в карту ничего не уехало.

        Пустое имя движок принял бы и написал в лог «не найдена в scope» — то
        есть беда была бы молчаливой.
        """
        _outputs_tab(maps)
        was = _maps_in_db(step_id)[1]

        maps.locator('button:has-text("+ Переменная наружу")').click()
        maps.wait_for_timeout(SAVE_WAIT_MS)

        assert _maps_in_db(step_id)[1] == was, 'пустая строка уехала в карту'


def _login(page: Page) -> None:
    """Вход через `/login`: поля `#username`/`#password`, редирект на `/`."""
    assert TEST_AUTH['password'], \
        'QA_PASSWORD не задан ни в окружении, ни в .env.local — авторизоваться нечем'

    page.goto(f'{BASE_URL}/login')
    page.wait_for_selector('#username', state='visible', timeout=10000)
    page.fill('#username', TEST_AUTH['username'])
    page.fill('#password', TEST_AUTH['password'])
    page.click('#loginBtn')
    page.wait_for_url(f'{BASE_URL}/', timeout=10000)


def _open_step(page: Page, step_id: int) -> None:
    """Открывает workflow по номеру и шаг по `data-id`.

    ⚠ Workflow — номером в адресе: список слева показывает `title` («Чат»), а не
    `name`, и по имени его там не найти.
    """
    got = mysql_query_run('SELECT workflow_id FROM agent_workflow_step WHERE id = %s',
                          (step_id,))
    workflow_id = int(got['rows'][0]['workflow_id'])

    page.goto(f'{BASE_URL}/admin/workflow?workflow_id={workflow_id}')
    page.wait_for_selector('.step-item-block', state='visible', timeout=10000)
    page.locator(f'.step-item-block[data-id="{step_id}"]').first.click()

    # ⚠⚠ Ждём **строку**, а не вкладку: вкладки рисуются сразу, а наполняются
    # после загрузки переменных подпотока (два запроса). Поймано гонкой — тест
    # читал заголовок «Входящие» до того, как к нему приписался счёт.
    page.wait_for_selector('.subflow-input-row', state='visible', timeout=10000)
    page.wait_for_function(
        "() => (document.querySelector('.subflow-tab')?.textContent || '').includes('(')",
        timeout=10000)


def _outputs_tab(page: Page) -> None:
    """Переключиться на «Исходящие»."""
    page.locator('.subflow-tab').nth(1).click()
    page.wait_for_timeout(300)


def _rows_shown(page: Page) -> dict:
    """Пары, которые видно в блоке: `{переменная подпотока: переменная родителя}`."""
    rows = page.locator('.subflow-output-row')

    return {rows.nth(i).locator('.map-child-select').input_value():
            rows.nth(i).locator('.map-parent-select').input_value()
            for i in range(rows.count())}


def _some_parent_variable(page: Page) -> str:
    """Любая переменная, которую селект родителя вправду предлагает.

    ⚠ Не зашитое имя: снесённая пара уносит из реестра и переменную, которую она
    клала, — выбор несуществующего варианта повис бы до таймаута.
    """
    options = page.locator('.subflow-output-row').first.locator(
        '.map-parent-select option')
    names = [options.nth(i).get_attribute('value') for i in range(options.count())]
    picked = next((one for one in names if one), None)

    assert picked, 'селект родительской переменной пуст — выбирать нечего'

    return picked


def _maps_in_db(step_id: int) -> tuple:
    """Обе карты шага из метаданных: `(inputs_map, outputs_map)`."""
    got = mysql_query_run('SELECT metadata FROM agent_workflow_step WHERE id = %s',
                          (step_id,))
    invoke = (json.loads(got['rows'][0]['metadata'] or '{}')
              .get('workflow_invoke') or {})

    return invoke.get('inputs_map') or {}, invoke.get('outputs_map') or {}


def _maps_to_db(step_id: int, maps: tuple) -> None:
    """Вернуть карты как было.

    ⚠ Правится только `workflow_invoke`: остальных метаданных шага тест не
    касался, и переписывать их целиком значило бы затереть чужую правку, если
    она случилась между открытием и уборкой.
    """
    got = mysql_query_run('SELECT metadata FROM agent_workflow_step WHERE id = %s',
                          (step_id,))
    meta = json.loads(got['rows'][0]['metadata'] or '{}')
    meta.setdefault('workflow_invoke', {})
    meta['workflow_invoke']['inputs_map'], meta['workflow_invoke']['outputs_map'] = maps

    mysql_query_run('UPDATE agent_workflow_step SET metadata = %s WHERE id = %s',
                    (json.dumps(meta, ensure_ascii=False), step_id))

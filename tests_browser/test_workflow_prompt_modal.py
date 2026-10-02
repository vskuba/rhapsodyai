"""Большое окно промпта на `/admin/workflow`: иконка, окно, сохранение при закрытии.

Проверять это можно только браузером: поле шага и иконку рисует JS уже после загрузки
(`step-widgets.js`), в разметке шаблона их нет — `curl` увидит пустой контейнер
`#dynamicStepFieldsContainer`.

## ⚠⚠ Что здесь главное

Не то, что окно открылось, а что **текст доехал до сервера**. Окно своего сохранения не
имеет намеренно: оно пишет в исходную `textarea` и пинает её теми же событиями,
которыми живёт страница (`input` → метаданные шага, `focusout` → отправка). Сломайся
эта связь — окно выглядело бы работающим, а правка терялась бы при переключении шага.

⚠ Поэтому последняя проверка перечитывает шаг **из базы через ручку**, а не смотрит в
поле на странице.

## ⚠ Текст возвращается на место

Тест правит живой шаг живого workflow: другого способа проверить сохранение нет.
Исходный текст снимается до правки и возвращается `finally` — иначе упавший на середине
тест оставил бы промпт со своей пометкой.

## ⚠ Почему своя оснастка, а не общий слой

Застава предлагает `web_drive_page`, `web_unit_run`, `web_watch` — здесь не подходят.
Первый вынимает **встроенный** в страницу ES-модуль и подключает его к разметке; у
`/admin/workflow` модуль внешний (`/static/js/workflow/main.js`), а путь до поля — два
щелчка по спискам, которые наполняет сервер. Второй гоняет тесты на инлайн-скрипте,
третий смотрит, что скрипты поменяли. Нужна живая страница со своей навигацией — то,
для чего в проекте и заведена `tests_browser/` со своим `conftest`.

## ⚠⚠ Сам этот тест не запускается в общем прогоне

Папки нет в `testpaths`, и правило проекта прямое: правишь страницу панели — **предложи
прогон и дождись ответа** (`tests_browser/conftest.py`).
"""

import os
import uuid

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Browser, Page, sync_playwright

from mysql_.mysql_query import mysql_query_run
from tests.constants import TEST_AUTH

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Шаг, на котором проверяем. ⚠ Берётся **по названию**, а не по номеру: номера у баз
# свои, и на другой установке номер указал бы на чужой шаг.
WORKFLOW_NAME = 'dating_talk'
STEP_TITLE = 'Ответ в чат'

# Иконка узнаётся по подсказке: класса у неё нет намеренно — страница живёт на
# встроенных стилях, и класс пришлось бы заводить только ради теста.
ICON = 'button[title="Открыть в большом окне"]'

# Кнопка выхода из окна — по своему тексту: класса у неё тоже нет.
DONE = 'button:has-text("Закрыть и сохранить")'

# Отправка шага идёт с дебаунсом 400 мс (`stepAutoSaveFlush`); ждём с запасом на сеть.
SAVE_WAIT_MS = 1500


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture(scope='module')
def page(browser: Browser):
    """Одна авторизованная вкладка на весь модуль: логин небыстрый."""
    context = browser.new_context(viewport={'width': 1600, 'height': 1000})
    tab = context.new_page()
    _login(tab)
    yield tab
    context.close()


@pytest.fixture
def step(page: Page):
    """Открытый шаг с полем User prompt. Текст возвращается на место."""
    _open_step(page)
    field = page.locator('#field_prompt_user')
    was = field.input_value()

    try:
        yield field
    finally:
        # ⚠ Возвращаем через саму страницу, а не ручкой: той же дорогой, какой правил
        # тест, — иначе восстановление шло бы путём, которым человек не ходит.
        field.fill(was)
        field.blur()
        page.wait_for_timeout(SAVE_WAIT_MS)


class TestTheIconIsNextToTheLabel:
    """⚠ Иконка — в одной строке с подписью поля, справа."""

    def test_the_icon_is_there(self, step):
        assert step.page.locator(ICON).count() == 1, \
            'иконки большого окна рядом с подписью нет'

    def test_the_icon_is_right_of_the_label(self, step):
        """⚠ «Справа» проверяется координатами, а не стилем: `justify-content` можно
        задать и не получить — если ряд не растянут, иконка встанет вплотную."""
        page = step.page
        label = page.locator('#dynamicStepFieldsContainer label').filter(
            has_text='User prompt').first

        assert page.locator(ICON).first.bounding_box()['x'] \
            > label.bounding_box()['x'], 'иконка стоит слева от подписи'

    def test_the_icon_is_on_the_label_line(self, step):
        """⚠ В одной строке, а не над полем: иначе ряд рассыпался в столбец."""
        page = step.page
        label = page.locator('#dynamicStepFieldsContainer label').filter(
            has_text='User prompt').first
        icon = page.locator(ICON).first

        assert abs(icon.bounding_box()['y'] - label.bounding_box()['y']) < 12, \
            'иконка и подпись на разных строках'

    def test_the_icon_is_coloured(self, step):
        """⚠ Цветная, а не серая: серую иконку рядом с подписью не замечают, и о
        большом окне никто не узнаёт — а ради него всё и делалось."""
        page = step.page
        colour = page.locator(ICON).first.evaluate(
            'el => getComputedStyle(el).color')

        assert colour not in ('rgb(74, 85, 104)', 'rgb(0, 0, 0)'), \
            f'иконка серого цвета: {colour}'

    def test_only_the_text_field_has_it(self, step):
        """⚠ Иконка только у текстового поля: у чекбоксов и селектов окно ни к чему."""
        assert step.page.locator(ICON).count() == 1, \
            'иконка появилась не только у промпта'


class TestTheWindowShowsTheSameText:
    """⚠⚠ В окне тот же текст, и оно занимает почти весь экран."""

    def test_the_text_matches(self, step):
        was = step.input_value()
        step.page.locator(ICON).first.click()

        assert _big(step.page).input_value() == was, \
            'в окне не тот текст, что в поле'

    def test_the_window_is_large(self, step):
        """⚠ Ради этого всё и делалось: в колонке поле высотой 170 пикселей."""
        small = step.bounding_box()
        step.page.locator(ICON).first.click()
        big = _big(step.page).bounding_box()

        assert big['width'] > small['width'] * 2, \
            f"окно не шире колонки: {big['width']} против {small['width']}"
        assert big['height'] > small['height'] * 2, \
            f"окно не выше поля: {big['height']} против {small['height']}"


class TestClosingSaves:
    """⚠⚠⚠ Главное: щелчок в сторону закрывает окно **и сохраняет** текст."""

    def test_a_click_aside_closes_it(self, step):
        page = step.page
        page.locator(ICON).first.click()
        page.wait_for_timeout(200)
        _aside(page)

        assert not _window(page).count(), 'окно не закрылось'

    def test_a_click_inside_keeps_it_open(self, step):
        """⚠ Сторож обратного: выделение текста мышью не должно закрывать окно.

        Ровно поэтому закрытие висит на цели события (`e.target === back`), а не на
        любом щелчке по подложке: отпустил кнопку над краем поля — и окно исчезло бы
        вместе с правкой.
        """
        page = step.page
        page.locator(ICON).first.click()
        page.wait_for_timeout(200)

        box = _big(page).bounding_box()
        page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        page.wait_for_timeout(200)

        assert _window(page).count() == 1, 'окно закрылось от щелчка внутри себя'

    def test_the_button_closes_and_saves(self, step):
        """⚠⚠ Третий путь выхода — кнопка, и он обязан сохранять так же.

        Прежде здесь стояла подсказка словами («щелчок вне окна или Esc»): правда, но
        её надо прочитать и поверить. Кнопка отвечает действием — и зовёт **то же**
        закрытие, а не своё сохранение: разойдись они, один путь сохранял бы, другой
        нет, и заметить это можно было бы только потерянной правкой.
        """
        page = step.page
        mark = f'проба-{uuid.uuid4().hex[:6]}'

        page.locator(ICON).first.click()
        _big(page).fill(mark)
        page.locator(DONE).first.click()
        page.wait_for_timeout(SAVE_WAIT_MS)

        assert not _window(page).count(), 'кнопка не закрыла окно'
        assert step.input_value() == mark, 'текст из окна не попал в поле'
        assert mark in _step_metadata(page), 'правка кнопкой не доехала до сервера'

    def test_escape_closes_it_too(self, step):
        page = step.page
        page.locator(ICON).first.click()
        page.wait_for_timeout(200)
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)

        assert not _window(page).count(), 'Esc не закрыл окно'

    def test_the_edit_reaches_the_field(self, step):
        page = step.page
        mark = f'проба-{uuid.uuid4().hex[:6]}'

        page.locator(ICON).first.click()
        _big(page).fill(mark)
        _aside(page)

        assert step.input_value() == mark, 'текст из окна не попал в поле шага'

    def test_the_edit_reaches_the_server(self, step):
        """⚠⚠ Перечитываем шаг **из базы**, а не из поля: окно могло обновить страницу
        и не дойти до сервера — ровно та беда, которую тест и ищет."""
        page = step.page
        mark = f'проба-{uuid.uuid4().hex[:6]}'

        page.locator(ICON).first.click()
        _big(page).fill(mark)
        _aside(page)
        page.wait_for_timeout(SAVE_WAIT_MS)

        assert mark in _step_metadata(page), \
            'правка из окна не доехала до сервера'


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


def _open_step(page: Page) -> None:
    """Открывает нужный workflow и шаг в нём — по названию workflow и шага.

    ## ⚠⚠⚠ Навигация была сломана, и все 13 тестов падали на первом же шаге

    Селектор списка слева — `.workflow-item` — в коде отсутствует **вовсе**: имя
    класса сменилось на `.agent-item` (`main.js`), и тест ждал элемент, которого
    нет, десять секунд, а потом падал ошибкой фикстуры. Красного никто не видел:
    папка вне `testpaths`, запуск только руками.

    ⚠ Поэтому workflow открывается **номером в адресе**: имени в списке слева
    нет совсем — там `title` («Чат»), а `name` (`dating_talk`) живёт только в
    базе, и `has_text` по нему не найдёт ничего.

    ⚠⚠ Шаг — по `data-id`, а не по заголовку: `has_text` ловит и соседей,
    которые на этот шаг только ссылаются условием перехода. Проверено на
    соседнем тесте: по тексту открывался не тот шаг.
    """
    got = mysql_query_run(
        'SELECT ws.id, ws.workflow_id FROM agent_workflow_step ws'
        ' JOIN agent_workflow w ON w.id = ws.workflow_id'
        ' WHERE w.name = %s AND ws.title = %s LIMIT 1',
        (WORKFLOW_NAME, STEP_TITLE))
    rows = got.get('rows') or []

    if not rows:
        pytest.skip(f'на установке нет шага «{STEP_TITLE}» у {WORKFLOW_NAME}')

    page.goto(f'{BASE_URL}/admin/workflow?workflow_id={rows[0]["workflow_id"]}')
    page.wait_for_selector('.step-item-block', state='visible', timeout=10000)
    page.locator(f'.step-item-block[data-id="{rows[0]["id"]}"]').first.click()
    page.wait_for_selector('#field_prompt_user', state='visible', timeout=10000)


def _window(page: Page):
    """Само окно — по подложке во весь экран."""
    return page.locator('div[style*="position: fixed"][style*="z-index: 9999"]')


def _big(page: Page):
    """Большая textarea внутри окна."""
    return _window(page).locator('textarea').first


def _aside(page: Page) -> None:
    """Щёлкнуть в сторону — по левому краю подложки, мимо самого окна."""
    page.mouse.click(10, 500)
    page.wait_for_timeout(200)


def _step_metadata(page: Page) -> str:
    """Метаданные открытого шага, прочитанные с сервера ручкой workflow."""
    workflow_id = page.locator('#workflowId').input_value()
    step_id = page.locator('.step-item-block.active').first.get_attribute('data-id')

    # ⚠⚠ Ручка называется `/steps`, а не `/step`: на единственном числе сервер
    # отвечает `405 Method Not Allowed` — там живёт только `POST` создания. Тест
    # ходил по ней и падал, но красного никто не видел: папка вне `testpaths`.
    got = page.request.get(f'{BASE_URL}/workflow/{workflow_id}/steps')
    assert got.ok, f'шаги не прочитались: {got.status}'

    # ⚠ Ответ лежит в `result` — общий контракт ручек проекта. Прежние `data` и
    # `steps` не отдаёт ни одна, и цикл молча не находил ничего.
    for one in got.json().get('result') or []:
        if str(one.get('id')) == str(step_id):
            return str(one.get('metadata') or '')

    raise AssertionError(f'шаг {step_id} не нашёлся в ответе ручки')


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

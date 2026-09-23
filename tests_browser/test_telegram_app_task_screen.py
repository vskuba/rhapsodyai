"""
Задачи доезжают до экрана мини-приложения и делятся по вкладкам-ролям (#6441).

Прежняя проверка (`test_telegram_app_task_wiring.py`) подменяла ответ
`/telegram-app/tasks` заглушкой: она держала подключение модулей и каркас вкладок,
но список из базы — нет, и на живом экране карточек не было. Здесь тот же экран
открывается без подмен: страница, статика и задачи приходят с сервера
(`task_server.sh up`), а задачи в базе — настоящие.

Цель читается двумя способами, и нужны оба:
  * набор карточек на вкладке совпадает с тем, что фильтрует `tasks.js` по строкам
    ответа сервера, — значит фильтр жив и считает не пустоту;
  * переключение вкладки меняет набор карточек, — значит четыре роли рисуют не
    один и тот же список.

Требуется chromium и запущенный сервер на `BASE_URL` (по умолчанию :8011,
для подзадачи — `BASE_URL=http://localhost:8013`).
"""

import os

import pytest

pytest.importorskip('playwright', reason='проверка нарисованного требует chromium')

from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402


pytestmark = pytest.mark.telegram

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')
ADMIN_ACCESS_TOKEN = "a0000000-1111-4444-bbbb-000000000001"

# Подписи вкладок — ролями, те же, что на странице задач (`PHASE_TAB_TITLES`).
PHASE_TABS = {
    'planning': 'Менеджер',
    'development': 'Разработчик',
    'testing': 'Тестировщик',
    'bugs': 'Багфиксер',
}

# Номера типов из `project_task_type` — зеркало `PHASE_TYPE_IDS` (`tasks.js`).
PHASE_TYPE_IDS = {'planning': (4, 5), 'development': (1,), 'testing': (3,), 'bugs': (2,)}


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser: Browser):
    """Открытое мини-приложение под сессией владельца: вкладка открывается кликом."""
    context = browser.new_context()
    tab = context.new_page()
    _open_as_owner(tab)
    tab.click('#tabBtnTasks')
    tab.wait_for_selector('#tab-tasks.active')
    try:
        yield tab
    finally:
        context.close()


class TestTasksOnScreen:
    """Живой экран: карточки из базы, вкладки-роли, переключение между ними."""

    def test_tasks_from_database_land_on_the_tab(self, page: Page):
        """Карточки рисуются ответом сервера: номер и заголовок настоящей задачи."""
        expected = _phase_ids(_server_tasks(page), _current_phase(page))
        page.wait_for_function(_counter_is(len(expected)), timeout=15000)

        drawn = _card_ids(page)
        assert drawn == set(expected), (
            f'карточки разошлись со списком сервера: лишние {drawn - set(expected)}, '
            f'нет {set(expected) - drawn}')
        assert drawn, 'ни одной карточки — вкладка открыта, а задач не видно'

    def test_role_tabs_are_drawn_with_the_admin_page_labels(self, page: Page):
        """Четыре вкладки — роли конвейера, названные теми же словами, что на /admin/task."""
        tabs = page.locator('#tab-tasks .task-phase-tab')
        assert tabs.count() == len(PHASE_TABS)
        keys = [tabs.nth(i).get_attribute('data-phase') for i in range(tabs.count())]
        assert keys == list(PHASE_TABS)
        texts = [tabs.nth(i).inner_text() for i in range(tabs.count())]
        assert texts == list(PHASE_TABS.values())

    def test_switching_role_tab_refilters_the_same_list(self, page: Page):
        """Переключение роли делит список: набор карточек меняется, а не остаётся тем же."""
        tasks = _server_tasks(page)
        seen = {}
        for phase in PHASE_TABS:
            page.click(f'.task-phase-tab[data-phase="{phase}"]')
            expected = _phase_ids(tasks, phase)
            page.wait_for_function(_counter_is(len(expected)), timeout=15000)
            seen[phase] = _card_ids(page)
            assert seen[phase] == set(expected), f'{phase}: вкладка показала не свой набор'

        # Закрытая работа живёт у тестировщика, открытая — у своего типа; поэтому хотя
        # бы две вкладки обязаны показать разные наборы. Один и тот же список на
        # четырёх вкладках означал бы, что фильтр не работает.
        distinct = {frozenset(v) for v in seen.values()}
        assert len(distinct) > 1, f'все вкладки показывают один и тот же список: {seen}'

    def test_empty_phase_says_so_instead_of_falling_silent(self, page: Page):
        """Пустая вкладка объясняет пустоту — так «здесь нет задач» отличается от «список не пришёл»."""
        tasks = _server_tasks(page)
        empty_phases = [ph for ph in PHASE_TABS if not _phase_ids(tasks, ph)]
        if not empty_phases:
            pytest.skip('на всех четырёх вкладках есть задачи — пустого состояния не видно')

        phase = empty_phases[0]
        page.click(f'.task-phase-tab[data-phase="{phase}"]')
        page.wait_for_selector('#tasksListView .empty-state', timeout=15000)
        assert page.locator('#tasksListView .task-card').count() == 0
        assert PHASE_TABS[phase] in page.locator('#tasksListView .empty-state').inner_text()

    def test_card_shows_status_and_pipeline_state(self, page: Page):
        """В карточке видны статус и состояние конвейера — то, чем задачу отслеживают."""
        tasks = _server_tasks(page)
        page.wait_for_function(_counter_is(len(_phase_ids(tasks, _current_phase(page)))),
                               timeout=15000)
        assert page.locator('#tab-tasks .task-status-chip').count(), 'чипса статуса нет'

        with_state = [ph for ph in PHASE_TABS
                      if any(t.get('pipeline_state') and t['pipeline_state'] != 'none'
                             for t in tasks if _task_in_phase(t, ph))]
        if not with_state:
            pytest.skip('в базе нет задач с состоянием конвейера — чипсу показывать нечего')

        phase = with_state[0]
        page.click(f'.task-phase-tab[data-phase="{phase}"]')
        expected = _phase_ids(tasks, phase)
        page.wait_for_function(_counter_is(len(expected)), timeout=15000)
        chips = page.locator('#tab-tasks .task-pipeline-chip')
        assert chips.count(), f'{phase}: состояние конвейера на экран не вышло'


def _open_as_owner(page: Page) -> None:
    """Открыть мини-приложение с токеном в query — тем же путём, что идёт Telegram WebView.

    `app.js` читает `access_token` из адреса и сам постит его на `/telegram-app/auth`;
    без успешного входа `init()` выходит и до `initTasks()` не доходит, поэтому вход —
    часть проверки экрана, а не обвязка. Post вручную здесь не годится: сессионную
    cookie заводит именно страница, и запрос в обход неё её не видит.
    """
    page.goto(f'{BASE_URL}/telegram-app?access_token={ADMIN_ACCESS_TOKEN}')
    # Вход — по иконке вкладки: она рисуется только после успешного `init()`.
    page.wait_for_selector('#tabBtnTasks', timeout=15000)


def _server_tasks(page: Page) -> list:
    """Строки списка, которые отдаёт сервер, — тот же ответ читает `tasks.js`."""
    response = page.request.get(f'{BASE_URL}/telegram-app/tasks')
    assert response.status == 200, f'список задач не пришёл: {response.status}'
    return response.json()['result']['tasks']


def _task_in_phase(task: dict, phase: str) -> bool:
    """Зеркало `taskInPhase` (`tasks.js`) — сверять экран с тем же правилом, а не с догадкой."""
    type_id = task.get('task_type_id')
    if task.get('status') == 'done' or task.get('pipeline_state') == 'done':
        return phase == ('bugs' if type_id == 2 else 'testing')
    # Типа нет (задача заведена до справочника или строка после `ON DELETE SET NULL`) —
    # вкладка разработчика, как на странице задач (`task.html:2349`).
    if type_id is None:
        return phase == 'development'
    return type_id in PHASE_TYPE_IDS[phase]


def _phase_ids(tasks: list, phase: str) -> list:
    return [t['id'] for t in tasks if _task_in_phase(t, phase)]


def _current_phase(page: Page) -> str:
    active = page.locator('#tab-tasks .task-phase-tab.active')
    return active.get_attribute('data-phase') if active.count() else 'planning'


def _card_ids(page: Page) -> set:
    """Номера карточек на вкладке — одним снимком DOM, без перебора локатора."""
    return set(page.eval_on_selector_all(
        '#tab-tasks .task-card',
        'els => els.map(el => Number(el.dataset.id))'))


def _counter_is(expected: int) -> str:
    return f'document.querySelectorAll("#tab-tasks .task-card").length === {expected}'

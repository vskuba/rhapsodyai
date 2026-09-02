"""
Вкладка «Задачи» собрана на экране: иконка, каркас, подключение модулей (#6441).

Соседняя проверка (`test_telegram_app_task_ui.py`) подкладывает каркас сама — ей важно
поведение панелей. Здесь же проверяется противоположное: страница, которую отдаёт
`/telegram-app`, уже содержит вкладку и контейнер `tasksListView`, а `app.js` вызывает
`initTasks()`. Пока этого нет, `initTasks` выходит по раннему возврату и вкладки по
ролям на экране не видно, хотя рисует их готовый `tasks.js`.

Страница грузится целиком, как её видит браузер: шаблон с диска, статика с диска,
ответы сервера подменены (`page.route`) — прокси-точек задач рисует соседняя подзадача,
и без них вкладка обязана открыться пустым состоянием, а не падением.

Требуется chromium; сервер и БД не нужны.
"""

import json
import os

import pytest

pytest.importorskip('playwright', reason='проверка нарисованного требует chromium')

from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402

TEMPLATE = os.path.join('data', 'uvicorn', 'template', 'telegram_app.html')
PUBLIC_DIR = os.path.join('data', 'uvicorn', 'public')
MODULES = ('tasks.js', 'questions.js', 'flags.js')

# Подпись вкладки — та же, что на админской странице задач (`PHASE_TAB_TITLES`).
ROLE_TABS = ('planning', 'development', 'testing', 'bugs')
ROLE_LABELS = ('Менеджер', 'Разработчик', 'Тестировщик', 'Багфиксер')

TASK_DEV = {
    'id': 8101, 'title': 'wiring: разработка идёт', 'status': 'active',
    'pipeline_state': 'none', 'task_type_id': 1, 'parent_id': None,
    'project_id': 21, 'metadata': {},
}
TASK_PLAN = {**TASK_DEV, 'id': 8102, 'title': 'wiring: план ждёт', 'task_type_id': 5}


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


class TestTasksWiring:
    """Иконка, каркас вкладки и подключение модуля — то, без чего панель не видна."""

    def test_icon_is_tasks_not_plans(self, browser: Browser):
        """В сайдбаре иконка «Задачи» с `data-tab="tasks"`; плановой кнопки больше нет.

        Цель задачи — замена иконки: по ней человек попадает на вкладку, поэтому
        проверяется и появление новой, и исчезновение прежней.
        """
        page = _open_page(browser)
        try:
            btn = page.locator('#tabBtnTasks')
            assert btn.count() == 1
            assert btn.get_attribute('data-tab') == 'tasks'
            assert 'Задач' in (btn.get_attribute('title') or '')
            assert page.locator('#tabBtnPlans').count() == 0
            assert page.locator('#tab-plans').count() == 0
        finally:
            page.context.close()

    def test_click_draws_role_tabs(self, browser: Browser):
        """Клик по иконке открывает вкладку с четырьмя подписями — ролями конвейера."""
        page = _open_page(browser, tasks=[TASK_DEV])
        try:
            page.click('#tabBtnTasks')
            page.wait_for_selector('#tab-tasks.active .task-phase-tab')

            tabs = page.locator('#tab-tasks .task-phase-tab')
            assert tabs.count() == len(ROLE_TABS)
            drawn = [tabs.nth(i).get_attribute('data-phase') for i in range(len(ROLE_TABS))]
            assert drawn == list(ROLE_TABS)
            texts = [tabs.nth(i).inner_text() for i in range(len(ROLE_TABS))]
            assert texts == list(ROLE_LABELS), 'подписи сверяются с админской страницей задач'

            header = page.locator('#pageHeaderTitle').inner_text()
            assert 'Задач' in header, 'заголовок вкладки называется тем же словом'
        finally:
            page.context.close()

    def test_card_lands_on_the_tab_and_roletab_switches_it(self, browser: Browser):
        """Карточка грузится на вкладку, а переключение по роли делит список по типу.

        Без подключения `initTasks` здесь пусто: ранний возврат по отсутствующему
        контейнеру — тот самый случай, который ловит эта проверка.
        """
        page = _open_page(browser, tasks=[TASK_DEV, TASK_PLAN])
        try:
            page.click('#tabBtnTasks')
            page.wait_for_selector('#tab-tasks .task-card')

            # Открыта «Менеджер»: plan(5) здесь, dev(1) — нет.
            assert _cards(page, 'wiring: план ждёт') == 1
            assert _cards(page, 'wiring: разработка идёт') == 0

            page.click('.task-phase-tab[data-phase="development"]')
            page.wait_for_function(_card_counter('wiring: разработка идёт', 1))
            assert _cards(page, 'wiring: разработка идёт') == 1
            assert _cards(page, 'wiring: план ждёт') == 0
        finally:
            page.context.close()

    def test_tab_opens_without_the_tasks_endpoint(self, browser: Browser):
        """Точку списка рисует соседняя подзадача: без неё вкладка открывается и не падает.

        Пустое состояние вместо карточек — единственный честный ответ; красная ошибка в
        консоли означала бы, что подключение вкладки держится на живом роутере.
        """
        page = _open_page(browser, tasks=None)
        try:
            page.click('#tabBtnTasks')
            page.wait_for_selector('#tab-tasks.active')
            assert page.locator('#tasksListView').count() == 1
            assert page.locator('#tab-tasks .task-phase-tab').count() == len(ROLE_TABS)
        finally:
            page.context.close()

    def test_modules_are_loaded_by_the_page(self, browser: Browser):
        """Модули вкладки запрошены страницей: мёртвый файл обещает поведение, которого нет."""
        seen: list = []
        page = _open_page(browser, tasks=[TASK_PLAN], scripts=seen)
        try:
            page.click('#tabBtnTasks')
            page.wait_for_selector('#tab-tasks .task-card')
            assert set(MODULES) <= set(seen), f'модули не загружаются: {set(MODULES) - set(seen)}'
        finally:
            page.context.close()

    def test_plans_module_is_off_the_page(self, browser: Browser):
        """`plans.js` сошёл с экрана: страница его не тянет, плановые поля не создаёт.

        Вкладка Планов ушла с иконкой; оставленное подключение грузило бы мёртвый модуль
        и рисовало поля ввода, которым нечего показывать.
        """
        seen: list = []
        page = _open_page(browser, tasks=[TASK_PLAN], scripts=seen)
        try:
            page.click('#tabBtnTasks')
            page.wait_for_selector('#tab-tasks .task-card')
            assert 'plans.js' not in seen
            assert page.locator('#planInputBar, #planCreateBar').count() == 0
        finally:
            page.context.close()


def _open_page(browser: Browser, tasks: list | None = None, scripts: list | None = None) -> Page:
    """Открыть настоящий шаблон мини-приложения с подменёнными ответами сервера."""
    context = browser.new_context()
    page = context.new_page()
    # 404 на подменённых точках — намеренный ответ, а не поломка кода: консольные
    # сообщения об этом пропускаем, настоящие ошибки приходят отдельным `pageerror`.
    page.on('console', lambda msg: pytest.fail(f'ошибка в консоли: {msg.text}')
            if msg.type == 'error' and 'Failed to load resource' not in msg.text else None)
    page.on('pageerror', lambda err: pytest.fail(f'непойманная ошибка скрипта: {err}'))
    _attach_routes(page, tasks, scripts)
    page.goto('http://mini.test/telegram-app')
    return page


def _attach_routes(page: Page, tasks: list | None, scripts: list | None) -> None:
    """Статика и шаблон — с диска; данные — из аргументов, остальное 404."""

    def handle(route):
        path = route.request.url.split('?')[0].replace('http://mini.test', '')

        if path.startswith('/static/'):
            _route_static(route, path[len('/static/'):])
        elif path == '/telegram-app':
            with open(TEMPLATE, encoding='utf-8') as fh:
                route.fulfill(status=200, content_type='text/html; charset=utf-8',
                              body=fh.read())
        elif path.endswith('/auth'):
            # Без успешной авторизации `app.js` выходит из `init()` и до вкладки не доходит.
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True}))
        elif path == '/telegram-app/config':
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'result': {}}))
        elif path == '/telegram-app/ping':
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True}))
        elif path == '/events':
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'result': []}))
        elif path == '/telegram-app/tasks':
            # `tasks=None` — точки нет вовсе (её рисует соседняя подзадача).
            if tasks is None:
                route.fulfill(status=404, content_type='application/json',
                              body=json.dumps({'detail': 'точку списка рисует сосед'}))
            else:
                route.fulfill(status=200, content_type='application/json',
                              body=json.dumps({'result': {'tasks': tasks}}))
        else:
            route.fulfill(status=404, content_type='application/json',
                          body=json.dumps({'detail': f'нет точки {path}'}))

        if scripts is not None and path.endswith('.js'):
            scripts.append(path.rsplit('/', 1)[-1])

    page.route('**/*', handle)


def _route_static(route, rel: str) -> None:
    full = os.path.abspath(os.path.join(PUBLIC_DIR, rel))
    if not full.startswith(os.path.abspath(PUBLIC_DIR)) or not os.path.isfile(full):
        route.fulfill(status=404, body=f'нет файла {rel}')
        return
    content_type = ('text/javascript; charset=utf-8' if rel.endswith('.js')
                    else 'text/css; charset=utf-8')
    with open(full, encoding='utf-8') as fh:
        route.fulfill(status=200, content_type=content_type, body=fh.read())


def _cards(page: Page, title: str) -> int:
    """Сколько карточек с таким заголовком на открытой вкладке — счёт по тексту."""
    return page.locator(f'#tab-tasks .task-card:has-text("{title}")').count()


def _card_counter(title: str, expected: int) -> str:
    return ("() => [...document.querySelectorAll('#tab-tasks .task-card')]"
            f".filter(el => el.textContent.includes({json.dumps(title)})).length === {expected}")

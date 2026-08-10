"""
Браузерные тесты страниц `/admin/team` и `/admin/task` (Playwright, sync API).

Проверяется именно то, что рисует JS, а не разметка шаблона: карточки команды и
селект типов задач наполняются из `/api/team` и `/api/team/types` уже после
загрузки страницы, поэтому в HTML их нет и curl'ом такое не поймать.

Требуется запущенный сервер на BASE_URL и живая БД (маркер `integration`).
Логин — общая QA-учётка из `tests.constants.TEST_AUTH`.
"""

import os

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Browser, Page, sync_playwright

from tests.constants import TEST_AUTH

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = pytest.mark.integration

# Названия из seed: project_team.name и project_task_type.title.
TEAM_NAMES = ['Manager', 'Developer', 'QA']
TASK_TYPE_NAMES = ['dev', 'bug', 'test', 'research', 'plan']


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture(scope='module')
def page(browser: Browser):
    """Одна авторизованная вкладка на весь модуль: логин небыстрый."""
    context = browser.new_context()
    tab = context.new_page()
    _login(tab)
    yield tab
    context.close()


class TestTeamPage:
    """`/admin/team` — мониторинг сессий команды."""

    def test_team_page_loads(self, page: Page):
        page.goto(f'{BASE_URL}/admin/team')
        assert page.url == f'{BASE_URL}/admin/team'
        assert page.locator('h1').first.text_content().strip() == 'Команда'

    def test_team_members_displayed(self, page: Page):
        page.goto(f'{BASE_URL}/admin/team')
        page.wait_for_selector('.team-card', state='visible', timeout=5000)

        cards = page.locator('.team-card')
        assert cards.count() >= 3, 'Ожидается минимум 3 члена команды'

        for i, name in enumerate(TEAM_NAMES):
            card_name = cards.nth(i).locator('h2').text_content()
            assert name in card_name, f'Ожидалось имя {name}, получено {card_name}'

    def test_team_member_fields(self, page: Page):
        """Карточка показывает роль, свежесть пинга и данные процесса."""
        page.goto(f'{BASE_URL}/admin/team')
        page.wait_for_selector('.team-card', state='visible', timeout=5000)

        card = page.locator('.team-card').first
        assert card.locator('.team-role').is_visible()
        assert card.locator('.status-indicator').first.is_visible()
        assert card.locator('.status-text').first.is_visible()
        assert card.locator('.team-command-code code').first.is_visible()
        # Session UUID, PID процесса, Последний пинг.
        assert card.locator('.meta-value').count() >= 3
        assert card.locator('.ping-time').is_visible()

    def test_copy_button_carries_command(self, page: Page):
        """Команда запуска берётся из data-атрибута кнопки, а не из шаблона.

        Раньше она подставлялась в `onclick` строкой и ломала обработчик на
        любой кавычке внутри команды.
        """
        page.goto(f'{BASE_URL}/admin/team')
        page.wait_for_selector('.team-card', state='visible', timeout=5000)

        card = page.locator('.team-card').first
        command = card.locator('.copy-btn').first.get_attribute('data-command')
        assert command, 'У кнопки копирования нет data-command'
        assert command.strip() == card.locator('.team-command-code code').first.text_content().strip()

    def test_team_api_endpoint(self, page: Page):
        response = page.request.get(f'{BASE_URL}/api/team')
        assert response.status == 200, f'API вернул {response.status}'

        data = response.json()
        assert isinstance(data, list), 'API должен вернуть список'
        assert len(data) >= 3, 'Ожидается минимум 3 члена команды'

        member = data[0]
        for field in ('id', 'name', 'role', 'status', 'command',
                      'last_ping_at', 'pid', 'session_uuid', 'work_dir'):
            assert field in member, f'В ответе нет поля {field}'

    def test_team_api_requires_auth(self, browser: Browser):
        """`/api/team` отдаёт work_dir, pid и session_uuid — без сессии нельзя."""
        context = browser.new_context()
        try:
            response = context.request.get(f'{BASE_URL}/api/team')
            assert response.status == 401, f'Ожидался 401, получен {response.status}'
        finally:
            context.close()

    def test_team_ping_endpoint(self, page: Page):
        """Пинг делает карточку живой: status=active и свежий last_ping_at."""
        members = page.request.get(f'{BASE_URL}/api/team').json()
        manager_id = next(m['id'] for m in members if m['name'] == 'Manager')

        ping = page.request.post(f'{BASE_URL}/api/team/ping',
                                 data={'member_id': manager_id})
        assert ping.status == 200, ping.text()

        members = page.request.get(f'{BASE_URL}/api/team').json()
        manager = next(m for m in members if m['id'] == manager_id)
        assert manager['status'] == 'active'
        assert manager['last_ping_at'] is not None


class TestTaskPage:
    """`/admin/task` — конвейер задач."""

    def test_task_page_loads(self, page: Page):
        page.goto(f'{BASE_URL}/admin/task')
        assert page.url == f'{BASE_URL}/admin/task'
        assert page.locator('.task-toolbar-title').first.text_content().strip() == 'Задачи'

    def test_phase_tabs_display(self, page: Page):
        """Задачи фильтруются по фазе; типы задач — это select, а не табы."""
        page.goto(f'{BASE_URL}/admin/task')
        page.wait_for_selector('#phaseTabs .page-tab', state='visible', timeout=5000)

        tabs = page.locator('#phaseTabs .page-tab')
        assert tabs.count() == 3, f'Ожидается 3 таба фаз, получено {tabs.count()}'

        labels = [tabs.nth(i).text_content().strip() for i in range(tabs.count())]
        assert labels == ['Планирование', 'Разработка', 'Тестирование/Баги']
        assert page.locator('#phaseTabs .page-tab.active').count() == 1

    def test_task_type_api_endpoint(self, page: Page):
        response = page.request.get(f'{BASE_URL}/api/team/types')
        assert response.status == 200, f'API вернул {response.status}'

        data = response.json()
        assert isinstance(data, list), 'API должен вернуть список'
        assert len(data) == len(TASK_TYPE_NAMES), \
            f'Ожидается {len(TASK_TYPE_NAMES)} типов задач, получено {len(data)}'

        for field in ('id', 'name', 'title'):
            assert field in data[0], f'В ответе нет поля {field}'

        names = [t['name'] for t in data]
        for expected in TASK_TYPE_NAMES:
            assert expected in names, f'Нет типа задачи {expected}'

    def test_create_task_has_type_select(self, page: Page):
        """Форма добавления даёт выбрать тип; опции приходят из API."""
        page.goto(f'{BASE_URL}/admin/task')
        # Форма свёрнута, поэтому ждём селект в DOM, а не видимым.
        page.wait_for_selector('#newTaskType', state='attached', timeout=5000)

        page.click('button:has-text("+ Добавить")')
        page.wait_for_selector('#taskAddForm.open', state='visible', timeout=5000)

        type_select = page.locator('#newTaskType')
        assert type_select.is_visible(), 'Select типа задачи должен быть виден'

        options = type_select.locator('option')
        # «Не указан» + типы из /api/team/types.
        assert options.count() >= len(TASK_TYPE_NAMES) + 1, \
            f'Ожидается минимум {len(TASK_TYPE_NAMES) + 1} опций, получено {options.count()}'


class TestIntegration:
    """Обе страницы вместе: доступность и живое обновление."""

    def test_team_and_task_pages_accessible(self, page: Page):
        page.goto(f'{BASE_URL}/admin/team')
        assert page.url == f'{BASE_URL}/admin/team'

        page.goto(f'{BASE_URL}/admin/task')
        assert page.url == f'{BASE_URL}/admin/task'

    def test_auto_refresh_team_page(self, page: Page):
        """Карточки переживают цикл авто-обновления статусов."""
        page.goto(f'{BASE_URL}/admin/team')
        page.wait_for_selector('.team-card', state='visible', timeout=5000)

        cards_before = page.locator('.team-card').count()
        assert page.locator('.ping-time').first.text_content().strip()

        page.wait_for_timeout(6000)

        assert page.locator('.team-card').count() == cards_before
        assert not page.locator('#teamGrid .error').count()


def _login(page: Page) -> None:
    """Вход через `/login`: поля `#username`/`#password`, редирект на `/`."""
    assert TEST_AUTH['password'], \
        'QA_PASSWORD не задан ни в окружении, ни в .env.local — авторизоваться нечем'

    page.goto(f'{BASE_URL}/login')
    page.wait_for_selector('#username', state='visible', timeout=10000)

    page.fill('#username', TEST_AUTH['username'])
    page.fill('#password', TEST_AUTH['password'])
    page.click('#loginBtn')

    # login.html после успеха уводит на `?next=` или на корень.
    page.wait_for_url(f'{BASE_URL}/', timeout=10000)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

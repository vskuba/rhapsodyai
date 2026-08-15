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

# Задача, которую тест страницы заводит под себя и удаляет за собой.
TASK_TEMP_TITLE = 'test_page_task_type_select'

# Опрос колонки «Прогресс» идёт раз в 15 секунд (`TASK_PROGRESS_REFRESH_MS`),
# поэтому ждём с запасом на сам запрос.
PROGRESS_REFRESH_WAIT_MS = 25000


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
        """Заголовок страницы — в `<title>`: своего `<h1>` у страницы нет."""
        page.goto(f'{BASE_URL}/admin/team')
        assert page.url == f'{BASE_URL}/admin/team'
        assert page.title().strip() == 'Команда'
        assert page.locator('#teamProjects').count() == 1

    def test_team_members_displayed(self, page: Page):
        """Карточки ролей есть в каждом блоке проекта.

        Проверяется набор имён, а не порядок карточек: страница группирует их
        блоками проектов, и одна и та же роль встречается столько раз, сколько
        проектов в установке.
        """
        page.goto(f'{BASE_URL}/admin/team')
        page.wait_for_selector('.team-card', state='visible', timeout=5000)

        assert page.locator('.project-block').count() >= 1, 'Ожидается хотя бы один блок проекта'

        names = {page.locator('.team-card-name .name').nth(i).text_content().strip()
                 for i in range(page.locator('.team-card-name .name').count())}
        for name in TEAM_NAMES:
            assert name in names, f'Нет карточки {name}, на странице: {sorted(names)}'

    def test_team_member_fields(self, page: Page):
        """Карточка показывает роль, свежесть пинга и то, чем роль работает."""
        page.goto(f'{BASE_URL}/admin/team')
        page.wait_for_selector('.team-card', state='visible', timeout=5000)

        card = page.locator('.team-card').first
        assert card.locator('.team-card-name .role').first.is_visible()
        assert card.locator('.team-status .status-indicator').first.is_visible()
        assert card.locator('.team-status span').last.text_content().strip(), \
            'У карточки пустая строка состояния'

        # Агент и его workflow — то, чем роль на самом деле работает (`team_agent.py`).
        assert page.locator('.team-card-meta a[href^="/admin/agent"]').count() >= 1
        assert page.locator('.team-card-meta a[href^="/admin/workflow"]').count() >= 1

    def test_copy_button_carries_command(self, page: Page):
        """Команда запуска берётся из data-атрибута кнопки, а не из шаблона.

        Раньше она подставлялась в `onclick` строкой и ломала обработчик на
        любой кавычке внутри команды. Кнопка есть только у погашенной карточки:
        живую оболочку запускать повторно не надо.
        """
        page.goto(f'{BASE_URL}/admin/team')
        page.wait_for_selector('.team-card', state='visible', timeout=5000)

        buttons = page.locator('.team-card-copy')
        if not buttons.count():
            pytest.skip('Все карточки активны — кнопки запуска на странице нет')

        command = buttons.first.get_attribute('data-command')
        assert command, 'У кнопки копирования нет data-command'

        commands = [m['command'] for m in page.request.get(f'{BASE_URL}/api/team').json()]
        assert command.strip() in [c.strip() for c in commands], \
            'Команда на кнопке не совпадает ни с одной командой из /api/team'

    def test_timeouts_block_lists_agent_steps(self, page: Page):
        """Блок «⏱ Таймауты» показывает и настройки, и сроки шагов workflow роли.

        Срок шага живёт литералом `_const_N` в самом шаге, а не в таблице
        `setting`, — до появления группы «Шаги агента» карточка обещала час там,
        где прогон обрывался на десятой минуте.
        """
        page.goto(f'{BASE_URL}/admin/team')
        page.wait_for_selector('.team-timeouts', state='attached', timeout=5000)

        items = page.request.get(f'{BASE_URL}/api/team/timeout').json()['result']['items']
        steps = [i for i in items if i['key'].startswith('step_timeout_') and i['role'] == 'manager']
        assert steps, 'API не вернул ни одного срока шага для менеджера'

        block = page.locator('.team-card', has=page.locator('.team-card-name .name',
                                                            has_text='Manager')).first
        groups = block.locator('.team-timeout-group')
        titles = [groups.nth(i).text_content().strip() for i in range(groups.count())]
        assert 'Шаги агента' in titles, f'Групп на карточке: {titles}'

        field = block.locator(f'.team-timeout-row input[data-key="{steps[0]["key"]}"]').first
        assert field.get_attribute('value') == str(steps[0]['value'])

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
        """Задачи фильтруются по фазе; типы задач — это select в строке, а не табы.

        В подписи таба, кроме названия фазы, живёт счётчик задач (`.page-tab-n`),
        поэтому сверяется название без него: число зависит от содержимого базы.
        """
        page.goto(f'{BASE_URL}/admin/task')
        page.wait_for_selector('#phaseTabs .page-tab', state='visible', timeout=5000)

        tabs = page.locator('#phaseTabs .page-tab')
        assert tabs.count() == 3, f'Ожидается 3 таба фаз, получено {tabs.count()}'

        labels = [_tab_label(tabs.nth(i)) for i in range(tabs.count())]
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

    def test_add_form_opens_without_type_select(self, page: Page):
        """Форма добавления просит только название и описание.

        Поля «Тип» в ней больше нет: тип новой задачи берётся из активной вкладки
        (`PHASE_NEW_TYPE_NAME`), потому что именно он решает, чья карточка возьмёт
        задачу в работу.
        """
        page.goto(f'{BASE_URL}/admin/task')
        page.wait_for_selector('#taskAddForm', state='attached', timeout=5000)

        page.click('button:has-text("+ Добавить")')
        page.wait_for_selector('#taskAddForm.open', state='visible', timeout=5000)

        form = page.locator('#taskAddForm')
        assert form.locator('#newTaskTitle').is_visible(), 'Поле названия должно быть видно'
        assert form.locator('#newTaskDesc').is_visible(), 'Поле описания должно быть видно'
        assert not form.locator('select').count(), \
            'В форме добавления не должно быть селекта типа — тип берётся из вкладки'

        page.click('#taskAddForm button:has-text("Отмена")')

    def test_row_type_select_lists_types(self, page: Page):
        """Тип меняется в строке задачи; опции — «не указан» плюс типы из API.

        Задача заводится через API в тот же проект, который выбран на странице, и
        удаляется после проверки: без своей строки на вкладке проверять нечего, а
        полагаться на чужие задачи в базе нельзя.
        """
        page.goto(f'{BASE_URL}/admin/task')
        page.wait_for_selector('#taskProjectSelect option', state='attached', timeout=5000)
        project_id = page.locator('#taskProjectSelect').input_value() or '0'

        created = page.request.post(f'{BASE_URL}/tasks/{project_id}',
                                    data={'title': TASK_TEMP_TITLE,
                                          'description': 'временная задача теста страницы'})
        assert created.status == 200, created.text()
        task_id = created.json()['task']['id']

        try:
            page.goto(f'{BASE_URL}/admin/task')
            # Задача без типа считается «dev» и живёт на вкладке разработки.
            page.click('#phaseTabs .page-tab[data-tab="development"]')
            row = page.locator(f'#tr-{task_id}')
            row.wait_for(state='visible', timeout=5000)

            options = row.locator('.task-type-select option')
            labels = [options.nth(i).text_content().strip() for i in range(options.count())]
            assert '— не указан —' in labels, f'Нет пустой опции, получено {labels}'

            titles = [t['title'] for t in page.request.get(f'{BASE_URL}/api/team/types').json()]
            for title in titles:
                assert title in labels, f'Нет типа «{title}» в списке строки: {labels}'
        finally:
            page.request.delete(f'{BASE_URL}/task/{task_id}')

    def test_progress_column_refreshes_without_reload(self, page: Page):
        """Колонка «Прогресс» догоняет состояние сама, без перезагрузки страницы.

        Состояния меняет конвейер, а не страница, поэтому статус правится через API
        и проверяется на той же, ни разу не перезагруженной вкладке: опрос
        `taskProgressRefresh` перерисовывает ячейку раз в `TASK_PROGRESS_REFRESH_MS`.
        """
        page.goto(f'{BASE_URL}/admin/task')
        page.wait_for_selector('#taskProjectSelect option', state='attached', timeout=5000)
        project_id = page.locator('#taskProjectSelect').input_value() or '0'

        created = page.request.post(f'{BASE_URL}/tasks/{project_id}',
                                    data={'title': TASK_TEMP_TITLE,
                                          'description': 'временная задача теста обновления'})
        assert created.status == 200, created.text()
        task_id = created.json()['task']['id']

        try:
            page.goto(f'{BASE_URL}/admin/task')
            page.click('#phaseTabs .page-tab[data-tab="development"]')
            cell = page.locator(f'#tr-{task_id} [data-col="goals"]')
            cell.wait_for(state='visible', timeout=5000)
            assert 'Ожидает' in cell.text_content(), cell.text_content()

            # Правка мимо страницы — ровно то, что делает конвейер.
            updated = page.request.put(f'{BASE_URL}/task/{task_id}', data={'status': 'active'})
            assert updated.status == 200, updated.text()

            # Ждём дольше периода опроса; перезагрузки страницы здесь нет.
            page.wait_for_function(
                'id => document.querySelector(`#tr-${id} [data-col="goals"]`)'
                '?.textContent.includes("В работе")',
                arg=task_id, timeout=PROGRESS_REFRESH_WAIT_MS)
        finally:
            page.request.delete(f'{BASE_URL}/task/{task_id}')


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
        assert page.locator('.team-status').first.text_content().strip()

        page.wait_for_timeout(6000)

        assert page.locator('.team-card').count() == cards_before
        # `renderProjects` рисует «Проектов нет» только на пустом ответе: появись
        # эта плашка после обновления — блоки потерялись.
        assert not page.locator('#teamProjects .team-empty').count()


def _tab_label(tab) -> str:
    """Название таба без счётчика задач: «Планирование (3)» → «Планирование»."""
    text = tab.text_content().strip()
    count = tab.locator('.page-tab-n').text_content().strip()

    return text[:len(text) - len(count)].strip() if count else text


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

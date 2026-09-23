"""
Браузерные тесты страниц `/admin/team` и `/admin/task` (Playwright, sync API).

Проверяется именно то, что рисует JS, а не разметка шаблона: карточки команды и
селект типов задач наполняются из `/api/team` и `/api/team/types` уже после
загрузки страницы, поэтому в HTML их нет и curl'ом такое не поймать.

Требуется запущенный сервер на BASE_URL и живая БД (маркер `integration`).
Логин — общая QA-учётка из `tests.constants.TEST_AUTH`.
"""

import os
import re

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Browser, Page, sync_playwright

from tests.constants import TEST_AUTH

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = [pytest.mark.team, pytest.mark.integration, pytest.mark.slow]

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

        # Та же команда — в `title`: копирование происходит вслепую, и без подсказки
        # не видно ни роли, ни флагов запуска, которые уедут в буфер.
        assert buttons.first.get_attribute('title') == command, \
            'В title кнопки не та команда, что уйдёт в буфер'

        # `/api/team` отдаёт сырую команду из `project_team.command`, а карточка блока
        # проекта подставляет к ней каталог: `cd <work_dir> && <команда>`
        # (`team_project._command_build`). Поэтому сверяем хвост, а не строку целиком —
        # у карточки проекта без каталога префикса не будет, и подходят оба вида.
        #
        # Флаги выбора модели и окна сверять нечем: их ставит сама страница по пулу
        # проекта (`shellCommandApply`), и в `project_team.command` их нет — там лежит
        # заготовка. Сравнивать с ней имеет смысл то, что страница не трогает: имя
        # оболочки и роль.
        commands = [_command_flags_drop(m['command']) for m in
                    page.request.get(f'{BASE_URL}/api/team').json()]
        command = _command_flags_drop(command)
        assert any(command == c or command.endswith(f'&& {c}') for c in commands), \
            f'Команда на кнопке не совпадает ни с одной командой из /api/team: {command!r}'

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
        """Вкладки названы по ролям: фильтруют они по типу, а тип — это исполнитель.

        Прежние «Планирование» и «Разработка» читались как этапы, и подзадача типа
        `dev` под задачей типа `plan` выглядела противоречием. Подзадачи плана всегда
        `dev` — их делает разработчик, каким бы ни был тип родителя, — так что
        противоречия не было, было имя, которое обещало не то.

        В подписи таба, кроме имени роли, живёт счётчик задач (`.page-tab-n`),
        поэтому сверяется имя без него: число зависит от содержимого базы.

        Ролей четыре: баги уехали с вкладки QA на свою вместе с владельцем — тип
        `bug` принадлежит роли `bugfixer`. Рядом в том же ряду живут «Журналы» и
        «Статистика» — это не роли, а другой взгляд на проект, и сверяем мы порядок
        первых четырёх, а не длину ряда.
        """
        page.goto(f'{BASE_URL}/admin/task')
        page.wait_for_selector('#phaseTabs .page-tab', state='visible', timeout=5000)

        tabs = page.locator('#phaseTabs .page-tab')
        labels = [_tab_label(tabs.nth(i)) for i in range(tabs.count())]
        assert labels[:4] == ['Менеджер', 'Разработчик', 'Тестировщик', 'Багфиксер'], \
            f'Не тот порядок ролей: {labels}'
        assert page.locator('#phaseTabs .page-tab.active').count() == 1

    def test_bugs_tab_filters_by_bug_type(self, page: Page):
        """Вкладка «Багфиксер» — своя роль со своим типом и своим счётчиком.

        Разметку сверяем по атрибутам, а не по содержимому таблицы: список задач
        зависит от базы, а контракт вкладки — нет. Ключ `bugs` остался прежним: по
        нему живёт сохранённый выбор вкладки в localStorage, и переименование его
        сбросило бы человеку выбор без всякой пользы.
        """
        page.goto(f'{BASE_URL}/admin/task')
        page.wait_for_selector('#phaseTabs .page-tab', state='visible', timeout=5000)

        assert page.locator('#phaseTabs .page-tab[data-tab="bugs"]').count() == 1
        assert page.locator('#tabCount-bugs').count() == 1

        html = page.content()
        assert 'Тестирование/Баги' not in html, 'старое имя вкладки осталось в разметке'

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

    def test_foreign_tab_subtask_is_a_stub(self, page: Page):
        """Задача показывается полной строкой только на вкладке своего типа.

        Тип — это нынешний владелец строки, а не род занятий: `task_state.py` гоняет
        его `plan` -> `dev` -> `test` по мере того, как задача переходит из рук в руки.
        Владелец один, значит и полная строка одна.

        Ветку это не рвёт: подзадача под задачей планирования на вкладке менеджера
        остаётся видна — иначе раскрытая задача выглядела бы бездетной, — но одной
        строкой-указателем: номер, название и куда идти. Ни описания, ни статуса, ни
        удаления: они принадлежат вкладке, где у задачи есть владелец.

        Раньше такая подзадача выходила полной строкой на обеих вкладках сразу, и с
        обеих её можно было удалить.
        """
        page.goto(f'{BASE_URL}/admin/task')
        page.wait_for_selector('#taskProjectSelect option', state='attached', timeout=5000)
        project_id = page.locator('#taskProjectSelect').input_value() or '0'

        types = {t['name']: t['id']
                 for t in page.request.get(f'{BASE_URL}/api/team/types').json()}

        parent = page.request.post(f'{BASE_URL}/tasks/{project_id}',
                                   data={'title': f'{TASK_TEMP_TITLE}_parent',
                                         'description': 'родитель на планировании',
                                         'task_type_id': types['plan']})
        assert parent.status == 200, parent.text()
        parent_id = parent.json()['task']['id']

        child = page.request.post(f'{BASE_URL}/tasks/{project_id}',
                                  data={'title': f'{TASK_TEMP_TITLE}_child',
                                        'description': 'подзадача разработки',
                                        'task_type_id': types['dev'],
                                        'parent_id': parent_id})
        assert child.status == 200, child.text()
        child_id = child.json()['task']['id']

        try:
            page.goto(f'{BASE_URL}/admin/task')
            page.wait_for_selector('#phaseTabs .page-tab', state='visible', timeout=5000)

            # Вкладка менеджера: родитель — полная строка, ребёнок — заглушка.
            page.click('#phaseTabs .page-tab[data-tab="planning"]')
            page.locator(f'#tr-{parent_id}').wait_for(state='visible', timeout=5000)
            assert 'tree-stub' not in (page.locator(f'#tr-{parent_id}')
                                       .get_attribute('class') or '')

            stub = page.locator(f'#tr-{child_id}')
            stub.wait_for(state='visible', timeout=5000)
            assert 'tree-stub' in (stub.get_attribute('class') or ''), \
                'подзадача чужой вкладки показана полной строкой'
            assert stub.locator('.btn-row-del').count() == 0, 'заглушка предлагает удаление'
            assert stub.locator('[data-col="desc"]').count() == 0, 'у заглушки есть описание'
            assert 'Разработчик' in stub.inner_text(), 'заглушка не говорит, где искать задачу'

            # Вкладка разработчика: зеркально — ребёнок полный, родителя нет вовсе.
            page.click('#phaseTabs .page-tab[data-tab="development"]')
            row = page.locator(f'#tr-{child_id}')
            row.wait_for(state='visible', timeout=5000)
            assert 'tree-stub' not in (row.get_attribute('class') or '')
            assert row.locator('.btn-row-del').count() == 1
            assert page.locator(f'#tr-{parent_id}').count() == 0, \
                'задача планирования попала на вкладку разработчика'
        finally:
            page.request.delete(f'{BASE_URL}/task/{child_id}')
            page.request.delete(f'{BASE_URL}/task/{parent_id}')

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
    """Название таба без счётчика задач: «Разработчик (3)» → «Разработчик»."""
    text = tab.text_content().strip()
    count = tab.locator('.page-tab-n').text_content().strip()

    return text[:len(text) - len(count)].strip() if count else text


def _command_flags_drop(command) -> str:
    """Команда без флагов, которые страница ставит сама (`shellCommandApply`).

    Модель, окно контекста и подробный лог зависят от пула проекта и от выбора
    человека в браузере — в `project_team.command` их нет, там заготовка. Сравнивать
    осмысленно то, что страница не трогает: имя оболочки и роль.
    """
    out = str(command or '').strip()
    for pattern in (r'\s--llm(?:[= ]\S+)?', r'\s--litellm\b',
                    r'\s--autocompact(?:[= ]\S+)?', r'\s--verbose\b'):
        out = re.sub(pattern, '', out)

    return ' '.join(out.split())


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

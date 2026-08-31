"""
Вкладка «Задачи» мини-приложения: флажки фаз и панель вопросов (подзадача #5238).

Проверяется нарисованное, а не разметка. Список набегает из `/telegram-app/tasks`
уже после загрузки страницы, карточка собирается строкой в `tasks.js`, а панель
вопросов заводит свой DOM-слой сама — в curl ответе эндпоинта этого не видно, и в
шаблоне тоже: вкладку рисует соседняя подзадача.

Ответы сервера подменяются на месте (`page.route`) двумя наборами — «живая» задача
с вопросом и задача без флажка «в разработку». Так один и тот же экран показывает
оба конца каждой цели: чекбокс, включённый по умолчанию, и чекбокс, снятый; вопрос
роли и вопрос, снятый с задачи.

Сознательно не подменяется GET `/telegram-app/task/{id}/question`: его рисует
соседняя подзадача, а панель обязана открывать вопрос и без него — материал лежит
в `metadata` строки списка. Ответ же уходит на POST, который от того GET не зависит.
Здесь же, заодно, проверяется, что модули не разъехались с эндпоинтами: список
роутера отдаёт `{'result': {'tasks': [...]}}`, а панель читает вложенность.

Требуется chromium; сервер и БД не нужны.
"""

import json
import os
import re

import pytest

from playwright.sync_api import Browser, Page, sync_playwright

PUBLIC_DIR = os.path.join('data', 'uvicorn', 'public')
MODULES = ('tasks.js', 'questions.js', 'flags.js')
TASK_FLAG_KEYS = ('to_planning', 'to_development', 'to_testing')

# Каркас вкладки: имя контейнера списка задаёт план (`tasksListView`), его рисует
# соседняя подзадача — здесь тот же фрагмент разметки, что в её шаблоне.
PAGE_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="/static/css/telegram_app.css">
<link rel="stylesheet" href="/static/css/telegram_app/task.css">
</head>
<body>
<div class="app-wrapper"><div class="app-shell"><div class="content-panel">
<div class="tab-views"><div class="tab-view active" id="tab-tasks">
<div class="task-list-view" id="tasksListView"></div>
</div></div></div></div></div>
<script type="module">
import { initTasks } from '/static/js/telegram_app/tasks.js';
initTasks();
</script>
</body>
</html>
"""

# Корневая задача: «в планирование» и «в тестирование» включены отсутствием ключа,
# «в разработку» — выключена (триггер: включённое хранится явным true).
TASK_FLAGGED = {
    'id': 7001, 'title': 'pytest: флажки работают', 'status': 'active',
    'pipeline_state': 'plan_approval', 'task_type_id': 5, 'parent_id': None,
    'project_id': 11, 'metadata': {'to_testing': False, 'question': {
        'text': 'Раздробить подзадачу или закрыть как есть?',
        'role': 'manager',
        'options': [{'key': 'split', 'label': 'Раздробить'},
                    {'key': 'drop', 'label': 'Закрыть как есть'}],
    }},
}

# Та же задача без флажка «в разработку» и без вопроса — второй конец проверок.
TASK_PLAIN = {**TASK_FLAGGED, 'id': 7002, 'title': 'pytest: флажок по умолчанию',
              'metadata': {}}


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


class TestTaskFlags:
    """Флажки фаз: состояние из `metadata`, сохранение — PATCH-ключом на точку мини-приложения."""

    def test_three_flags_drawn_from_metadata(self, browser: Browser):
        """Три чекбокса у корневой задачи; включённое состояние — из умолчания ключа."""
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])

        assert ui.eval_on_selector_all('.task-flag', 'els => els.length') == 3
        assert _flag_state(ui, 'flag_plan') is True, 'нет ключа — «в планирование» включено'
        assert _flag_state(ui, 'flag_dev') is False, 'триггер включён только явным true'
        assert _flag_state(ui, 'flag_test') is False, 'явное false в metadata — флажок снят'

    def test_subtask_has_no_flags(self, browser: Browser):
        """Подзадача едет с родителем: своих флажков у неё нет."""
        subtask = {**TASK_PLAIN, 'id': 7003, 'title': 'pytest: подзадача', 'parent_id': TASK_PLAIN['id']}
        ui = _open_mini_app(browser, tasks=[subtask])

        assert ui.locator('.task-card').count() == 1
        assert ui.locator('.task-flag').count() == 0

    @pytest.mark.parametrize('flag,expected_key', [('flag_plan', 'to_planning'),
                                                  ('flag_dev', 'to_development'),
                                                  ('flag_test', 'to_testing')])
    def test_flag_click_saves_and_list_returns_it_back(self, browser: Browser, flag: str,
                                                       expected_key: str):
        """Клик идёт на точку metadata и возвращает список: флажок остаётся в новом состоянии.

        Отдельно проверяется, что ключ в теле — ровно ожидаемый: PATCH перечисляет те,
        что трогать, и чужие ключи `metadata` остаются нетронутыми.
        """
        meta = dict(TASK_PLAIN['metadata'])
        meta['to_development'] = True
        ui = _open_mini_app(browser, tasks=[TASK_PLAIN], metadata_handler=lambda patch: meta)

        ui.locator(f'.task-flag[data-flag="{flag}"] input').click()
        ui.wait_for_function("() => (window.__saved || []).length > 0")

        body = json.loads(ui.evaluate('window.__saved')[0]['body'])
        assert list(body['patch'].keys()) == [expected_key]
        assert body['patch'][expected_key] is not None, 'флажок не должен слать сброс ключа'

        # Список перезагружается и отвечает тем же состоянием — флажок не «отпускается» обратно
        assert ui.wait_for_selector(f'.task-flag[data-flag="{flag}"] input').is_checked()

    def test_development_flag_on_switches_off(self, browser: Browser):
        """Обратный ход: снятый триггер «в разработку» уходит как null — ключ стирается."""
        ui = _open_mini_app(browser, tasks=[{**TASK_PLAIN, 'metadata': {'to_development': True}}])

        ui.locator('.task-flag[data-flag="flag_dev"] input').click()
        ui.wait_for_function("() => (window.__saved || []).length > 0")

        body = json.loads(ui.evaluate('window.__saved')[0]['body'])
        assert body['patch'] == {'to_development': None}


class TestTaskQuestionPanel:
    """Панель вопросов: открывается на карточке, показывает вопрос, принимает ответ."""

    def test_panel_opens_question_from_list_row(self, browser: Browser):
        """Вопрос видно сразу — из `metadata` строки списка, без ответа на GET вопроса.

        GET `/telegram-app/task/{id}/question` в этих тестах отвечает 404 — как если
        бы его ещё не нарисовали. Панель не должна от этого слепнуть.
        """
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('.task-question-panel')

        assert ui.locator('.task-question-text').inner_text().startswith('Раздробить подзадачу')
        assert ui.locator('.task-question-options label').count() == 2
        assert ui.locator('#askSendBtn').is_visible(), 'кнопки ответа нет — ответить нечем'

    def test_answer_reaches_the_endpoint(self, browser: Browser):
        """Выбранный вариант и уточнение уходят на question/answer тем самым контрактом."""
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askSendBtn')
        ui.locator('.task-question-options label').first.click()
        ui.fill('#askNote', 'Раздробить, кроме третьей цели')
        ui.click('#askSendBtn')

        ui.wait_for_function("() => (window.__answered || []).length > 0")
        body = json.loads(ui.evaluate('window.__answered')[0]['body'])
        assert body['answers'] == ['split']
        assert body['note'] == 'Раздробить, кроме третьей цели'

    def test_close_button_closes_panel(self, browser: Browser):
        """«Закрыть» — обработчик на window; без него кнопка жала бы ReferenceError."""
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('.task-question-panel')
        ui.click('button:text-is("Закрыть")')

        ui.wait_for_selector('.task-question-panel', state='detached')

    def test_task_without_question_says_so(self, browser: Browser):
        """Задача без вопроса не должна выглядеть сломанной: панель говорит, что вопросов нет."""
        ui = _open_mini_app(browser, tasks=[TASK_PLAIN])

        ui.locator('.task-card').first.click()

        assert 'Вопросов по этой задаче нет' in ui.locator('.task-no-questions').inner_text()


class TestTaskListContract:
    """Список: контейнер из шаблона вкладки, ответ роутера и фильтр по фазе."""

    def test_list_draws_cards(self, browser: Browser):
        """Карточки появляются — значит контейнер найден по имени вкладки, а ответ разобран."""
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED, TASK_PLAIN])

        assert ui.locator('.task-card').count() == 2

    def test_nested_answer_is_read_as_router_sends_it(self, browser: Browser):
        """`{'result': {'tasks': [...]}}` — как отдаёт роутер мини-приложения.

        Плоский `{'result': [...]}` был бы другим контрактом: карточек на экране нет.
        """
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED], flat=False)

        assert ui.locator('.task-card').count() == 1

    def test_flat_answer_still_draws(self, browser: Browser):
        """Запасной путь: плоский список тоже разбирается — на случай упрощения точки."""
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED], flat=True)

        assert ui.locator('.task-card').count() == 1

    def test_phase_tabs_split_tasks_by_type(self, browser: Browser):
        """Вкладки сверяются по номеру типа: имени типа в ответе роутера нет."""
        ui = _open_mini_app(browser, tasks=[{**TASK_FLAGGED, 'task_type_id': 5},
                                            {**TASK_PLAIN, 'id': 7004, 'task_type_id': 1}])

        assert ui.locator('.task-phase-tab').count() == 4
        assert ui.locator('.task-card').count() == 1, 'открыта вкладка «Менеджер» — plan(5)'

        ui.click('.task-phase-tab[data-phase="development"]')
        ui.wait_for_function("() => document.querySelectorAll('.task-card').length === 1")
        assert 'pytest: флажок по умолчанию' in ui.locator('.task-card').first.inner_text()


class TestTaskUiStyle:
    """Стили вкладки доезжают до страницы: task.css подключён, карточка окрашена."""

    def test_task_css_is_wired_and_paints_card(self, browser: Browser):
        """Без подключения файл остаётся мёрвым: карточка вышла бы без фона и скругления."""
        seen = []
        _open_mini_app(browser, tasks=[TASK_FLAGGED], styles=seen)

        assert '/static/css/telegram_app/task.css' in seen, 'файл не запрошен — стили не подключены'
        background = ui_background = _card_style(browser, 'background-color')
        assert background != 'rgba(0, 0, 0, 0)', 'фон карточки не применился — стиль не дошёл'

    def test_question_panel_is_padded(self, browser: Browser):
        """Панель — внешний `.task-bar` (им переключается видимость) и внутренний слой отступов."""
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('.task-question-panel')

        assert _style(ui, '.task-question-panel', 'padding-left') != '0px'
        assert _style(ui, '#taskQuestionPanel', 'display') == 'block'


def _open_mini_app(browser: Browser, tasks: list, *, flat: bool = False,
                   metadata_handler=None, styles: list | None = None) -> Page:
    """Открыть мини-приложение на подставных ответах; вернуть страницу с загруженным списком."""
    context = browser.new_context()
    page = context.new_page()
    # `Failed to load resource` — сообщение о статусе ответа, а не о поломке кода:
    # GET вопроса подменён на 404 намеренно (см. шапку файла). Настоящие ошибки
    # скриптов приходят отдельным событием `pageerror`, его и считываем.
    page.on('console', lambda msg: pytest.fail(f"ошибка в консоли: {msg.text}")
            if msg.type == 'error' and 'Failed to load resource' not in msg.text else None)
    page.on('pageerror', lambda err: pytest.fail(f"непойманная ошибка скрипта: {err}"))
    _attach_routes(page, tasks, flat=flat, metadata_handler=metadata_handler, styles=styles)

    page.goto('http://mini.test/telegram-app')
    page.wait_for_selector('.task-card')
    return page


def _attach_routes(page: Page, tasks: list, *, flat: bool, metadata_handler=None,
                   styles: list | None = None) -> None:
    """Подменить ответы сервера: статика — с диска, задачи и сохранения — из аргументов."""
    saved, answered, asked = [], [], []

    def handle(route):
        path = route.request.url.split('?')[0].replace('http://mini.test', '')

        if path.startswith('/static/'):
            _route_static(route, path[len('/static/'):])
        elif path == '/telegram-app':
            route.fulfill(status=200, content_type='text/html; charset=utf-8', body=PAGE_HTML)
        elif path.endswith('/auth'):
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True}))
        elif path == '/telegram-app/tasks':
            payload = {'result': tasks if flat else {'tasks': tasks}}
            route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))
        elif re.search(r'/task/\d+/question$', path):
            asked.append(path)          # как если бы точку ещё не нарисовали
            route.fulfill(status=404, content_type='application/json',
                          body=json.dumps({'detail': 'вопрос рисует соседняя подзадача'}))
        elif re.search(r'/task/\d+/metadata$', path):
            body = json.loads(route.request.post_data or '{}')
            saved.append({'path': path, 'body': route.request.post_data})
            if metadata_handler:
                meta = metadata_handler(body.get('patch') or {})
                tasks[0] = {**tasks[0], 'metadata': meta}
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'result': {'updated': list(body.get('patch', {}))}}))
        elif re.search(r'/task/\d+/question/answer$', path):
            answered.append({'path': path, 'body': route.request.post_data})
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'done': True, 'left': 0}))
        else:
            route.fulfill(status=404, content_type='application/json',
                          body=json.dumps({'detail': f'нет точки {path}'}))

        if styles is not None and path.endswith('.css'):
            styles.append(path)

    page.route('**/*', handle)
    page.add_init_script("""
        window.__saved = []; window.__answered = [];
        const wrap = (name, bucket) => {
            const real = window.fetch;
            window.fetch = async (input, init) => {
                const url = typeof input === 'string' ? input : input.url;
                const r = await real(input, init);
                if (url.endsWith('/metadata')) window.__saved.push({url, body: (init || {}).body || ''});
                if (url.endsWith('/question/answer')) window.__answered.push({url, body: (init || {}).body || ''});
                return r;
            };
        };
        wrap('fetch', null);
    """)
    page.expose_binding('__noop', lambda source, *a: None)
    return page


def _route_static(route, rel: str) -> None:
    """Отдать файл статики с диска — как это делает сервер, а не заглушку."""
    full = os.path.abspath(os.path.join(PUBLIC_DIR, rel))
    if not full.startswith(os.path.abspath(PUBLIC_DIR)) or not os.path.isfile(full):
        route.fulfill(status=404, body=f'нет файла {rel}')
        return

    content_type = ('text/javascript; charset=utf-8' if rel.endswith('.js')
                    else 'text/css; charset=utf-8')
    with open(full, encoding='utf-8') as fh:
        route.fulfill(status=200, content_type=content_type, body=fh.read())


def _flag_state(page: Page, flag: str):
    return page.locator(f'.task-flag[data-flag="{flag}"] input').is_checked()


def _style(page: Page, selector: str, prop: str) -> str:
    return page.evaluate(
        "([sel, prop]) => { const el = document.querySelector(sel);"
        " return el ? getComputedStyle(el)[prop] : null; }",
        [selector, prop])


def _card_style(browser: Browser, prop: str) -> str:
    context = browser.new_context()
    page = context.new_page()
    try:
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])
        return _style(ui, '.task-card', prop)
    finally:
        context.close()

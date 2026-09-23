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

GET `/telegram-app/task/{id}/question` подменяется двояко. По умолчанию он отвечает
404 — как если бы его ещё не нарисовали (его рисует соседняя подзадача), и панель
обязана открыть вопрос из `metadata` строки списка. В тестах про цели (`question=`)
отвечает живым списком: `goal_indexes` сервер применяет к своей нормализованной
колонке, поэтому отметка ведётся по серверной нумерации, а цели карточки остаются
подстраховкой показа. Ответ же уходит на POST, который от того GET не зависит.
Здесь же, заодно, проверяется, что модули не разъехались с эндпоинтами: список
роутера отдаёт `{'result': {'tasks': [...]}}`, а панель читает вложенность.

Требуется chromium; сервер и БД не нужны.
"""

import json
import os
import re

import pytest

pytest.importorskip('playwright', reason='проверка нарисованного требует chromium')

from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402


pytestmark = pytest.mark.telegram

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

# Готовая работа по обеим осям закрытия (`task.html:2329`): человеческое «Готово» и
# конвейерный done. Обе уходят с вкладки своего типа тестировщику, баг — остаётся у себя.
TASK_DONE_DEV = {**TASK_PLAIN, 'id': 7005, 'title': 'pytest: готова dev', 'status': 'done',
                 'pipeline_state': 'resolved', 'task_type_id': 1, 'metadata': {}}
TASK_DONE_PIPELINE = {**TASK_PLAIN, 'id': 7006, 'title': 'pytest: закрыл конвейер',
                      'status': 'active', 'pipeline_state': 'done', 'task_type_id': 1,
                      'metadata': {}}
TASK_DONE_BUG = {**TASK_PLAIN, 'id': 7007, 'title': 'pytest: закрытый баг', 'status': 'done',
                 'pipeline_state': 'done', 'task_type_id': 2, 'metadata': {}}
# Та же dev-работа, но не закрытая — на ней проверяется, что прежнее сверки по типу не сломалось.
TASK_DEV_OPEN = {**TASK_PLAIN, 'id': 7008, 'title': 'pytest: разработка идёт', 'task_type_id': 1}
# План уже утверждён — второй конец проверки кнопки приёмки: на приёмке она одна задача,
# и у этой её быть нечем (`task.html` рисует приёмку ровно на состоянии plan_approval).
TASK_PLAN_PASSED = {**TASK_PLAIN, 'id': 7009, 'title': 'pytest: план утверждён',
                    'pipeline_state': 'qa_pending'}


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

    def test_flag_failure_stays_on_the_card_after_reload(self, browser: Browser):
        """Отказ точки не теряется с перезагрузкой: чип красный, чекбокс — как его принял сервер.

        Список перерисовывает карточку строкой, поэтому подсветка не может висеть на
        старом узле: иначе отказ вспыхнул бы на миг, а затем карточка делала бы вид,
        что запись прошла. Взят `to_testing` со `false` в `metadata`: попытка включить
        её не принята, и оставшийся отмеченным флажок показывал бы состояние,
        которого в базе нет.
        """
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED], metadata_status=500)

        ui.locator('.task-flag[data-flag="flag_test"] input').click()
        ui.wait_for_function("() => (window.__saved || []).length > 0")
        ui.wait_for_selector('.task-flag-failed')

        chip = ui.locator('.task-flag[data-flag="flag_test"]')
        assert not _flag_state(ui, 'flag_test'), 'непринятая запись осталась отмечаемой'
        assert 'не сохран' in chip.get_attribute('title').lower()
        # Красным залился один чип, а не список: отказ касается одной записи одной задачи
        assert ui.locator('.task-flag-failed').count() == 1

    def test_development_flag_on_switches_off(self, browser: Browser):
        """Обратный ход: снятый триггер «в разработку» уходит как null — ключ стирается."""
        ui = _open_mini_app(browser, tasks=[{**TASK_PLAIN, 'metadata': {'to_development': True}}])

        ui.locator('.task-flag[data-flag="flag_dev"] input').click()
        ui.wait_for_function("() => (window.__saved || []).length > 0")

        body = json.loads(ui.evaluate('window.__saved')[0]['body'])
        assert body['patch'] == {'to_development': None}


    def test_flag_survives_a_list_that_never_redrew(self, browser: Browser):
        """Без перерисовки списка чекбокс всё равно остаётся кликабельным.

        Разморозка висела на новом карточном разметчике: пока вкладка не нарисована
        или её коллбек не дошёл, чекбокс замирал `disabled` до первой перерисовки,
        которой могло и не быть. Здесь перезагрузка списка снята до клика — и второй
        клик обязан состояться с обратным значением того же ключа.
        """
        meta = {'to_testing': False}
        ui = _open_mini_app(browser, tasks=[{**TASK_PLAIN, 'metadata': dict(meta)}],
                            metadata_handler=lambda patch: {**meta, **patch})

        ui.evaluate('window._tg_reload_tasks = null')      # список не перерисует карточку
        chip = '.task-flag[data-flag="flag_test"] input'
        ui.locator(chip).click()
        ui.wait_for_function("() => (window.__saved || []).length > 0")

        assert ui.locator(chip).is_enabled(), 'чекбокс замёрз снятым до перерисовки'
        ui.locator(chip).click()
        ui.wait_for_function("() => (window.__saved || []).length > 1")

        bodies = [json.loads(x['body'])['patch'] for x in ui.evaluate('window.__saved')]
        # Первый ход: ключ стёрт (умолчание «включено»), обратный: выключенное хранится явным false
        assert bodies == [{'to_testing': None}, {'to_testing': False}], \
            'обратный ход должен вернуться к выключённому флажку, а не застыть на первом значении'

    def test_plan_flag_title_promises_only_what_the_write_does(self, browser: Browser):
        """Подпись чипа не обещает остановить прогон: точки остановки у мини-приложения нет.

        `metadata` читает отбор менеджера (`task_metadata_plan_free_sql`), а не идущий
        круг: обещание «планирование прекратится» было бы враньем ровно там, где человек
        снял бы флажок, чтобы остановить работу. Админский выключатель фазы
        (`task.html:3823`) шлёт второй запрос, закрытый правом `planning.update`.
        """
        ui = _open_mini_app(browser, tasks=[TASK_PLAIN])

        title = ui.locator('.task-flag[data-flag="flag_plan"]').get_attribute('title')
        assert 'прекрат' not in title.lower(), f'чип обещает остановку прогона: {title!r}'
        assert 'останов' in title.lower(), f'из подписи не видно, что прогон не гасится: {title!r}'

    def test_rejected_flag_is_reclickable_after_the_reload(self, browser: Browser):
        """Отказ не запирает чип: подсветка есть, разморозка тоже.

        Отказ красит чип и возвращает чекбокс в принятое сервером. Если бы разморозка
        шла только по успешной ветке, человек получил бы красный флажок, которым больше
        нельзя ничего сделать, — ровно до первой перерисовки списка.
        """
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED], metadata_status=500)
        ui.evaluate('window._tg_reload_tasks = null')

        ui.locator('.task-flag[data-flag="flag_test"] input').click()
        ui.wait_for_function("() => (window.__saved || []).length > 0")

        assert ui.locator('.task-flag[data-flag="flag_test"]').evaluate(
            'el => el.classList.contains("task-flag-failed")'), 'отказ не подсветился'
        assert ui.locator('.task-flag[data-flag="flag_test"] input').is_enabled()


class TestTaskQuestionPanel:
    """Панель вопросов: открывается на карточке, показывает вопрос, принимает ответ."""

    def test_goals_open_with_the_action_that_needs_them(self, browser: Browser):
        """«Раздробить/убрать» отмечает цели: список открывается на таком варианте и уходит индексом.

        Цели — колонка задачи, а не ключ `metadata`: панель, собранная из строки
        списка, обязана их видеть — иначе ответ о целях упирался бы в запрет
        отмечать то, чего не показали.
        """
        with_goals = {**TASK_FLAGGED, 'metadata': {**TASK_FLAGGED['metadata'], 'question': {
            'text': 'Раздробить подзадачу?', 'role': 'manager',
            'options': [{'key': 'goals_split', 'label': 'Раздробить'},
                        {'key': 'as_is', 'label': 'Оставить как есть'}],
        }}, 'goals': ['Две первые цели', 'Третья цель']}
        ui = _open_mini_app(browser, tasks=[with_goals])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askSendBtn')
        assert not ui.locator('#askGoals').is_visible(), 'список целей показан до выбора действия'

        ui.click('.task-question-options input[value="goals_split"]')
        ui.wait_for_selector('#askGoals input[name="askGoal"]', state='visible')
        assert ui.locator('#askGoals input[name="askGoal"]').count() == 2
        ui.locator('#askGoals input[name="askGoal"]').nth(1).check()
        ui.click('#askSendBtn')

        ui.wait_for_function("() => (window.__answered || []).length > 0")
        assert json.loads(ui.evaluate('window.__answered')[0]['body'])['goal_indexes'] == [1]

    def test_goal_action_without_marks_is_refused_only_when_choice_exists(self, browser: Browser):
        """Отметка требуется, когда отмечать чем; на пустом списке вопрос не запирается."""
        no_goals = {**TASK_FLAGGED, 'metadata': {**TASK_FLAGGED['metadata'], 'question': {
            'text': 'Раздробить подзадачу?', 'role': 'manager',
            'options': [{'key': 'goals_drop', 'label': 'Убрать цель'}],
        }}}
        ui = _open_mini_app(browser, tasks=[no_goals])

        ui.locator('.task-card').first.click()
        ui.click('.task-question-options input[value="goals_drop"]')
        ui.click('#askSendBtn')

        ui.wait_for_function("() => (window.__answered || []).length > 0")
        assert json.loads(ui.evaluate('window.__answered')[0]['body'])['answers'] == ['goals_drop']

    def test_closed_goal_stays_unchecked(self, browser: Browser):
        """Принятую цель не вычеркнуть: она нарисована снятой и недоступной."""
        with_done = {**TASK_FLAGGED, 'metadata': {**TASK_FLAGGED['metadata'], 'question': {
            'text': 'Что убрать?', 'role': 'developer',
            'options': [{'key': 'goals_drop', 'label': 'Убрать цель'}],
        }}, 'goals': [{'text': 'Закрытая', 'done': True}, {'text': 'Открытая', 'done': False}]}
        ui = _open_mini_app(browser, tasks=[with_done])

        ui.locator('.task-card').first.click()
        ui.click('.task-question-options input[value="goals_drop"]')

        flags = ui.eval_on_selector_all(
            '#askGoals input[name="askGoal"]', 'els => els.map(e => [e.disabled, e.checked])')
        assert flags == [[True, False], [False, False]]

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

    def test_question_button_opens_the_panel_by_itself(self, browser: Browser):
        """Кнопка «Вопрос» в карточке открывает панель: до вопроса тянуться тапом не нужно.

        На мобильной ширине карточка под `max-height` со `overflow: hidden`, и
        полагаться на клик по всей карточке — значит оставить вопрос недостижимым.
        Вложенная кнопка останавливает всплытие, поэтому открывается сама.
        """
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])

        assert ui.locator('.task-btn-ask').count() == 1
        ui.click('.task-btn-ask')
        ui.wait_for_selector('.task-question-panel')

        assert ui.locator('.task-question-text').inner_text().startswith('Раздробить подзадачу')

    def test_task_without_question_gets_no_button(self, browser: Browser):
        """Кнопка — только там, где спрашивают: на молчаливой задаче она звала бы в «нет вопросов»."""
        ui = _open_mini_app(browser, tasks=[TASK_PLAIN])

        assert ui.locator('.task-btn-ask').count() == 0

    def test_answered_question_takes_the_button_back(self, browser: Browser):
        """Отвеченный вопрос снимает кнопку: ответ в `metadata`, и больше звать некуда."""
        answered = {**TASK_FLAGGED, 'metadata': {
            'question': {**TASK_FLAGGED['metadata']['question'],
                         'answer': {'text': 'Закрыть как есть', 'keys': ['drop']}}}}
        ui = _open_mini_app(browser, tasks=[answered])

        assert ui.locator('.task-btn-ask').count() == 0

    def test_panel_lands_under_the_list_not_beside_it(self, browser: Browser):
        """Полоса вопросов — под списком, а не боковой колонкой.

        `.app-shell` — горизонтальный flex: вставленной в неё панелью страница
        разъехалась бы на два столбца, и ответ уехал бы за правый край экрана.
        """
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('.task-question-panel')
        ui.wait_for_function("() => { const p = document.querySelector('#taskQuestionPanel');"
                             " return p && p.getBoundingClientRect().height > 0; }")

        place = ui.evaluate("""() => {
            const panel = document.querySelector('#taskQuestionPanel').getBoundingClientRect();
            const list = document.querySelector('#tasksListView').getBoundingClientRect();
            return {parent: document.querySelector('#taskQuestionPanel').parentElement.className,
                    below: panel.top >= list.bottom - 1,
                    inside: panel.left >= list.left - 1 && panel.right <= list.right + 1};
        }""")
        assert 'content-panel' in place['parent'], f"панель приросла к {place['parent']!r}"
        assert place['below'], 'панель встала над списком'
        assert place['inside'], 'панель вышла за колонку списка — значит стала боковой'

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

    def test_batch_answer_survives_a_missing_question_endpoint(self, browser: Browser):
        """Пачка не упирается в алерт, когда GET вопроса ещё не нарисован.

        Сервер ответ принял — значит отказ на полпути показал бы человеку ошибку там,
        где всё сошлось. Панель пересчитывает неотвеченные сама и открывает следующий.
        """
        batch = {**TASK_PLAIN, 'metadata': {'questions': [
            {'text': 'Первый вопрос?', 'role': 'manager',
             'options': [{'key': 'yes', 'label': 'Да'}]},
            {'text': 'Второй вопрос?', 'role': 'manager',
             'options': [{'key': 'no', 'label': 'Нет'}]},
        ]}}
        ui = _open_mini_app(browser, tasks=[batch], answer={'done': False, 'left': 1})

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askSendBtn')
        ui.click('.task-question-options input[value="yes"]')
        ui.click('#askSendBtn')

        ui.wait_for_function("() => (window.__answered || []).length > 0")
        assert json.loads(ui.evaluate('window.__answered')[0]['body'])['index'] == 0
        assert not ui.evaluate('window.__alerts'), f"алерт на принятом ответе: {ui.evaluate('window.__alerts')}"
        # Следующий вопрос открылся сам: листать пачку руками не приходится
        ui.wait_for_selector('.task-question-text:text("Второй вопрос?")')

        ui.click('.task-question-options input[value="no"]')
        ui.click('#askSendBtn')
        ui.wait_for_function("() => (window.__answered || []).length > 1")
        assert json.loads(ui.evaluate('window.__answered')[1]['body'])['index'] == 1

    def test_batch_answer_carries_no_goal_indexes(self, browser: Browser):
        """Ответ пачки уходит без отметок целей — сервер их на этом пути не берёт.

        `task_question_batch_answer` (`project_task_question.py:139-141`) читает
        только `answers` и `note`: пачку задаёт менеджер про замысел, охват подзадачи
        ею не меняют, и `_scope_apply` здесь не зовётся. Отправить номера целей
        значило бы записать заказ на дробление, которого не будет: по телу запроса
        выходит, что цели указаны, а по колонке — что их никто не трогал.
        """
        batch = {**TASK_PLAIN, 'goals': ['Первая цель', 'Вторая цель'],
                 'metadata': {'questions': [
                     {'text': 'Раздробить замысел?', 'role': 'manager',
                      'options': [{'key': 'goals_split', 'label': 'Раздробить'}]},
                     {'text': 'Второй вопрос?', 'role': 'manager',
                      'options': [{'key': 'no', 'label': 'Нет'}]},
                 ]}}
        ui = _open_mini_app(browser, tasks=[batch], answer={'done': False, 'left': 1})

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askSendBtn')
        ui.click('.task-question-options input[value="goals_split"]')
        ui.wait_for_selector('#askGoals input[name="askGoal"]', state='visible')
        ui.locator('#askGoals input[name="askGoal"]').nth(1).check()
        ui.click('#askSendBtn')

        ui.wait_for_function("() => (window.__answered || []).length > 0")
        body = json.loads(ui.evaluate('window.__answered')[0]['body'])
        assert body['index'] == 0
        assert 'goal_indexes' not in body, 'пачка отправила отметки целей, которые сервер выбросит'

    def test_single_answer_reads_the_same_form_as_the_batch(self, browser: Browser):
        """Обе отправки собирают форму одним разбором — `askFormRead`.

        Форма читалась дважды: одиночный путь ходил в DOM сам. Пара таких сборок
        расходится молча, и цель, отмеченную на экране, теряет тот путь, который
        забыли поправить. Здесь проверяется единственный разбор: он же приносит
        вариант, текст и отметку цели.
        """
        with_goals = {**TASK_FLAGGED, 'metadata': {**TASK_FLAGGED['metadata'], 'question': {
            'text': 'Раздробить подзадачу?', 'role': 'manager',
            'options': [{'key': 'goals_split', 'label': 'Раздробить'}],
        }}, 'goals': ['Первая цель', 'Вторая цель']}
        ui = _open_mini_app(browser, tasks=[with_goals])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askSendBtn')
        ui.click('.task-question-options input[value="goals_split"]')
        ui.wait_for_selector('#askGoals input[name="askGoal"]', state='visible')
        ui.locator('#askGoals input[name="askGoal"]').first.check()
        ui.fill('#askNote', 'Первую — отдельной подзадачей')
        ui.click('#askSendBtn')

        ui.wait_for_function("() => (window.__answered || []).length > 0")
        body = json.loads(ui.evaluate('window.__answered')[0]['body'])
        assert body == {'answers': ['goals_split'], 'note': 'Первую — отдельной подзадачей',
                        'goal_indexes': [0]}

    def test_answered_batch_question_stays_editable_without_the_get_endpoint(self, browser: Browser):
        """Локальное состояние пачки — тем же видом, что кладёт сервер.

        Без точки GET панель обновляет свой мешок сама. Если при этом забыть `keys`
        и собрать `text` из ключей, возвращаться к отвеченному вопросу пришлось бы
        «вслепую»: вариант не отмечен, а в поле — `yes` вместо человеческой подписи.
        Правка ответа не должна превращаться в ответ заново.
        """
        batch = {**TASK_PLAIN, 'metadata': {'questions': [
            {'text': 'Первый вопрос?', 'role': 'manager',
             'options': [{'key': 'yes', 'label': 'Да'}]},
            {'text': 'Второй вопрос?', 'role': 'manager',
             'options': [{'key': 'no', 'label': 'Нет'}]},
        ]}}
        ui = _open_mini_app(browser, tasks=[batch], answer={'done': False, 'left': 1})

        ui.locator('.task-card').first.click()
        ui.click('.task-question-options input[value="yes"]')
        ui.fill('#askNote', 'только вторую цель')
        ui.click('#askSendBtn')
        ui.wait_for_selector('.task-question-text:text("Второй вопрос?")')

        # Вернулись к первому — ответ на месте: подпись варианта в поле и сам вариант отмечен.
        # Отметка ставится постом (панель перерисована строкой), поэтому ждём, а не считываем сразу.
        ui.locator('.task-question-batch-tab').nth(0).click()
        ui.wait_for_selector('.task-question-text:text("Первый вопрос?")')
        ui.wait_for_function("""() => { const i = document.querySelector('.task-question-options input[value="yes"]');
                                          return !!i && i.checked; }""")
        assert ui.input_value('#askNote') == 'только вторую цель'
        # Галочка отвеченного вопроса — она же подсчёт «без ответа: 1 из 2»
        assert ui.locator('.task-question-batch-tab.done').count() == 1
        assert 'Без ответа: 1 из 2' in ui.locator('.task-question-hint').inner_text()

    def test_answered_batch_question_reopens_with_its_own_text(self, browser: Browser):
        """Черновик пачки возвращается в поле: сервер складывает ответ в `text`, а не в `note`.

        `task_question_batch_answer` пишет в черновик и вольный текст (`note`), и
        собранный из подписей вариантов (`text` — `task_question.py:226`). У ответа
        кликом `note` пустой, поэтому поле, собранное только по нему, открывалось
        пустым там, где человек уже ответил, — следующий ответ затирал бы набранное.
        Ведущие подписи снимаются по равенству: «Да» не должно съедать «Да, но позже».
        """
        answered = {**TASK_PLAIN, 'metadata': {'questions': [
            {'text': 'Первый вопрос?', 'role': 'manager',
             'options': [{'key': 'yes', 'label': 'Да'}, {'key': 'no', 'label': 'Нет'}],
             'answer': {'text': 'Да; кроме третьей цели', 'keys': ['yes'], 'note': ''}},
            {'text': 'Второй вопрос?', 'role': 'manager',
             'options': [{'key': 'no', 'label': 'Нет'}]},
        ]}}
        ui = _open_mini_app(browser, tasks=[answered])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askNote')

        assert ui.input_value('#askNote') == 'кроме третьей цели', \
            'поле уточнения открылось пустым — набранное человеком потеряно'
        # Отметка варианта берётся из ключей ответа: правка ответа — не ответ заново
        assert ui.locator('.task-question-options input[value="yes"]').is_checked()
        assert not ui.locator('.task-question-options input[value="no"]').is_checked()

        # Второй вопрос без ответа — поле пустое, подсказка своя
        ui.locator('.task-question-batch-tab').nth(1).click()
        ui.wait_for_selector('.task-question-text:text("Второй вопрос?")')
        assert ui.input_value('#askNote') == ''

    def test_free_answer_without_options_is_not_eaten_by_its_own_label(self, browser: Browser):
        """Свободный текст не режется по подстроке: ответ «Да, но позже» остаётся целиком.

        Разбор поля ведётся сравнением с подписями отмеченных вариантов. Сверка на
        вхождение стёрла бы половину собственного ответа — и человек дописывал бы то,
        что уже написал.
        """
        free = {**TASK_PLAIN, 'metadata': {'questions': [
            {'text': 'Объём?', 'role': 'manager',
             'options': [{'key': 'yes', 'label': 'Да'}, {'key': 'later', 'label': 'Да, но позже'}],
             # Сервер склеил подписи и вольный текст через '; ' — тут ровно тот случай,
             # где часть ответа совпадает с подписью другого варианта.
             'answer': {'text': 'Да, но позже; если QA успеет', 'keys': ['later']}},
        ]}}
        ui = _open_mini_app(browser, tasks=[free])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askNote')

        assert ui.input_value('#askNote') == 'если QA успеет'

    def test_free_text_starting_with_the_chosen_label_survives_whole(self, browser: Browser):
        """Человек начал вольный текст с той же подписи, что отметил, — начало не отрезается.

        Соседняя проверка ловит совпадение с чужой подписью; здесь опаснее: ведущие
        части совпадают с **отмеченными** по одной. Сервер складывает `text` как
        `метки; вольный текст` (`task_question_batch_answer`), поэтому меток впереди
        ровно столько, сколько отмечено, — и срез обязан остановиться на этом числе.
        Без границы «Да; Да; но не в этой версии» разобралось бы как «но не в этой
        версии»: начало ответа человека уехало бы в мусор, а правка ответа дописала бы
        его заново.
        """
        same_lead = {**TASK_PLAIN, 'metadata': {'questions': [
            {'text': 'Первый вопрос?', 'role': 'manager',
             'options': [{'key': 'yes', 'label': 'Да'}, {'key': 'no', 'label': 'Нет'}],
             'answer': {'text': 'Да; Да; но не в этой версии', 'keys': ['yes'], 'note': ''}},
            {'text': 'Второй вопрос?', 'role': 'manager', 'multi': True,
             'options': [{'key': 'yes', 'label': 'Да'}, {'key': 'no', 'label': 'Нет'}],
             'answer': {'text': 'Да; Нет; Да; Нет; и Да, потом',
                        'keys': ['yes', 'no'], 'note': ''}},
        ]}}
        ui = _open_mini_app(browser, tasks=[same_lead])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askNote')
        assert ui.input_value('#askNote') == 'Да; но не в этой версии', \
            'начало вольного текста срезано вместе с меткой варианта'

        # Две отмеченные метки — срез тоже останавливается на двух, а не идёт по тексту
        ui.locator('.task-question-batch-tab').nth(1).click()
        ui.wait_for_selector('.task-question-text:text("Второй вопрос?")')
        assert ui.input_value('#askNote') == 'Да; Нет; и Да, потом'
        # Отметки на месте: разбор поля не должен стоить галочек варианта. Галочки
        # проставляются после вставки разметки (`setTimeout(0)` в `renderAsk`), поэтому
        # ждём вторую — она ставится только когда ключи ответа прочитаны целиком.
        ui.wait_for_function("""() => {
            const no = document.querySelector('.task-question-options input[value="no"]');
            return !!no && no.checked;
        }""")
        assert ui.locator('.task-question-options input[value="yes"]').is_checked()
        assert ui.locator('.task-question-options input[value="no"]').is_checked()

    def test_stale_answer_key_does_not_cut_deeper_than_the_labels(self, browser: Browser):
        """Черновик остался от прежнего вопроса — срез останавливается на подписях, не на ключах.

        `answer` собран сервером по вариантам того момента, а подписи `_labelsFor`
        считает по пришедшим сейчас: ключ, под который варианта нет, остаётся без метки
        и в префикс `text` не попадает (`_answer_labels`). Значит `keys` их может быть
        больше, чем меток впереди, — и граница по числу ключей дорезала бы фразу дальше,
        чем следует. Здесь префикс одна метка «Да», ключей два: при границе по ключам из
        вольного текста пропало бы его начало.
        """
        stale_key = {**TASK_PLAIN, 'metadata': {'questions': [
            {'text': 'Первый вопрос?', 'role': 'manager',
             'options': [{'key': 'yes', 'label': 'Да'}, {'key': 'no', 'label': 'Нет'}],
             # `drop` — ключ прежнего вопроса: вариант не пришёл, метки у него нет.
             'answer': {'text': 'Да; Да; но не в этой версии',
                        'keys': ['yes', 'drop'], 'note': ''}},
        ]}}
        ui = _open_mini_app(browser, tasks=[stale_key])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askNote')

        assert ui.input_value('#askNote') == 'Да; но не в этой версии', \
            'срез ориентировался на число ключей, а не на число меток в префиксе'
        # Пропущенный ключ не должен стоить и отметок: активным остаётся известный вариант.
        assert ui.locator('.task-question-options input[value="yes"]').is_checked()
        assert not ui.locator('.task-question-options input[value="no"]').is_checked()

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

    def test_answer_is_not_lost_when_the_question_call_fails(self, browser: Browser):
        """404 на GET — не беда: панель открыта со строки списка и ответ уходит."""
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])   # GET отвечает 404

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askSendBtn')
        ui.locator('.task-question-options label').first.click()
        ui.click('#askSendBtn')

        ui.wait_for_function("() => (window.__answered || []).length > 0")

    def test_goals_as_json_string_from_database(self, browser: Browser):
        """Колонку `goals` MySQL отдаёт строкой — список целей должен собраться и из неё."""
        as_string = _goal_question({**TASK_FLAGGED, 'goals': json.dumps(
            [{'text': 'Цель из строки', 'done': False}, 'Просто строкой'], ensure_ascii=False)})
        ui = _open_mini_app(browser, tasks=[as_string])

        ui.locator('.task-card').first.click()
        ui.click('.task-question-options input[value="goals_drop"]')
        ui.wait_for_selector('#askGoals input[name="askGoal"]', state='visible')

        html = ui.locator('#askGoals').inner_html()
        assert 'Цель из строки' in html and 'Просто строкой' in html
        assert ui.locator('#askGoals input[name="askGoal"]').count() == 2

    def test_garbage_goal_entry_is_not_numbered(self, browser: Browser):
        """`{}` и `{done: true}` без текста — не цель: под номером не должно быть `[object Object]`."""
        junk = _goal_question({**TASK_FLAGGED, 'goals': [{}, {'done': True}, {'text': 'Настоящая цель'}]})
        ui = _open_mini_app(browser, tasks=[junk])

        ui.locator('.task-card').first.click()
        ui.click('.task-question-options input[value="goals_drop"]')
        ui.wait_for_selector('#askGoals input[name="askGoal"]', state='visible')

        assert ui.locator('#askGoals input[name="askGoal"]').count() == 1
        assert 'object Object' not in ui.locator('#askGoals').inner_html()

    def test_server_goals_are_the_numbering_the_answer_uses(self, browser: Browser):
        """Отметка ведётся по серверному списку целей: к нему сервер и применит индексы.

        Карточка принесла три цели, GET — две (схлопнутые `task_plan_goals_normalize`).
        Нумерация с карточки отправила бы индекс мимо цели, поэтому панель обязана
        перерисоваться серверным списком.
        """
        row = {**TASK_FLAGGED, 'goals': ['Цель карточки раз', 'Цель карточки два',
                                         'Цель карточки три']}
        server = {'question': {'text': 'Как поступить с целями?', 'role': 'manager',
                               'options': [{'key': 'goals_drop', 'label': 'Убрать цель'}]},
                  'goals': [{'text': 'Цель сервера раз', 'done': False},
                            {'text': 'Цель сервера два', 'done': False}],
                  'decisions': []}
        ui = _open_mini_app(browser, tasks=[_goal_question(row)], question=lambda task: server)

        ui.locator('.task-card').first.click()
        # Ответ GET доезжает асинхронно: панель сначала собрана с карточки (три цели)
        ui.wait_for_function(
            "() => (document.querySelector('#askGoals') || {}).textContent"
                "?.includes('Цель сервера два')")
        assert 'Цель карточки' not in ui.locator('#askGoals').inner_text(), \
            'цели карточки остались под серверным списком'

        ui.click('.task-question-options input[value="goals_drop"]')
        ui.locator('#askGoals input[name="askGoal"]').nth(1).check()
        ui.click('#askSendBtn')

        ui.wait_for_function("() => (window.__answered || []).length > 0")
        body = json.loads(ui.evaluate('window.__answered')[0]['body'])
        assert body['goal_indexes'] == [1], 'индекс считается по целям карточки, а не сервера'

    def test_row_goals_stand_in_when_the_question_sends_none(self, browser: Browser):
        """GET без целей — панель остаётся с целями карточки: пустой список запирал бы ответ."""
        row = {**TASK_FLAGGED, 'goals': ['Цель из карточки']}
        ui = _open_mini_app(browser, tasks=[row], question={'question': {'text': 'Что-то', 'role': 'manager',
                                                                         'options': [{'key': 'goals_drop',
                                                                                    'label': 'Убрать'}]},
                                                           'goals': []})

        ui.locator('.task-card').first.click()
        ui.click('.task-question-options input[value="goals_drop"]')
        ui.wait_for_selector('#askGoals input[name="askGoal"]', state='visible')

        assert ui.locator('#askGoals input[name="askGoal"]').count() == 1
        assert 'Цель из карточки' in ui.locator('#askGoals').inner_text()

    def test_decisions_from_the_question_are_shown(self, browser: Browser):
        """Принятые решения дорисовывает GET — из строки списка их не взять."""
        ui = _open_mini_app(browser, tasks=[TASK_PLAIN], question={
            'question': {'text': 'Уточнить объём?', 'role': 'tester', 'options': []},
            'decisions': [{'question': 'Брать ли правку?', 'answer': 'Брать целиком', 'at': '2026-09-01'}],
        })

        ui.locator('.task-card').first.click()
        # Задача была без вопроса — панель сначала говорит «вопросов нет», ответ GET доезжает следом
        ui.wait_for_selector('.task-decision')

        # Сверка без учёта регистра: `.task-question-label` тянет `text-transform: uppercase`,
        # и `inner_text` возвращает уже поднятые буквы — регистр здесь не про смысл
        panel = ui.locator('.task-question-panel').inner_text().lower()
        assert 'принятые решения (1)' in panel
        assert 'Брать целиком' in ui.locator('.task-decision').first.inner_text()


class TestTaskListContract:
    """Список: контейнер из шаблона вкладки, ответ роутера и фильтр по фазе."""

    def test_list_draws_cards(self, browser: Browser):
        """Карточки появляются — значит контейнер найден по имени вкладки, а ответ разобран."""
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED, TASK_PLAIN])

        assert ui.locator('.task-card').count() == 2

    def test_every_module_actually_loads(self, browser: Browser):
        """Каждый модуль вкладки запрошен страницей.

        Мёртвый файл — тот, который никто не импортирует: он не участвует ни в одной
        проверке, но читателю обещает поведение, которого нет. Поэтому `MODULES`
        сверяется с фактическими запросами, а не остаётся списком «для порядка».
        """
        seen: list = []
        _open_mini_app(browser, tasks=[TASK_FLAGGED], scripts=seen)

        assert set(MODULES) <= set(seen), f'модули не загружаются: {set(MODULES) - set(seen)}'

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

    @pytest.mark.parametrize('task', [TASK_DONE_DEV, TASK_DONE_PIPELINE],
                            ids=['готово руками', 'закрыл конвейер'])
    def test_done_task_leaves_its_own_phase_for_testing(self, browser: Browser, task: dict):
        """Готовая работа — одна вкладка: тестировщик, а не «своя по типу» и не обе сразу.

        Закрытую задачу принимают именно там; у разработки кнопок приёмки нет, поэтому
        строка, оставшаяся на «Разработке», висела бы непринятой. Рядом лежит открытая
        работа того же типа — она-то на разработке и должна остаться.
        """
        # TASK_FLAGGED — якорь: без задачи на вкладке по умолчанию страница не считается открытой
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED, TASK_DEV_OPEN, task])

        ui.click('.task-phase-tab[data-phase="development"]')
        ui.wait_for_function(_card_counter(TASK_DEV_OPEN['title'], 1))
        assert _cards_named(ui, task['title']) == 0, 'готовая dev-задача осталась на разработке'

        ui.click('.task-phase-tab[data-phase="testing"]')
        ui.wait_for_function(_card_counter(task['title'], 1))
        assert _cards_named(ui, TASK_DEV_OPEN['title']) == 0, 'открытая задача ушла к тестировщику'

    def test_done_bug_stays_on_bug_tab(self, browser: Browser):
        """У бага инстанция своя: вкладка «Багфиксер» — полный цикл, уводить закрытый некуда."""
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED, TASK_DONE_BUG])

        ui.click('.task-phase-tab[data-phase="bugs"]')
        ui.wait_for_function(_card_counter(TASK_DONE_BUG['title'], 1))

        ui.click('.task-phase-tab[data-phase="testing"]')
        ui.wait_for_function(_card_counter(TASK_DONE_BUG['title'], 0))


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

    def test_head_does_not_share_height_with_the_list(self, browser: Browser):
        """Шапка (селектор проекта + вкладки фаз) не отдаёт высоту списку.

        Она стоит в той же flex-колонке, что и прокручиваемый список, и со значением
        `flex-shrink` по умолчанию сжимается вместе с ним: вкладки фаз уезжают за
        экран, а именно вкладкой определяется, какую половину задач человек видит.
        """
        ui = _open_mini_app(browser, tasks=[
            {**TASK_FLAGGED, 'id': 7100 + n, 'title': f'pytest: задача {n}'} for n in range(30)
        ])

        assert _style(ui, '.task-head', 'flex-shrink') == '0', 'шапка сожмётся длинным списком'

    def test_goals_block_is_set_apart_from_the_options(self, browser: Browser):
        """Цели рисуются теми же `.task-question-options`, что варианты ответа над ними,
        и без отрыва слипаются с ними в одну простыню: чекбоксы ниже — про цели.

        Проверяем на скрытом блоке: видимостью правит `_setGoalsVisible`, и править её
        в CSS значило бы спорить с кодом, поэтому стиль сверяется не с видимостью.
        """
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED])

        ui.locator('.task-card').first.click()
        ui.wait_for_selector('#askGoals', state='attached')

        assert _style(ui, '.task-question-goals', 'border-left-width') != '0px'

    def test_approve_button_follows_the_opened_card(self, browser: Browser):
        """Кнопка приёмки плана живёт в карточке открытой задачи и только при `plan_approval`.

        Флажки фаз без неё работают впустую: `to_development` — триггер того же перехода
        (чип `flag_dev` в `renderRootFlags`), а план, который нечем утвердить, до
        разработки не доводит.
        """
        ui = _open_mini_app(browser, tasks=[TASK_FLAGGED, TASK_PLAN_PASSED])

        card = ui.locator(f'.task-card[data-id="{TASK_FLAGGED["id"]}"]')
        card.click()
        ui.wait_for_selector('.task-approve-btn')
        assert 'Утвердить план' in card.inner_text()

        # Соседняя карточка — не на приёмке: кнопка рисуется в открытой, а не во всех сразу
        assert ui.locator(f'.task-card[data-id="{TASK_PLAN_PASSED["id"]}"] .task-approve-btn').count() == 0

        # Открыли ту, что уже прошла приёмку, — кнопка снимается, а не остаётся висеть
        ui.locator(f'.task-card[data-id="{TASK_PLAN_PASSED["id"]}"]').click()
        ui.wait_for_function("() => !document.querySelector('.task-approve-btn')")


def _open_mini_app(browser: Browser, tasks: list, *, flat: bool = False, question=None,
                   metadata_handler=None, styles: list | None = None,
                   scripts: list | None = None, metadata_status: int = 200,
                   answer=None) -> Page:
    """Открыть мини-приложение на подставных ответах; вернуть страницу с загруженным списком.

    `question` — ответ GET вопроса: словарь или функция от строки задачи. По умолчанию
    None — точка отвечает 404 («её ещё не нарисовали»), и панель работает со строки списка.
    `metadata_status` — код ответа точки сохранения: 500 рисует отказ флажка.
    `answer` — ответ на POST ответа: по умолчанию «отвечено на всё» (`done: true`);
    `{'done': False, 'left': 1}` — принят частичный, и панель листает пачку сама.
    """
    context = browser.new_context()
    page = context.new_page()
    # `Failed to load resource` — сообщение о статусе ответа, а не о поломке кода:
    # GET вопроса подменён на 404 намеренно (см. шапку файла). Настоящие ошибки
    # скриптов приходят отдельным событием `pageerror`, его и считываем.
    page.on('console', lambda msg: pytest.fail(f"ошибка в консоли: {msg.text}")
            if msg.type == 'error' and 'Failed to load resource' not in msg.text else None)
    page.on('pageerror', lambda err: pytest.fail(f"непойманная ошибка скрипта: {err}"))
    _attach_routes(page, tasks, flat=flat, question=question,
                   metadata_handler=metadata_handler, styles=styles, scripts=scripts,
                   metadata_status=metadata_status, answer=answer)

    page.goto('http://mini.test/telegram-app')
    page.wait_for_selector('.task-card')
    return page


def _attach_routes(page: Page, tasks: list, *, flat: bool, question=None, metadata_handler=None,
                   styles: list | None = None, scripts: list | None = None,
                   metadata_status: int = 200, answer=None) -> None:
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
            asked.append(path)
            # По умолчанию 404 — «точку ещё не нарисовали». Тесты про цели подкладывают
            # живой ответ: он и есть источник серверной нумерации `goal_indexes`.
            if question is None:
                route.fulfill(status=404, content_type='application/json',
                              body=json.dumps({'detail': 'вопрос рисует соседняя подзадача'}))
            else:
                payload = question(tasks[0]) if callable(question) else question
                route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))
        elif re.search(r'/task/\d+/metadata$', path):
            body = json.loads(route.request.post_data or '{}')
            saved.append({'path': path, 'body': route.request.post_data})
            if metadata_status != 200:
                route.fulfill(status=metadata_status, content_type='application/json',
                              body=json.dumps({'detail': 'сервер не сохранён'}))
                return
            if metadata_handler:
                meta = metadata_handler(body.get('patch') or {})
                tasks[0] = {**tasks[0], 'metadata': meta}
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'result': {'updated': list(body.get('patch', {}))}}))
        elif re.search(r'/task/\d+/question/answer$', path):
            answered.append({'path': path, 'body': route.request.post_data})
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps(answer if answer is not None else {'done': True, 'left': 0}))
        else:
            route.fulfill(status=404, content_type='application/json',
                          body=json.dumps({'detail': f'нет точки {path}'}))

        if scripts is not None and path.endswith('.js'):
            # Имя файла, а не путь: так проверка сверяется с MODULES, а не с тем,
            # в какую подпапку статики модуль переедет.
            scripts.append(path.rsplit('/', 1)[-1])
        if styles is not None and path.endswith('.css'):
            styles.append(path)

    page.route('**/*', handle)
    page.add_init_script("""
        window.__saved = []; window.__answered = []; window.__alerts = [];
        // alert() на принятом ответе — то же вранье, что и красный чип без причины:
        // считаем его как событие, а не глушим молча.
        window.alert = (msg) => { window.__alerts.push(String(msg)); };
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


def _goal_question(task: dict) -> dict:
    """Задача с вопросом, ответом на который правят цели: только такой список и открывается."""
    meta = dict(task.get('metadata') or {})
    meta['question'] = {'text': 'Как поступить с целями?', 'role': 'manager',
                        'options': [{'key': 'goals_drop', 'label': 'Убрать цель'},
                                    {'key': 'as_is', 'label': 'Оставить как есть'}]}
    return {**task, 'metadata': meta}


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


def _cards_named(page: Page, title: str) -> int:
    """Сколько карточек с таким заголовком на текущей вкладке.

    Счёт по тексту, а не по общему числу карточек: на вкладке лежит и якорная задача,
    и иначе «карточка ушла» было бы неотличимо от «карточка появилась».
    """
    return page.locator(f'.task-card:has-text("{title}")').count()


def _card_counter(title: str, expected: int) -> str:
    """JS-условие для `wait_for_function`: переключение вкладки перезагружает список."""
    return ("() => [...document.querySelectorAll('.task-card')]"
            f".filter(el => el.textContent.includes({json.dumps(title)})).length === {expected}")


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

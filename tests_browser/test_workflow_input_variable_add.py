"""Новая входящая переменная на `/admin/workflow`: имя из формы доезжает до базы.

## ⚠⚠⚠ Что здесь главное

Кнопка «+ Добавить переменную» заводит переменную **только на странице**: в базу
она уезжает вместе с workflow, по кнопке «Сохранить workflow». Между этими двумя
мигами имя живёт в скрытой строке `#inputVariablesContainer` — из неё и только из
неё читает `saveInputVariables`.

Беда, ради которой тест: у новой переменной скрытой строки **не находили**.
Форма правит объект в памяти и зовёт `syncHiddenRow`, а та ищет строку по
`[data-id="…"]`, которого у новой нет вовсе. Имя оставалось в объекте, скрытая
строка хранила пустоту, сохранение видело пустое имя и молча пропускало строку
(`if (!name) continue`). Человек видел: «переименовал, сохранил, имя прежнее» —
**без единой ошибки** ни в консоли, ни в панели.

Проверять это можно только браузером: и форма, и скрытая строка рисуются JS уже
после загрузки (`variables.js`), в разметке шаблона их нет.

## ⚠ Почему своя оснастка, а не общий слой

Застава предлагает `web_drive_page`, `web_unit_run`, `web_watch` — и этот разбор
для **этой же страницы** уже сделан в `test_workflow_subflow_maps.py`: первый
подключает модуль страницы к своей разметке, второй гоняет тесты на одном
js-файле, третий смотрит перемены DOM. Здесь же нужен путь по живой странице в
несколько щелчков и проверка того, что легло **в базу** после сохранения формы.

## ⚠ Workflow заводится свой и сносится после

Тест пишет в базу, и писать он обязан в чужое: переменная принадлежит workflow
(`agent_workflow_variable.workflow_id`). Брать живой — значит оставить в нём
мусор, если прогон упадёт на середине. Поэтому заводится пустой workflow и
сносится `finally` вместе со всем, что к нему приписалось.

## ⚠⚠ Сам этот тест не запускается в общем прогоне

Папки нет в `testpaths`, и правило проекта прямое: правишь страницу панели —
**предложи прогон и дождись ответа** (`tests_browser/conftest.py`).
"""

import os
import time

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Browser, Page, sync_playwright

from mysql_.mysql_query import mysql_query_run
from tests.constants import TEST_AUTH

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8011')

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Имя переменной, которое человек вписывает в форму вместо пустого.
#
# ⚠ Годный идентификатор: `saveInputVariables` и ручка PUT проверяют имя
# выражением `[A-Za-z_][A-Za-z0-9_]*` — пробел или дефис провалили бы тест по
# другой причине, чем проверяемая.
VAR_NAME = 'pytest_fresh_name'
VAR_DEFAULT = 'значение по умолчанию'
VAR_NOTE = 'зачем она нужна'

# Соседняя переменная: её правка — повод для перерисовки списка.
NEIGHBOUR_NAME = 'pytest_neighbour'
NEIGHBOUR_RENAMED = 'pytest_neighbour_renamed'

# ⚠ Имя с дефисом: метка `%имя%` в промпте ждёт идентификатор, и разборщик
# прочёл бы такое как текст задания. Ровно его и отвергают обе проверки.
BAD_NAME = 'pytest-bad-name'

# Имя, уже занятое переменной прогона: так было с `invite_done` у #72.
TAKEN_NAME = 'pytest_taken_name'

# Сохранение идёт сетью: PUT workflow, затем POST переменной. Ждём с запасом.
SAVE_WAIT_MS = 3000


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
def workflow_id():
    """Пустой workflow на один тест. Сносится вместе с переменными и историей."""
    name = f'pytest_input_var_{int(time.time() * 1000) % 100000000}'
    mysql_query_run(
        'INSERT INTO agent_workflow (`name`, `title`, `description`) '
        'VALUES (%s, %s, %s)', (name, name, 'временный workflow теста'))
    got = mysql_query_run('SELECT id FROM agent_workflow WHERE name = %s', (name,))
    new_id = int(got['rows'][0]['id'])

    try:
        yield new_id
    finally:
        mysql_query_run('DELETE FROM agent_workflow_variable WHERE workflow_id = %s',
                        (new_id,))
        mysql_query_run('DELETE FROM agent_workflow_history WHERE workflow_id = %s',
                        (new_id,))
        mysql_query_run('DELETE FROM agent_workflow WHERE id = %s', (new_id,))


@pytest.fixture
def settings(page: Page, workflow_id: int):
    """Открытая вкладка «Настройки» своего workflow."""
    _open_settings(page, workflow_id)

    return page


class TestTheFreshVariableReachesTheDatabase:
    """⚠⚠⚠ Главное: имя из формы новой переменной доезжает до базы."""

    def test_the_name_typed_in_the_form_is_saved(self, settings: Page,
                                                 workflow_id: int):
        """⚠⚠ Форма — единственное место, где у новой переменной есть имя.

        Связать её со скрытой строкой по номеру нельзя: номера у новой нет.
        Ломалось ровно здесь, и правда о ней переехала в состояние страницы.
        """
        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)
        _save_workflow(settings)

        names = [row['name'] for row in _variables_in_db(workflow_id)]

        assert VAR_NAME in names, \
            f'имени из формы в базе нет, там: {names or "пусто"}'

    def test_the_default_typed_in_the_form_is_saved(self, settings: Page,
                                                    workflow_id: int):
        """⚠ Умолчание правится в той же форме и той же дорогой, что имя."""
        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)
        _fill_form_default(settings, VAR_DEFAULT)
        _save_workflow(settings)

        saved = _variables_in_db(workflow_id)

        assert saved, 'переменная не завелась вовсе'
        assert saved[0]['default'] == VAR_DEFAULT, \
            f"умолчание не доехало: {saved[0]['default']!r}"

    def test_the_note_typed_in_the_form_is_saved(self, settings: Page,
                                                 workflow_id: int):
        """⚠⚠ Описание у новой переменной уезжает **только** этим POST.

        У существующей оно сохраняется само, отдельным PUT по уходу из поля, —
        а у новой слать PUT некуда, и до правки описание просто пропадало:
        форма его спрашивает, сохранение его не отправляло.
        """
        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)
        _fill_form_note(settings, VAR_NOTE)
        _save_workflow(settings)

        saved = _variables_in_db(workflow_id)

        assert saved, 'переменная не завелась вовсе'
        assert saved[0]['description'] == VAR_NOTE, \
            f"описание не доехало: {saved[0]['description']!r}"

    def test_the_variable_is_an_input_one(self, settings: Page, workflow_id: int):
        """⚠ Тип `input`: блок называется «Входящие переменные», и заведённая
        отсюда обязана попасть именно в них, а не в переменные прогона."""
        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)
        _save_workflow(settings)

        saved = _variables_in_db(workflow_id)

        assert saved, 'переменная не завелась вовсе'
        assert saved[0]['type'] == 'input', f"тип не тот: {saved[0]['type']}"

    def test_an_untouched_fresh_row_stays_out(self, settings: Page,
                                              workflow_id: int):
        """⚠⚠ Нажал «добавить» и передумал — в базу ничего не уехало.

        Безымянная переменная прошла бы в реестр и показалась бы в списках
        выбора пустой строкой: беда тихая, как и та, ради которой тест.
        """
        _add_variable(settings)
        _save_workflow(settings)

        assert not _variables_in_db(workflow_id), \
            'пустая строка уехала в базу'


class TestTheFreshVariableSurvivesARedraw:
    """⚠⚠⚠ Несохранённая переменная переживает перерисовку списка.

    Список перерисовывается не только по сохранению: хватит переименовать
    соседнюю переменную — `bindSave` зовёт `renderInputVariables`, та чистит
    контейнер целиком. Пока новая жила только узлами DOM, её при этом уносило
    вместе с набранным именем, молча. Поэтому она лежит в состоянии страницы
    (`state.inputVarPending`), а перерисовка рисует её заново.
    """

    def test_it_stays_after_renaming_a_neighbour(self, settings: Page,
                                                 workflow_id: int):
        """⚠⚠ Два дела подряд: завёл новую, поправил имя соседней.

        ⚠ Соседняя нужна настоящая — у пустого workflow её нет, и перерисовку
        нечем вызвать. Поэтому сперва заводим и сохраняем одну.
        """
        _add_variable(settings)
        _fill_form_name(settings, NEIGHBOUR_NAME)
        _save_workflow(settings)

        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)

        _pick_in_list(settings, NEIGHBOUR_NAME)
        _fill_form_name(settings, NEIGHBOUR_RENAMED)
        settings.wait_for_timeout(1500)

        shown = settings.locator('#inputVariablesList .input-var-label')

        assert VAR_NAME in shown.all_text_contents(), \
            f'новую унесло перерисовкой, в списке: {shown.all_text_contents()}'

    def test_it_still_reaches_the_database_after_that(self, settings: Page,
                                                      workflow_id: int):
        """⚠ И сохраняется: пережить перерисовку мало, надо доехать до базы."""
        _add_variable(settings)
        _fill_form_name(settings, NEIGHBOUR_NAME)
        _save_workflow(settings)

        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)

        _pick_in_list(settings, NEIGHBOUR_NAME)
        _fill_form_name(settings, NEIGHBOUR_RENAMED)
        settings.wait_for_timeout(1500)

        _save_workflow(settings)

        names = [row['name'] for row in _variables_in_db(workflow_id)]

        assert VAR_NAME in names, f'в базе: {names}'
        assert NEIGHBOUR_RENAMED in names, f'соседняя не переименовалась: {names}'


    def test_it_stays_after_a_trip_to_the_steps_tab(self, settings: Page,
                                                    workflow_id: int):
        """⚠⚠⚠ Сходил на «Шаги» и вернулся — переменная на месте и сохранилась.

        Самый обычный заход человека, и он ломался наглухо: «Шаги» зовут
        `loadWorkflowSteps`, та перечитывает переменные, перерисовка чистит
        список — и новой нет. Доклад с установки был именно такой: «добавляю,
        сохраняю, переменной нет».
        """
        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)

        settings.click('#tabSteps')
        settings.wait_for_timeout(1200)
        settings.click('#tabSettings')
        settings.wait_for_timeout(600)

        shown = settings.locator('#inputVariablesList .input-var-label')

        assert VAR_NAME in shown.all_text_contents(), \
            f'после захода на «Шаги» в списке: {shown.all_text_contents()}'

        _save_workflow(settings)
        names = [row['name'] for row in _variables_in_db(workflow_id)]

        assert VAR_NAME in names, f'в базе: {names or "пусто"}'


class TestANameTakenByAnotherKind:
    """⚠⚠⚠ Имя занято переменной прогона — ей меняется род, а не отказ.

    Ручка отбирала по одному имени, без рода: входящая натыкалась на
    `workflow`-переменную с тем же именем и получала в ответ **её** номер.
    Редактор рапортовал «сохранено», а список входящих отбирает по
    `type='input'` — и переменная пропадала из него на глазах. Поймано на
    `invite_done` у `dating_invite_one`.
    """

    def test_the_existing_variable_becomes_an_input(self, settings: Page,
                                                    workflow_id: int):
        _workflow_variable_make(workflow_id, TAKEN_NAME, 'workflow')
        settings.reload()
        _open_settings(settings, workflow_id)

        _add_variable(settings)
        _fill_form_name(settings, TAKEN_NAME)
        _save_workflow(settings)

        rows = [r for r in _variables_in_db(workflow_id) if r['name'] == TAKEN_NAME]

        assert len(rows) == 1, f'записей с этим именем {len(rows)}, ждали одну'
        assert rows[0]['type'] == 'input', f"род не сменился: {rows[0]['type']}"

    def test_it_shows_up_in_the_input_list(self, settings: Page,
                                           workflow_id: int):
        """⚠⚠ То самое, на что смотрит человек: переменная в списке входящих."""
        _workflow_variable_make(workflow_id, TAKEN_NAME, 'workflow')
        settings.reload()
        _open_settings(settings, workflow_id)

        _add_variable(settings)
        _fill_form_name(settings, TAKEN_NAME)
        _save_workflow(settings)

        shown = settings.locator('#inputVariablesList .input-var-label')

        assert TAKEN_NAME in shown.all_text_contents(), \
            f'во входящих её нет: {shown.all_text_contents()}'

    def test_the_change_of_kind_is_said_out_loud(self, settings: Page,
                                                 workflow_id: int):
        """⚠ Смена рода — не мелочь: значение теперь приходит снаружи."""
        _workflow_variable_make(workflow_id, TAKEN_NAME, 'workflow')
        settings.reload()
        _open_settings(settings, workflow_id)

        _add_variable(settings)
        _fill_form_name(settings, TAKEN_NAME)
        _save_workflow(settings)

        said = ' '.join(settings.locator('.notification').all_text_contents())

        assert TAKEN_NAME in said and 'входящая' in said, \
            f'о смене рода не сказано: {said!r}'

    def test_the_change_of_kind_lands_in_history(self, settings: Page,
                                                 workflow_id: int):
        """⚠⚠ История заведена ровно ради таких правок — молчать им нельзя."""
        _workflow_variable_make(workflow_id, TAKEN_NAME, 'workflow')
        settings.reload()
        _open_settings(settings, workflow_id)

        _add_variable(settings)
        _fill_form_name(settings, TAKEN_NAME)
        _save_workflow(settings)

        got = mysql_query_run(
            'SELECT `action`, `changes` FROM agent_workflow_history '
            "WHERE workflow_id = %s AND object = 'variable' AND object_name = %s",
            (workflow_id, TAKEN_NAME))
        rows = got.get('rows') or []

        assert rows, 'смена рода в историю не попала'
        assert 'workflow' in str(rows[-1]['changes']), \
            f"прежний род не записан: {rows[-1]['changes']}"

    def test_adding_the_same_input_twice_is_quiet(self, settings: Page,
                                                  workflow_id: int):
        """⚠ Повтор **того же** рода событием не является: страница заводит
        переменную и кнопкой, и подхватом из шага, и результат один и тот же."""
        _workflow_variable_make(workflow_id, TAKEN_NAME, 'input')
        settings.reload()
        _open_settings(settings, workflow_id)

        _add_variable(settings)
        _fill_form_name(settings, TAKEN_NAME)
        _save_workflow(settings)

        rows = [r for r in _variables_in_db(workflow_id) if r['name'] == TAKEN_NAME]

        assert len(rows) == 1, f'дубликат: записей {len(rows)}'
        assert rows[0]['type'] == 'input'


class TestABadNameIsNotSwallowed:
    """⚠⚠⚠ Пропущенная переменная больше не молчит.

    Прежде негодное имя давало две тишины подряд: поле само откатывалось к
    пустоте (у новой «прежнее значение» — пустая строка), а сохранение
    пропускало строку и показывало зелёное «Изменения успешно сохранены».
    Человек видел успех и не досчитывался переменной.
    """

    def test_the_typed_text_is_not_wiped(self, settings: Page):
        """⚠⚠ Набранное остаётся в поле: чинить можно на месте."""
        _add_variable(settings)
        _fill_form_name(settings, BAD_NAME)

        field = settings.locator('#inputVariablesForm input.form-control').first

        assert field.input_value() == BAD_NAME, \
            f'поле стёрли, там «{field.input_value()}»'

    def test_the_save_says_what_it_skipped(self, settings: Page,
                                           workflow_id: int):
        """⚠⚠⚠ Сохранение называет пропущенное, а не рапортует об успехе."""
        _add_variable(settings)
        _fill_form_name(settings, BAD_NAME)
        _save_workflow(settings)

        said = ' '.join(settings.locator('.notification').all_text_contents())

        assert BAD_NAME in said, f'о пропуске не сказано: {said!r}'
        assert not _variables_in_db(workflow_id), 'негодное имя уехало в базу'


class TestTheSaveKeepsTheTab:
    """⚠⚠⚠ Сохранение не уводит с вкладки, на которой человек правил.

    `initWorkflowManager` после сохранения перечитывает список и открывает тот
    же workflow заново, а открытие показывало «Шаги» всегда. Человек правил
    входящие переменные в «Настройках», жал «Сохранить» — и оказывался там, где
    переменных не видно вовсе. Доклад с установки был именно такой: «сохранил,
    перебросило на шаги, вернулся — переменной нет».
    """

    def test_the_settings_tab_stays_open(self, settings: Page):
        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)
        _save_workflow(settings)

        active = settings.locator('.tab-btn.active')

        assert active.get_attribute('id') == 'tabSettings', \
            f'увело на вкладку «{active.text_content().strip()}»'

    def test_the_fresh_variable_is_in_the_list_right_after_saving(
            self, settings: Page):
        """⚠ И список перечитан: имя пришло из базы, а не осталось от формы."""
        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)
        _save_workflow(settings)

        shown = settings.locator('#inputVariablesList .input-var-label')

        assert VAR_NAME in shown.all_text_contents(), \
            f'после сохранения в списке: {shown.all_text_contents()}'

    def test_the_fresh_variable_stays_selected(self, settings: Page):
        """⚠⚠ Форма остаётся на только что заведённой, а не прыгает на первую.

        Ключ `new:N` живёт до отъезда в базу; не переехав на номер, выбор после
        перечитывания не находил ничего и открывал `inputs[0]`. Человек
        сохранял свою переменную и смотрел на чужую — та же порода «куда делось
        то, что я правил».
        """
        _add_variable(settings)
        _fill_form_name(settings, NEIGHBOUR_NAME)
        _save_workflow(settings)

        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)
        _save_workflow(settings)

        field = settings.locator('#inputVariablesForm input.form-control').first

        assert field.input_value() == VAR_NAME, \
            f'форма ушла на «{field.input_value()}»'


class TestTheListShowsTheNewName:
    """⚠ Список слева — то, на что человек смотрит, решая «сохранилось ли».

    Имя он вписывает в форму справа, а подтверждения ждёт слева: там строка
    выбранной переменной. Пока она пишет «(без имени)», правка выглядит
    потерянной, даже если доехала.
    """

    def test_the_name_appears_in_the_list_before_saving(self, settings: Page):
        _add_variable(settings)
        _fill_form_name(settings, VAR_NAME)

        shown = settings.locator('#inputVariablesList .input-var-label').last

        assert shown.text_content().strip() == VAR_NAME, \
            f'в списке осталось «{shown.text_content().strip()}»'


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


def _open_settings(page: Page, workflow_id: int) -> None:
    """Открывает workflow по номеру и вкладку «Настройки».

    ⚠ Workflow — номером в адресе: список слева показывает `title`, и свежий
    пустой workflow искать там по имени не на что.

    ⚠⚠⚠ Ждём **заполненного `#workflowId`**, а не «сеть затихла». Обработчик
    вкладки первым делом смотрит на него и при пустом **молча выходит**
    (`main.js`), а заполняет его `fillWorkflowForm` — асинхронно, уже после
    ответа списка. `networkidle` этого не гарантирует: он говорит про запросы, а
    не про то, докуда дошёл обработчик между своими `await`. Поймано одиночным
    красным на пятом прогоне — щелчок пришёлся в это окно, «Настройки» не
    открылись, и кнопка добавления осталась невидимой при исправном коде.

    ⚠ Ждём ещё и наполнения списка слева: переменные грузятся отдельным
    запросом, и `renderInputVariables` чистит блок целиком — подоспей она после
    нашего «добавить», новая строка исчезла бы.
    """
    page.goto(f'{BASE_URL}/admin/workflow?workflow_id={workflow_id}')
    page.wait_for_function(
        f"() => document.getElementById('workflowId')?.value === '{workflow_id}'",
        timeout=15000)
    page.click('#tabSettings')
    page.wait_for_selector('#addInputVariableBtn', state='visible', timeout=10000)
    page.wait_for_selector(
        '#inputVariablesList .input-vars-empty, #inputVariablesList .input-var-name',
        state='attached', timeout=10000)


def _add_variable(page: Page) -> None:
    """Кнопка «+ Добавить переменную»: строка в списке и пустая форма."""
    page.click('#addInputVariableBtn')
    page.wait_for_selector('#inputVariablesForm input.form-control',
                           state='visible', timeout=5000)


def _fill_form_name(page: Page, name: str) -> None:
    """Имя в форме справа.

    ⚠ Уводим фокус явно: правка сохраняется по `blur`, а не по каждой букве.
    """
    field = page.locator('#inputVariablesForm input.form-control').first
    field.fill(name)
    field.blur()
    page.wait_for_timeout(200)


def _fill_form_default(page: Page, value: str) -> None:
    """Умолчание в форме справа: первая `textarea` блока."""
    field = page.locator('#inputVariablesForm textarea.form-control').first
    field.fill(value)
    field.blur()
    page.wait_for_timeout(200)


def _pick_in_list(page: Page, name: str) -> None:
    """Выбрать переменную в списке слева по её имени."""
    page.locator('#inputVariablesList .input-var-name').filter(
        has_text=name).first.click()
    page.wait_for_timeout(300)


def _fill_form_note(page: Page, value: str) -> None:
    """Описание в форме справа.

    ⚠ Поля там изначально нет: описание показано текстом, а поле открывается
    щелчком по нему (`noteView`). Читают описание в разы чаще, чем правят.
    """
    page.locator('#inputVariablesForm .note-text').click()
    field = page.locator('#inputVariablesForm textarea.field-note')
    field.fill(value)
    field.blur()
    page.wait_for_timeout(200)


def _save_workflow(page: Page) -> None:
    """Кнопка «Сохранить workflow» в подвале формы."""
    page.locator('.editor-footer .btn-save').click()
    page.wait_for_timeout(SAVE_WAIT_MS)


def _workflow_variable_make(workflow_id: int, name: str, kind: str) -> None:
    """Завести переменную записью в базу — мимо страницы.

    ⚠ Именно записью: род `workflow` редактор входящих завести не может, а
    проверяем мы столкновение с ней. Через страницу такую не поставить.
    """
    mysql_query_run(
        'INSERT INTO agent_workflow_variable (workflow_id, name, `type`) '
        'VALUES (%s, %s, %s)', (workflow_id, name, kind))


def _variables_in_db(workflow_id: int) -> list:
    """Переменные этого workflow: что вправду легло в базу."""
    got = mysql_query_run(
        'SELECT `name`, `type`, `default`, `description` '
        'FROM agent_workflow_variable WHERE workflow_id = %s ORDER BY id',
        (workflow_id,))

    return got.get('rows') or []

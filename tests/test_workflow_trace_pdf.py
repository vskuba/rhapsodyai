"""Выгрузка прогона в PDF: сборка документа и ссылки внутри него.

⚠⚠ Проверяется **разметка**, а не байты PDF: документ собирает
`ai_workflow_trace_pdf_html`, а печатает его Chrome, и печать в тесте стоила бы
запуска браузера на каждый прогон сюиты. Всё, что здесь может сломаться,
ломается в разметке — Chrome из неё делает ровно то, что в ней написано
(проверено живьём: 25 ссылок разметки стали 25 аннотациями `/Subtype /Link`).

⚠ Сторож ссылок (`test_every_link_has_its_target`) — главный в файле. Висячая
ссылка в PDF не видна ничем: она просто не срабатывает по щелчку, и узнают об
этом не раньше, чем кто-то щёлкнет.
"""
import json
import re

import pytest

from src.ai.ai_workflow_trace_pdf import (ai_workflow_trace_pdf_filename,
                                          ai_workflow_trace_pdf_html)

pytestmark = pytest.mark.ai

ICONS = {'topic_action': '🌿', 'llm_to_json': '🧠', 'workflow_invoke': '🇼'}

# Описание жребия ровно той формы, что лежит на проде: доля числом и доля
# «остатком», у `dice_batch` выпадает серия.
DICE_SPEC = {
    'dice_mail_opening': {'вспомнила о тебе': 40, 'новость про себя': 35,
                          'вопрос в лоб': 25},
    'dice_mail_story': {'да': 35, 'нет': 'rest'},
}

# Настройка прогона — то, что ручке отдаёт `ai_workflow_trace_pdf_source`.
SOURCE = {
    'agents': [{
        'id': 232, 'name': 'mail', 'title': 'Рассылка: шаблон',
        'node_name': 'Ladadate',
        'prompt_system': 'Ты пишешь письма от имени [[girl_name]].\n\nБудь краткой.',
        'agent_variable': '{"girl_name": "Валентина", "girl_age": 36}',
        'workflow_variable': None,
    }],
    'inputs': {
        7: [{'name': 'girl_name', 'default': None, 'description': 'Имя девушки'},
            {'name': 'tone', 'default': 'тёплый', 'description': None}],
    },
    'dice': {
        7: [{'step_id': 40, 'title': 'Жребий: приём письма', 'tool_name': 'dice',
             'spec_ref': 'dice_mail_spec',
             'outputs_map': {'dice_mail_opening': 'dice_mail_opening',
                             'dice_mail_story': 'dice_mail_story'}},
            {'step_id': 41, 'title': 'Жребий: не дошли', 'tool_name': 'dice',
             'spec_ref': 'dice_other_spec', 'outputs_map': {}}],
    },
}


@pytest.fixture
def run():
    """Прогон с петлёй, подпотоком и переходом в неисполненный шаг."""
    child = {
        'id': 900, 'run_uuid': 'child-uuid', 'parent_step_id': 30, 'depth': 1,
        'workflow_title': 'Полировка', 'workflow_name': 'polish',
        'status': 'success', 'duration_ms': 5000, 'variables_start': '{}',
        'prompt_user': 'Отполируй', 'result': 'ok', 'steps': [
            _step(910, 1, 301, 'Полировка текста', 'llm_to_json'),
        ], 'children': [],
    }
    return {
        'id': 500, 'run_uuid': 'root-uuid', 'depth': 0, 'status': 'success',
        'workflow_id': 7, 'agent_id': 232,
        'workflow_title': 'Рассылка: шаблон', 'workflow_name': 'dating_mail_write',
        'agent_title': 'Рассылка', 'agent_name': 'mail', 'duration_ms': 66200,
        'started_at': None, 'finished_at': None, 'session_uuid': 's-1',
        'request_uuid': 'r-1', 'message_id': 77,
        'prompt_user': 'Напиши шаблон письма.', 'result': 'Hello there.',
        'request_json': '{"question": "Напиши шаблон письма."}',
        'response_json': None, 'error': None,
        'variables_start': json.dumps(
            {'girl_name': 'Валентина', 'dice_mail_spec': json.dumps(DICE_SPEC, ensure_ascii=False)},
            ensure_ascii=False),
        'steps': [
            # Шаг 20 исполняется дважды — петля: ровно та форма, на которой
            # ссылка «откуда» показывала чужой заход.
            _step(101, 1, 20, 'Проверка темы', 'topic_action',
                  transition='{"phase": "after", "condition": "t == 1",'
                             ' "from_step_id": 20, "to_step_id": 30}'),
            _step(102, 2, 30, 'Вызов подпотока', 'workflow_invoke'),
            _step(103, 3, 20, 'Проверка темы', 'topic_action',
                  transition='{"phase": "after", "condition": "t == 2",'
                             ' "from_step_id": 20, "to_step_id": 999}'),
            # ⚠ Жребий стоит ПОСЛЕДНИМ намеренно: соседние тесты адресуют
            # `steps[0]`/`steps[1]`, и вставка в начало сдвинула бы их молча.
            _step(104, 4, 40, 'Жребий: приём письма', 'tool_invoke',
                  variables_changed=json.dumps(
                      {'dice_mail_opening': 'новость про себя',
                       'dice_mail_story': 'нет'}, ensure_ascii=False)),
        ],
        'children': [child],
    }


class TestWorkflowTracePdfDocument:

    def test_every_link_has_its_target(self, run):
        """Ни одна ссылка документа не висит: у каждой `href="#x"` есть `id="x"`."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        targets = set(re.findall(r'id="([^"]+)"', page))
        links = set(re.findall(r'href="#([^"]+)"', page))
        assert links, 'в документе нет ни одной внутренней ссылки'
        assert links <= targets, f'ссылки в никуда: {sorted(links - targets)}'

    def test_contents_lists_every_step_and_subflow(self, run):
        """Содержание перечисляет все шаги и подпотоки — и ровно в порядке тела."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        contents, body = page.split('id="summary"', 1)

        in_toc = re.findall(r'href="#((?:step|run)-\d+)"', contents)
        in_body = re.findall(r'<div class="(?:step|child)[^"]*" id="((?:step|run)-\d+)"', body)
        assert in_toc == in_body, 'содержание и тело документа разошлись порядком'
        assert set(in_toc) == {'step-101', 'step-102', 'step-103', 'step-104',
                               'run-900', 'step-910'}

    def test_transition_points_at_the_right_pass_of_the_loop(self, run):
        """У петли «откуда» — свой заход шага, «куда» — следующий, а не первый."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        # ⚠ Границей блока берётся следующий шаг (или конец документа), а не
        # первое `</div></div>`: закрывающих пар внутри одного шага много, и
        # срез по ним обрезал бы блок на середине перехода.
        block = re.split(r'<div class="step[ "]', page.split('id="step-103"', 1)[1])[0]

        # Третий шаг — второй заход в step_id 20: «откуда» это он сам (#3),
        # а не первый заход (#1), который показывался до починки.
        assert '#3 · Проверка темы (ID 20)' in block
        assert '#1 · Проверка темы (ID 20)' not in block
        # Переход ведёт в шаг, которого в прогоне нет, — так и сказано.
        assert 'шага нет в прогоне' in block

    def test_subflow_links_both_ways(self, run):
        """Подпоток и породивший его шаг ссылаются друг на друга."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        step = page.split('id="step-102"', 1)[1].split('id="run-900"', 1)[0]
        child = page.split('id="run-900"', 1)[1]

        assert 'href="#run-900"' in step, 'из шага нет ссылки вниз в подпоток'
        assert 'href="#step-102"' in child.split('</div>', 3)[0], \
            'из подпотока нет возврата в породивший шаг'

    def test_long_value_is_cut_and_the_cut_is_named(self, run):
        """Длинное значение обрезано, и обрезка названа — молча не теряем ничего."""
        run['steps'][0]['output'] = 'я' * 50_000
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        assert 'обрезано: показано' in page
        assert 'я' * 20_000 not in page, 'значение попало в документ целиком'

    def test_markup_from_data_is_escaped(self, run):
        """Данные прогона не становятся разметкой: заголовок шага экранирован."""
        run['steps'][0]['step_title'] = '<script>alert(1)</script>'
        run['prompt_user'] = '<img src=x onerror=alert(2)>'
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        assert '<script>alert(1)</script>' not in page
        assert '<img src=x' not in page
        assert '&lt;script&gt;' in page

    def test_missing_contract_says_why(self, run):
        """Пустой контракт объясняется словами, а не прочерком."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        assert 'не записан' in page.split('Response contract', 1)[1][:400]

    def test_filename_stays_ascii(self, run):
        """Имя файла остаётся ASCII без пробелов: оно уезжает в заголовок HTTP."""
        run['workflow_name'] = 'рассылка/шаблон письма'
        name = ai_workflow_trace_pdf_filename(run)
        assert name.isascii() and name.endswith('.pdf')
        assert '/' not in name and ' ' not in name


class TestWorkflowTracePdfValues:
    """Как показан вход шага: пары «ключ → значение», живые переносы, приметы."""

    def test_line_breaks_stay_breaks(self, run):
        """Перенос в значении остаётся переносом, а не знаками `\\n` в тексте.

        ⚠ Главный сторож этого класса. Прежний рендер делал
        `json.dumps(json.loads(...))` и экранировал переносы заново — абзацы
        письма приезжали в документ пунктуацией посреди строки. Глазами это
        ловится только на кадре, а здесь — одной подстрокой.
        """
        run['steps'][0]['metadata_rendered'] = json.dumps(
            {'prompt_user': 'Первая строка.\nВторая строка.\n\nНовый абзац.'},
            ensure_ascii=False)
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')

        assert '\\n' not in page, 'переносы уехали в документ знаками `\\n`'
        assert 'Первая строка.\nВторая строка.' in page

    def test_blank_line_runs_collapse_but_paragraphs_live(self, run):
        """Серия пустых строк сжата до абзаца: восемь подряд — дыра в треть листа.

        ⚠ Замер на проде: живой `dating_mail_write` шлёт до восьми переносов
        подряд, по 12 таких серий на значение. Сам абзац при этом обязан
        остаться — ради него вся правка и делалась.
        """
        run['steps'][0]['metadata_rendered'] = json.dumps(
            {'prompt_user': 'До.' + '\n' * 8 + 'После.\n\nОбычный абзац.'},
            ensure_ascii=False)
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')

        assert 'До.\n\nПосле.' in page, 'серия пустых строк не сжата'
        assert 'После.\n\nОбычный абзац.' in page, 'сжали и настоящий абзац'

    def test_object_becomes_key_value_rows(self, run):
        """Объект показан строками «ключ → значение», а не JSON-простынёй."""
        run['steps'][0]['metadata_rendered'] = json.dumps(
            {'prompt_user': 'текст', 'temperature': 0.8}, ensure_ascii=False)
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')

        assert '<td class="kv-key">prompt_user</td>' in page
        assert '<td class="kv-key">temperature</td>' in page
        # Фигурных скобок и кавычек JSON в показе объекта больше нет
        block = page.split('id="step-101"', 1)[1].split('Выход', 1)[0]
        assert '"prompt_user":' not in block

    def test_markers_are_highlighted(self, run):
        """Подстановки и рамки разделов подсвечены — их ищут глазами."""
        run['steps'][0]['metadata_rendered'] = json.dumps(
            {'prompt_user': '=== Раздел ===\nЗовут [[girl_name]], поле %companion_name%.'},
            ensure_ascii=False)
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')

        assert '<span class="mark-var">[[girl_name]]</span>' in page
        assert '<span class="mark-var">%companion_name%</span>' in page
        assert '<span class="mark-section">=== Раздел ===</span>' in page

    def test_marks_cannot_smuggle_markup(self, run):
        """Подсветка не превращает данные в разметку: `<` до неё уже экранирован."""
        run['steps'][0]['metadata_rendered'] = json.dumps(
            {'prompt_user': '[[<script>alert(1)</script>]]'}, ensure_ascii=False)
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')

        assert '<script>' not in page
        assert '&lt;script&gt;' in page

    def test_list_is_rows_and_plain_text_is_text(self, run):
        """Список — строки с номером ключа; не-JSON остаётся текстом.

        ⚠ Номер и есть честное имя элемента списка, поэтому форма у него та же
        таблица. А вот обычный текст в таблицу заворачивать нельзя: пары из
        него не выйдет, и врать формой — хуже, чем показать как есть.
        """
        run['steps'][0]['metadata_rendered'] = '[10, 20]'
        run['steps'][0]['variables_changed'] = 'просто текст, не JSON'
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        block = page.split('id="step-101"', 1)[1].split('id="step-102"', 1)[0]

        assert '<td class="kv-key">[0]</td>' in block
        assert '<td class="kv-key">[1]</td>' in block
        # Текст показан текстом, без выдуманных ключей вокруг него
        tail = block.split('Выход', 1)[1]
        assert 'просто текст, не JSON' in tail
        assert '<td class="kv-key">' not in tail, 'из текста собрали таблицу пар'

    def test_raw_output_gets_the_same_care(self, run):
        """`Raw output` — такое же значение: объект парами, текст абзацами.

        ⚠ Замер на проде: `output` шага в 68 случаях из 400 — объект, и в 142
        несёт переносы строк. Показывать его `<pre>`-лесенкой, когда соседний
        «Вход» уже разложен парами, значило бы два ответа на один вопрос.
        """
        run['steps'][0]['output'] = json.dumps(
            {'invite_keep': '1,2,4', 'invite_why': 'строка 3 повторяет\nстроку 2'},
            ensure_ascii=False)
        run['steps'][1]['output'] = 'Первая строка.\nВторая строка.'
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')

        first = page.split('id="step-101"', 1)[1].split('id="step-102"', 1)[0]
        assert '<td class="kv-key">invite_keep</td>' in first
        assert 'строка 3 повторяет\nстроку 2' in first, 'перенос внутри значения потерян'

        second = page.split('id="step-102"', 1)[1].split('id="run-900"', 1)[0]
        assert 'Первая строка.\nВторая строка.' in second

    def test_run_answer_gets_the_same_care(self, run):
        """Ответ прогона — абзацами и с подсветкой, а не монохромной лесенкой.

        ⚠ Замер на проде: 243 ответа из 400 несут переносы. Это письмо или
        реплика собеседнику, а не код.
        """
        run['result'] = 'Привет.\n\n\n\n\nЯ [[girl_name]].\n=== Подпись ==='
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        block = page.split('Ответ</div>', 1)[1].split('Request contract', 1)[0]

        assert 'Привет.\n\nЯ' in block, 'серия пустых строк не сжата в ответе'
        assert '<span class="mark-var">[[girl_name]]</span>' in block
        assert '<span class="mark-section">=== Подпись ===</span>' in block

    def test_failed_run_keeps_traceback_monospace(self, run):
        """Отказ остаётся `<pre>`: трейсбек — код, у него значимы отступы.

        ⚠ Исключение из общего показа, и намеренное: подсветка `%имя%` и
        сжатие пустых строк в трейсбеке меняли бы то, что надо читать буквой
        в букву.
        """
        run['status'] = 'error'
        run['error'] = 'Traceback (most recent call last):\n  File "x.py", line 1\n    %boom%'
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        block = page.split('Ошибка</div>', 1)[1].split('Request contract', 1)[0]

        assert '<pre>' in block, 'трейсбек потерял моноширинный блок'
        assert 'mark-var' not in block, 'в трейсбеке подсветили %имя%'

    def test_json_string_is_shown_decoded(self, run):
        """Строка JSON показывается РАЗОБРАННОЙ, а не исходной с `\\n`.

        ⚠⚠ Ровно эта беда и жила: `output` шага бывает строкой JSON, разбор
        давал настоящие переносы, а в документ уезжала исходная строка — с
        кавычками и `\\n`. Поймано замером на живом прогоне прода: 145
        литеральных `\\n` там, где ожидался ноль.
        """
        run['steps'][0]['output'] = json.dumps('Строка раз.\nСтрока два.')
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        block = page.split('id="step-101"', 1)[1].split('id="step-102"', 1)[0]

        assert 'Строка раз.\nСтрока два.' in block
        assert '\\n' not in block, 'показана исходная строка JSON, а не разобранная'

    def test_nested_values_keep_their_line_breaks(self, run):
        """Вложенный список объектов раскладывается, а не сериализуется в `\\n`.

        ⚠⚠ Форма с прода: `variable_conversion` — список объектов, и у его
        `text` внутри настоящие переносы. `json.dumps` на вложенном значении
        съедал их все (34 штуки в одном поле).
        """
        run['steps'][0]['metadata_rendered'] = json.dumps({
            'variable_conversion': [
                {'variable': 'invite_done', 'text': 'Первая.\n---\nВторая.'},
            ]}, ensure_ascii=False)
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        block = page.split('id="step-101"', 1)[1].split('id="step-102"', 1)[0]

        assert 'Первая.\n---\nВторая.' in block, 'переносы вложенного значения потеряны'
        assert '<td class="kv-key">variable_conversion</td>' in block
        assert '<td class="kv-key">text</td>' in block, 'вложенный объект не разложен'
        assert '\\n' not in block

    def test_nesting_stops_at_the_ceiling(self, run):
        """Глубже потолка — JSON, а не бесконечные вложенные таблицы."""
        deep = {'a': {'b': {'c': {'d': {'e': 'дно'}}}}}
        run['steps'][0]['metadata_rendered'] = json.dumps(deep, ensure_ascii=False)
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        block = page.split('id="step-101"', 1)[1].split('id="step-102"', 1)[0]

        assert 'дно' in block, 'глубокое значение потерялось вовсе'
        assert 'kv-json' in block, 'на потолке не перешли к JSON'

    def test_literal_escapes_in_data_stay_literal(self, run):
        """`\\n`, правда лежащие в данных, так и показываются — это не беда.

        ⚠ В промпт движок вклеивает JSON прошлого шага строкой, и модель
        видела там ровно `\\n`. Подменять их переносами значило бы врать о том,
        чем её кормили.
        """
        run['steps'][0]['metadata_rendered'] = json.dumps(
            {'prompt_user': 'Было прислано: {"why": "строка 1\\nстрока 2"}'},
            ensure_ascii=False)
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        block = page.split('id="step-101"', 1)[1].split('id="step-102"', 1)[0]

        assert 'строка 1\\nстрока 2' in block, 'подменили данные переносами'

    def test_long_value_inside_a_pair_is_cut(self, run):
        """Обрезка работает и внутри пары, а не только у блока."""
        run['steps'][0]['metadata_rendered'] = json.dumps(
            {'prompt_user': 'я' * 50_000}, ensure_ascii=False)
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')

        assert 'обрезано: показано' in page
        assert 'я' * 20_000 not in page


class TestWorkflowTracePdfSetup:
    """Разделы «Агент» и «Workflow»: чем прогон был задан, а не что в нём было."""

    def test_sections_are_absent_without_source(self, run):
        """Нет справочников — нет и разделов: документ обязан собраться без них."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0')
        assert 'id="agent"' not in page
        assert 'id="workflow"' not in page
        assert 'id="steps"' in page, 'без справочников развалился весь документ'

    def test_agent_shows_prompt_and_variables(self, run):
        """Агент: системный промпт и переменные агента — и оговорка «на сейчас»."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0', SOURCE)

        block = page.split('id="agent"', 1)[1].split('id="workflow"', 1)[0]
        # ⚠ Подстановка в промпте подсвечена, поэтому строка разрезана
        # span-ом — проверяем обе половины и саму подсветку.
        assert 'Ты пишешь письма от имени' in block
        assert '<span class="mark-var">[[girl_name]]</span>' in block
        assert 'Будь краткой.' in block
        assert '<td class="kv-key">girl_name</td>' in block
        assert 'Валентина' in block
        # ⚠ Оговорка обязательна: промпт трасса не хранит, и с тех пор его
        # могли править. Без неё раздел читался бы как «вот чем кормили».
        assert 'какая она сейчас' in block

    def test_workflow_shows_declared_inputs_with_values(self, run):
        """Входящие переменные ветки — с их значениями и источником значения."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0', SOURCE)
        block = page.split('id="workflow"', 1)[1].split('id="variables"', 1)[0]

        assert '%girl_name%' in block
        assert 'Валентина' in block and 'прогон' in block
        # Объявленная, но не присланная — показывает умолчание, а не пустоту
        assert '%tone%' in block and 'умолчание' in block and 'тёплый' in block

    def test_dice_lists_every_option_and_marks_the_rolled_one(self, run):
        """Жребий: все варианты с долями, выпавший помечен."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0', SOURCE)
        block = page.split('id="workflow"', 1)[1].split('id="variables"', 1)[0]

        # Все варианты на месте, а не только выпавший
        for option in ('вспомнила о тебе', 'новость про себя', 'вопрос в лоб'):
            assert option in block, f'вариант «{option}» потерян'
        # Выпавший помечен строкой-попаданием
        hit = [row for row in block.split('<tr') if 'новость про себя' in row]
        assert hit and 'dice-hit' in hit[0], 'выпавший вариант не помечен'
        assert '40%' in block and '25%' in block

    def test_dice_rest_share_is_named(self, run):
        """Доля «остаток» показана числом, а не словом `rest`."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0', SOURCE)
        block = page.split('id="workflow"', 1)[1].split('id="variables"', 1)[0]
        assert 'остаток (65%)' in block, 'rest не переведён в проценты'

    def test_dice_that_never_fired_is_still_listed(self, run):
        """Жребий, до которого прогон не дошёл, остаётся в списке и подписан."""
        page = ai_workflow_trace_pdf_html(run, ICONS, '+0', SOURCE)
        block = page.split('id="workflow"', 1)[1].split('id="variables"', 1)[0]

        assert 'Жребий: не дошли' in block
        assert 'не бросали' in block, 'несработавший жребий выдан за сработавший'


# ── вспомогательное ────────────────────────────────────────────────────────

def _step(trace_id, exec_index, step_id, title, step_type, **extra):
    """Строка шага трассы — ровно те поля, что отдаёт ручка детали."""
    step = {'id': trace_id, 'exec_index': exec_index, 'step_id': step_id,
            'step_title': title, 'step_type': step_type, 'status': 'success',
            'duration_ms': 1000, 'metadata_rendered': '{"a": 1}',
            'variables_changed': '{"b": 2}', 'output': 'ok', 'transition': None,
            'error': None, 'llm_name': None, 'tokens_input': None,
            'tokens_output': None}
    step.update(extra)
    return step

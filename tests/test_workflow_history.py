"""История правок workflow: дифф, запись и лента.

## ⚠⚠⚠ ЗАЧЕМ: ошибка была неявной

03.10.2026 цикл инвайтов стал давать один шаблон вместо одиннадцати — у шага
`workflow_invoke` поле `repeat.count` потеряло метку `%invite_count%` и стало
единицей. Ошибки не случилось **ни одной**: прогон шёл, пул набирался, панель
докладывала «готово 93». А следа правки не было нигде, и время поломки искали
косвенно — по числу разных текстов в чужой базе, с точностью до трёх минут.

## Что проверяется

**Дифф** — главное. Он отвечает на вопрос «что стало другим», и именно его
отсутствие стоило того дня: плоское «изменилось metadata» на 656 знаков
человеку не говорит ничего.

**Что пустая правка записи не заводит.** Автосохранение шлёт `PUT` через 400 мс
после касания поля, и «тронул, но не изменил» — не событие.

**Что длинные значения идут только изменившимися строками** (решение человека:
полный промпт в истории не нужен ни «до», ни «после»).

**Что запись не роняет правку**: журнал важен, но правка важнее.

⚠⚠ **База напрямую здесь не трогается вовсе, и это не удобство.** Пул соединений
привязан к событийной петле; инициализируй его тест — и session-уборка сюиты
(`conftest.cleanup_test_tasks`) падает потом «attached to a different loop», то
есть один файл ломает прогон всем. Поэтому запись проверяется **настоящей
дорогой**: ручки правки по HTTP, лента — ручкой чтения.
"""

import json
import uuid

import pytest

from src.ai.ai_workflow_history import (HISTORY_LINES_MAX,
                                        HISTORY_VALUE_SHORT,
                                        workflow_history_changes,
                                        workflow_history_name)

pytestmark = pytest.mark.core

# Приставка имени у заводимых workflow — **та же, что у соседних тестов**
# (`test_workflow_crud.py`): по ней сюита убирает за собой.
TEST_WF_PREFIX = 'test_wf_pytest_'


class TestTheDiffFindsTheChangedKey:
    """⚠⚠ Главное: путь до листа, а не «изменилось metadata»."""

    def test_the_very_loss_that_started_this(self):
        """Ровно та правка, что сломала инвайты: метка стала единицей."""
        was = {'metadata': json.dumps({'workflow_invoke': {
            'workflow_id': 72, 'repeat': {'count': '%invite_count%'}}})}
        now = {'metadata': json.dumps({'workflow_invoke': {
            'workflow_id': 72, 'repeat': {'count': 1}}})}

        got = workflow_history_changes(was, now)

        assert len(got) == 1, f'ожидалась одна правка, пришло {got}'
        assert got[0]['field'] == 'metadata.workflow_invoke.repeat.count'
        assert got[0]['was'] == '%invite_count%'
        assert got[0]['now'] == 1

    def test_a_number_and_a_string_are_not_the_same(self):
        """⚠⚠ `1` и `"1"` — разное, и это не придирка: единица против
        строки-метки и есть та разница, из-за которой история завелась."""
        got = workflow_history_changes({'metadata': '{"a": 1}'},
                                       {'metadata': '{"a": "1"}'})

        assert len(got) == 1, got

    def test_key_order_is_not_a_change(self):
        """⚠ Метаданные приезжают строкой JSON, и смена порядка ключей правкой
        не является: сравнивай их как строки — каждое сохранение было бы
        «изменением»."""
        got = workflow_history_changes({'metadata': '{"a": 1, "b": 2}'},
                                       {'metadata': '{"b": 2, "a": 1}'})

        assert got == [], got

    def test_an_added_key_is_found(self):
        got = workflow_history_changes({'metadata': '{}'},
                                       {'metadata': '{"repeat": {"count": 3}}'})

        assert [one['field'] for one in got] == ['metadata.repeat.count']
        assert got[0]['was'] is None

    def test_a_removed_key_is_found(self):
        got = workflow_history_changes({'metadata': '{"repeat": {"count": 3}}'},
                                       {'metadata': '{}'})

        assert got[0]['field'] == 'metadata.repeat.count'
        assert got[0]['now'] is None

    def test_plain_fields_work_too(self):
        got = workflow_history_changes({'title': 'Жребий'}, {'title': 'Кубик'})

        assert got == [{'field': 'title', 'was': 'Жребий', 'now': 'Кубик'}]

    def test_only_sent_fields_are_compared(self):
        """⚠ В запросе шага приезжают `metadata` и `title`; отсутствие прочих
        полей не значит, что их стёрли."""
        got = workflow_history_changes({'title': 'A', 'position': 5},
                                       {'title': 'A'})

        assert got == [], got

    def test_service_fields_are_skipped(self):
        got = workflow_history_changes({'id': 1, 'updated_at': 'вчера'},
                                       {'id': 2, 'updated_at': 'сегодня'})

        assert got == [], 'служебные поля попали в историю'

    def test_broken_json_does_not_crash(self):
        """⚠ Не разобралось — сравниваем как есть: история не должна ронять
        правку из-за своего разбора."""
        got = workflow_history_changes({'metadata': '{не json'},
                                       {'metadata': '{тоже не json'})

        assert len(got) == 1 and got[0]['field'] == 'metadata'


class TestLongValuesComeAsChangedLinesOnly:
    """⚠ Решение человека: полный промпт не нужен ни «до», ни «после»."""

    @staticmethod
    def _prompt(line_7: str) -> str:
        rows = [f'строка {n}' for n in range(1, 13)]
        rows[6] = line_7

        # ⚠ Длиннее порога: иначе сработает обычный путь «целиком».
        return '\n'.join(rows) + '\n' + 'х' * HISTORY_VALUE_SHORT

    def test_only_the_changed_line_is_kept(self):
        got = workflow_history_changes(
            {'metadata': json.dumps({'prompt_user': self._prompt('было так')})},
            {'metadata': json.dumps({'prompt_user': self._prompt('стало иначе')})})

        assert len(got) == 1
        one = got[0]
        assert one['field'] == 'metadata.prompt_user'
        assert 'was' not in one and 'now' not in one, \
            'полный текст промпта всё ещё хранится'

        texts = [row['text'] for row in one['lines']]
        assert 'было так' in texts and 'стало иначе' in texts
        assert not any('строка 3' in one for one in texts), \
            'в историю уехали неизменившиеся строки'

    def test_line_numbers_are_human(self):
        """Номер с единицы: по нему ищут глазами в поле промпта."""
        got = workflow_history_changes(
            {'metadata': json.dumps({'prompt_user': self._prompt('было')})},
            {'metadata': json.dumps({'prompt_user': self._prompt('стало')})})

        assert {row['line'] for row in got[0]['lines']} == {7}

    def test_a_rewritten_prompt_is_capped(self):
        """⚠ Переписанный целиком промпт не перечисляется построчно: довольно
        сказать «и ещё N»."""
        one = '\n'.join(f'было {n}' for n in range(60)) + 'х' * HISTORY_VALUE_SHORT
        two = '\n'.join(f'стало {n}' for n in range(60)) + 'х' * HISTORY_VALUE_SHORT

        got = workflow_history_changes({'metadata': json.dumps({'p': one})},
                                       {'metadata': json.dumps({'p': two})})

        lines = got[0]['lines']
        assert len(lines) == HISTORY_LINES_MAX + 1
        assert 'more' in lines[-1], lines[-1]

    def test_short_values_stay_whole(self):
        got = workflow_history_changes({'title': 'коротко'}, {'title': 'тоже'})

        assert got[0]['was'] == 'коротко' and got[0]['now'] == 'тоже'




class TestTheRealPathWrites:
    """⚠⚠ Запись проверяется настоящей дорогой: ручки правки по HTTP.

    База напрямую не трогается — см. шапку модуля.
    """

    @pytest.fixture
    async def step(self, client):
        """Заведённый workflow со шагом. Отдаёт `(номер workflow, номер шага)`.

        ⚠ Убирает за собой сам: удаление workflow уносит шаги, а историю
        оставляет — у неё нет внешнего ключа намеренно, и запись «кто удалил»
        обязана пережить удаление.
        """
        made = (await client.post('/workflow', json={
            'name': f'{TEST_WF_PREFIX}{uuid.uuid4().hex[:8]}',
            'title': 'История: стенд'})).json()['result']
        workflow_id = int(made if isinstance(made, int) else made.get('id'))

        step_id = int((await client.post(f'/workflow/{workflow_id}/step',
                                         json={'type_id': 1})).json()['result'])

        yield workflow_id, step_id

        await client.delete(f'/workflow/{workflow_id}')

    async def _feed(self, client, workflow_id: int, **ask) -> dict:
        tail = ''.join(f'&{k}={v}' for k, v in ask.items())

        return (await client.get(
            f'/workflow/{workflow_id}/history?limit=100{tail}')).json()

    async def test_a_real_edit_lands_in_the_feed(self, client, step):
        """Та самая правка: метка в `repeat.count` заменена единицей."""
        workflow_id, step_id = step

        was = json.dumps({'workflow_invoke': {'workflow_id': 72,
                                              'repeat': {'count': '%invite_count%'}}})
        await client.put(f'/workflow/{workflow_id}/step/{step_id}',
                         json={'metadata': was, 'title': 'Цикл'})

        now = json.dumps({'workflow_invoke': {'workflow_id': 72,
                                              'repeat': {'count': 1}}})
        await client.put(f'/workflow/{workflow_id}/step/{step_id}',
                         json={'metadata': now, 'title': 'Цикл'})

        got = await self._feed(client, workflow_id)
        edits = [one for one in got['result'] if one['action'] == 'update']

        assert edits, f'правка не попала в историю: {got}'
        fields = [row['field'] for one in edits for row in one['changes']]
        assert 'metadata.workflow_invoke.repeat.count' in fields, fields

    async def test_the_same_metadata_writes_nothing(self, client, step):
        """⚠⚠ Автосохранение не означает, что было изменение."""
        workflow_id, step_id = step
        same = json.dumps({'a': 1})

        await client.put(f'/workflow/{workflow_id}/step/{step_id}',
                         json={'metadata': same, 'title': 'Шаг'})
        before = len((await self._feed(client, workflow_id))['result'])

        # Тот же запрос ещё дважды — ровно то, что делает автосохранение на
        # щелчок по полю.
        for _ in range(2):
            await client.put(f'/workflow/{workflow_id}/step/{step_id}',
                             json={'metadata': same, 'title': 'Шаг'})

        after = len((await self._feed(client, workflow_id))['result'])

        assert after == before, \
            'повтор той же правки завёл запись — лента забьётся пустыми'

    async def test_creating_a_step_is_an_event(self, client, step):
        workflow_id, _ = step
        got = await self._feed(client, workflow_id)

        assert any(one['action'] == 'create' and one['object'] == 'step'
                   for one in got['result']), got['result']

    async def test_deleting_a_step_keeps_its_name(self, client, step):
        """⚠⚠ Имя копией: после удаления шага его больше не существует, а
        запись «удалён шаг #803» через месяц не читается никак."""
        workflow_id, step_id = step

        await client.put(f'/workflow/{workflow_id}/step/{step_id}',
                         json={'metadata': '{}', 'title': 'Жребий'})
        await client.delete(f'/workflow/{workflow_id}/step/{step_id}')

        got = await self._feed(client, workflow_id)
        gone = [one for one in got['result'] if one['action'] == 'delete']

        assert gone, got['result']
        assert gone[0]['object_name'] == 'Жребий', gone[0]

    async def test_the_author_is_the_logged_in_user(self, client, step):
        workflow_id, step_id = step

        await client.put(f'/workflow/{workflow_id}/step/{step_id}',
                         json={'metadata': '{"x": 1}', 'title': 'Шаг'})

        got = await self._feed(client, workflow_id)

        assert got['result'][0]['author'] == 'human'
        assert got['result'][0]['username'], 'правка без автора'

    async def test_a_variable_edit_lands_too(self, client, step):
        workflow_id, _ = step

        made = (await client.post(f'/workflow/{workflow_id}/variable', json={
            'name': 'invite_count', 'default': '1'})).json()['result']
        await client.put(f'/workflow/{workflow_id}/variable/{int(made)}',
                         json={'default': '11'})

        got = await self._feed(client, workflow_id, object='variable')
        edits = [one for one in got['result'] if one['action'] == 'update']

        assert edits, got['result']
        assert edits[0]['changes'][0]['now'] == '11', edits[0]['changes']

    async def test_the_workflow_rename_lands(self, client, step):
        workflow_id, _ = step

        await client.put(f'/workflow/{workflow_id}',
                         json={'title': 'История: переименован'})

        got = await self._feed(client, workflow_id, object='workflow')

        assert any(row['field'] == 'title'
                   for one in got['result'] for row in one['changes']), got


class TestTheFeedReads:
    """Ручка вкладки: отбор и страницы — **на сервере**.

    ⚠ Отдай ручка всё и листай страница сама — «все правки этого шага» означало
    бы «те, что попали на открытую страницу», а список молча обрывался бы на
    пределе: эту грабли уже проходили диалоги и журнал доставки в DatingAi.
    """

    async def test_an_empty_history_still_answers_the_pager(self, client):
        """⚠ Пустой ответ несёт те же поля: `pages: undefined` нарисовало бы
        пейджер из одной мёртвой страницы вместо пустого подвала."""
        got = (await client.get('/workflow/999777/history')).json()

        assert got == {'result': [], 'total': 0, 'page': 1, 'pages': 1}

    async def test_a_page_past_the_end_is_corrected(self, client):
        """⚠ Лента растёт на каждой правке: номер, открытый минуту назад, мог
        стать несуществующим — сервер поправит."""
        got = (await client.get('/workflow/999777/history?page=99')).json()

        assert got['page'] == 1, got


class TestTheTabIsWired:
    """⚠ Вкладка и её проводка: лента бесполезна, если её не открыть.

    Проверяется **разметка и связи**, а не вид: у вида нет утверждения, которое
    не ломалось бы от смены отступа (тот же довод, что в
    `test_workflow_subflow_maps.py`).
    """

    PAGE = 'data/uvicorn/template/admin/agent_workflow.html'
    MAIN = 'data/uvicorn/public/js/workflow/main.js'

    def test_the_fourth_tab_exists(self):
        page = open(self.PAGE, encoding='utf-8').read()

        assert 'id="tabHistory"' in page, 'кнопки вкладки нет'
        assert 'id="workflowHistory"' in page, 'панели ленты нет'

    def test_the_tab_opens_the_feed(self):
        main = open(self.MAIN, encoding='utf-8').read()

        assert "getElementById('tabHistory')" in main, 'вкладка ни к чему не привязана'
        assert 'openWorkflowHistory' in main, 'лента не читается при открытии'

    def test_every_other_tab_hides_the_feed(self):
        """⚠⚠ Все три соседние, а не только текущая: вкладку открывают с любой
        из них, и забытая оставила бы ленту видимой под шагами."""
        main = open(self.MAIN, encoding='utf-8').read()

        assert main.count("getElementById('workflowHistory').style.display = 'none'") >= 3, \
            'какая-то из вкладок не прячет историю'

    def test_the_feed_is_not_read_on_page_load(self):
        """⚠ Правки читаются при открытии вкладки, а не при загрузке страницы:
        на странице, где историю не смотрят, это лишний запрос на каждое
        открытие workflow."""
        page = open(self.PAGE, encoding='utf-8').read()
        at = page.index('id="workflowHistory"')

        assert 'display: none' in page[at:at + 120], 'панель открыта по умолчанию'

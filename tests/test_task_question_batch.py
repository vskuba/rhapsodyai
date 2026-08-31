"""
Пачка вопросов разведки: ответы черновиками, порядок свободный.

Зачем отдельно от одиночного вопроса роли. У того механика простая: спросил —
ответили — пошёл дальше. Здесь развилок сразу несколько, и отвечают на них не подряд:
ответ на третий вопрос нередко меняет ответ на первый, поэтому человек ходит между
ними и правит уже данные ответы.

Главное, что проверяется: **до последнего ответа ничего не считается решённым**. В
`decisions` пачка уезжает целиком и разом. Половина развилок, поданная роли как
решённая, хуже, чем ни одной, — она примет её за полный ответ и спланирует по нему.

Второе: черновик помнит не только текст ответа, но и чем его набрали. Вернувшись к
отвеченному вопросу, человек должен увидеть свой выбор отмеченным, а не пустую форму,
иначе правка превращается в ответ заново.

Тесты заводят свою строку и сносят её в конце.
"""

import pytest

pytestmark = pytest.mark.pipeline

TEST_TITLE = '__pytest_question_batch'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """Закрыть пул MySQL после теста: он привязан к циклу, а цикл у каждого теста свой."""
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


@pytest.fixture
async def task():
    """Строка задачи с пачкой из трёх вопросов: два с вариантами, один открытый."""
    from mysql_.mysql_ import mysql_get_db_async
    from src.project.task.task_question import task_question_set_many

    await _drop()
    async with mysql_get_db_async() as db:
        await db.execute("INSERT INTO project_task (title, pipeline_state) VALUES (%s, 'new')",
                         (TEST_TITLE,))
        task_id = db.lastrowid
        await db.connection.commit()

    await task_question_set_many(task_id, [
        {'text': 'Первый', 'options': ['А', 'Б']},
        {'text': 'Второй', 'options': ['В', 'Г']},
        {'text': 'Третий'}], role='manager')

    yield task_id

    await _drop()


class TestBatch:
    """Ответы копятся черновиками и уезжают в решения разом."""

    async def test_partial_answers_make_no_decisions(self, task):
        """
        Главное правило. Пока хоть одна развилка без ответа, роль не должна увидеть
        ничего: половина ответов читается ею как полный ответ.
        """
        from src.project.task.task_question import task_question_batch_answer, task_question_decisions

        result = await task_question_batch_answer(task, await _row(task), 0, ['1'], '')

        assert result['done'] is False
        assert result['left'] == 2
        assert task_question_decisions(await _row(task)) == []

    async def test_any_order(self, task):
        """
        Порядок свободный: отвечаем с последнего. Человек читает всю пачку и начинает
        с того, что ему яснее.
        """
        from src.project.task.task_question import task_question_batch_answer

        assert (await task_question_batch_answer(task, await _row(task), 2, [], 'ответ'))['left'] == 2
        assert (await task_question_batch_answer(task, await _row(task), 1, ['1'], ''))['left'] == 1

    async def test_answer_can_be_changed(self, task):
        """
        Правка ответа — обычное дело, пока пачка открыта, и она не должна считаться
        вторым ответом: счётчик оставшихся не меняется, а в решение уедет последний.
        """
        from src.project.task.task_question import task_question_batch_answer

        await task_question_batch_answer(task, await _row(task), 0, ['1'], '')
        again = await task_question_batch_answer(task, await _row(task), 0, ['2'], 'передумал')

        assert again['left'] == 2, 'правка не должна считаться новым ответом'
        assert (await _batch(task))[0]['answer']['text'] == 'Б; передумал'

    async def test_last_answer_closes_the_batch(self, task):
        """Отвечены все — решения записаны разом, пачка снята, вопросов больше нет."""
        from src.project.task.task_question import (task_question_batch, task_question_batch_answer,
                                                    task_question_decisions)

        for index, answers, note in ((0, ['1'], ''), (1, ['2'], ''), (2, [], 'своими словами')):
            result = await task_question_batch_answer(task, await _row(task), index, answers, note)

        assert result['done'] is True
        assert len(result['decisions']) == 3
        assert task_question_batch(await _row(task)) == [], 'пачка должна сняться'

        kept = [d['answer'] for d in task_question_decisions(await _row(task))]
        assert kept == ['А', 'Г', 'своими словами']

    async def test_draft_keeps_what_was_picked(self, task):
        """
        Черновик помнит ключи вариантов и заметку — по ним попап возвращает выбор в
        форму. Без них он показал бы «ответ есть», но чем именно — неизвестно.
        """
        from src.project.task.task_question import task_question_batch_answer

        await task_question_batch_answer(task, await _row(task), 0, ['2'], 'заметка')
        answer = (await _batch(task))[0]['answer']

        assert answer['keys'] == ['2']
        assert answer['note'] == 'заметка'
        assert answer['text'] == 'Б; заметка'


class TestGuards:
    """Чего механизм не делает."""

    async def test_empty_answer_refused(self, task):
        """Пустой ответ не ответ: вопрос остался бы отмеченным без содержимого."""
        from src.project.task.task_question import task_question_batch_answer

        assert await task_question_batch_answer(task, await _row(task), 0, [], '') == {}

    async def test_unknown_index_refused(self, task):
        """
        Номера вне пачки быть не может: попап шлёт его сам. Но ручка публичная, и
        запись за пределы списка молча испортила бы чужой вопрос.
        """
        from src.project.task.task_question import task_question_batch_answer

        assert await task_question_batch_answer(task, await _row(task), 9, ['1'], '') == {}
        assert await task_question_batch_answer(task, await _row(task), -1, ['1'], '') == {}

    async def test_single_question_path_untouched(self, task):
        """
        Одиночный вопрос роли живёт своим ключом и своим путём: ответ на него гасит
        вопрос, а пачку не трогает. Иначе вопрос разработчика стирал бы развилки
        менеджера.
        """
        from src.project.task.task_question import (task_question_answer, task_question_batch,
                                                    task_question_get, task_question_set)

        await task_question_set(task, {'text': 'Вопрос роли', 'options': []}, role='developer')
        row = await _row(task)
        await task_question_answer(task, row, [], 'решение', by='tester')

        assert task_question_get(await _row(task)) == {}
        assert len(task_question_batch(await _row(task))) == 3, 'пачка должна уцелеть'

    async def test_batch_limit(self, task):
        """
        Пачка длиннее предела означает, что агент не разведал, а переложил работу на
        человека. Берём столько, сколько он вправе спросить.
        """
        from src.project.task.task_question import (TASK_QUESTION_QUEUE_MAX, task_question_batch,
                                                    task_question_set_many)

        many = [{'text': f'Вопрос {n}'} for n in range(TASK_QUESTION_QUEUE_MAX + 4)]
        taken = await task_question_set_many(task, many, role='manager')

        assert taken == TASK_QUESTION_QUEUE_MAX
        assert len(task_question_batch(await _row(task))) == TASK_QUESTION_QUEUE_MAX

    async def test_empty_questions_dropped(self, task):
        """
        Вопрос без текста не вопрос: пустой попап хуже отсутствующего.

        А вот голая строка — вопрос: разбор терпим к форме намеренно, потому что агент
        присылает то объект с вариантами, то просто фразу, и терять из-за этого
        развилку нельзя (`task_question_parse`).
        """
        from src.project.task.task_question import task_question_set_many

        assert await task_question_set_many(task, [{'text': ''}, {}]) == 0
        assert await task_question_set_many(task, [{'text': ''}, 'просто спросил']) == 1


class TestBothKinds:
    """Пачка разведки и одиночный вопрос роли на одной строке."""

    async def test_manager_can_leave_both(self, task):
        """
        Менеджер кладёт и то, и другое: развилки разведки пачкой и вопрос из плана
        отдельным ключом. Ключи разные, и один другого не затирает.
        """
        from src.project.task.task_question import (task_question_batch, task_question_get,
                                                    task_question_set)

        await task_question_set(task, {'text': 'Вопрос из плана', 'options': ['А', 'Б']},
                                role='manager')

        assert task_question_get(await _row(task))['text'] == 'Вопрос из плана'
        assert len(task_question_batch(await _row(task))) == 3, 'пачка должна уцелеть'

    async def test_answering_one_leaves_the_other(self, task):
        """
        Ответ на вопрос плана снимает его и не трогает пачку: у них разные механики —
        одиночный отвечается разом, пачка копится черновиками до последнего ответа.
        """
        from src.project.task.task_question import (task_question_answer, task_question_batch,
                                                    task_question_get, task_question_set)

        await task_question_set(task, {'text': 'Вопрос из плана', 'options': ['А', 'Б']},
                                role='manager')
        row = await _row(task)
        await task_question_answer(task, row, ['1'], '', by='tester')

        assert task_question_get(await _row(task)) == {}
        assert len(task_question_batch(await _row(task))) == 3

    async def test_options_are_normalized_on_write(self, task):
        """
        Варианты приводятся к `{key, label}` при записи, а не при чтении.

        Раньше клали как дали, и список строк доживал до ответа человека: там
        `_answer_labels` зовёт у варианта `.get()` и падал с «'str' object has no
        attribute 'get'». Ошибка вылезала не при записи, а при ответе, и по тексту к
        причине не сводилась.
        """
        from src.project.task.task_question import task_question_get, task_question_set

        await task_question_set(task, {'text': 'Вопрос', 'options': ['А', 'Б']}, role='manager')
        options = task_question_get(await _row(task))['options']

        assert all(isinstance(o, dict) and o.get('key') and o.get('label') for o in options)

    async def test_extra_marks_survive_normalization(self, task):
        """
        Пометки вне общей формы переносятся: по `dialog` и `back_state` конвейер
        решает, куда вернуть строку после ответа. Потеряв их, он оставил бы задачу
        лежать там, откуда её сняли.
        """
        from src.project.task.task_question import task_question_get, task_question_set

        await task_question_set(task, {'text': 'Оболочка встала', 'options': [],
                                       'dialog': True, 'back_state': 'reviewing'},
                                role='manager')
        stored = task_question_get(await _row(task))

        assert stored['dialog'] is True
        assert stored['back_state'] == 'reviewing'


async def _row(task_id: int) -> dict:
    """Строка задачи целиком — механизм читает мешок из уже прочитанной строки."""
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, metadata FROM project_task WHERE id = %s', (task_id,))

        return await db.fetchone() or {}


async def _batch(task_id: int) -> list:
    from src.project.task.task_question import task_question_batch

    return task_question_batch(await _row(task_id))


async def _drop() -> None:
    from mysql_.mysql_ import mysql_get_db_async

    async with mysql_get_db_async() as db:
        await db.execute('DELETE FROM project_task WHERE title = %s', (TEST_TITLE,))
        await db.connection.commit()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])


class TestAutoQuestionFacts:
    """
    Автовопрос конвейера: по каким прогонам он делает вывод о причине.

    Вопрос собирается из статистики попыток, и статистику легко отравить. Живьём:
    подзадача #5219 набрала шесть срывов по 7–26 секунд, когда миграция сломала JSON
    промпта и движок слал агенту пустоту. Автовопрос увидел «8 прогонов, 6 оборвалось»
    и объявил неподъёмным охват — предложил дробить работу, к которой поломка не имела
    отношения. Ответь человек «раздробить» — подзадачу разрезали бы впустую.
    """

    def test_instant_runs_are_not_attempts(self):
        """
        Прогон короче минуты — поломка установки, а не работа агента: настоящий круг
        идёт минутами. В вывод о причине такие не входят.
        """
        from src.project.task.task_question import _attempts_facts

        facts = _attempts_facts([
            {'error': 'прогон не состоялся — Разработчик не ответил', 'duration_ms': 7000},
            {'error': 'прогон не состоялся — Разработчик не ответил', 'duration_ms': 26000},
        ])

        assert facts['broken'] == 0, 'мгновенные срывы не считаются оборванными кругами'
        assert facts['instant'] == 2
        assert facts['runs'] == 2, 'из счёта прогонов они не исчезают — человек вправе знать'

    def test_long_timeouts_still_count(self):
        """Настоящий таймаут — это круг, который шёл и не дошёл. Он остаётся уликой."""
        from src.project.task.task_question import _attempts_facts

        facts = _attempts_facts([
            {'error': 'прогон не состоялся — Разработчик не ответил', 'duration_ms': 900000},
            {'error': 'timeout', 'duration_ms': 600000},
        ])

        assert facts['broken'] == 2
        assert facts['instant'] == 0

    def test_verdict_is_not_scope_after_instant_failures(self):
        """
        Главное. Шесть мгновенных срывов не должны давать вывод «объём не влезает»:
        охват тут ни при чём, и предлагать дробление — вредный совет.
        """
        from src.project.task.task_question import task_question_auto

        runs = [{'error': 'прогон не состоялся — Разработчик не ответил', 'duration_ms': 8000}
                for _ in range(6)]
        runs.append({'error': 'Цели не подтверждены', 'duration_ms': 700000})

        text = task_question_auto({'pipeline_state': 'failed_qa', 'pipeline_attempt_count': 1,
                                   'goals': '[]'}, runs, 3)['text']

        assert 'объём не влезает' not in text
        assert 'оборвались за секунды' in text, 'о срывах человеку сказать надо'

    def test_missing_duration_counts_as_real(self):
        """
        Без длительности прогон считаем настоящим: молча выкидывать из статистики то,
        о чём ничего не известно, — худший вид догадки.
        """
        from src.project.task.task_question import _attempts_facts

        facts = _attempts_facts([{'error': 'прогон не состоялся', 'duration_ms': None}])

        assert facts['broken'] == 1
        assert facts['instant'] == 0

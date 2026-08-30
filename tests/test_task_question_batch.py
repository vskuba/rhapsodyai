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

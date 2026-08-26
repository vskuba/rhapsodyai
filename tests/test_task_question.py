"""
Вопрос роли и решение человека — `src/project/task/task_question.py`.

Проверяется разбор: вопрос пишет живой Claude Code, и форма у него гуляет —
то строка, то объект, то массив строк вместо массива объектов. Терпимость к этому
и есть главное свойство модуля: не разобранный вопрос означает, что подзадача
молча сгорит по кругам вместо того, чтобы дождаться человека.

Чтение и запись в БД сюда не входят — они проверяются круговым прогоном через API.

Модуль импортируется внутри тестов: он тянет `mysql_`, который читает `MYSQL_HOST`
на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""
import json


class TestQuestionParse:
    """Разбор вопроса из отчёта роли."""

    def test_task_question_parse_object_with_options(self):
        from src.project.task.task_question import task_question_parse

        q = task_question_parse({'question': {
            'text': 'Переименовывать ли инструменты?',
            'options': [{'key': 'yes', 'label': 'Да', 'hint': 'с реестром'}, 'Нет'],
        }})

        assert q['text'] == 'Переименовывать ли инструменты?'
        assert [o['key'] for o in q['options']] == ['yes', '2']
        assert q['options'][0]['hint'] == 'с реестром'
        assert q['multi'] is False
        assert q['asked_at']

    def test_task_question_parse_string_becomes_question(self):
        """Агент поленился завести объект — вопрос всё равно не теряем."""
        from src.project.task.task_question import task_question_parse

        q = task_question_parse({'question': 'Что делать с реестром?'})

        assert q['text'] == 'Что делать с реестром?'
        assert q['options'] == []

    def test_task_question_parse_options_as_dict(self):
        from src.project.task.task_question import task_question_parse

        q = task_question_parse({'question': {'text': 'Как?', 'options': {'a': 'Так', 'b': 'Иначе'}}})

        assert [(o['key'], o['label']) for o in q['options']] == [('a', 'Так'), ('b', 'Иначе')]

    def test_task_question_parse_empty_is_not_question(self):
        """Пустой вопрос увёл бы подзадачу в blocked с пустым попапом."""
        from src.project.task.task_question import task_question_parse

        assert task_question_parse({}) == {}
        assert task_question_parse(None) == {}
        assert task_question_parse({'question': ''}) == {}
        assert task_question_parse({'question': {'options': ['Да']}}) == {}
        assert task_question_parse({'question': ['не тот тип']}) == {}

    def test_task_question_parse_options_capped(self):
        from src.project.task.task_question import TASK_QUESTION_OPTIONS_MAX, task_question_parse

        q = task_question_parse({'question': {'text': 'Что?', 'options': [f'в{n}' for n in range(20)]}})

        assert len(q['options']) == TASK_QUESTION_OPTIONS_MAX

    def test_task_question_parse_long_text_cut(self):
        from src.project.task.task_question import TASK_QUESTION_TEXT_MAX, task_question_parse

        q = task_question_parse({'question': {'text': 'я' * 5000}})

        assert len(q['text']) == TASK_QUESTION_TEXT_MAX

    def test_task_question_parse_option_without_label_skipped(self):
        from src.project.task.task_question import task_question_parse

        q = task_question_parse({'question': {'text': 'Что?', 'options': ['', {'key': 'x'}, 'Годный']}})

        assert [o['label'] for o in q['options']] == ['Годный']


class TestQuestionRead:
    """Чтение вопроса и решений из строки подзадачи."""

    def test_task_question_read_from_metadata(self):
        from src.project.task.task_question import task_question_get

        row = {'metadata': {'question': {'text': 'Как быть?'}}}

        assert task_question_get(row)['text'] == 'Как быть?'

    def test_task_question_metadata_as_mysql_string(self):
        """JSON-колонка приходит строкой, если строку не пропустили через row_apply."""
        from src.project.task.task_question import task_question_get

        row = {'metadata': json.dumps({'question': {'text': 'Как быть?'}}, ensure_ascii=False)}

        assert task_question_get(row)['text'] == 'Как быть?'

    def test_task_question_read_no_question(self):
        from src.project.task.task_question import task_question_get

        assert task_question_get({}) == {}
        assert task_question_get({'metadata': None}) == {}
        assert task_question_get({'metadata': {'question': {'text': ''}}}) == {}
        assert task_question_get({'metadata': {'question': 'мусор'}}) == {}

    def test_task_question_read_decisions_as_list(self):
        from src.project.task.task_question import task_question_decisions

        row = {'metadata': {'decisions': [{'answer': 'раз'}, 'мусор', {'answer': 'два'}]}}

        assert [d['answer'] for d in task_question_decisions(row)] == ['раз', 'два']

    def test_task_question_read_no_decisions(self):
        from src.project.task.task_question import task_question_decisions

        assert task_question_decisions({}) == []
        assert task_question_decisions({'metadata': {'decisions': 'не список'}}) == []


class TestDecisionsText:
    """Решения для промпта роли."""

    def test_task_question_decisions_text_pairs_question_and_answer(self):
        from src.project.task.task_question import task_question_decisions_text

        row = {'metadata': {'decisions': [{'question': 'Переименовывать?', 'answer': 'Нет'}]}}

        assert task_question_decisions_text(row) == '- Вопрос: Переименовывать?\n  Решение: Нет'

    def test_task_question_decisions_text_answer_without_question(self):
        from src.project.task.task_question import task_question_decisions_text

        row = {'metadata': {'decisions': [{'question': '', 'answer': 'Реестр не трогать'}]}}

        assert task_question_decisions_text(row) == '- Реестр не трогать'

    def test_task_question_decisions_text_empty_is_falsy(self):
        """Пустая строка — то, что `%if subtask_decisions%` не раскроет."""
        from src.project.task.task_question import task_question_decisions_text

        assert task_question_decisions_text({}) == ''
        assert task_question_decisions_text({'metadata': {'decisions': [{'answer': ''}]}}) == ''


class TestAutoQuestion:
    """
    Вопрос конвейера — когда роль не спросила, а подзадача всё равно встала.

    Второго вида сущности тут нет: человеку всё равно, кто сформулировал развилку,
    он открывает строку, которая не движется. Поэтому форма ответа та же.
    """

    def test_task_question_auto_skips_running_subtask(self):
        from src.project.task.task_question import task_question_auto

        assert task_question_auto({'pipeline_state': 'developing'}, []) == {}
        assert task_question_auto({'pipeline_state': 'done'}, []) == {}
        assert task_question_auto({}, []) == {}

    def test_task_question_auto_asks_stuck_subtask_with_options(self):
        """С несколькими целями дробление осмысленно — его и предлагаем первым."""
        from src.project.task.task_question import (TASK_QUESTION_ACTION_DROP,
                                                    TASK_QUESTION_ACTION_RETRY,
                                                    TASK_QUESTION_ACTION_SPLIT, task_question_auto)

        subtask = {'pipeline_state': 'blocked', 'pipeline_attempt_count': 3,
                   'goals': '[{"text": "разрезать файлы", "done": false}, '
                            ' {"text": "перенести приватные вниз", "done": false}]'}

        q = task_question_auto(subtask, [], max_attempts=3)

        assert q['auto'] is True
        assert 'кругов потрачено 3 из 3' in q['text']
        assert [o['key'] for o in q['options']] == [TASK_QUESTION_ACTION_SPLIT,
                                                    TASK_QUESTION_ACTION_DROP,
                                                    TASK_QUESTION_ACTION_RETRY]

    def test_task_question_auto_single_goal_offers_planning(self):
        """
        Раздробить единственную цель нечем, а убрать её — отменить подзадачу.

        Развилка тут ложная, и настоящая причина в другом: раз строка встала, охват
        ей задали неподъёмный — ошиблось планирование, а не исполнение. Поэтому
        вместо двух пустых кнопок предлагаем вернуть строку менеджеру, чтобы он
        разложил её на подзадачи следующего уровня (`task_goal_replan`).
        """
        from src.project.task.task_question import (TASK_QUESTION_ACTION_DROP,
                                                    TASK_QUESTION_ACTION_PLAN,
                                                    TASK_QUESTION_ACTION_RETRY,
                                                    TASK_QUESTION_ACTION_SPLIT, task_question_auto)

        subtask = {'pipeline_state': 'blocked', 'pipeline_attempt_count': 3,
                   'goals': '[{"text": "разрезать файлы", "done": false}]'}

        keys = [o['key'] for o in task_question_auto(subtask, [], max_attempts=3)['options']]

        assert keys == [TASK_QUESTION_ACTION_PLAN, TASK_QUESTION_ACTION_RETRY]
        assert TASK_QUESTION_ACTION_SPLIT not in keys
        assert TASK_QUESTION_ACTION_DROP not in keys

    def test_task_question_auto_done_goals_not_counted_as_scope(self):
        """Одна незакрытая при закрытых соседях — тот же случай: дробить нечего."""
        from src.project.task.task_question import TASK_QUESTION_ACTION_PLAN, task_question_auto

        subtask = {'pipeline_state': 'failed_qa', 'pipeline_attempt_count': 2,
                   'goals': '[{"text": "сделана", "done": true}, '
                            ' {"text": "осталась одна", "done": false}]'}

        keys = [o['key'] for o in task_question_auto(subtask, [], max_attempts=3)['options']]

        assert keys[0] == TASK_QUESTION_ACTION_PLAN

    def test_task_question_auto_without_goals_only_restart(self):
        """Варианты про цели были бы кнопками в пустоту."""
        from src.project.task.task_question import TASK_QUESTION_ACTION_RETRY, task_question_auto

        q = task_question_auto({'pipeline_state': 'blocked', 'goals': '[]'}, [])

        assert [o['key'] for o in q['options']] == [TASK_QUESTION_ACTION_RETRY]

    def test_task_question_auto_done_goals_not_counted(self):
        from src.project.task.task_question import TASK_QUESTION_ACTION_RETRY, task_question_auto

        subtask = {'pipeline_state': 'blocked', 'goals': '[{"text": "сделано", "done": true}]'}

        assert [o['key'] for o in task_question_auto(subtask, [])['options']] == [TASK_QUESTION_ACTION_RETRY]

    def test_task_question_auto_timeouts_hint_at_volume(self):
        """Два оборванных прогона — уже свойство подзадачи, а не случайность."""
        from src.project.task.task_question import task_question_auto

        attempts = [{'error': 'Developer: прогон не состоялся — Разработчик не ответил'},
                    {'error': 'Агент developer не ответил за 2800с'},
                    {'error': 'Подзадача не выполнена: файлы не разрезаны', 'duration_ms': 1_800_000}]

        q = task_question_auto({'pipeline_state': 'blocked', 'goals': '[{"text": "цель"}]'}, attempts)

        assert 'оборвалось по таймауту 2' in q['text']
        assert 'объём не влезает в круг' in q['text']
        assert 'файлы не разрезаны' in q['text']

    def test_task_question_auto_without_timeouts_other_hint(self):
        from src.project.task.task_question import task_question_auto

        attempts = [{'error': 'проверки не прошли'}, {'error': 'проверки не прошли снова'}]

        q = task_question_auto({'pipeline_state': 'failed_qa', 'goals': '[{"text": "цель"}]'}, attempts)

        assert 'дело не во времени' in q['text']


class TestGoalsPartition:
    """Разделение целей на отмеченные и оставшиеся."""

    def test_task_question_goals_partition_keeps_order(self):
        from src.project.task.task_goal_scope import _goals_partition

        goals = [{'text': 'раз'}, {'text': 'два'}, {'text': 'три'}]
        picked, kept = _goals_partition(goals, [2, 0])

        assert [g['text'] for g in picked] == ['раз', 'три']
        assert [g['text'] for g in kept] == ['два']

    def test_task_question_goals_partition_skips_out_of_range(self):
        """Пока попап был открыт, цели мог поменять сам агент."""
        from src.project.task.task_goal_scope import _goals_partition

        picked, kept = _goals_partition([{'text': 'раз'}], [7])

        assert picked == []
        assert [g['text'] for g in kept] == ['раз']

    def test_task_question_goals_partition_garbage_numbers(self):
        from src.project.task.task_goal_scope import _goals_partition

        picked, kept = _goals_partition([{'text': 'раз'}], ['0', None, 'ой'])

        assert [g['text'] for g in picked] == ['раз']
        assert kept == []


class TestAnswerLabels:
    """Ключи выбранных вариантов превращаются в подписи."""

    def test_task_question_answer_labels_instead_of_keys(self):
        from src.project.task.task_question import _answer_labels

        question = {'options': [{'key': 'a', 'label': 'Так'}, {'key': 'b', 'label': 'Иначе'}]}

        assert _answer_labels(question, ['b', 'a']) == ['Иначе', 'Так']

    def test_task_question_answer_unknown_key_skipped(self):
        """Вопрос мог смениться, пока попап был открыт."""
        from src.project.task.task_question import _answer_labels

        assert _answer_labels({'options': [{'key': 'a', 'label': 'Так'}]}, ['z']) == []

    def test_task_question_answer_labels_empty(self):
        from src.project.task.task_question import _answer_labels

        assert _answer_labels({'options': []}, None) == []

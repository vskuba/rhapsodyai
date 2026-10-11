"""Сверка двух файлов ноды (`scripts/workflow_export_diff.py`).

## ⚠⚠ Что здесь стережётся и какой ценой узнано

Сверка отвечает на один вопрос — «изменились только мои правки или уехало
чужое», — и цена её ошибки в том, что ответ **всегда выглядит убедительно**:
список расхождений короткий, в нём ровно то, что ждали, и пропущенное в него не
попадает по определению.

Поймано дважды, на живом импорте на прод:

1. **Адрес переменной — имя И ТИП.** `girl_response` законно живёт двумя
   строками: `workflow` (её считает сам поток) и `input` (её подаёт родитель).
   Сверка по одному имени сливала обе, и появление второй — ровно та правка,
   которой подпоток начинает видеть ответ агента, — не показывалось вовсе.
2. **Вопросы тем не сверялись никак.** Переформулированный вопрос темы менял
   поведение шага и в расхождениях не значился.

Оба случая здесь закреплены: это не догадки о возможных поломках, а два
промаха, увиденных на настоящем переносе.

⚠ Тесты без базы и без HTTP: сверка — чистая функция над двумя разобранными
файлами. Поднимать для неё установку незачем.

⚠⚠ Номера записей в данных тестов нарочно **разные** у двух сторон: на
установках они свои, и сверка обязана этого не замечать. Совпадут номера в
данных — тест перестанет стеречь главное свойство (адресация по именам).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.workflow_export_diff import (workflow_export_diff,
                                          workflow_export_diff_report)


def _payload(steps=(), variables=(), topics=(), questions=()):
    """Файл ноды из того малого, что сверке нужно. Остального в нём и не бывает."""
    return {
        'workflows': [{'id': 7, 'name': 'talk'}, {'id': 9, 'name': 'talk_topic'}],
        'steps': [dict(workflow_id=7, **s) for s in steps],
        'variables': list(variables),
        'topics': list(topics),
        'topic_questions': list(questions),
    }


def test_the_same_file_shows_no_difference():
    one = _payload(steps=[{'id': 1, 'title': 'Ответ', 'position': 3, 'metadata': '{}'}])
    assert all(not rows for rows in workflow_export_diff(one, one).values())
    assert 'ни одного расхождения' in workflow_export_diff_report(
        workflow_export_diff(one, one))


def test_other_numbers_alone_are_not_a_difference():
    """⚠⚠ Главное свойство: номера на установках свои, правкой они не считаются."""
    was = _payload(steps=[{'id': 1, 'title': 'Ответ', 'position': 3, 'metadata': '{}'}])
    now = _payload(steps=[{'id': 904, 'title': 'Ответ', 'position': 3, 'metadata': '{}'}])
    assert all(not rows for rows in workflow_export_diff(was, now).values())


def test_a_moved_step_is_reported_with_both_positions():
    was = _payload(steps=[{'id': 1, 'title': 'Ответ', 'position': 3, 'metadata': '{}'}])
    now = _payload(steps=[{'id': 1, 'title': 'Ответ', 'position': 8, 'metadata': '{}'}])
    assert workflow_export_diff(was, now)['steps_moved'] == ['talk / Ответ: 3 → 8']


def test_edited_step_metadata_is_reported():
    was = _payload(steps=[{'id': 1, 'title': 'Ответ', 'position': 3, 'metadata': '{"a":1}'}])
    now = _payload(steps=[{'id': 1, 'title': 'Ответ', 'position': 3, 'metadata': '{"a":2}'}])
    assert workflow_export_diff(was, now)['steps_changed'] == ['talk / Ответ']


def test_added_and_removed_steps_are_named_with_their_workflow():
    was = _payload(steps=[{'id': 1, 'title': 'Ответ', 'position': 3, 'metadata': '{}'}])
    now = _payload(steps=[{'id': 2, 'title': 'Вопрос', 'position': 3, 'metadata': '{}'}])
    got = workflow_export_diff(was, now)
    assert got['steps_appeared'] == ['talk / Вопрос']
    assert got['steps_vanished'] == ['talk / Ответ']


def test_a_variable_of_a_second_type_under_the_same_name_is_seen():
    """⚠⚠ Промах №1 живого импорта: по одному имени эта правка была невидима."""
    was = _payload(variables=[{'id': 11, 'name': 'girl_response', 'type': 'workflow'}])
    now = _payload(variables=[{'id': 11, 'name': 'girl_response', 'type': 'workflow'},
                              {'id': 90, 'name': 'girl_response', 'type': 'input'}])
    got = workflow_export_diff(was, now)
    assert got['variables_appeared'] == ['girl_response / input']
    assert got['variables_vanished'] == []


def test_a_rewritten_topic_question_is_seen():
    """⚠⚠ Промах №2 живого импорта: вопросы тем не сверялись вовсе."""
    topics = [{'id': 5, 'name': 'photo_send', 'tags': 'photo', 'tags_qty_accept': 2,
               'instructions': 'x', 'title': 't', 'questions_qty_yes_accept': 1,
               'is_enabled': 1}]
    was = _payload(topics=topics,
                   questions=[{'id': 1, 'topic_id': 5, 'question': 'Is she promised?'}])
    now = _payload(topics=topics,
                   questions=[{'id': 1, 'topic_id': 5, 'question': 'Has she agreed?'}])
    got = workflow_export_diff(was, now)
    assert got['topic_questions_appeared'] == ['photo_send / Has she agreed?']
    assert got['topic_questions_vanished'] == ['photo_send / Is she promised?']


@pytest.mark.parametrize('field, value', [
    ('tags', 'photo, pic'),
    ('tags_qty_accept', 5),
    ('instructions', 'she_promised_something_else'),
    ('is_enabled', 0),
])
def test_an_edited_topic_is_reported(field, value):
    base = {'id': 5, 'name': 'photo_send', 'tags': 'photo', 'tags_qty_accept': 2,
            'instructions': 'x', 'title': 't', 'questions_qty_yes_accept': 1,
            'is_enabled': 1}
    was = _payload(topics=[dict(base)])
    now = _payload(topics=[dict(base, **{field: value})])
    assert workflow_export_diff(was, now)['topics_changed'] == ['photo_send']


def test_a_file_without_topic_sections_does_not_read_as_wiped_topics():
    """⚠ Старый файл — не «темы снесли»: импорт считает секции необязательными."""
    old = {'workflows': [], 'steps': [], 'variables': []}
    got = workflow_export_diff(old, old)
    assert got['topics_vanished'] == []
    assert got['topic_groups_vanished'] == []
    assert got['topic_questions_vanished'] == []

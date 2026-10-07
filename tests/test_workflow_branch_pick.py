"""
Выбор темы по меткам: счёт, порог ветки, ничья.

⚠ Без HTTP и без базы: правило выбора — чистая функция, и проверяется вызовом.
Живого LLM здесь нет тем более — метки подаются готовой строкой, как если бы
шаг-развилка уже отработал.

⚠⚠ Главный тест здесь — `test_more_matches_wins`. Он сторожит то свойство, ради
которого счёт считается по всему реестру, а не по темам одной ветки: цепочка
шагов иначе берёт первую прошедшую порог, а не лучшую, и промахивается ровно
там, ради чего заведены двухсловные метки.
"""

import pytest

from src.ai.ai_workflow_branch import ai_workflow_branch_pick, ai_workflow_branch_tags_split

# ⚠ Группа `ai`, как у соседей по слою: правило относится к движку workflow.
# Без маркера файл не попал бы ни в один прогон по группе — это стережёт
# `test_marks.py`, и он же меня поймал.
pytestmark = pytest.mark.ai


def _topic(name, tags, branch_id=1, match_min=1):
    return {'name': name, 'tags': tags, 'branch_id': branch_id, 'match_min': match_min}


class TestTagsSplit:
    def test_splits_on_comma_and_normalises(self):
        assert ai_workflow_branch_tags_split(" Обмен  Письмами , пришли письмо ") == \
               ['обмен письмами', 'пришли письмо']

    def test_drops_repeats_and_empties(self):
        assert ai_workflow_branch_tags_split("письмо,, письмо ,") == ['письмо']

    def test_empty_gives_empty_list(self):
        assert ai_workflow_branch_tags_split('') == []

    def test_none_gives_empty_list(self):
        assert ai_workflow_branch_tags_split(None) == []


class TestPick:
    def test_more_matches_wins(self):
        """Тема соседней ветки с большим счётом обязана победить тему, стоящую
        в цепочке выше: «почта как служба» (2) против «обмена письмами» (4)."""
        topics = [
            _topic('post_service', 'почта служба, письмо от родных', branch_id=2),
            _topic('photo_mail', 'обмен письмами, пришли письмо, интимное письмо', branch_id=1),
        ]
        picked = ai_workflow_branch_pick(topics, 'обмен письмами, пришли письмо, письмо от родных')
        assert picked['name'] == 'photo_mail'

    def test_below_own_branch_threshold_drops_out(self):
        topics = [_topic('photo_mail', 'обмен письмами, пришли письмо', match_min=2)]
        assert ai_workflow_branch_pick(topics, 'обмен письмами') is None

    def test_strict_branch_does_not_block_a_lenient_one(self):
        """Порог живёт в ветке, поэтому строгая ветка выбывает сама, а не уносит
        с собой годную тему соседней."""
        topics = [
            _topic('money', 'перевод денег, оплата письма', branch_id=2, match_min=3),
            _topic('photo_mail', 'обмен письмами, пришли письмо', branch_id=1, match_min=1),
        ]
        picked = ai_workflow_branch_pick(topics, 'перевод денег, обмен письмами')
        assert picked['name'] == 'photo_mail'

    def test_equal_score_decided_by_share(self):
        topics = [
            _topic('wide', 'а б, в г, д е, ж з'),
            _topic('narrow', 'а б, в г'),
        ]
        picked = ai_workflow_branch_pick(topics, 'а б, в г')
        assert picked['name'] == 'narrow'

    def test_equal_score_and_share_gives_nothing(self):
        topics = [_topic('one', 'а б, в г'), _topic('two', 'а б, в г')]
        assert ai_workflow_branch_pick(topics, 'а б, в г') is None

    def test_a_better_topic_clears_an_earlier_tie(self):
        """Ничья, перебитая лучшей темой, не должна глушить выбор."""
        topics = [
            _topic('one', 'а б, в г'),
            _topic('two', 'а б, в г'),
            _topic('best', 'а б, в г, д е'),
        ]
        picked = ai_workflow_branch_pick(topics, 'а б, в г, д е')
        assert picked['name'] == 'best'

    def test_unknown_tag_matches_nothing(self):
        topics = [_topic('photo_mail', 'обмен письмами')]
        assert ai_workflow_branch_pick(topics, 'погода завтра') is None

    def test_no_tags_gives_nothing(self):
        topics = [_topic('photo_mail', 'обмен письмами')]
        assert ai_workflow_branch_pick(topics, '') is None

    def test_topic_without_tags_is_skipped(self):
        topics = [_topic('empty', ''), _topic('photo_mail', 'обмен письмами')]
        picked = ai_workflow_branch_pick(topics, 'обмен письмами')
        assert picked['name'] == 'photo_mail'

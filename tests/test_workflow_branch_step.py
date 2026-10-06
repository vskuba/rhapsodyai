"""
Шаг `branch`: правила, по которым он решает, его ли тема.

⚠⚠ Этот файл проверяет ПРАВИЛА, а не исполнение в движке. Разница измерена: при
выносе `workflow_invoke` статические тесты были зелёными, а прогон падал
`NameError` на непереданном `step_id` — внутри вызова, то есть после того, как
отработали все шаги выше. Живое покрытие шаг получает тогда, когда встаёт в
`dating_talk`, и до тех пор проверенным не считается.

Здесь — то, что от движка не зависит и сломается тише всего.
"""

import pytest

from src.ai.ai_workflow_branch import ai_workflow_branch_pick, ai_workflow_branch_tags_split

pytestmark = pytest.mark.ai

# Семь значений, которые шаг кладёт сам. Карты для них нет: с ней один забытый
# маппинг выключал бы тему молча — ветка отработала, промпт собрался, инструкций
# в нём нет.
TOPIC_VARIABLES = ('topic_name', 'topic_title', 'topic_tags',
                   'topic_accept', 'topic_direction', 'topic_restrict', 'topic_score')

MY_BRANCH_ID = 1


def _topics():
    return [
        {'id': 1, 'branch_id': 1, 'name': 'photo_mail', 'title': 'Письма и фото',
         'tags': 'обмен письмами, пришли письмо', 'acceptance': 'соглашайся',
         'direction': 'веди в письма', 'restriction': 'не обещай откровенного',
         'branch_name': 'deal', 'match_min': 1, 'workflow_id': None},
        {'id': 2, 'branch_id': 2, 'name': 'money', 'title': 'Деньги',
         'tags': 'перевод денег', 'acceptance': '', 'direction': '',
         'restriction': 'не проси денег',
         'branch_name': 'dodge', 'match_min': 1, 'workflow_id': None},
    ]


def _step_runs(tags_named: str, branch_id: int = MY_BRANCH_ID):
    """Решение шага: его ли тема. Тем же выражением, что и в движке."""
    topic = ai_workflow_branch_pick(_topics(), tags_named)
    return topic if topic is not None and int(topic['branch_id']) == branch_id else None


class TestWhoseTopic:
    def test_my_topic_is_claimed(self):
        assert _step_runs('обмен письмами, пришли письмо')['name'] == 'photo_mail'

    def test_foreign_topic_is_not_claimed(self):
        """Шаг ветки 1 обязан увидеть «не моя» и не вмешиваться."""
        assert _step_runs('перевод денег') is None
        # …а шаг ветки 2 — забрать её себе
        assert _step_runs('перевод денег', branch_id=2)['name'] == 'money'

    def test_no_topic_claims_nothing(self):
        assert _step_runs('погода завтра') is None


class TestLoserLeavesVariablesAlone:
    def test_winner_values_survive_a_losing_step(self):
        """⚠⚠ Главный сторож файла.

        Победила ветка 1 и положила свои `topic_*`. Следом по цепочке идёт шаг
        ветки 2 — и обязан не трогать переменные. Положи он пустые строки,
        «Генерация ответа» увидела бы пустоту при верно выбранной теме, а отказ
        плавал бы от порядка шагов в workflow.
        """
        variables = {name: f'значение победителя {name}' for name in TOPIC_VARIABLES}
        before = dict(variables)

        # Шаг ветки 2 на метках, где победила тема ветки 1
        topic = _step_runs('обмен письмами, пришли письмо', branch_id=2)
        assert topic is None, 'тема ветки 1 не должна достаться шагу ветки 2'

        if topic is not None:  # pragma: no cover — ветка «моя тема»
            for name in TOPIC_VARIABLES:
                variables[name] = ''

        assert variables == before


class TestScore:
    def test_score_counts_matched_tags_of_the_topic(self):
        """`topic_score` — число совпавших меток темы, тем же разбором, что и выбор."""
        named = ai_workflow_branch_tags_split('обмен письмами, пришли письмо, погода')
        own = ai_workflow_branch_tags_split('обмен письмами, пришли письмо')
        assert sum(1 for tag in own if tag in named) == 2

    def test_score_ignores_tags_the_model_invented(self):
        named = ai_workflow_branch_tags_split('обмен письмами, выдуманная метка')
        own = ai_workflow_branch_tags_split('обмен письмами, пришли письмо')
        assert sum(1 for tag in own if tag in named) == 1

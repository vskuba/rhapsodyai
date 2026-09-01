"""
Колонка «llm» на карточке роли: чем оболочка работает **сейчас**.

Вопрос у колонки один, и ответов на него два разных источника. Имя модели знает
живой захват пула (`team_llm_lock`) — он гаснет вместе с кругом. Режим запуска знает
сама оболочка: без `--litellm` она пишет в реестр `anthropic` и шлёт это каждым
пингом.

Главное, что здесь проверяется: **эти два источника не подменяют друг друга**. Имя
модели из реестра — память о прошлом круге, и показывать его нельзя: модель уже
отдана соседней роли, а карточка держала бы её за собой. А `anthropic` — не память, а
свойство самой оболочки, и терять его нельзя: такая роль работает за облачные токены
мимо пула, и на странице это отдельная подсветка.

Функция чистая, база не нужна — оттого и файл отдельный: соседние тесты команды
живут на живой БД и тянут за собой фикстуры пула.
"""

import pytest

pytestmark = pytest.mark.team

# Оболочка, захватившая модель на круг: её `session_uuid` есть в `llm_by_session`.
CARD_BUSY = {'session_uuid': 'shell-busy-0001', 'server_llm': 'gx10/qwen-large'}

# Оболочка без `--litellm`: реестр говорит `anthropic`, захвата нет и не будет.
CARD_CLOUD = {'session_uuid': 'shell-cloud-0002', 'server_llm': 'anthropic'}

# Оболочка под пулом между кругами: `litellm` — это «жду выдачи», а не имя модели.
CARD_PENDING = {'session_uuid': 'shell-pend-0003', 'server_llm': 'litellm'}

# Оболочка, помнящая модель прошлого круга: захват уже погас.
CARD_STALE = {'session_uuid': 'shell-stale-0004', 'server_llm': 'gx10/qwen-large'}

LOCKS = {'shell-busy-0001': 'gx10/qwen-large'}


class TestWithPool:
    """Проект с пулом: имя модели — только из живого захвата."""

    def test_captured_model_is_shown(self):
        from src.project.team.team_project import _card_llm

        assert _card_llm(CARD_BUSY, LOCKS, has_pool=True) == 'gx10/qwen-large'

    def test_remembered_model_is_not_shown(self):
        """
        Захват погас — модель ушла соседу, и держать её за этой карточкой нельзя:
        иначе одна модель «работает» сразу в двух местах.
        """
        from src.project.team.team_project import _card_llm

        assert _card_llm(CARD_STALE, LOCKS, has_pool=True) == ''

    def test_pool_mode_reads_as_no_model(self):
        """`litellm` — не модель, а ожидание выдачи: карточка скажет «не выбрана»."""
        from src.project.team.team_project import _card_llm

        assert _card_llm(CARD_PENDING, LOCKS, has_pool=True) == ''

    def test_cloud_shell_stays_visible(self):
        """
        Оболочка без `--litellm` работает облачным Claude Code — и это видно.

        Пока правило было общим на все значения реестра, она показывала «не выбрана»
        с подсказкой «роль между кругами»: выглядела ждущей модель из пула, хотя ждать
        ей нечего, а счёт идёт за облачные токены. Подсветка `cloud` на странице
        проверяет ровно это значение и без него была мертва.
        """
        from src.project.team.team_project import _card_llm

        assert _card_llm(CARD_CLOUD, LOCKS, has_pool=True) == 'anthropic'


class TestWithoutPool:
    """Пул пуст — захватывать нечего, и реестр единственный источник."""

    def test_registry_value_is_shown(self):
        from src.project.team.team_project import _card_llm

        assert _card_llm(CARD_STALE, {}, has_pool=False) == 'gx10/qwen-large'

    def test_cloud_mode_is_shown(self):
        from src.project.team.team_project import _card_llm

        assert _card_llm(CARD_CLOUD, {}, has_pool=False) == 'anthropic'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

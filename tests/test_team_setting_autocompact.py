"""
Порог автосжатия контекста — настройка, а не константа в коде.

Число зависит от модели, а модель меняют: у GX10 окно 131072 токена, у следующей
будет другое. И внутри одной модели порог двигают — работа после сжатия идёт по
пересказу, то есть вслепую, поэтому чем позже оно случится, тем лучше; но слишком
поздний порог упирается в потолок окна, прогон падает с
`exceed_context_size_error`, а конвейер засчитывает это как состоявшийся круг и
жжёт попытку впустую.

Главное, что здесь проверяется: значение подставляется **при показе карточки**.
Команда лежит в `project_team.command` и переживает правку настройки — подставь
её один раз при заведении проекта, и смена настройки не дошла бы до уже созданных
карточек.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает
`MYSQL_HOST` на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

CMD = 'claude-shell --gx10 --developer --autocompact 115k'


@pytest.fixture(autouse=True)
async def db_pool_release():
    """
    Закрыть пул MySQL после каждого теста.

    Пул в `mysql_` модульный и привязан к циклу событий, в котором создан, а
    pytest-asyncio даёт каждому тесту свой. Оставленный пул ломает сессионную
    уборку `conftest.py`: «Future attached to a different loop» на teardown.
    Та же дисциплина в `test_task_log.py` и соседних.
    """
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


class TestValueParsing:
    """Что считается допустимым значением настройки."""

    def test_tokens_and_auto_pass(self):
        from src.project.team.team_setting_autocompact import TEAM_SETTING_AUTOCOMPACT_RE

        for good in ('115k', '90k', 'auto', '120000', '2m'):
            assert TEAM_SETTING_AUTOCOMPACT_RE.match(good), good

    def test_garbage_rejected(self):
        """
        Мусор не должен доехать до команды.

        Claude Code на непонятном значении откажется стартовать вовсе, и роль
        просто не поднимется — молчаливый откат к умолчанию безопаснее.
        """
        from src.project.team.team_setting_autocompact import TEAM_SETTING_AUTOCOMPACT_RE

        for bad in ('много', '115 k', '-5k', '', '115k;rm -rf /'):
            assert not TEAM_SETTING_AUTOCOMPACT_RE.match(bad), bad


class TestCommandSubstitution:
    """Подстановка в готовую команду."""

    def test_replaces_existing_value(self):
        from src.project.team.team_project import _autocompact_replace

        assert _autocompact_replace(CMD, '90k').endswith('--autocompact 90k')

    def test_does_not_duplicate_the_flag(self):
        """
        Второй флаг Claude Code взял бы последним, а человек прочёл бы первый.

        В команде стояло бы два разных числа — и то, что скопируют кнопкой, не
        совпало бы с тем, что показано.
        """
        from src.project.team.team_project import _autocompact_replace

        assert _autocompact_replace(CMD, '90k').count('--autocompact') == 1

    def test_command_without_flag_untouched(self):
        """
        Команда без флага — осознанный случай, а не недосмотр.

        Так выглядит оболочка без `--gx10` (ходит в облако, там своё окно) и
        команда, которую человек правил руками, сознательно убрав автосжатие.
        """
        from src.project.team.team_project import _autocompact_replace

        plain = 'claude-shell --developer'

        assert _autocompact_replace(plain, '90k') == plain

    def test_equals_form_replaced_too(self):
        """Флаг пишут и через пробел, и через `=` — оба варианта наши."""
        from src.project.team.team_project import _autocompact_replace

        result = _autocompact_replace('claude-shell --gx10 --qa --autocompact=200k', '90k')

        assert result.count('--autocompact') == 1
        assert '90k' in result and '200k' not in result


class TestFallback:
    """Настройки нет или она испорчена — работает умолчание."""

    async def test_missing_setting_gives_default(self):
        from src.project.team.team_setting_autocompact import (TEAM_SETTING_AUTOCOMPACT_DEFAULT,
                                                               team_setting_autocompact_get)

        value = await team_setting_autocompact_get()

        assert value and (value == TEAM_SETTING_AUTOCOMPACT_DEFAULT or value.endswith(('k', 'm'))
                          or value == 'auto' or value.isdigit())

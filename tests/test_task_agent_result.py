"""
Разбор ответа агента: несостоявшийся прогон против состоявшейся неудачи.

Различие не формальное — от него зависит, сгорит ли круг QA. Работа, которая не
сошлась, круг закрывает (`task_state_subtask_fail`, потолок `timeout_attempt_max`).
Прогон, которого не было, круг закрывать не должен: `env_ok = False` уводит ответ
в `task_retry` вместе с перезапуском оболочки.

Ловится здесь ровно то, на чём конвейер горел вживую по задаче #895: llama.cpp на
GX10 отвечал объектом `exceed_context_size_error`, у которого нет ключа `ok`, —
и умолчание `parsed.get('ok', True)` записывало переполненный контекст в успешный
круг разработки. Нетронутый код уходил на проверку QA, QA его закономерно
возвращал, и попытка сгорала за прогон, до которого модель даже не дошла.

Модули агентов импортируются внутри тестов: они тянут `mysql_`, который читает
`MYSQL_HOST` на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""
import pytest

pytestmark = pytest.mark.pipeline

# Ответ провайдера как есть — llama.cpp, переполненный контекст.
PROVIDER_ERROR = {
    'code': 400,
    'message': 'request (134521 tokens) exceeds the available context size (131072 tokens), '
               'try increasing it',
    'type': 'exceed_context_size_error',
    'n_prompt_tokens': 134521,
    'n_ctx': 131072,
}

# Заглушка workflow «агент недоступен»: шаги 443 / 456 / 564. Контракт агента тут
# соблюдён, поэтому опознаётся она не по форме ответа, а по явному `env_ok`.
SHELL_DOWN = {'env_ok': False, 'ok': False, 'report': {},
              'error': 'Разработчик не ответил. Статус: timeout. Ошибка: ...'}


class TestProviderErrorDetect:
    """`task_agent_result_provider_error` — опознание чужого объекта ошибки."""

    def test_provider_error_recognised(self):
        from src.project.task.task_agent_result import task_agent_result_provider_error
        text = task_agent_result_provider_error(PROVIDER_ERROR)
        assert 'exceed_context_size_error' in text
        assert '131072' in text

    def test_agent_contract_is_not_an_error(self):
        """Отчёт агента с `ok`/`report` — работа, а не сбой, даже с ошибкой внутри."""
        from src.project.task.task_agent_result import task_agent_result_provider_error
        assert task_agent_result_provider_error(
            {'ok': False, 'report': {}, 'error': 'проверки не прошли'}) == ''
        assert task_agent_result_provider_error(
            {'ok': True, 'report': {'summary': 'сделано'}}) == ''

    def test_plain_message_is_not_an_error(self):
        """Одного `message` мало: без `code`/`type` это может быть чей угодно текст."""
        from src.project.task.task_agent_result import task_agent_result_provider_error
        assert task_agent_result_provider_error({'message': 'привет'}) == ''

    def test_empty_and_non_dict(self):
        from src.project.task.task_agent_result import task_agent_result_provider_error
        assert task_agent_result_provider_error({}) == ''
        assert task_agent_result_provider_error(None) == ''
        assert task_agent_result_provider_error([1, 2]) == ''

    def test_error_text_is_trimmed(self):
        """В сообщение провайдера попадает и промпт целиком — режем."""
        from src.project.task.task_agent_result import (
            TASK_AGENT_RESULT_ERROR_MAX, task_agent_result_provider_error)
        text = task_agent_result_provider_error({'code': 500, 'message': 'ы' * 5000})
        assert len(text) == TASK_AGENT_RESULT_ERROR_MAX


@pytest.mark.parametrize('module_name, parse_name', [
    ('src.project.task.task_agent_developer', '_result_parse'),
    ('src.project.task.task_agent_qa', '_result_parse'),
    ('src.project.task.task_agent_bugfixer', '_result_parse'),
])
class TestRoleResultParse:
    """Все три роли обязаны разбирать нерабочий прогон одинаково."""

    @staticmethod
    def _parse(module_name, parse_name, payload):
        import importlib
        import json
        module = importlib.import_module(module_name)
        return getattr(module, parse_name)('json:' + json.dumps(payload, ensure_ascii=False))

    def test_provider_error_is_not_a_round(self, module_name, parse_name):
        """
        Ошибка провайдера — не успех и не провал круга, а повтор.

        Главная регрессия: без разбора этот ответ давал `ok = True`, и подзадача
        уезжала к QA с нетронутым кодом.
        """
        result = self._parse(module_name, parse_name, PROVIDER_ERROR)
        assert result['ok'] is False, 'ошибка провайдера засчитана как выполненная работа'
        assert result['env_ok'] is False, 'ошибка провайдера закроет круг и сожжёт попытку'
        assert 'exceed_context_size_error' in result['error']

    def test_shell_down_is_not_a_round(self, module_name, parse_name):
        """Заглушка «агент недоступен» тоже не круг: оболочка не ответила."""
        result = self._parse(module_name, parse_name, SHELL_DOWN)
        assert result['ok'] is False
        assert result['env_ok'] is False

    def test_real_failure_still_burns_the_round(self, module_name, parse_name):
        """Работа была и не сошлась — круг закрывается, иначе повторы стали бы вечными."""
        result = self._parse(module_name, parse_name,
                             {'ok': False, 'report': {}, 'error': 'цели не подтверждены'})
        assert result['ok'] is False
        assert result['env_ok'] is True

    def test_success_unchanged(self, module_name, parse_name):
        result = self._parse(module_name, parse_name,
                             {'ok': True, 'report': {'summary': 'сделано'}})
        assert result['ok'] is True
        assert result['env_ok'] is True

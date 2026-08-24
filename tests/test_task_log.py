"""
Журнал работы по строке задачи — `src/project/task/task_log.py`.

Журнал ведёт код, а не агент: шаги workflow с ответами уже лежат в трассе, и
`task_log_write_run` их оттуда перекладывает. Смысл в том, чтобы следующий круг
после обрыва начинал не с нуля — поэтому проверяется в первую очередь разбор
сорвавшегося прогона: у него ответа нет, а пройденные шаги есть.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает
`MYSQL_HOST` на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""
from datetime import datetime

import pytest

# Ответ вызова оболочки как есть: служебных полей больше, чем полезных.
SHELL_OK = ("{'status': 'answered', 'response': 'Разбор подзадачи: правила 1 и 3', "
            "'payload_json': '', 'error': '', 'session_uuid': 'abc', 'elapsed': 266}")
SHELL_TIMEOUT = ("{'status': 'timeout', 'response': '', 'payload_json': '', "
                 "'error': 'Агент developer не ответил за 2800с', 'elapsed': 2844}")
STUB_REPORT = ('json:{"env_ok": false, "ok": false, "report": {}, '
               '"error": "Разработчик не ответил. Статус: timeout"}')


def _step(title, output='', status='success', ms=1000):
    return {'step_title': title, 'status': status, 'duration_ms': ms,
            'output': output, 'error': '', 'created_at': datetime(2026, 8, 24, 12, 30, 15)}


class TestStepLine:
    """Строка журнала: время, ключевое слово, шаг, время, суть ответа."""

    def test_answer_extracted_from_shell_result(self):
        """В журнал идёт ответ агента, а не словарь со служебными полями."""
        from src.project.task.task_log import _step_line

        line = _step_line(_step('Разработчик: разбор', SHELL_OK, ms=266000))

        assert 'Разбор подзадачи: правила 1 и 3' in line
        assert 'session_uuid' not in line, 'служебные поля попали в журнал'
        assert '4 мин' in line, 'не показано, сколько шаг занял'

    def test_empty_response_does_not_grab_neighbours(self):
        """
        Пустой `response` не должен утащить соседние ключи.

        На нежадном `.+?` разбор перескакивал через кавычки, и в журнал уезжало
        «', 'payload_json': '» вместо причины отказа.
        """
        from src.project.task.task_log import _step_line

        line = _step_line(_step('Разработчик: реализация', SHELL_TIMEOUT))

        assert 'не ответил за 2800с' in line
        assert 'payload_json' not in line

    def test_timeout_is_a_blocker(self):
        """
        Таймаут вызова — затык, хотя движок счёл шаг успешным.

        Инструмент отработал и вернул результат, поэтому `status` шага —
        `success`. Для работы же прогона не было, и человек ищет в журнале
        именно затык.
        """
        from src.project.task.task_log import _step_line

        assert 'затык' in _step_line(_step('Разработчик: реализация', SHELL_TIMEOUT))

    def test_stub_report_is_a_blocker(self):
        """Заглушка «роль недоступна» отдаёт готовый отчёт с ok:false — это не работа."""
        from src.project.task.task_log import _step_line

        assert 'затык' in _step_line(_step('Разработчик недоступен', STUB_REPORT))

    def test_success_is_done(self):
        from src.project.task.task_log import _step_line

        assert 'сделал' in _step_line(_step('Разработчик: разбор', SHELL_OK))

    def test_answer_trimmed(self):
        """Ответы у ролей на десятки килобайт: в строку идёт суть, не простыня."""
        from src.project.task.task_log import TASK_LOG_STEP_MAX_CHARS, _step_line

        line = _step_line(_step('Шаг', "{'response': '" + 'я' * 5000 + "'}"))

        assert len(line) < TASK_LOG_STEP_MAX_CHARS + 200


class TestStepSkip:
    """Служебные шаги в журнал не идут."""

    def test_prompt_step_skipped(self):
        """
        Сборка промпта работой не является.

        Такие шаги ничего не возвращают и давали пустую строку на каждой второй
        позиции, топя в себе настоящие события.
        """
        from src.project.task.task_log import _step_skip

        assert _step_skip(_step('Промпт: реализация', ''))

    def test_step_with_answer_kept(self):
        from src.project.task.task_log import _step_skip

        assert not _step_skip(_step('Разработчик: разбор', SHELL_OK))


class TestPaths:
    """Журнал лежит в каталоге строки — там же, где работает агент."""

    def test_dir_is_worktree_of_the_row(self):
        from src.project.task.task_log import task_log_dir

        assert task_log_dir('/srv/app', 1028).endswith('.claude/worktrees/feature_task_1028')

    def test_read_missing_is_empty_not_error(self, tmp_path):
        """
        Нет файлов — пустые строки, а не исключение.

        Строка могла ещё не браться в работу, а каталог — уже уехать после
        слияния ветки: и то, и другое штатно.
        """
        from src.project.task.task_log import task_log_read

        result = task_log_read(str(tmp_path), 999999)

        assert result['log'] == '' and result['state'] == ''


@pytest.mark.asyncio
async def test_write_run_without_trace_writes_nothing(tmp_path):
    """Трассы нет — писать нечего, и это не ошибка."""
    from src.project.task.task_log import task_log_write_run

    assert await task_log_write_run(str(tmp_path), 1, '', 'developer', 1, 'итог') == 0

"""
Замеры работы ролей — `src/project/task/task_metric.py` и `task_metric_gx10.py`.

Проверяется то, из-за чего статистика может незаметно врать: разбор счётчиков
модели, дельта между снимками и вытаскивание токенов из ответа инструмента.

Почему именно это. Числа здесь никто не перепроверяет глазами — их складывают в
средние, а по средним потом ставят таймауты и оценивают сроки. Ошибка в разборе
не упадёт и не заметится: она просто сдвинет среднее, и порог разбиения окажется
подобран по мусору.

Отдельно проверяется, что сбой замера отличим от честного нуля. Модель
недоступна, счётчик пропал, сервер перезапустился — во всех этих случаях в
таблицу идут нули, и они не должны выглядеть как «модель ничего не сгенерировала».

Модули импортируются внутри тестов: они тянут `mysql_`, который читает
`MYSQL_HOST` на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

import pytest

pytestmark = pytest.mark.pipeline
# Ответ `/metrics` в том виде, в каком его отдаёт llama.cpp: комментарии `# HELP`
# содержат те же имена, что и сами счётчики, — на этом ломается разбор регуляркой.
METRICS_BODY = """# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 850269
# HELP llamacpp:tokens_predicted_total Number of generation tokens processed.
llamacpp:tokens_predicted_total 145813
# HELP llamacpp:tokens_predicted_seconds_total Predict process time
llamacpp:tokens_predicted_seconds_total 7010.14
llamacpp:prompt_tokens_seconds 621.039
"""


class TestCountersParse:
    """Разбор ответа счётчиков: комментарии с теми же именами не должны мешать."""

    def test_all_three_counters_found(self):
        from src.project.task.task_metric_gx10 import _counters_parse

        assert _counters_parse(METRICS_BODY) == {
            'tokens_prompt': 850269.0,
            'tokens_output': 145813.0,
            'gen_seconds': 7010.14,
        }

    def test_partial_answer_is_no_answer(self):
        """
        Нет хотя бы одного счётчика — снимка нет вовсе.

        Половина снимка хуже его отсутствия: дельта по ней посчиталась бы и легла
        в среднее как факт, хотя не описывает ничего.
        """
        from src.project.task.task_metric_gx10 import _counters_parse

        assert _counters_parse('llamacpp:tokens_predicted_total 100\n') == {}
        assert _counters_parse('') == {}
        assert _counters_parse('совсем не те данные') == {}


class TestDelta:
    """Что модель сделала между снимками."""

    BEFORE = {'tokens_output': 1000.0, 'tokens_prompt': 5000.0, 'gen_seconds': 100.0}

    def test_normal_window(self):
        from src.project.task.task_metric_gx10 import task_metric_gx10_delta

        after = {'tokens_output': 1500.0, 'tokens_prompt': 8000.0, 'gen_seconds': 125.0}
        delta = task_metric_gx10_delta(self.BEFORE, after)

        assert delta == {'tokens_output': 500, 'tokens_prompt': 3000, 'tokens_per_sec': 20.0}

    def test_missing_snapshot_gives_zeros(self):
        """Замер не состоялся — нули во всех трёх полях сразу: по ним это и видно."""
        from src.project.task.task_metric_gx10 import task_metric_gx10_delta

        empty = {'tokens_output': 0, 'tokens_prompt': 0, 'tokens_per_sec': 0.0}

        assert task_metric_gx10_delta({}, {'tokens_output': 5.0}) == empty
        assert task_metric_gx10_delta(self.BEFORE, {}) == empty

    def test_server_restart_does_not_give_negative(self):
        """
        Счётчики поехали вниз — сервер модели перезапустили между снимками.

        Разница по ним бессмысленна, и отрицательные токены испортили бы сумму по
        задаче: она считается обычным SUM.
        """
        from src.project.task.task_metric_gx10 import task_metric_gx10_delta

        after = {'tokens_output': 10.0, 'tokens_prompt': 20.0, 'gen_seconds': 1.0}
        delta = task_metric_gx10_delta(self.BEFORE, after)

        assert delta['tokens_output'] == 0 and delta['tokens_prompt'] == 0

    def test_no_generation_time_leaves_speed_undefined(self):
        """Секунд генерации ноль — скорость не определена, а не бесконечна."""
        from src.project.task.task_metric_gx10 import task_metric_gx10_delta

        after = {'tokens_output': 1000.0, 'tokens_prompt': 5100.0, 'gen_seconds': 100.0}

        assert task_metric_gx10_delta(self.BEFORE, after)['tokens_per_sec'] == 0.0


class TestTokensFromToolOutput:
    """
    Токены вытаскиваются из ответа инструмента, записанного в трассу.

    Ответ там лежит как repr словаря, и внутри `response` живёт текст агента с
    кавычками и переносами — разбор регуляркой цеплялся бы за первую же кавычку.
    """

    def test_reads_tool_result(self):
        from src.project.task.task_metric import _tokens_parse

        output = ("{'status': 'answered', 'response': 'Готово: правки в 7 файлах', "
                  "'payload_json': '', 'error': '', 'session_uuid': 'abc', 'inbox_id': 5, "
                  "'elapsed': 2517, 'tokens_out': 4200, 'tokens_prompt': 91000, 'tokens_sec': 20.7}")

        assert _tokens_parse(output) == {'tokens_out': 4200, 'tokens_prompt': 91000,
                                         'tokens_sec': 20.7}

    def test_quotes_inside_response_survive(self):
        """Кавычка в тексте агента не должна ломать разбор."""
        from src.project.task.task_metric import _tokens_parse

        output = ('{"status": "answered", "response": "он сказал \\"готово\\" и ушёл", '
                  '"tokens_out": 10, "tokens_prompt": 20, "tokens_sec": 5.0}')

        assert _tokens_parse(output)['tokens_out'] == 10

    def test_old_result_without_tokens(self):
        """Круги до появления замера токенов не имеют — это нули, а не сбой."""
        from src.project.task.task_metric import _tokens_parse

        assert _tokens_parse("{'status': 'answered', 'elapsed': 100}") == {
            'tokens_out': 0, 'tokens_prompt': 0, 'tokens_sec': 0.0}

    def test_unparsable_output_is_zeros(self):
        from src.project.task.task_metric import _tokens_parse

        empty = {'tokens_out': 0, 'tokens_prompt': 0, 'tokens_sec': 0.0}

        assert _tokens_parse('json:не словарь') == empty
        assert _tokens_parse('') == empty
        assert _tokens_parse('{оборванный') == empty


class TestDeleteGuard:
    """
    Удаление всей таблицы одним вызовом не предусмотрено.

    Накопленное здесь не восстановить: оно копится кругами по сорок минут, и
    «удалить всё» — не та операция, которую стоит уметь.
    """

    async def test_no_id_deletes_nothing(self):
        from src.project.task.task_metric import task_metric_delete

        assert await task_metric_delete() == 0
        assert await task_metric_delete(task_id=None, parent_id=None) == 0

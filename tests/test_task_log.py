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


@pytest.fixture(autouse=True)
async def db_pool_release():
    """
    Закрыть пул MySQL после каждого теста.

    Пул в `mysql_` модульный и привязан к циклу событий, в котором создан, а
    pytest-asyncio даёт каждому тесту свой. `task_log_read` теперь ходит в базу
    за идущими прогонами — оставленный пул ломал сессионную уборку `conftest.py`,
    у которой цикл свой: «Event loop is closed» на teardown всей сюиты.
    Та же дисциплина в `test_task_metadata.py` и `test_planning.py`.
    """
    yield
    from mysql_.mysql_ import mysql_pool_close
    await mysql_pool_close()


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

    @pytest.mark.asyncio
    async def test_read_missing_is_empty_not_error(self, tmp_path):
        """
        Нет файлов и нет идущего прогона — пустые строки, а не исключение.

        Строка могла ещё не браться в работу, а каталог — уже уехать после
        слияния ветки: и то, и другое штатно.
        """
        from src.project.task.task_log import task_log_read

        result = await task_log_read(str(tmp_path), 999999)

        assert result['log'] == '' and result['state'] == ''
        assert result['running'] is False


@pytest.mark.asyncio
async def test_write_run_without_trace_writes_nothing(tmp_path):
    """Трассы нет — писать нечего, и это не ошибка."""
    from src.project.task.task_log import task_log_write_run

    assert await task_log_write_run(str(tmp_path), 1, '', 'developer', 1, 'итог') == 0


class TestAnswerParsing:
    """
    Разбор ответа шага. Все образцы — с живых прогонов: менеджера (трасса 1085) и
    QA (1082). Регулярка на них спотыкалась о первую кавычку внутри значения, и в
    журнал уезжала одна скобка вместо плана на восемь шагов.
    """

    def test_json_inside_shell_answer(self):
        """`response` сам бывает JSON-ом в markdown-заборе — достаём смысл."""
        from src.project.task.task_log import _answer_text

        text = _answer_text("{'status': 'answered', 'response': '```json\\n"
                            '{"task_plan_json": {"plan_text": "1. Прогнать автопроверки"}}'
                            "```', 'elapsed': 3}")

        assert text == '1. Прогнать автопроверки'

    def test_wrapper_key_unwrapped(self):
        """Обёртка `task_plan_json` человеку не говорит ничего — спускаемся внутрь."""
        from src.project.task.task_log import _answer_text

        assert _answer_text('{"qa_report_json": {"summary": "ветка проверена"}}') == 'ветка проверена'

    def test_list_wrapper_numbered(self):
        """Цели приходят массивом: нумеруем, а не показываем квадратные скобки."""
        from src.project.task.task_log import _answer_text

        text = _answer_text('{"task_goals_json": ["первая цель", "вторая цель"]}')

        assert text == '1) первая цель · 2) вторая цель'

    def test_json_prefix_stripped(self):
        """Шаг «Вернуть результат» отдаёт ответ с префиксом `json:`."""
        from src.project.task.task_log import _answer_text

        assert _answer_text('json:{"plan": {"plan_text": "план работ"}}') == 'план работ'

    def test_unknown_keys_rendered_as_pairs(self):
        """Известных ключей нет — пары «ключ: значение» читаются лучше сырого JSON."""
        from src.project.task.task_log import _answer_text

        text = _answer_text('{"qa_goal_ok": "yes", "qa_goal_evidence": "живое воспроизведение"}')

        assert 'qa_goal_ok: yes' in text and 'живое воспроизведение' in text

    def test_tool_result_in_russian(self):
        """Инструменты возвращают словари под движок — человеку нужен смысл."""
        from src.project.task.task_log import _answer_text

        assert _answer_text("{'env_ok': 'yes', 'env_error': '', 'env_dir': '/app'}") == 'среда готова'
        assert 'взял цель 1 из 2' in _answer_text(
            "{'goal_has': 'yes', 'goal_text': 'цель', 'goal_number': 1, 'goal_total': 2}")
        assert 'целей закрыто 1 из 2' in _answer_text(
            "{'goal_done_count': 1, 'goal_open_count': 1, 'goal_total': 2}")

    def test_literal_newline_flattened(self):
        """
        В repr словаря перенос строки остаётся двумя символами.

        Без замены он выглядел бы в журнале мусором «\\n» посреди фразы.
        """
        from src.project.task.task_log import _answer_text

        assert '\\n' not in _answer_text("{'response': 'первая строка\\\\nвторая строка'}")

    def test_broken_json_returned_as_is(self):
        """Ответ обрезан трассой — отдаём как есть, журнал из-за формата не роняем."""
        from src.project.task.task_log import _answer_text

        assert _answer_text('{"summary": "обрезанны') == '{"summary": "обрезанны'


def test_counter_step_skipped():
    """Счётчик круга возвращает голое число — в журнале это строка без содержания."""
    from src.project.task.task_log import _step_skip

    assert _step_skip(_step('Счётчик итераций проверки', '1'))
    assert not _step_skip(_step('Отметить цель', "{'goal_done_count': 1}"))


class TestTimezone:
    """
    Метки времени показываются в поясе настройки `timezone`, а не базы.

    Трассу пишет MySQL, в контейнере он живёт по UTC. Человек сверяет журнал с
    часами на стене: без сдвига «47 минут без записей» приходилось пересчитывать
    руками, а сама метка выглядела меткой из прошлого.
    """

    def test_offset_applied_to_stored_time(self):
        from datetime_.datetime_ import datetime_offset_apply

        shifted = datetime_offset_apply(datetime(2026, 8, 24, 7, 56, 38), '+3')

        assert shifted.hour == 10 and shifted.minute == 56

    def test_negative_and_prefixed_offsets(self):
        from datetime_.datetime_ import datetime_offset_apply

        value = datetime(2026, 8, 24, 12, 0, 0)

        assert datetime_offset_apply(value, 'UTC-2').hour == 10
        assert datetime_offset_apply(value, '+0').hour == 12

    def test_garbage_offset_is_utc(self):
        """Мусор в настройке — показываем UTC, а не падаем."""
        from datetime_.datetime_ import datetime_offset_apply

        assert datetime_offset_apply(datetime(2026, 8, 24, 12, 0, 0), 'какая-то ерунда').hour == 12

    def test_none_stays_none(self):
        """Пустой колонке нечего сдвигать — подставлять «сейчас» было бы враньём."""
        from datetime_.datetime_ import datetime_offset_apply

        assert datetime_offset_apply(None, '+3') is None


def test_retry_mark_on_second_run(tmp_path):
    """
    Технический повтор круг не жжёт — и два блока подряд подписывались одинаково.

    Человек не понимал, почему «круг 1 · developer» случился дважды.
    """
    from src.project.task.task_log import TASK_LOG_FILE, _retry_mark

    assert _retry_mark(str(tmp_path), 1, 'developer') == ''

    (tmp_path / TASK_LOG_FILE).write_text('## круг 1 · developer · 2026-08-24 10:56\n')

    assert _retry_mark(str(tmp_path), 1, 'developer') == ' · повтор 2'
    assert _retry_mark(str(tmp_path), 2, 'developer') == '', 'у нового круга пометки быть не должно'


class TestOutcomeKeyword:
    """
    Ключевое слово итога круга. Формулировку задаёт `task_pipeline._log_run`,
    разбирает её `_outcome_line` — договорённость строковая, и её надо держать.

    Наступили живьём: QA закрыл подзадачу #1030 с `qa_ok: yes`, но вернул
    замечания на будущее («стоит явно пометить»), они легли в `error`, и круг
    подписался «затык». Человек видел затык у принятой работы, а следующий круг
    прочёл бы это как «не приняли» и пошёл переделывать.
    """

    def test_plain_success(self):
        from src.project.task.task_log import TASK_LOG_OUTCOME_OK, _outcome_line

        assert 'готово' in _outcome_line(datetime(2026, 8, 24, 16, 19), TASK_LOG_OUTCOME_OK)
        assert 'затык' not in _outcome_line(datetime(2026, 8, 24, 16, 19), TASK_LOG_OUTCOME_OK)

    def test_success_with_notes_is_not_a_blocker(self):
        from src.project.task.task_log import _outcome_line

        line = _outcome_line(datetime(2026, 8, 24, 16, 19),
                             'готово, с замечаниями: blog.md §1 стоит пометить явно')

        assert 'готово' in line and 'затык' not in line

    def test_failure_is_a_blocker(self):
        from src.project.task.task_log import _outcome_line

        line = _outcome_line(datetime(2026, 8, 24, 16, 19),
                             'Цели, которые проверка не подтвердила: …')

        assert 'затык' in line


class TestCutText:
    """
    Обрезка длинного ответа. Ставили 220 символов — мысль не успевала дочитаться,
    строки рвались на «Второй раунд я …». И рвались молча: понять, кончилась фраза
    или её отрезали, было нельзя.
    """

    def test_short_text_untouched(self):
        from src.project.task.task_log import TASK_LOG_CUT_MARK, _cut_text

        assert _cut_text('коротко') == 'коротко'
        assert TASK_LOG_CUT_MARK not in _cut_text('коротко')

    def test_long_text_marked(self):
        from src.project.task.task_log import (TASK_LOG_CUT_MARK, TASK_LOG_STEP_MAX_CHARS,
                                               _cut_text)

        result = _cut_text('я' * (TASK_LOG_STEP_MAX_CHARS * 3))

        assert result.endswith(TASK_LOG_CUT_MARK), 'обрезка должна быть видна'
        assert len(result) == TASK_LOG_STEP_MAX_CHARS + len(TASK_LOG_CUT_MARK)

    def test_cap_fits_a_paragraph(self):
        """Потолок должен вмещать законченную мысль, а не полфразы."""
        from src.project.task.task_log import TASK_LOG_STEP_MAX_CHARS

        assert TASK_LOG_STEP_MAX_CHARS >= 500

    def test_step_line_marks_the_cut(self):
        from src.project.task.task_log import TASK_LOG_CUT_MARK, _step_line

        line = _step_line(_step('Шаг', "{'response': '" + 'я' * 4000 + "'}"))

        assert TASK_LOG_CUT_MARK in line


class TestSummaryChunks:
    """
    Нарезка длинных ответов на порции под контекст модели.

    Порция — не украшение, а следствие двух измеренных ограничений: контекст
    `gx10/qwen-small` отвечает `exceed_context_size_error` на 2583 токенах, а
    вызовы одного агента не параллелятся (слот один) и на 180 секундах их рвёт
    сам фреймворк. Поэтому режем и шлём по очереди.
    """

    def test_короткие_идут_одной_порцией(self):
        from src.project.task.task_log_summary import _chunks_split

        items = [{'key': n, 'text': 'я' * 300} for n in range(3)]

        assert [len(c) for c in _chunks_split(items)] == [3]

    def test_длинные_делятся(self):
        from src.project.task.task_log_summary import TASK_LOG_SUMMARY_CHUNK_MAX, _chunks_split

        items = [{'key': n, 'text': 'я' * (TASK_LOG_SUMMARY_CHUNK_MAX // 2 + 50)} for n in range(4)]
        chunks = _chunks_split(items)

        assert len(chunks) > 1
        assert sum(len(c) for c in chunks) == 4

    def test_блок_больше_порции_уходит_один(self):
        """Он уже урезан по своему потолку — выбрасывать его нечестно."""
        from src.project.task.task_log_summary import TASK_LOG_SUMMARY_CHUNK_MAX, _chunks_split

        items = [{'key': 0, 'text': 'я' * (TASK_LOG_SUMMARY_CHUNK_MAX * 3)},
                 {'key': 1, 'text': 'коротко'}]
        chunks = _chunks_split(items)

        assert [len(c) for c in chunks] == [1, 1]

    def test_пусто(self):
        from src.project.task.task_log_summary import _chunks_split

        assert _chunks_split([]) == []


class TestSummaryBlocks:
    """Сборка промпта из блоков порции."""

    def test_нумерация_с_единицы(self):
        from src.project.task.task_log_summary import _blocks_build

        text = _blocks_build([{'text': 'раз', 'title': 'Разбор', 'kind': 'сделал'},
                              {'text': 'два', 'title': 'Вердикт', 'kind': 'затык'}])

        assert '=== 1 · Шаг: Разбор · Исход: сделал ===' in text
        assert '=== 2 · Шаг: Вердикт · Исход: затык ===' in text

    def test_длинный_ответ_режется(self):
        from src.project.task.task_log_summary import TASK_LOG_SUMMARY_BLOCK_MAX, _blocks_build

        text = _blocks_build([{'text': 'я' * 9000, 'title': 'Ш', 'kind': 'сделал'}])

        assert len(text) < TASK_LOG_SUMMARY_BLOCK_MAX + 200

    def test_пустой_ответ_пропускается(self):
        from src.project.task.task_log_summary import _blocks_build

        assert _blocks_build([{'text': '   ', 'title': 'Ш', 'kind': 'сделал'}]) == ''


class TestSummaryAnswer:
    """
    Разбор ответа модели. Терпимость к форме тут не вежливость: пересказ уже
    стоил десятков секунд, и терять его из-за того, что модель назвала номер
    `number` вместо `n`, — расточительство.
    """

    def test_обычная_форма(self):
        from src.project.task.task_log_summary import _answer_parse

        raw = 'json:{"log_summary_json": {"lines": [{"n": 1, "text": "суть"}]}}'

        assert _answer_parse(raw, 850) == {1: 'суть'}

    def test_список_прямо_под_ключом(self):
        from src.project.task.task_log_summary import _answer_parse

        raw = '{"log_summary_json": [{"n": 2, "text": "суть"}]}'

        assert _answer_parse(raw, 850) == {2: 'суть'}

    def test_массив_строк_нумеруется_по_месту(self):
        from src.project.task.task_log_summary import _answer_parse

        raw = '{"lines": ["первая", "вторая"]}'

        assert _answer_parse(raw, 850) == {1: 'первая', 2: 'вторая'}

    def test_переводы_строк_схлопываются(self):
        """Журнал читают построчно — перенос внутри строки его ломает."""
        from src.project.task.task_log_summary import _answer_parse

        raw = '{"lines": [{"n": 1, "text": "две\\nстроки"}]}'

        assert _answer_parse(raw, 850) == {1: 'две строки'}

    def test_длина_режется_потолком(self):
        from src.project.task.task_log_summary import _answer_parse

        raw = '{"lines": [{"n": 1, "text": "' + 'я' * 3000 + '"}]}'

        assert len(_answer_parse(raw, 850)[1]) == 850

    def test_мусор_даёт_пустоту(self):
        from src.project.task.task_log_summary import _answer_parse

        assert _answer_parse('', 850) == {}
        assert _answer_parse('не json вовсе', 850) == {}
        assert _answer_parse('{"lines": "не список"}', 850) == {}


class TestShellBlocks:
    """
    Хронология оболочки живёт отдельным файлом и сводится с журналом только на
    странице человека.

    Разделение не косметическое: общий журнал следующий круг читает целиком, и
    «задание ушло, ответ получен» для него шум — работу он ведёт не с оболочкой, а
    внутри неё. Человеку же без этих отметок не видно, на чьей стороне затык:
    поймано на планировании #1027, где оболочка ответ выдала, а шаг разведки всё
    равно закрылся как «менеджер не ответил».
    """

    LOG = ('\n## круг 1 · manager · 2026-08-25 17:03\n'
           '17:03:21  сделал    Промпт: разведка: собран\n'
           '17:17:59  затык     Менеджер: разведка [14 мин]: ответа нет\n')
    SHELL = ('\n## круг 1 · manager · 2026-08-25 17:03\n'
             '17:03:21  запрос    оболочка manager ← задание: Ты менеджер разработки\n'
             '17:17:58  ответ     оболочка manager → ответ [14 мин]: план готов\n')

    def test_lines_interleave_by_time(self):
        """Смысл именно в чередовании: ответ оболочки должен стоять перед затыком шага."""
        from src.project.task.task_log import _blocks_merge

        lines = [line for line in _blocks_merge(self.LOG, self.SHELL).splitlines() if line.strip()]

        assert lines[0].startswith('## круг 1'), 'заголовок круга остаётся один'
        assert [line.split()[0] for line in lines[1:]] == ['17:03:21', '17:03:21',
                                                           '17:17:58', '17:17:59']
        assert 'ответ' in lines[3] and 'затык' in lines[4], \
            'ответ оболочки пришёл раньше, чем шаг сдался, — иначе затык не прочитать'

    def test_blocks_pair_by_round_head(self):
        """Круги сводятся по заголовку: строка несёт время без даты."""
        from src.project.task.task_log import _blocks_merge

        second_log = '\n## круг 2 · manager · 2026-08-25 18:00\n18:00:10  сделал    Промпт: план: собран\n'
        merged = _blocks_merge(self.LOG + second_log, self.SHELL)

        first, second = merged.split('## круг 2')
        assert 'оболочка manager' in first, 'события первого круга остались в первом круге'
        assert 'оболочка manager' not in second, 'во второй круг чужие события попасть не должны'

    def test_shell_block_without_pair_kept(self):
        """Журнал не записался — хронологию оболочки всё равно не теряем."""
        from src.project.task.task_log import _blocks_merge

        assert 'оболочка manager' in _blocks_merge('', self.SHELL)
        assert _blocks_merge(self.LOG, '') == self.LOG, 'без оболочки журнал не трогаем'

    def test_service_command_reads_as_words(self):
        """`__RESTART_WATCH__` в ленте — это причина потерянного ответа, а не мусор."""
        from src.project.task.task_log_shell import TASK_LOG_SHELL_SERVICE, task_log_shell_line

        line = task_log_shell_line({'created_at': datetime(2026, 8, 25, 17, 19, 5),
                                    'keyword': 'запрос',
                                    'title': f"оболочка manager: {TASK_LOG_SHELL_SERVICE['__RESTART_WATCH__']}",
                                    'text': '', 'seconds': 0})

        assert line == '17:19:05  запрос    оболочка manager: оболочка перезапущена\n'
        assert not line.rstrip().endswith(':'), 'висящее двоеточие читается как потерянное значение'


class TestHonestReportIsNotBlocker:
    """
    `ok: false` сам по себе затыком не считается.

    Роль отвечает так и когда работала честно: «переименовал девять функций, но
    остановился на развилке» — это состоявшийся ход с содержанием. Помечать его
    наравне с мёртвой оболочкой значит врать: человек ищет в журнале, где всё
    встало, и красная пометка на нормальном ответе уводит его не туда.

    Поймано вживую на #1626: строка «10:58:27 затык Ответ JSON: отчёт» стояла
    рядом с тем же текстом, помеченным «ответ», — один и тот же ответ LLM с двумя
    разными ярлыками.

    Отличаем по содержанию: у заглушки несостоявшегося прогона его нет — пустой
    отчёт и текст ошибки вместо работы.
    """

    STUB = ('json:{"env_ok": false, "ok": false, "report": {}, '
            '"error": "Разработчик не ответил. Статус: timeout"}')
    REAL = ('json:{"dev_report_json": {"ok": false, "summary": '
            '"Переименовал 9 публичных инструментов в 3 файлах"}}')

    def test_stub_without_work_is_a_blocker(self):
        from src.project.task.task_log import _step_failed

        assert _step_failed(_step('Разработчик недоступен', self.STUB))

    def test_short_stub_without_report_is_a_blocker(self):
        """Заглушка бывает и без ключа `report` — отличает её отсутствие сути."""
        from src.project.task.task_log import _step_failed

        assert _step_failed(_step('QA недоступен', 'json:{"ok": false, "error": "QA не ответил"}'))

    def test_report_with_work_is_not_a_blocker(self):
        from src.project.task.task_log import _step_failed

        assert not _step_failed(_step('Ответ JSON: отчёт', self.REAL))

    def test_qa_verdict_with_work_is_not_a_blocker(self):
        """Вердикт «не принято» — тоже состоявшаяся работа, а не затык."""
        from src.project.task.task_log import _step_failed

        output = ('json:{"qa_report_json": {"ok": false, '
                  '"verdict": "цель закрыта, но документация устарела"}}')

        assert not _step_failed(_step('Ответ JSON: вердикт', output))

    def test_line_keyword_follows(self):
        """Ярлык строки journal идёт за тем же решением."""
        from src.project.task.task_log import _step_line

        assert 'сделал' in _step_line(_step('Ответ JSON: отчёт', self.REAL))
        assert 'затык' in _step_line(_step('Разработчик недоступен', self.STUB))

    def test_dead_shell_still_a_blocker(self):
        """Статус вызова оболочки проверяется отдельно и остаётся затыком."""
        from src.project.task.task_log import _step_failed

        assert _step_failed(_step('Разработчик: реализация', SHELL_TIMEOUT))

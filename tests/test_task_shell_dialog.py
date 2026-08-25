"""
Диалог Claude Code внутри оболочки — `src/project/task/task_shell_dialog.py`.

Проверяется разбор отказа, помеченного оболочкой (`DIALOG_MARKER` в
`claude-shell/shell.py`), в вопрос человеку.

Зачем это вообще. Claude Code иногда останавливается и ждёт клавишу. Оболочка
вопрос распознавала и слала человеку в чат, но ждущее задание конвейера не
трогала: оно висело до таймаута и падало с «не смогла получить ответ агента» — то
же самое, что у зависшей оболочки. Зависшую конвейер лечит перезапуском,
перезапуск сносит диалог вместе с ходом, следующий круг упирается в тот же вопрос.
Живьём на планировании #1027 так сгорело четыре круга.

Отсюда предмет проверки: отказ из-за диалога обязан отличаться от обычного
молчания, а варианты — доезжать до попапа вместе со своими номерами. Номер здесь
не украшение: им отвечает Claude Code, и в записанном решении он единственное, по
чему потом видно, что именно выбрали.

Модули импортируются внутри тестов: они тянут `mysql_`, который читает
`MYSQL_HOST` на импорте, а подмена хоста живёт в фикстурах `conftest.py`.
"""

# Отказ ровно в той форме, в какой его шлёт оболочка: метка, заголовок
# уведомления, текст вопроса, варианты и подсказка «ответь номером».
DIALOG_ERROR = """[[dialog]]
🔐 Claude ждёт ответа:

What do you want to do?

1. Stop and wait for limit to reset
2. Ask your admin for more usage

Ответь номером, «да»/«нет», либо напиши, что делать вместо этого."""

PLAIN_ERROR = 'Оболочка не смогла получить ответ агента'


class TestDialogDetect:
    """Отказ из-за диалога против обычного молчания — их лечат по-разному."""

    def test_marked_error_is_dialog(self):
        from src.project.task.task_shell_dialog import task_shell_dialog_has

        assert task_shell_dialog_has(DIALOG_ERROR)

    def test_plain_silence_is_not_dialog(self):
        """Молчащая оболочка лечится перезапуском — эту ветку трогать нельзя."""
        from src.project.task.task_shell_dialog import task_shell_dialog_has

        assert not task_shell_dialog_has(PLAIN_ERROR)
        assert not task_shell_dialog_has('')
        assert not task_shell_dialog_has(None)


class TestDialogQuestion:
    """Разбор диалога в вопрос той же формы, что задают роли."""

    def test_options_keep_their_digits(self):
        """Номер варианта — клавиша, которой отвечает Claude Code."""
        from src.project.task.task_shell_dialog import task_shell_dialog_question

        question = task_shell_dialog_question(DIALOG_ERROR, 'Менеджер')

        assert [(o['key'], o['label']) for o in question['options']] == [
            ('1', 'Stop and wait for limit to reset'),
            ('2', 'Ask your admin for more usage'),
        ]

    def test_text_names_the_role_and_keeps_the_question(self):
        from src.project.task.task_shell_dialog import task_shell_dialog_question

        text = task_shell_dialog_question(DIALOG_ERROR, 'Менеджер')['text']

        assert 'Менеджер' in text, 'человеку важно, чья оболочка встала'
        assert 'What do you want to do?' in text
        assert '🔐' not in text, 'заголовок уведомления написан для чата, в попапе он лишний'
        assert 'Ответь номером' not in text, 'подсказка про номера в попапе не нужна — там кнопки'

    def test_plain_silence_gives_no_question(self):
        """Без метки вопроса быть не должно: иначе повтор подменится вопросом всегда."""
        from src.project.task.task_shell_dialog import task_shell_dialog_question

        assert task_shell_dialog_question(PLAIN_ERROR, 'Менеджер') == {}

    def test_marked_as_dialog_not_role_question(self):
        """Спросил не агент, а мы за него — попап должен это различать."""
        from src.project.task.task_shell_dialog import task_shell_dialog_question

        assert task_shell_dialog_question(DIALOG_ERROR, 'QA')['dialog'] is True

    def test_survives_dialog_without_options(self):
        """Диалог, вариантов которого не видно, вопросом остаётся — без кнопок."""
        from src.project.task.task_shell_dialog import task_shell_dialog_question

        question = task_shell_dialog_question('[[dialog]]\n🔐 Claude ждёт ответа:\n', 'Менеджер')

        assert question['options'] == []
        assert question['text'], 'пустой вопрос открыл бы попап ни с чем'

    def test_role_optional(self):
        from src.project.task.task_shell_dialog import task_shell_dialog_question

        assert task_shell_dialog_question(DIALOG_ERROR)['text'].startswith('Оболочка остановилась')


class TestQuestionPipeline:
    """Разбор общий с ролями: вопрос диалога должен пройти `task_question_parse`."""

    def test_parses_into_role_question_shape(self):
        from src.project.task.task_question import task_question_parse
        from src.project.task.task_shell_dialog import task_shell_dialog_question

        raw = task_shell_dialog_question(DIALOG_ERROR, 'Менеджер')
        question = task_question_parse({'question': raw})

        assert question['text']
        assert [o['key'] for o in question['options']] == ['1', '2']
        assert question['multi'] is False


class TestDialogHoldRoundTrip:
    """
    Вопрос из диалога помнит, куда вернуть строку.

    Без этого задача остаётся в `failed` навсегда: круга не было, а ответ снял то,
    из-за чего он не состоялся, — вернуть её больше некому. А вернуть надо ровно
    туда, откуда сняли: планирование ждёт задачу в `new`, пересмотр плана — в
    `reviewing`, и перепутать их значит переписать план вместо правки.
    """

    def test_question_carries_back_state(self):
        from src.project.task.task_question import task_question_parse
        from src.project.task.task_shell_dialog import task_shell_dialog_question

        dialog = task_shell_dialog_question(DIALOG_ERROR, 'Менеджер')
        question = {**task_question_parse({'question': dialog}), 'dialog': True,
                    'back_state': 'reviewing'}

        assert question['dialog'] is True
        assert question['back_state'] == 'reviewing'
        assert question['text'] and question['options'], \
            'разбор не должен терять текст и варианты при добавлении пометок'

    def test_plan_question_has_no_back_state(self):
        """Вопрос менеджера с планом задачу не двигает — ей и так ждать человека."""
        from src.project.task.task_question import task_question_parse

        question = task_question_parse({'question': {'text': 'Меняем ли контракт API?',
                                                     'options': ['Да', 'Нет']}})

        assert not question.get('dialog')
        assert not question.get('back_state')

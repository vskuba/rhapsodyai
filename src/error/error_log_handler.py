"""Застава на корневом логгере: всё, что пишется как ошибка, попадает в журнал.

Журнал (`error_log.py`) мог бы наполняться вызовами по месту — «поймал
исключение, записал». Так его наполняют ровно до первой забытой ветки: пишущий
код занят своей работой, а строчку про журнал в нём надо помнить. Поэтому
источник один и внешний: обработчик, подвешенный к корневому логгеру на уровне
ERROR. Любой `logger_exception`, `logging.error`, `logging.exception` и
необработанное исключение asyncio-задачи (его печатает сам asyncio через свой
логгер) оставляют строку в журнале **без единой строчки про журнал в коде**.

## ⚠ Ставится один раз на процесс, и его надо поставить

Обработчик не появляется сам: `logging_init()` живёт в общем слое
(`py_modules/logging_`) и про таблицы этого проекта не знает. Поэтому каждая
точка входа зовёт `error_log_handler_install` рядом со своим `logging_init()`:
`main_uvicorn`, `main_telegram`, воркеры `rq`, кронджобы. Забытая точка входа не
ломается — она просто молчит в журнале.

⚠ `main_browser` намеренно **не** в этом списке: у контейнера-браузера нет базы
(та же причина, по которой ошибки окна пишет `uvicorn`, — см. `browser_error`).

## ⚠⚠ Не все логгеры доходят до корня

Uvicorn настраивает свои (`uvicorn.error`) с `propagate = False`: его
собственные ошибки до корневого обработчика не доходят вовсе. Поэтому установка
проходит по списку `ERROR_LOG_HANDLER_LOGGERS` и подвешивается к каждому, кто
оторван от корня. Тем, кто до корня доходит, второй обработчик не вешается:
запись задвоилась бы (и стала бы двумя `hits` на одно падение).
"""

import logging
import threading
import traceback as traceback_module

from src.error.error_log import error_log_write

# Логгеры, которые бывают оторваны от корня своими настройками. Подвешиваемся к
# ним, только если `propagate` действительно выключен — иначе задвоение.
ERROR_LOG_HANDLER_LOGGERS = ('uvicorn.error', 'rq.worker')

# Уровень, с которого пишем. Ниже ERROR — не ошибки: WARNING в этом проекте
# означает «странно, но работаем», и журнал бы им затопило.
ERROR_LOG_HANDLER_LEVEL = logging.ERROR

# Чьи записи пропускаем мимо журнала. Сам журнал о своих неудачах говорит через
# `logger_info` (INFO сюда не доходит), но если модуль когда-нибудь пожалуется
# на уровне ERROR — запись о недоступной базе пошла бы в ту же недоступную базу.
ERROR_LOG_HANDLER_SKIP = ('src.error.', 'error_log')

# Приметы чужого кода в пути файла. По ним из трассировки выбирается последний
# **свой** кадр: в строке журнала нужна строка нашего кода, а не одинаковая у
# всех ошибок база чужой библиотеки (`_error_log_handler_frame`).
ERROR_LOG_HANDLER_FOREIGN = ('/site-packages/', '/dist-packages/', '/lib/python')


class ErrorLogHandler(logging.Handler):
    """Обработчик журнала: строка уровня ERROR — строка в таблице `error_log`.

    Заводится не напрямую, а через `error_log_handler_install`: тот следит, чтобы
    обработчик на процесс был один.
    """

    def __init__(self, source: str):
        super().__init__(level=ERROR_LOG_HANDLER_LEVEL)
        self.source = source

    def emit(self, record: logging.LogRecord) -> None:
        """Пишет запись в журнал. Не бросает — как и положено обработчику.

        ⚠ Защита от круга обязательна: запись в базу сама зовёт код, который
        может пожаловаться в тот же логгер. Без флага потока это уходит в
        бесконечную рекурсию, а не в журнал.
        """
        # ⚠ `getattr`, а не `.flag`: `threading.local` заводит значение своё на
        # поток, и в потоке, который его не ставил, атрибута попросту нет.
        if getattr(_error_log_handler_busy, 'flag', False):
            return
        if any(record.name.startswith(skip) for skip in ERROR_LOG_HANDLER_SKIP):
            return

        _error_log_handler_busy.flag = True
        try:
            error_log_write(
                source=self.source,
                message=record.getMessage(),
                level=record.levelname,
                logger_name=record.name,
                traceback_text=_error_log_handler_traceback(record),
                context=_error_log_handler_context(record),
            )
        except Exception:
            # Обработчик журнала не имеет права уронить того, кто журналит.
            self.handleError(record)
        finally:
            _error_log_handler_busy.flag = False


def error_log_handler_install(source: str) -> ErrorLogHandler | None:
    """Подвешивает журнал к логгерам процесса. Зовётся рядом с `logging_init()`.

    Args:
        source: чей это процесс — ключ из `ERROR_LOG_SOURCES`
            (`uvicorn`, `worker`, `telegram`, `cronjob`).

    Returns:
        ErrorLogHandler: поставленный обработчик; `None` — если он уже стоял.

    ⚠ **Идемпотентна.** Второй вызов не ставит второй обработчик: у uvicorn
    lifespan запускается заново при перезагрузке кода, и каждая ошибка считалась
    бы дважды.

    ⚠ Неизвестный `source` не отвергается, а пишется как есть: журнал не место
    для проверки словаря — потерянная запись хуже незнакомой подписи. Но подпись
    для человека возьмётся только у известных (`ERROR_LOG_SOURCES`).
    """
    global _error_log_handler_current

    if _error_log_handler_current is not None:
        return None

    handler = ErrorLogHandler(source)

    root = logging.getLogger()
    root.addHandler(handler)

    # Логгеры, оторванные от корня своими настройками, иначе молчали бы в
    # журнале (шапка модуля). Проверка `propagate` обязательна: у доходящих до
    # корня второй обработчик дал бы два `hits` на одно падение.
    for name in ERROR_LOG_HANDLER_LOGGERS:
        other = logging.getLogger(name)
        if not other.propagate:
            other.addHandler(handler)

    _error_log_handler_current = handler
    return handler


def error_log_handler_remove() -> None:
    """Снимает обработчик — нужно тестам и разовым скриптам, не приложению."""
    global _error_log_handler_current

    if _error_log_handler_current is None:
        return

    logging.getLogger().removeHandler(_error_log_handler_current)
    for name in ERROR_LOG_HANDLER_LOGGERS:
        logging.getLogger(name).removeHandler(_error_log_handler_current)

    _error_log_handler_current = None


# ── Приватное ────────────────────────────────────────────────────────────────

# Обработчик процесса: он один, и повторная установка это знает.
_error_log_handler_current: ErrorLogHandler | None = None

# Флаг «мы сейчас внутри записи» — свой на поток: пишут из разных.
_error_log_handler_busy = threading.local()
_error_log_handler_busy.flag = False


def _error_log_handler_traceback(record: logging.LogRecord) -> str:
    """Трассировка записи: из исключения, а если его нет — из стека вызова."""
    if _error_log_handler_exception(record):
        return ''.join(traceback_module.format_exception(*record.exc_info))

    return record.stack_info or ''


def _error_log_handler_context(record: logging.LogRecord) -> dict:
    """Где случилось. Поля выбраны так, чтобы по ним можно было открыть файл.

    ⚠ **Место берётся из трассировки, а не из полей записи**, когда исключение
    есть. Поля записи показывают, кто позвал логгер, а зовут его через обёртку
    общего слоя (`logger_exception`) — и в журнале у каждой второй ошибки стояло
    бы одно и то же `logging_.py:49`. Последний кадр трассировки показывает, где
    на самом деле сломалось.

    `trace_id` кладёт в запись `logger_info`/`logger_exception` общего слоя — по
    нему ошибка сходится с остальными строками того же прогона в `app.log` и в
    OpenSearch.
    """
    context = {
        'module': record.module,
        'func': record.funcName,
        'line': record.lineno,
        'file': record.pathname,
        'thread': record.threadName,
        'process': record.process,
    }

    if _error_log_handler_exception(record):
        frame = _error_log_handler_frame(traceback_module.extract_tb(record.exc_info[2]))
        if frame:
            context |= {'file': frame.filename, 'line': frame.lineno, 'func': frame.name}

    trace_id = getattr(record, 'trace_id', '')
    if trace_id:
        context['trace_id'] = str(trace_id)

    return context


def _error_log_handler_frame(frames: list) -> traceback_module.FrameSummary | None:
    """Кадр трассировки, который стоит показать в строке журнала.

    ⚠ **Не последний кадр, а последний свой.** Последний — почти всегда чужая
    библиотека: у ошибки базы это `pymysql/err.py:154 raise_mysql_exception`,
    одинаковое у всех запросов и ни о чём не говорящее. Человеку нужна строка
    **нашего** кода, из которой чужую библиотеку позвали, — она и открывается в
    редакторе. Сама чужая часть никуда не девается: трассировка хранится целиком
    и раскрывается по щелчку.

    ⚠⚠ Общий слой (`py_modules/`) в этом смысле тоже «чужой», хотя код наш: он
    почти весь — тонкие обёртки, и на ошибке запроса кадр остановился бы на
    `mysql_.py:111 execute`, одинаковом у всех запросов проекта. Поэтому
    предпочтение трёхступенчатое: код проекта → общий слой → чужая библиотека.
    """
    if not frames:
        return None

    own = [frame for frame in frames
           if not any(mark in frame.filename for mark in ERROR_LOG_HANDLER_FOREIGN)]
    project = [frame for frame in own if '/py_modules/' not in frame.filename]

    return (project or own or frames)[-1]


def _error_log_handler_exception(record: logging.LogRecord) -> bool:
    """Есть ли в записи настоящее исключение.

    ⚠ Проверять `record.exc_info` мало: `logger_exception` зовут и вне `except`,
    и тогда logging кладёт в запись `(None, None, None)` — форматирование такой
    «трассировки» даёт строку `NoneType: None`, которую мы бы сохранили как
    трассировку ошибки.
    """
    return bool(record.exc_info and record.exc_info[1] is not None)

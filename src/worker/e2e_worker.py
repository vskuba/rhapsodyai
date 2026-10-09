"""Прогон E2E по кнопке: работа уезжает в очередь, страница не ждёт.

Прогон длится минуты — на случай × ширину приходится запуск браузера, а случаев
у установки будут десятки. Делать это прямо в обработчике запроса нельзя: ручка
обязана ответить сразу, иначе браузер оборвёт её по своему таймауту, а работа
останется идти в осиротевшем обработчике.

Очередь — `default`, та же, что у конвейера задач (`worker_task`). Своей заводить
незачем: прогон идёт раз в сутки плюс изредка по кнопке, а контейнер очереди
собран из того же образа, и браузер в нём есть — проверено.

## ⚠⚠ Single-flight: второй прогон не заводится

Ключ в Redis на время прогона. Без него десять нажатий кнопки дают десять
прогонов разом — это десять браузеров на одной машине, и все они снимают одни и
те же страницы. Кадры при этом пишутся в разные каталоги, так что молча портить
друг друга не будут, но машина встанет, а страница покажет десять одинаковых
прогонов подряд.

⚠ Ключ снимается **по завершении**, а не по сроку: прогон по кнопке — не
расписание, и ждать после него нечего. Срок у ключа всё же есть, и это страховка
от потерянного воркера: убитый контейнер снять ключ не успеет, и без срока
кнопка осталась бы заблокированной навсегда.
"""

import asyncio

from logging_.logging_ import logger_exception, logger_info
from redis_.redis_ import redis_conn_get
from redis_.redis_queue import redis_queue_get

# Очередь конвейера: отдельная для E2E не нужна — см. шапку.
E2E_WORKER_QUEUE_NAME = 'default'

# Потолок одного прогона. Случай × ширина — это запуск браузера на секунды;
# полчаса хватает на десятки случаев и не даёт зависшему прогону висеть вечно.
E2E_WORKER_JOB_TIMEOUT = 1800

# Сколько держим результат job'а в Redis. Нужен он только чтобы страница могла
# спросить «как там», а настоящий ответ лежит в базе.
E2E_WORKER_RESULT_TTL = 600

# Ключ single-flight и его срок. Срок — страховка от потерянного воркера, а не
# расписание: обычно ключ снимает сам прогон (см. шапку).
E2E_WORKER_FLIGHT_KEY = 'e2e_worker:flight'
E2E_WORKER_FLIGHT_TTL = E2E_WORKER_JOB_TIMEOUT + 120


def e2e_worker_enqueue() -> dict:
    """Поставить прогон в очередь, если он там ещё не стоит.

    Returns:
        dict: `started` — завели ли прогон, `job_id` — id job'а (пусто, когда
        прогон уже идёт), `reason` — почему не завели.
    """
    if not e2e_worker_flight_take():
        return {'started': False, 'job_id': '',
                'reason': 'Прогон уже идёт. Дождитесь его — второй браузер на '
                          'той же машине только замедлит первый.'}

    try:
        job = redis_queue_get(E2E_WORKER_QUEUE_NAME).enqueue(
            e2e_worker_job_run,
            job_timeout=E2E_WORKER_JOB_TIMEOUT,
            result_ttl=E2E_WORKER_RESULT_TTL,
            failure_ttl=E2E_WORKER_RESULT_TTL,
        )
    except Exception:
        # ⚠ Ключ снимаем сами: job в очередь не встал, и снять его некому —
        # кнопка осталась бы заблокированной до истечения срока.
        e2e_worker_flight_release()
        raise

    return {'started': True, 'job_id': job.id, 'reason': ''}


def e2e_worker_job_run() -> dict:
    """Точка входа rq: прогнать все случаи установки.

    Синхронная намеренно — rq зовёт job обычной функцией, своего цикла событий у
    него нет. Внутри `asyncio.run`, потому что сам прогон ходит в базу.

    ⚠ Ключ single-flight снимается в `finally`: упавший прогон обязан отпустить
    кнопку так же, как удачный, иначе одна беда запирает проверку до срока.
    """
    from src.e2e.e2e_runner import e2e_runner_all

    try:
        report = asyncio.run(e2e_runner_all())
        logger_info(f"🧪 E2E по кнопке: тестов {report['tests']}, "
                    f"провалов {report['failed']}, сорвалось {report['errored']}")
        return report
    except Exception as err:
        logger_exception(f'E2E: прогон по кнопке сорвался: {err}')
        raise
    finally:
        e2e_worker_flight_release()


def e2e_worker_running() -> bool:
    """Идёт ли прогон прямо сейчас — по ключу single-flight."""
    try:
        return bool(redis_conn_get().exists(E2E_WORKER_FLIGHT_KEY))
    except Exception:
        # Redis молчит — честнее сказать «не идёт» и дать нажать кнопку: на
        # неработающей очереди прогон всё равно не заведётся, и ошибку человек
        # увидит сразу, а не в виде вечно «идущего» прогона.
        return False


def e2e_worker_flight_take() -> bool:
    """Занять single-flight; False — прогон уже идёт."""
    return bool(redis_conn_get().set(E2E_WORKER_FLIGHT_KEY, '1', nx=True,
                                     ex=E2E_WORKER_FLIGHT_TTL))


def e2e_worker_flight_release() -> None:
    """Освободить single-flight. Повторный вызов безвреден."""
    try:
        redis_conn_get().delete(E2E_WORKER_FLIGHT_KEY)
    except Exception as err:
        # Ключ протухнет сам по сроку: это и есть та страховка, ради которой
        # срок у него есть. Валить из-за этого прогон нечего.
        logger_exception(f'E2E: ключ прогона не снялся: {err}')

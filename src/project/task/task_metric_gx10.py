"""
Счётчики локальной модели: сколько токенов сгенерировано и с какой скоростью.

Зачем. Время шага само по себе мало что говорит: сорок минут при загруженной
модели и сорок минут при свободной — разные новости. Чтобы связывать объём
контекста со сроком, нужен третий показатель — скорость, с которой модель писала
именно в это время.

Откуда берём. llama.cpp отдаёт накопительные счётчики на `/metrics`:

    llamacpp:tokens_predicted_total          сгенерировано всего
    llamacpp:tokens_predicted_seconds_total  сколько на это ушло секунд
    llamacpp:prompt_tokens_total             прочитано всего

Счётчики накопительные, поэтому меряем дельтой: снимок до хода агента, снимок
после, разница — то, что сгенерировано за этот ход. Модель одна и обслуживает
один ход за раз, так что дельта достаётся тому, кто её и потратил. Ходов от
соседних проектов в это окно попасть может, и это осознанная неточность: точного
разделения счётчики не дают, а порядок величины они дают верно.

Скорость считаем по своей же дельте (`токены / секунды генерации`), а не по
готовому `prompt_tokens_seconds`: тот показывает мгновенное значение на момент
запроса, а нам нужно среднее за окно шага.

Сбой замера — не сбой работы. Модель недоступна, ключ не тот, формат сменился —
возвращаем пустой снимок, и метрика запишется с нулями. Ноль в таблице означает
«счётчик недоступен», а не «модель молчала»: разницу видно по тому, что ноль
стоит во всех трёх полях сразу.
"""
import urllib.error
import urllib.request

from config.config import config_get
from logging_.logging_ import logger_info

# Адрес модели ролей. Тот же, на который смотрит LiteLLM (`GX10_URL` у прокси), —
# роли ходят через него, и счётчики надо снимать с той же машины.
TASK_METRIC_GX10_URL_KEY = 'GX10_LARGE_API_URL'
TASK_METRIC_GX10_KEY = 'GX10_API_KEY'

# Ждём недолго: замер вспомогательный, и держать из-за него ход агента нельзя.
TASK_METRIC_GX10_TIMEOUT = 5

# Имена счётчиков в ответе `/metrics` (формат Prometheus: «имя значение»).
TASK_METRIC_GX10_COUNTERS = {
    'tokens_output':  'llamacpp:tokens_predicted_total',
    'tokens_prompt':  'llamacpp:prompt_tokens_total',
    'gen_seconds':    'llamacpp:tokens_predicted_seconds_total',
}


def task_metric_gx10_snapshot() -> dict:
    """
    Снимок накопительных счётчиков модели. Недоступна — `{}`.

    Пустой словарь и есть признак «замера не было»: вызывающий по нему отличает
    сбой съёма от честного нуля.
    """
    base = str(config_get(TASK_METRIC_GX10_URL_KEY) or '').strip().rstrip('/')
    if not base:
        return {}

    url = f"{base.removesuffix('/v1')}/metrics"
    request = urllib.request.Request(url)
    key = str(config_get(TASK_METRIC_GX10_KEY) or '').strip()
    if key:
        request.add_header('Authorization', f'Bearer {key}')

    try:
        with urllib.request.urlopen(request, timeout=TASK_METRIC_GX10_TIMEOUT) as response:
            body = response.read().decode('utf-8', errors='replace')
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger_info(f'task_metric_gx10: счётчики недоступны ({type(e).__name__}: {e})')
        return {}

    return _counters_parse(body)


def task_metric_gx10_delta(before: dict, after: dict) -> dict:
    """
    Что модель сделала между двумя снимками.

    Returns: `{'tokens_output', 'tokens_prompt', 'tokens_per_sec'}`. Любого снимка
        нет — нули: замер не состоялся.

    Отрицательную дельту отбрасываем в ноль. Она означает перезапуск сервера
    модели между снимками — счётчики начались заново, и разница по ним
    бессмысленна.
    """
    if not before or not after:
        return {'tokens_output': 0, 'tokens_prompt': 0, 'tokens_per_sec': 0.0}

    tokens = max(0, int(after.get('tokens_output', 0) - before.get('tokens_output', 0)))
    prompt = max(0, int(after.get('tokens_prompt', 0) - before.get('tokens_prompt', 0)))
    seconds = max(0.0, after.get('gen_seconds', 0.0) - before.get('gen_seconds', 0.0))

    return {
        'tokens_output': tokens,
        'tokens_prompt': prompt,
        # Делим на время генерации, а не на длительность шага: шаг включает и
        # чтение промпта, и ожидание, а скорость — это про то, как быстро модель
        # пишет. Секунд ноль — писать было нечего, и скорость не определена.
        'tokens_per_sec': round(tokens / seconds, 2) if seconds > 0 else 0.0,
    }


def _counters_parse(body: str) -> dict:
    """
    Значения нужных счётчиков из ответа Prometheus. Ни одного не нашлось — `{}`.

    Разбираем построчно, а не регулярным выражением по всему тексту: формат
    простой («имя значение»), а строк в ответе сотни, и половина — комментарии
    `# HELP` с теми же именами внутри.
    """
    wanted = {name: key for key, name in TASK_METRIC_GX10_COUNTERS.items()}
    found = {}

    for line in body.splitlines():
        if line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 2 or parts[0] not in wanted:
            continue
        try:
            found[wanted[parts[0]]] = float(parts[1])
        except ValueError:
            continue

    return found if len(found) == len(TASK_METRIC_GX10_COUNTERS) else {}

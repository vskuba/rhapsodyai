"""
Пересказ ответа шага для журнала подзадачи — вместо обрезки по символам.

Зачем. Журнал режет длинный ответ по потолку и ставит многоточие. Обрезка не знает,
что в тексте важно: у вердикта QA первым абзацем идёт преамбула, а перечень
непройденного оказывается за потолком и пропадает целиком. Следующий круг читает
журнал, чтобы не переделывать сделанное, — и не находит там главного.

Пересказ выбирает по смыслу: модель видит весь ответ и оставляет суть, конкретику
и причину затыка. Работа ровно того рода, который отдают локальной модели —
объёмная, механическая, и весь нужный контекст помещается в один промпт.

Платить за это не приходится: агент `task_log_summarizer` сидит на ноде Dashboard,
а она начинается с локальных gx10. Платные модели там дальше по списку и вступают
только когда GX10 не отвечает.

**Отказ пересказа не является ошибкой.** Модель не ответила, вернула не JSON,
выдала пустоту, превысила бюджет времени — строка просто обрезается по-старому.
Журнал вспомогательный: он не имеет права ни ронять круг, ни задерживать его
надолго. Поэтому здесь нет ни одного `raise` наружу и стоит общий потолок времени
на весь прогон.

Пересказываем только то, что не влезает. Короткий ответ уже и есть суть — звать
для него модель значит платить временем за переписывание готового.

**Вызовы идут порциями и строго по очереди.** Тут сошлись два ограничения, и
каждое из них проверено на живых прогонах.

Первое: LLM зовётся не напрямую. `framework_workflow_run` кладёт модель в общую
очередь `ai_framework_model`, а разбирает её фоновый цикл `ai_thread_framework_run`
— по одному прогону на агента (`node.llm_parallel_per_agent_max` = 1). Пачка
вызовов одного агента поэтому не параллелится: она выстраивается в очередь, и всё,
что не дождалось за `AI_FRAMEWORK_QUEUE_TTL`, отбрасывается молча. Четыре
одновременных вызова дали ровно это: 13.9с, 24.6с, 36.0с и один отброшенный —
работа у каждого была на десять секунд, а ждали они друг друга.

Второе: контекст. `gx10/qwen-small` отвечает на своё окно
`exceed_context_size_error` с `n_ctx: 2048`, и свод из четырёх ответов (2583
токена) в него не влез. Взять модель побольше не выход: `gx10/qwen-large` тот же
свод не осилил за 180 секунд — жёсткий потолок одного LLM-вызова во фреймворке
(`ai_framework.engine_run`), — и прогон умер целиком.

Отсюда форма: длинные ответы круга режутся на порции под контекст маленькой
модели, порции идут последовательно. Порция из двух-трёх блоков укладывается в
десяток секунд, и весь круг обходится дешевле, чем одна попытка объять его
целиком.

Цикл-потребитель живёт в процессе приложения: `main_uvicorn` и воркеры поднимают
его при старте. Журнал пишет `worker_task` — там цикл есть. А вот отдельный
`docker exec python3 -c ...` его не поднимает: модель уйдёт в очередь, забирать её
будет некому, и вызов честно провисит до таймаута. Проверять пересказ надо на
живом круге или изнутри процесса, где цикл запущен.
"""
import asyncio
import uuid

from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from src.ai.ai_llm import ai_llm_node_get
from src.ai.ai_workflow import (ai_workflow_load, ai_workflow_variables_base,
                                ai_workflow_variables_defaults_apply)
from src.ai.framework.agent.ai_framework_manager import AiFrameworkAgentManager
from src.mysql_.repository.agent_repository import AgentRepository

TASK_LOG_SUMMARY_AGENT_NAME = 'task_log_summarizer'

# Кому приписан прогон. Пересказ идёт от имени системы, живого человека за ним нет.
TASK_LOG_SUMMARY_USER_ID = 1

# Потолок на одну порцию. Замеренная порция укладывается в 10-25 секунд; 90 —
# запас на случай, когда GX10 занят прогонами конвейера. Выше поднимать нельзя:
# сам фреймворк рвёт LLM-вызов на 180 секундах (`ai_framework.engine_run`), и
# ждать дольше значит ждать заведомо мёртвого.
TASK_LOG_SUMMARY_TIMEOUT = 90.0

# Потолок на все порции круга вместе. Журнал дописывается после работы круга и
# никого не держит, но и растягивать это на десять минут незачем: не успели —
# оставшиеся строки уйдут обрезкой, как раньше.
TASK_LOG_SUMMARY_BUDGET = 300.0

# Сколько блоков отдаём за раз. Больше — не про нагрузку, а про осмысленность:
# столько длинных шагов в одном круге не бывает, и такой круг лучше отдать
# обрезкой, чем ждать пересказ простыни.
TASK_LOG_SUMMARY_BLOCKS_MAX = 12

# Размер порции. Контекст маленькой модели — 2048 токенов на запрос, из них часть
# съедает сам промпт с правилами. 3500 символов содержимого — это примерно 1200
# токенов: помещается с запасом на разметку блоков и на ответ.
TASK_LOG_SUMMARY_CHUNK_MAX = 3500

# Сколько берём от одного ответа. Один многословный шаг не должен вытеснить
# соседей из порции; по началу ответа суть видна, а хвост её почти не меняет.
TASK_LOG_SUMMARY_BLOCK_MAX = 1800


async def task_log_summary_many(items: list, limit: int) -> dict:
    """
    Пересказать длинные ответы круга одним вызовом. Ключ результата — `item['key']`.

    Args:
        items: `[{'key', 'title', 'kind', 'text'}]` — что сжимать. `kind` это
            «сделал» или «затык»: у затыка на первом месте должна оказаться
            причина, и модель об этом надо предупредить.
        limit: потолок строки журнала в символах.

    Returns: `{key: пересказ}` только для удавшихся. Не вышло — `{}`, и вызывающий
        обрезает по-старому. Отсутствие ключа и есть «не вышло»: отдельного
        признака неудачи нет, потому что реакция на неё одна.
    """
    if not items:
        return {}
    if len(items) > TASK_LOG_SUMMARY_BLOCKS_MAX:
        logger_info(f'task_log: пересказ пропущен, длинных шагов {len(items)} — больше потолка')
        return {}

    try:
        agent, llms, workflow = await _agent_load()
    except Exception as e:
        logger_info(f'task_log: пересказ недоступен: {type(e).__name__}: {e}')
        return {}

    result   = {}
    deadline = asyncio.get_running_loop().time() + TASK_LOG_SUMMARY_BUDGET
    for chunk in _chunks_split(items):
        # Бюджет проверяем перед порцией, а не после: начатую не бросаем, но и
        # новую не начинаем — иначе последняя порция утянула бы за потолок.
        if asyncio.get_running_loop().time() >= deadline:
            logger_info('task_log: бюджет пересказа исчерпан, остальные строки обрежем')
            break

        answer = await _run(agent, llms, workflow, _blocks_build(chunk), len(chunk), limit)
        # Номера блоков модель возвращает от единицы внутри порции, а ключи у
        # вызывающего свои — сопоставляем по позиции в порции.
        for number, text in _answer_parse(answer, limit).items():
            if 1 <= number <= len(chunk):
                result[chunk[number - 1]['key']] = text

    logger_info(f'task_log: пересказано шагов {len(result)} из {len(items)}')

    return result


def _chunks_split(items: list) -> list:
    """
    Разложить блоки по порциям, влезающим в контекст модели.

    Порция набирается жадно: пока помещается — добавляем. Один блок, который не
    помещается и сам по себе, всё равно уходит своей порцией: он уже урезан по
    `TASK_LOG_SUMMARY_BLOCK_MAX`, и выбросить его значило бы отдать строку
    обрезкой при живой модели.
    """
    chunks, current, size = [], [], 0
    for item in items:
        length = len(str(item.get('text') or ''))
        if current and size + length > TASK_LOG_SUMMARY_CHUNK_MAX:
            chunks.append(current)
            current, size = [], 0
        current.append(item)
        size += length
    if current:
        chunks.append(current)

    return chunks


async def _agent_load() -> tuple[dict, list, dict]:
    """Агент пересказа, его модели и шаги workflow. Чего-то нет — исключение."""
    agent = await AgentRepository().find_one_by({'name': TASK_LOG_SUMMARY_AGENT_NAME})
    if not agent:
        raise RuntimeError(f'агент {TASK_LOG_SUMMARY_AGENT_NAME!r} не найден')
    if not agent.get('workflow_id'):
        raise RuntimeError(f'у агента {TASK_LOG_SUMMARY_AGENT_NAME!r} не задан workflow')

    llms = await ai_llm_node_get(agent.get('node_id'))
    if not llms:
        raise RuntimeError(f'у ноды агента {TASK_LOG_SUMMARY_AGENT_NAME!r} нет LLM-моделей')

    return agent, llms, await ai_workflow_load(agent['workflow_id'])


def _blocks_build(items: list) -> str:
    """
    Блоки порции — в один пронумерованный текст для промпта.

    Каждый ответ режется по своему потолку: один многословный шаг иначе вытеснил
    бы из порции соседей. Размер порции целиком держит `_chunks_split` — он и
    отвечает за то, чтобы промпт влез в контекст модели.
    """
    parts = []
    for number, item in enumerate(items, 1):
        text = ' '.join(str(item.get('text') or '').split())[:TASK_LOG_SUMMARY_BLOCK_MAX]
        if not text:
            continue
        parts.append(f"=== {number} · Шаг: {item.get('title') or 'шаг'} · "
                     f"Исход: {item.get('kind') or 'сделал'} ===\n{text}")

    return '\n\n'.join(parts)


async def _run(agent: dict, llms: list, workflow: dict, blocks: str, count: int, limit: int) -> str:
    """
    Один прогон workflow пересказа. Любая беда — пустая строка, наружу ничего не летит.

    Ловим всё подряд намеренно. Причин отказа много и они разные — модель не
    ответила, ответила не-JSON, провайдер отдал ошибку, очередь отбросила по TTL, —
    а реакция на них одна: обрезать строки по-старому. Разбирать их по видам
    значило бы писать ветки, сходящиеся в одну точку.
    """
    session_uuid = str(uuid.uuid4())
    wf_vars = {
        **ai_workflow_variables_base(
            prompt_user=blocks,
            user_id=TASK_LOG_SUMMARY_USER_ID,
            entity_agent=agent,
            session_uuid=session_uuid,
            workflow_id=agent['workflow_id'],
        ),
        'log_blocks':       blocks,
        'log_blocks_count': str(count),
        'log_step_limit':   str(limit),
    }
    ai_workflow_variables_defaults_apply(wf_vars, workflow['variables'])

    loop   = asyncio.get_running_loop()
    future = loop.create_future()
    manager = AiFrameworkAgentManager()
    model = await manager.framework_model_create({
        'entity_agent':       agent,
        'entities_llm':       llms,
        'workflow_steps':     workflow['steps'],
        'workflow_variables': wf_vars,
        'prompt_user':        blocks,
        'user_id':            TASK_LOG_SUMMARY_USER_ID,
        'companion_id':       None,
        'session_uuid':       session_uuid,
        'tools':              {},
    })
    running = manager.framework_workflow_run(model, future, loop)

    try:
        return await asyncio.wait_for(future, timeout=TASK_LOG_SUMMARY_TIMEOUT)
    except Exception as e:
        # Брошенный future сам workflow не останавливает: он продолжит идти по
        # шагам уже никому не нужный. Гасим явно — так же, как это делают роли.
        running.cancel()
        future.cancel()
        logger_info(f'task_log: пересказ не вышел: {type(e).__name__}: {e}')
        return ''


def _answer_parse(answer, limit: int) -> dict:
    """
    Ответ workflow -> `{номер блока: строка}`. Не разобралось — пустой словарь.

    Терпимо к форме: модель кладёт список то под `lines`, то прямо под ключом
    ответа, а номер называет то `n`, то `number`. Годный пересказ терять из-за
    формы обидно — он уже стоил минуты ожидания.

    Длину режем сами: модель просили не превышать потолок, но просьба это не
    гарантия. Обрезка тут уже не потеря смысла — сжатый текст плотный, и лишнее у
    него в хвосте, а не в середине.
    """
    raw = str(answer or '').removeprefix('json:').strip()
    if not raw:
        return {}

    parsed = json_from_string(raw)
    if not isinstance(parsed, dict):
        return {}

    inner = parsed.get('log_summary_json', parsed)
    if isinstance(inner, dict):
        inner = inner.get('lines', inner)
    if not isinstance(inner, list):
        return {}

    lines = {}
    for position, row in enumerate(inner, 1):
        if isinstance(row, str):
            number, text = position, row
        elif isinstance(row, dict):
            number = row.get('n', row.get('number', position))
            text = row.get('text', '')
        else:
            continue
        text = ' '.join(str(text or '').split())[:limit]
        if text and str(number).lstrip('-').isdigit():
            lines[int(number)] = text

    return lines

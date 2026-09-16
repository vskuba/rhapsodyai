import re

from typing import Any

from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Условный блок в шаблонах: %if var%...%else%...%endif% (с отрицанием %if !var%).
# Регулярка матчит только ВНУТРЕННИЕ блоки (содержимое без вложенных %if) —
# вложенность разрешается повторными проходами изнутри наружу.
WORKFLOW_IF_BLOCK_RE = re.compile(
    r'%if (!?)(\w+)%'
    r'((?:(?!%if ).)*?)'
    r'(?:%else%((?:(?!%if ).)*?))?'
    r'%endif%',
    re.DOTALL
)


def ai_workflow_variables_agent_get(entity_agent: dict) -> dict:
    """Переменные агента — словарь из колонки `agent.agent_variable` (JSON).

    Чем отличаются от `agent.workflow_variable`: те задают **вход workflow**, эти —
    подставляются в **системный промпт и приветствие самого агента**. Разница
    видна на сотне собеседниц, живущих на одном `dating_talk`: раньше каждой
    заводили своего агента только потому, что в промпте стоит её имя, — сто
    записей с одинаковым текстом. С переменной агента запись одна: в промпте
    `%girl_name%`, а значение приходит из `agent.agent_variable` (умолчание) или
    из переменных запроса (конкретная анкета).

    Значения попадают в общий scope workflow — шаг читает `%girl_name%` наравне
    с остальными переменными, отдельного пространства имён у них нет.

    Битый JSON — не повод ронять запрос: агент ответит с нераскрытым `%имя%` в
    промпте, и это заметнее и безопаснее, чем 500 на ровном месте.
    """
    raw = entity_agent.get('agent_variable')
    if not raw:
        return {}

    variables = json_from_string(raw)
    if not variables:
        logger_info(f"⚠️ agent_variable агента '{entity_agent.get('name')}' не разобран как JSON: {raw!r}")
        return {}

    return {str(name).strip(): value for name, value in variables.items() if str(name).strip()}


def ai_workflow_variables_base(
        *,
        prompt_user: str,
        user_id: int,
        entity_agent: dict,
        session_uuid: str,
        workflow_id: int,
        user_username: str = '',
        user_email: str = '',
        companion_id: int | None = None,
        companion_name: str = '',
        companion_title: str = '',
) -> dict:
    """
    Единый набор базовых переменных workflow — имена соответствуют глобальным
    переменным (agent_workflow_variable type='global'). Единственный источник
    этих имен: используется всеми точками входа (веб-чат, переводчик и т.д.),
    чтобы правки не приходилось дублировать по копиям словаря.

    Переменные агента (`agent.agent_variable`) кладутся **под** базовыми: собственное
    имя вроде `agent_title` в переменных агента не должно подменять базовое —
    глобальные имена одинаковы во всех workflow, и workflow на них рассчитывает.
    """
    return {
        **ai_workflow_variables_agent_get(entity_agent),
        'prompt_user': prompt_user,
        'user_id': user_id,
        'user_username': user_username,
        'user_email': user_email,
        'companion_id': companion_id,
        'companion_name': companion_name,
        'companion_title': companion_title,
        'agent_id': entity_agent.get('id'),
        'agent_name': entity_agent.get('name'),
        'agent_title': entity_agent.get('title'),
        'agent_greeting': entity_agent.get('greeting'),
        'session_uuid': session_uuid,
        'workflow_id': workflow_id,
        'node_id': entity_agent.get('node_id'),
    }


def ai_workflow_variables_defaults_apply(variables: dict, raw_variables: list[dict]) -> dict:
    """Дозаполняет scope default-значениями переменных workflow (не перезаписывая уже заданные).

    ⚠⚠ **Пустое умолчание — пустая строка, а не `None`.** Здесь стояло
    `v.get('default')`, и переменная без умолчания попадала в scope со значением
    `None`. Подстановка делает `str(None)`, и в промпт уходит **слово «None»**:

        === Метки в тексте ===
        None

    Это опаснее оставшейся метки. Метка выглядит поломкой, и её замечают; а «None»
    читается как осмысленное указание — модель честно исполняет его и отвечает
    правдоподобно. В журнале всё зелено, ответ построен на слове, которого никто
    не писал.

    Поймано на инвайтах: вызов без `invite_slots` получал «None» вместо списка
    меток — и, по случайности, ответ выходил похожим на правильный («никаких
    меток»), поэтому беда не всплывала.

    ⚠ Пустая строка, а не пропуск переменной: под `%if var%` она читается как
    «ложь» и прячет секцию целиком — то самое поведение, которого от незаданной
    переменной и ждут.
    """
    for v in raw_variables:
        v_name = (v.get('name') or '').strip()
        if v_name and v_name not in variables:
            value = v.get('default')
            variables[v_name] = '' if value is None else value
    return variables


async def ai_workflow_load(workflow_id: int) -> dict:
    """Загружает workflow для выполнения: сущность workflow, нормализованные шаги
    (metadata распарсен, строки очищены от пробелов CHAR-типа) и переменные
    с default-значениями.
    Используется точкой входа chat.py и шагом workflow_invoke (sub-workflow)."""
    sql_workflow = "SELECT * FROM agent_workflow WHERE id = %s"
    sql_steps = """
        SELECT ws.*, wst.name as step_type_name
        FROM agent_workflow_step ws
        LEFT JOIN agent_workflow_step_type wst ON ws.type_id = wst.id
        WHERE ws.workflow_id = %s
        ORDER BY ws.position ASC
    """
    sql_vars = """
        SELECT v.name, v.`default`
        FROM agent_workflow_variable v
        JOIN agent_workflow_variable_workflow vw ON v.id = vw.variable_id
        WHERE vw.workflow_id = %s
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql_workflow, (workflow_id,))
        workflow_row = await db.fetchone()

        await db.execute(sql_steps, (workflow_id,))
        raw_steps = await db.fetchall()

        await db.execute(sql_vars, (workflow_id,))
        raw_variables = await db.fetchall()

    steps = []
    for step in raw_steps:
        steps.append({
            "id": step.get('id'),
            "step_type_name": step.get('step_type_name', '').strip(),
            "title": step.get('title', '').strip(),
            "metadata": json_from_string(step.get('metadata', {}))
        })

    return {"workflow": workflow_row or {}, "steps": steps, "variables": list(raw_variables)}


async def ai_workflow_variables_global_get() -> list[dict]:
    sql = """
        SELECT v.*
        FROM agent_workflow_variable v
        WHERE v.type = 'global'
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql)
        return await db.fetchall()


async def ai_workflow_variables_node_get(node_id: int) -> list[dict]:
    # Переменные ноды (включая proxy) — порядок по position важен: переменная
    # ниже по списку может ссылаться на %переменные% выше и должна получить их
    # уже раскрытыми, а не сырым шаблоном
    sql = """
        SELECT v.*
        FROM node_variable v
        WHERE v.node_id = %s
        ORDER BY v.position ASC, v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (node_id,))
        return await db.fetchall()


async def ai_workflow_variables_input_get(workflow_id: int) -> list[dict]:
    sql = """
        SELECT v.*
        FROM agent_workflow_variable v
        LEFT JOIN agent_workflow_variable_workflow vw ON v.id = vw.variable_id
        WHERE v.type = 'input' AND vw.workflow_id = %s
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        return await db.fetchall()


def ai_workflow_variable_truthy(variables: dict, name: str) -> bool:
    """Истинность переменной для %if%: существует и значение не пустое,
    не '0' и не 'false' ('0' — принятый в workflow сигнал «ничего нет»)."""
    value = variables.get(name)
    if value is None:
        return False
    return str(value).strip().lower() not in ('', '0', 'false')


def ai_workflow_if_blocks_render(source: str, variables: dict) -> str:
    """Разворачивает условные блоки %if var%...%else%...%endif% в строке шаблона.

    Условие проверяется по словарю переменных ДО подстановки %переменных%:
    блок остается (или берется ветка else) в зависимости от истинности переменной.
    %if !var% — отрицание. Вложенные блоки поддерживаются (изнутри наружу).
    Незакрытый/некорректный блок остается в тексте как есть."""

    def replace(match: re.Match) -> str:
        negate, name, then_text, else_text = match.groups()
        condition = ai_workflow_variable_truthy(variables, name)
        if negate:
            condition = not condition
        return then_text if condition else (else_text or '')

    while '%if ' in source:
        rendered = WORKFLOW_IF_BLOCK_RE.sub(replace, source)
        if rendered == source:
            break
        source = rendered
    return source


# Метка переменной в промпте: `%имя%`. ⚠ Имя обязано быть **идентификатором** —
# буквы, цифры, подчёркивание, и не с цифры. Без этого сторож ловил бы обычные
# проценты в тексте: «выполнено на 100% сотрудниками и на 0% роботами» между
# двумя `%` содержит пробелы, и идентификатором не является.
WORKFLOW_MARK_RE = re.compile(r'%([a-zA-Z_][a-zA-Z0-9_]*)%')

# Остатки условных блоков. ⚠ Разбираются отдельно от прочих меток: `%endif%` без
# пары — это не «забыли передать переменную», а сломанный блок в самом промпте, и
# чинится он иначе. Сказать об этом надо разными словами.
WORKFLOW_BLOCK_MARKS = ('if', 'else', 'endif')


class AiWorkflowMarkError(RuntimeError):
    """В промпте осталась метка, которой никто не дал значения."""


def ai_workflow_marks_left(text: str) -> list[str]:
    """Метки, пережившие подстановку. Пусто — промпт собран целиком.

    ⚠⚠ **Зачем это нужно, и чего стоило не иметь.** Подстановка заменяет только
    те метки, чьи имена есть в словаре; чужая остаётся в тексте **как есть** — и
    уезжает в LLM словами. Модель читает `%invite_angle%` как часть задания и
    отвечает наугад, а мы видим осмысленный на вид ответ и ничего не замечаем.

    Поймано на живом: у инвайтов промпт ссылался на `%invite_angle%`, переменная
    была заведена типом `workflow` без умолчания — то есть необязательной, — и
    любой вызов, не передавший её, получал в промпте саму метку. Работало только
    потому, что единственный вызывающий её передавал.

    ⚠ **Проверять можно только после подстановки и только на прогоне.** Статически
    это не решается: переменные приходят из четырёх мест, и три невидимы из базы —
    запрос клиента, переменные узла и результаты предыдущих шагов
    (`{инструмент}_{шаг}_result_{ключ}`). Замер по живой базе: статическая проверка
    объявила бы сломанными 26 workflow из 66, почти все — ложно.
    """
    return [name for name in WORKFLOW_MARK_RE.findall(str(text or ''))
            if name not in WORKFLOW_BLOCK_MARKS]


def ai_workflow_marks_check(text: str, where: str = '') -> None:
    """Бросает `AiWorkflowMarkError`, если в тексте осталась метка без значения.

    Args:
        text: промпт **после** подстановки.
        where: чей это промпт — имя шага. Уходит в текст ошибки: без него человек
            ищет метку по всему workflow глазами.

    ⚠ **Отказ, а не предупреждение.** Промпт с меткой словами даёт правдоподобный
    на вид ответ — и тем опасен: в журнале всё зелено, а работа испорчена. У
    инвайтов такой шаблон уходит полусотне живых людей разом.
    """
    left = ai_workflow_marks_left(text)
    if not left:
        return

    names = ', '.join(f'%{one}%' for one in dict.fromkeys(left))
    raise AiWorkflowMarkError(
        f'в промпте шага «{where or "?"}» остались метки без значения: {names}. '
        f'Передайте переменную в запросе либо задайте ей умолчание в реестре — '
        f'иначе метка уйдёт в LLM словами, и ответ будет построен на ней как на '
        f'части задания.')


def ai_workflow_variables_render(source: Any, variables: dict) -> Any:
    """ Рекурсивно подставляет значения %переменных% во все строки метаданных """
    if isinstance(source, str):
        # Быстрая проверка: если в строке нет знака %, пропускаем циклы
        if "%" not in source:
            return source

        # Сначала разворачиваем условные блоки, затем подставляем переменные
        rendered_str = ai_workflow_if_blocks_render(source, variables)
        for key, val in variables.items():
            placeholder = f"%{key}%"

            # Умная замена типов: если строка состоит ТОЛЬКО из плейсхолдера (н-р, "%id%")
            # возвращаем исходный тип значения (int, bool, list и т.д.), а не строку
            if rendered_str == placeholder:
                return val

            if placeholder in rendered_str:
                rendered_str = rendered_str.replace(placeholder, str(val))
        return rendered_str

    elif isinstance(source, dict):
        # Теперь рекурсивный вызов работает правильно
        return {k: ai_workflow_variables_render(v, variables) for k, v in source.items()}

    elif isinstance(source, list):
        # Теперь рекурсивный вызов работает правильно
        return [ai_workflow_variables_render(item, variables) for item in source]

    return source


def ai_workflow_text_render(source: Any, variables: dict) -> str:
    """То же, что `ai_workflow_variables_render`, но результат всегда строка.

    Нужен там, где шаблон — текст для модели (системный промпт, приветствие), а
    не значение переменной. У общего рендера есть «умная замена типов»: строка
    ровно из одного плейсхолдера возвращает исходное значение с его типом — и
    промпт `%girl_prompt%` уехал бы в движок списком или числом. `None`
    превращаем в пустую строку, а не в текст «None».
    """
    rendered = ai_workflow_variables_render(source, variables)
    if rendered is None:
        return ''

    return rendered if isinstance(rendered, str) else str(rendered)

import re

from typing import Any

from json_.json_ import json_from_string
from logging_.logging_ import logger_info
from mysql_.mysql_ import mysql_get_db_async

# Условный блок в шаблонах: `[<if var>]…[<else>]…[<endif>]`, отрицание —
# `[<if !var>]`.
#
# ## ⚠⚠ Почему синтаксис сменился с `%if var%…%endif%`
#
# Прежний делил проценты с метками переменных, и страдали обе стороны:
#
#     %if var%      начинается как метка, меткой не является
#     %endif%       то же — и попадал в улов сторожа
#
# Разборщику приходилось держать список «слова разметки, которые выглядят
# переменной» (`if`, `else`, `endif`) и вычитать его из улова меток — и то же самое
# повторяла подсветка в редакторе. Два места, знающих один список, расходятся.
#
# Теперь они не пересекаются вовсе: `[<…>]` — управление, `%…%` — подстановка.
#
# ⚠ Внутри условия имя пишется **без процентов**, и это не небрежность: проценты
# означают «сюда встанет значение», а условие значение не вставляет — оно его
# проверяет. `[<if var>]` читается «если var истинна», `%var%` — «здесь будет var».
#
# ## ⚠⚠ Почему `[<…>]`, а не `[[…]]`
#
# Двойные квадратные скобки были взяты первыми и прожили полдня. Они **уже заняты**,
# причём дважды, и оба места — живые:
#
#     [[Создать проект]]   чипса чата (кнопка под ответом агента), chat.html
#     [[firstName]]        метка переменной письма в DatingAi, src/dating/mail.py
#
# ⚠⚠⚠ Первое опаснее. `MESSAGE_TOKEN_REGEX` в `chat.html` ловит **любое** `[[…]]`,
# и неразвёрнутый блок показался бы человеку **кнопкой**: `[[if var]]` — кнопкой
# «if var», по щелчку отправляющей эти слова агенту как реплику. А отрицание
# `[[!var]]` попадает в ветку `[[!текст]]` — «опасное действие», то есть **красную**
# кнопку. Промпт с ошибкой превращался бы не в мусор на экране, а в предложение
# нажать.
#
# Второе — тот же вид записи с двумя смыслами в одном тексте: промпт шага «Что не
# так» одновременно содержит условие блока и просьбу к модели «вставь метку
# `[[имя]]`».
#
# Различать их по содержимому нельзя: `endif` — законное имя переменной письма.
# Поэтому скобки разведены **видом**, а не списком исключений.
#
# ⚠ Отсюда правило на будущее: разметку узнаём по **слову вместе со скобками**
# (`[<if `, `[<else>]`, `[<endif>]`), никогда по одним скобкам. Проверка «есть ли
# здесь наша разметка», написанная как «есть ли `[<`», завтра поймает чужое.
#
# ⚠ Регулярка матчит только ВНУТРЕННИЕ блоки (содержимое без вложенных `[<if`) —
# вложенность разрешается повторными проходами изнутри наружу.
#
# ⚠⚠⚠ Условие — «любой знак, кроме `>` перед `]` и кроме `[`». Ни «всё кроме
# `>`», ни нежадное `.+?` здесь не годятся, и обе ошибки были сделаны:
#
#     [^>]+     ломает сравнение: `[<if count > 5>]` обрывается на первом `>`
#     .+?       перескакивает через `>]` к следующему и съедает чужой блок —
#               на `[<if a>][<if count > 5>]…` условием становилось
#               `a>][<if count > 5`, а внешний блок пропадал целиком
#
# `>` разрешён, только если за ним не `]`: тогда `count > 5` читается условием,
# а `a>]` закрывает блок. Запрет `[` держит условие внутри своего блока.
WORKFLOW_IF_BLOCK_RE = re.compile(
    r'\[<if ((?:[^>\[]|>(?!\]))+)>\]'
    r'((?:(?!\[<if ).)*?)'
    r'(?:\[<else>\]((?:(?!\[<if ).)*?))?'
    r'\[<endif>\]',
    re.DOTALL
)

# Начало блока — им же цикл разворачивания решает, есть ли ещё работа.
WORKFLOW_IF_OPEN = '[<if '

# Операторы сравнения. ⚠⚠ Порядок в списке = порядок поиска, и двухсимвольные
# обязаны стоять раньше: иначе `>=` разберётся как `>` со значением `=5`.
WORKFLOW_COMPARE_OPERATORS = ('==', '!=', '>=', '<=', '>', '<')

# Имя переменной. ⚠ Тот же вид, что у метки `%имя%`: буквы, цифры, подчёркивание,
# не с цифры. Им же справа от оператора отличают переменную от числа.
WORKFLOW_NAME_RE = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')

# Связки условия. ⚠ Разделитель — слово **в окружении пробелов**: `\bor\b`
# поймал бы `oregon`, а имя переменной пробелов не содержит.
WORKFLOW_OR_RE = re.compile(r'\s+or\s+')
WORKFLOW_AND_RE = re.compile(r'\s+and\s+')

# Атом условия: `!var`, `var`, `var <оп> значение`.
#
# ⚠ Значение берётся «всё до конца атома» и может быть в кавычках — иначе
# `[<if name == John Smith>]` оборвался бы на пробеле. Кавычки снимаются в
# `_condition_value_clean`.
#
# ⚠⚠ Список операторов берётся из константы, а не повторяется строкой: иначе
# добавленный в список `<>` работал бы в переходах и молча не работал в блоках.
WORKFLOW_IF_ATOM_RE = re.compile(
    r'^(!?)([a-zA-Z_][a-zA-Z0-9_]*)'
    r'(?:\s*(' + '|'.join(re.escape(one) for one in WORKFLOW_COMPARE_OPERATORS)
    + r')\s*(.*))?$',
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
) -> dict:
    """
    Единый набор базовых переменных workflow — имена соответствуют глобальным
    переменным (agent_workflow_variable type='global'). Единственный источник
    этих имен: используется всеми точками входа (веб-чат, переводчик и т.д.),
    чтобы правки не приходилось дублировать по копиям словаря.

    Переменные агента (`agent.agent_variable`) кладутся **под** базовыми: собственное
    имя вроде `agent_title` в переменных агента не должно подменять базовое —
    глобальные имена одинаковы во всех workflow, и workflow на них рассчитывает.

    ⚠ Собеседника здесь **больше нет** (`companion_id/name/title` убраны из
    подстановки). Он не дело всех workflow: где троица нужна, она объявлена
    входящей, и её полным списком присылает вызывающий — чат стейтлесс.
    """
    return {
        **ai_workflow_variables_agent_get(entity_agent),
        'prompt_user': prompt_user,
        'user_id': user_id,
        'user_username': user_username,
        'user_email': user_email,
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

    ⚠ Пустая строка, а не пропуск переменной: под `[<if var>]` она читается как
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
        WHERE v.workflow_id = %s
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


# Тип переменной ноды, который человек настраивает сам. Второй — `proxy`,
# служебный псевдоним: его значение подставляет другую переменную
# (`girl_title` = `%prompt_user%`), и предлагать его в списке «на что сослаться и
# что настроить» незачем. Подробности — `workflow.md` §3.0a.
#
# ⚠⚠ Живёт у движка, рядом с `ai_workflow_variables_node_get`: словарь колонки
# `node_variable.type` — его знание. Читают его двое — роутер переменных и сбор
# индекса «Undefined переменные», — и двух копий строки `'public'` им не нужно.
WORKFLOW_VARIABLE_NODE_PUBLIC = 'public'


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
        WHERE v.type = 'input' AND v.workflow_id = %s
        ORDER BY v.name ASC
    """
    async with mysql_get_db_async() as db:
        await db.execute(sql, (workflow_id,))
        return await db.fetchall()


def ai_workflow_variable_truthy(variables: dict, name: str) -> bool:
    """Истинность переменной для `[<if …>]`: существует и значение не пустое,
    не '0' и не 'false' ('0' — принятый в workflow сигнал «ничего нет»)."""
    value = variables.get(name)
    if value is None:
        return False
    return str(value).strip().lower() not in ('', '0', 'false')


def ai_workflow_variable_compare(variables: dict, name: str, operator: str,
                                 value) -> bool | None:
    """Сравнить переменную с готовым значением. `None` — переменной нет.

    Args:
        variables: словарь переменных прогона.
        name: имя переменной.
        operator: один из `WORKFLOW_COMPARE_OPERATORS`.
        value: **готовое значение** справа. ⚠ Имя переменной здесь уже не
            различают: кто сравнивает две переменные, подставляет вторую сам
            (`_condition_value_resolve`), а переходы кладут константу поля.

    ## ⚠⚠ Одно правило на переходы и на `[<if …>]`

    Сравнение жило в `_transition_condition_check` (`ai_framework_manager.py`) и
    было приватным методом менеджера. Когда условные блоки научились сравнивать,
    второе такое же правило рядом означало бы, что `>` в переходе и `>` в блоке
    однажды разойдутся молча. Теперь оно здесь — там, где уже лежит знание о
    переменных (`ai_workflow_variable_truthy`), а менеджер зовёт эту функцию.

    ## ⚠⚠ Числа сравниваются числами, остальное — строками

    `str(10) > str(5)` лексикографически **ложь**: «1» меньше «5». Поэтому обе
    стороны пробуются как `float`, и только если не вышло — сравниваются как
    текст.

    ## ⚠ `exists`, `empty` и `not_empty` работают и для отсутствующей переменной

    Они спрашивают про сам факт наличия, поэтому проверяются до возврата
    `None`. Остальным операторам без значения ответить нечем.

    ## ⚠⚠ `not_empty` — не то же самое, что `!= ''`

    Разница ровно в отсутствующей переменной. `!= ''` на ней отдаёт `None`,
    то есть «не знаю»: переход такое пропускает с предупреждением, а условный
    блок остаётся в тексте и достаётся сторожу меток. `not_empty` отвечает
    `False` — «непустой она быть не может, раз её нет вовсе», и ветка честно
    не срабатывает.

    ⚠ Отсюда и правило выбора: `!= ''` годится там, где переменная заведомо
    заведена (её кладёт шаг выше), `not_empty` — там, где её может не быть:
    результат пропущенного шага, выход подпотока, вход, который не прислали.
    """
    exists = name in variables
    current = variables.get(name)
    empty = not exists or current is None or str(current).strip() == ''

    if operator == 'exists':
        return exists

    if operator == 'empty':
        return empty

    if operator == 'not_empty':
        return not empty

    if not exists:
        return None

    if operator == 'contains':
        return str(value) in str(current)

    if operator == 'not_contains':
        return str(value) not in str(current)

    if operator == 'regex':
        try:
            return re.search(str(value), str(current)) is not None
        except re.error as e:
            logger_info(f"⚠️ Некорректное регулярное выражение '{value}': {e}")

            return False

    left, right = str(current), str(value)

    try:
        left, right = float(left), float(right)
    except (ValueError, TypeError):
        pass

    return (
        operator == '==' and left == right
        or operator == '!=' and left != right
        or operator == '>' and left > right
        or operator == '<' and left < right
        or operator == '>=' and left >= right
        or operator == '<=' and left <= right
    )


def ai_workflow_condition_check(expression: str, variables: dict) -> bool | None:
    """Истинность условия блока `[<if …>]`. `None` — выражение не разобралось.

    Args:
        expression: то, что стоит между `[<if ` и `>]`.
        variables: словарь переменных прогона.

    Понимает четыре вида записи:

        var                   истинность переменной (пусто, `0`, `false` — ложь)
        !var                  отрицание
        var <оп> что-то       сравнение: == != > < >= <=
        A and B,  A or B      связки, `and` связывает сильнее `or`

    ⚠⚠ Справа кавычки решают, слово это или переменная — см.
    `_condition_value_resolve`:

        kind == 'chat'        слово «chat»
        kind == other         значение переменной `other`

    ## ⚠⚠ `None` — не «ложь», а «я это не понял»

    Вызывающий обязан различать: при ложном условии блок исчезает, при
    неразобранном — **остаётся в тексте как есть** и ловится сторожем
    (`ai_workflow_marks_check`). Верни мы здесь `False`, опечатка в условии
    молча съедала бы кусок промпта, и заметить это было бы нечем.

    ## ⚠⚠ Справа кавычки решают: слово или переменная

    `[<if kind == 'chat'>]` сравнивает со словом «chat»,
    `[<if kind == other>]` — со значением переменной `other`. Кавычки любые,
    одинарные и двойные равны. Разбор — `_condition_value_resolve`.

    ⚠ Переходы устроены иначе: `value` в них всегда константа. Там правило
    выбирает человек в поле формы, и путать нечего, а здесь запись одна.

    ## ⚠ Связки ищутся только в окружении пробелов

    `\\bor\\b` поймал бы `oregon` в середине имени, поэтому разделитель — ровно
    ` or ` и ` and `. Имя переменной пробелов не содержит, так что это не
    ограничение, а защита.
    """
    text = str(expression or '').strip()

    if not text:
        return None

    # ⚠ Все части считаются до ответа, а не по короткому замыканию: нам важно
    # заметить непонятную часть даже справа от истинной. `[<if a or мусор>]`
    # должен достаться сторожу, а не тихо сработать по левой половине.
    parts = [_condition_and_check(one, variables)
             for one in WORKFLOW_OR_RE.split(text)]

    if any(one is None for one in parts):
        return None

    return any(parts)


def ai_workflow_if_blocks_render(source: str, variables: dict) -> str:
    """Разворачивает условные блоки `[<if var>]…[<else>]…[<endif>]` в шаблоне.

    Условие проверяется по словарю переменных **до** подстановки `%переменных%`:
    блок остаётся (или берётся ветка `[<else>]`) по истинности условия.
    Вложенные блоки разворачиваются изнутри наружу.

    Что понимает условие — `ai_workflow_condition_check`: истинность, отрицание
    `!var`, сравнения `== != > < >= <=` и связки `and` / `or`.

    ⚠ Незакрытый или неверно написанный блок остаётся в тексте **как есть** — и
    ловится потом сторожем (`ai_workflow_marks_check`). Молча такое уезжать в LLM
    не должно: модель прочтёт `[<if …>]` как часть задания.

    ## ⚠⚠ Непонятое условие тоже остаётся целиком

    Разборщик отвечает `None` на выражение, которого не понял, и блок уходит в
    текст нетронутым — вместе с `[<endif>]`. Сверни мы его как ложное, опечатка
    (`[<if a && b>]`) молча съедала бы кусок промпта: ни ошибки, ни следа, а
    модель получила бы задание без половины.

    ⚠ Поэтому же цикл считает работу законченной, когда проход ничего не
    изменил: непонятый блок остаётся на месте и зацикливания не создаёт.
    """

    def replace(match: re.Match) -> str:
        expression, then_text, else_text = match.groups()
        condition = ai_workflow_condition_check(expression, variables)

        if condition is None:
            return match.group(0)

        return then_text if condition else (else_text or '')

    while WORKFLOW_IF_OPEN in source:
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

# Остатки условной разметки — сломанный блок. ⚠ Это **не** «забыли передать
# переменную», и чинится иначе, поэтому вид беды отдельный и слова отдельные.
#
# ⚠⚠ Проверка обязательна именно с новым синтаксисом: в `[<…>]` нет процентов, и
# сторож меток такой остаток не видит вовсе. Прежде роль эту играл сам вид `%endif%`
# — он попадал в улов меток и там отбрасывался списком слов разметки.
#
# ⚠ Приметы — **слово вместе со скобками**, а не `[<`: по одним скобкам проверка
# завтра поймает чужой текст.
WORKFLOW_BLOCK_LEFT = ('[<if ', '[<else>]', '[<endif>]')

# Прежние синтаксисы. ⚠⚠ Ловятся **намеренно и отдельным сообщением**: оставь их
# просто неработающими — и старый блок уедет в LLM словами, потому что `%if var%`
# меткой не является (пробел внутри), а `%endif%` прежде отбрасывался как слово
# разметки. То есть промпт собрался бы «успешно» и с мусором.
#
# ⚠ Второй здесь — `[[…]]`, проживший полдня до `[<…>]` (см. шапку файла). В базе
# его быть не должно, миграция перевела всё; примета стоит на случай промпта,
# написанного в тот же день руками.
WORKFLOW_BLOCK_OLD = ('%if ', '%else%', '%endif%', '[[if ', '[[else]]', '[[endif]]')


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
    return list(WORKFLOW_MARK_RE.findall(str(text or '')))


def ai_workflow_blocks_left(text: str) -> list[str]:
    """Остатки условной разметки. Пусто — все блоки развернулись.

    Returns:
        list[str]: что именно осталось — `[<if `, `[<else>]`, `[<endif>]` либо
        приметы прежнего синтаксиса (`%if `, `%endif%`).

    ⚠⚠ Вид беды отдельный от метки без значения. Метка значит «переменную не
    передали», остаток разметки — «блок написан неверно»: не закрыт, перепутаны
    скобки, `[<else>]` без `[<if`. Чинится это в самом промпте, а не в реестре
    переменных, и сказать об этом надо другими словами.
    """
    said = str(text or '')

    return [one for one in WORKFLOW_BLOCK_LEFT + WORKFLOW_BLOCK_OLD if one in said]


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
    # ⚠ Разметка проверяется **первой**: сломанный блок обычно и оставляет метки
    # внутри себя, и сказать надо о причине, а не о следствии.
    blocks = ai_workflow_blocks_left(text)
    if blocks:
        seen = ', '.join(f'«{one}»' for one in blocks)
        old = [one for one in blocks if one in WORKFLOW_BLOCK_OLD]
        hint = ('Это **прежний** синтаксис условного блока. Новый: '
                '`[<if переменная>]…[<else>]…[<endif>]`, отрицание — '
                '`[<if !переменная>]`.' if old else
                'Блок не развернулся: проверьте, что он закрыт `[<endif>]`, а имя '
                'переменной внутри написано без процентов — `[<if имя>]`.')

        raise AiWorkflowMarkError(
            f'в промпте шага «{where or "?"}» осталась условная разметка: {seen}. '
            f'{hint} Неразвёрнутый блок уходит в LLM словами, и модель читает его '
            f'как часть задания.')

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
        # Быстрая проверка: ни метки, ни условного блока — работы нет.
        #
        # ⚠⚠ Проверять один `%` **нельзя**, и это не мелочь. Пока условие писалось
        # `%if var%`, оно само несло процент, и проверка закрывала оба случая
        # случайно. С `[<if var>]` блок, внутри которого нет меток
        # (`[<if test_dialog>]просто текст[<endif>]`), процентов не содержит вовсе —
        # и такая строка возвращалась как есть, то есть уезжала в LLM **вместе с
        # разметкой**. Поймано сюитой в тот же час; в базе такие блоки есть.
        if '%' not in source and WORKFLOW_IF_OPEN not in source:
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


# Шаги, зовущие подпоток. Имя типа шага совпадает с ключом `metadata`, под
# которым лежит вызов (`{"topic_action": {"workflow_id": 76, ...}}`), поэтому
# список служит и отбору по типу, и чтению метаданных.
#
# ⚠⚠ Список заведён потому, что родов стало два, а знавшие о подпотоках места
# знали один. Ручка «Вызывается из» отбирала шаги по подстроке
# `metadata LIKE '%workflow_invoke%'` — и подпоток, который зовёт `topic_action`,
# отвечал «не используется ни одним workflow» про того, кто звал его прямо
# сейчас (`dating_talk_intention` #76, шаг #816). Тем же были слепы
# предупреждение экспорта о чужом подпотоке и сторож неопределённых переменных.
#
# ⚠ Появится третий род — правится здесь, и все трое узнают разом.
WORKFLOW_SUBFLOW_STEP_TYPES = ('workflow_invoke', 'topic_action')

# Ссылки на id шага внутри `metadata` — три вида: число в переходах, строка
# «на всякий случай» и имя переменной результата. Один проход с подстановкой по
# словарю: последовательные `.replace` цепляются друг за друга (25 → 26, а
# потом 26 → 27 перетёрло бы и новое).
_STEP_REF_NUM_RE = re.compile(r'("step_id"\s*:\s*)(\d+)(\s*[,}\]])')
_STEP_REF_STR_RE = re.compile(r'("step_id"\s*:\s*")(\d+)(")')
_STEP_RESULT_RE = re.compile(r'(?<![\d_])_(\d+)(_result)')

# Ссылки шага на чужие записи: номер подпотока и номер группы тем. Число или
# строка — редактор кладёт `parseInt`, но миграции и переносы между базами
# приносят значение, однажды прошедшее через `str()`.
#
# ⚠ Хвост `[,}]` обязателен обеим: без него номер `7` нашёлся бы внутри `76`.
_SUBFLOW_REF_RE = re.compile(r'("workflow_id"\s*:\s*"?)(\d+)("?\s*[,}])')
_TOPIC_GROUP_REF_RE = re.compile(r'("topic_group_id"\s*:\s*"?)(\d+)("?\s*[,}])')


def ai_workflow_step_refs_remap(metadata: str, id_map: dict) -> str:
    """Переписать ссылки на id шагов внутри `metadata` одним проходом по виду ссылки.

    Знание о формах ссылки живёт здесь, а политики у потребителей разные:
    `workflow_duplicate` перенумеровывает шаги всегда (новые id из
    автоинкремента, и они заведомо больше всех старых), импорт сохраняет id
    файла и зовёт remap только при столкновении с чужими записями. Пустой
    словарь — дословно: текст не трогаем нигде, в том числе в шагах, которые
    не разбираются как JSON.
    """
    if not id_map or not metadata:
        return metadata

    def _by_mapping(match_number, match_text):
        old = int(match_number)
        return f'{match_text}{id_map.get(old, old)}'

    metadata = _STEP_REF_NUM_RE.sub(
        lambda m: _by_mapping(m.group(2), m.group(1)) + m.group(3), metadata)
    metadata = _STEP_REF_STR_RE.sub(
        lambda m: _by_mapping(m.group(2), m.group(1)) + m.group(3), metadata)
    metadata = _STEP_RESULT_RE.sub(
        lambda m: f'_{id_map.get(int(m.group(1)), int(m.group(1)))}{m.group(2)}', metadata)
    return metadata


def ai_workflow_step_refs_find(metadata: str) -> set:
    """Номера шагов, на которые `metadata` шага ведёт переходом.

    Знание о форме ссылки живёт здесь, рядом с тем, кто её переписывает
    (`ai_workflow_step_refs_remap`): вторая копия шаблона у спрашивающего
    разошлась бы с этой молча — ссылка не нашлась, значит «никто не ссылается»,
    и ровно этим ответом удаляют шаг.

    ## ⚠⚠ Имя переменной результата ссылкой **не** считается

    Из трёх шаблонов берутся два — `step_id` числом и строкой, — а
    `_STEP_RESULT_RE` (`%..._819_result_str%`) остаётся в стороне, и это
    решение, а не упущение. Висячая цель перехода роняет **весь прогон**:
    движок достаёт индекс цели до проверки условия (`KeyError` на любом заходе
    в шаг). Имя переменной от удаления всего лишь становится неопределённым —
    прогон идёт, а на пропажу указывает свой указатель в редакторе. Запрети мы
    удаление и по имени, шаг нельзя было бы убрать, пока кто-то читает его
    результат, — то есть почти никогда.

    Args:
        metadata: метаданные шага сырой строкой (как лежат в базе).

    Returns:
        set: номера шагов-целей; пустое множество, если переходов нет.
    """
    if not metadata:
        return set()

    return ({int(found.group(2)) for found in _STEP_REF_NUM_RE.finditer(metadata)}
            | {int(found.group(2)) for found in _STEP_REF_STR_RE.finditer(metadata)})


def ai_workflow_subflow_refs_find(metadata: str) -> set:
    """Номера подпотоков, на которые ссылается `metadata` шага.

    Годится обоим родам вызова (`WORKFLOW_SUBFLOW_STEP_TYPES`): номер лежит под
    одним и тем же ключом `workflow_id`, различается лишь ключ-обёртка. Кому
    важен род — отбирает шаги по типу до вызова.

    Returns:
        set: номера подпотоков (пустое множество, если ссылок нет).
    """
    if not metadata:
        return set()

    return {int(found.group(2)) for found in _SUBFLOW_REF_RE.finditer(metadata)}


def ai_workflow_subflow_ref_pattern_sql(workflow_id: int) -> str:
    """Шаблон MySQL `REGEXP`, которым ту же ссылку ищут **в базе**.

    ## ⚠⚠ Почему шаблон строит этот модуль, а не тот, кто спрашивает базу

    Форма ссылки одна, а движка регулярок два: Python (`\\s`) и MySQL
    (`[[:space:]]`). Свести их в один шаблон нельзя — синтаксис разный, — и
    ровно поэтому обе формы обязаны жить у одного владельца: иначе правка
    формы в Python-поиске молча расходится с запросом к базе.

    ⚠ Почему `REGEXP` по тексту, а не `JSON_EXTRACT`: в таблице есть строки с
    невалидным JSON (`response_soko`, `response_cashier`, `test`), и
    `JSON_EXTRACT` в `WHERE` упал бы на них целиком — ответ стал бы отказом
    вместо списка. Текстовый поиск их просто не находит.

    ⚠ Номер бывает и числом, и строкой (`"workflow_id": "36"`). Движку разницы
    нет — он приводит к `int` при вызове, — поэтому расхождение ломало бы
    только показ, то есть молча.
    """
    return (r'"workflow_id"[[:space:]]*:[[:space:]]*"?'
            + str(int(workflow_id)) + r'"?[[:space:]]*[,}]')


def ai_workflow_topic_group_refs_find(metadata: str) -> set:
    """Номера групп тем, на которые ссылается `metadata` шага.

    Знание о **форме** ссылки живёт здесь, рядом с тем, кто её переписывает, —
    вторая копия шаблона в читающем модуле разошлась бы с этой на первой же
    правке и молча: ссылка не нашлась — предупреждения нет, а шаг на той
    стороне не поднимет ни одной темы.

    Returns:
        set: номера групп (пустое множество, если ссылок нет).
    """
    if not metadata:
        return set()

    return {int(found.group(2)) for found in _TOPIC_GROUP_REF_RE.finditer(metadata)}


def ai_workflow_topic_group_refs_remap(metadata: str, id_map: dict) -> str:
    """Переписать номер группы тем внутри `metadata` шага `topic_action`.

    Отдельной функцией, а не доводом к `ai_workflow_step_refs_remap`: ссылка
    другая и словарь другой. Шаги перенумеровываются при столкновении с чужими
    шагами, группы — при столкновении с чужими группами, и смешать эти два
    словаря значило бы однажды переписать номер группы номером шага.

    Пустой словарь — дословно, как и у соседа: метаданные не трогаются нигде,
    в том числе в шагах, которые не разбираются как JSON.
    """
    if not id_map or not metadata:
        return metadata

    return _TOPIC_GROUP_REF_RE.sub(
        lambda m: f'{m.group(1)}{id_map.get(int(m.group(2)), int(m.group(2)))}{m.group(3)}',
        metadata)


# ── детали разбора условия ──

def _condition_and_check(part: str, variables: dict) -> bool | None:
    """Цепочка через `and`. `None` — хоть один атом не разобрался.

    ⚠ Короткого замыкания нет намеренно: непонятный атом справа от ложного
    должен быть замечен, иначе опечатка в условии живёт, пока первая половина
    ложна, и проявляется в тот день, когда она станет истинной.
    """
    atoms = [_condition_atom_check(one, variables)
             for one in WORKFLOW_AND_RE.split(part)]

    if any(one is None for one in atoms):
        return None

    return all(atoms)


def _condition_atom_check(atom: str, variables: dict) -> bool | None:
    """Один атом: `var`, `!var` или `var <оп> значение`. `None` — не разобрался."""
    found = WORKFLOW_IF_ATOM_RE.match(str(atom or '').strip())

    if not found:
        return None

    negate, name, operator, value = found.groups()

    if not operator:
        result = ai_workflow_variable_truthy(variables, name)

        return not result if negate else result

    # ⚠⚠ Отрицание вместе со сравнением запрещено: `!a == b` читается двояко —
    # «не（a == b）» или «（!a） == b». Вместо догадки отдаём это сторожу, а
    # пишущему остаётся `!=`, который значит ровно одно.
    if negate:
        return None

    right, known = _condition_value_resolve(value, variables)

    # ⚠ Правая переменная не заполнена — условие ложно, а не «текст непонятен».
    # Сравнивать с её отсутствием нечего, но и ругаться не на что: имя написано
    # верно, значения пока нет.
    if not known:
        return False

    compared = ai_workflow_variable_compare(variables, name, operator, right)

    # ⚠ Левой переменной нет — то же самое: «условие не выполнено». Иначе
    # промпт с условием по ещё не заполненной переменной уехал бы к модели с
    # разметкой внутри.
    return False if compared is None else compared


def _condition_value_resolve(value: str, variables: dict) -> tuple:
    """Правая часть сравнения в значение. Возвращает `(значение, известно ли)`.

    ## ⚠⚠⚠ Кавычки решают, что это — слово или переменная

        kind == 'chat'      слово «chat»
        kind == "chat"      то же, кавычки любые
        a == b              значение переменной `b`
        count > 5           число 5: не идентификатор, значит литерал

    Сперва здесь было наоборот: голое слово считалось литералом, а сравнить две
    переменные было нельзя вовсе. Правило сменил человек, и оно лучше: запись
    `kind == chat` читается как «сравни с chat», и спорить о том, слово это или
    переменная, не приходится — кавычки видны.

    ⚠ Отсюда следствие: **слово для сравнения обязано быть в кавычках**.
    Забыли — сравнение пойдёт с переменной, которой обычно нет, и условие
    окажется ложным. Это заметно сразу (блок пропал целиком), в отличие от
    молчаливой правды наоборот.

    ⚠ Второе значение в ответе отличает «переменной нет» от «её значение
    пусто»: первое делает условие ложным, второе — законное сравнение с
    пустотой (`a == ''`).
    """
    text = str(value or '').strip()

    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        # ⚠ Кавычки снимаются только парные по краям: `5" труба` остаётся как
        # есть — там кавычка часть значения.
        return text[1:-1], True

    if WORKFLOW_NAME_RE.fullmatch(text):
        # ⚠ `None` у заполненной переменной — это пустота, а не слово «None»:
        # сравнение ниже приводит правую часть к строке, и `str(None)` дал бы
        # `'None'`, с которым никто никогда не сравнивает нарочно.
        got = variables.get(text)

        return ('' if got is None else got), text in variables

    return text, True

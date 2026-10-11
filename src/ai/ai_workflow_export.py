"""
Экспорт workflow узла — ноды карусели страницы `/admin/workflow`.

Зачем. Настройки workflow (строки `agent_workflow`, шаги с промптами в
`metadata`, входящие переменные, переменные ноды с готовым текстом промптов)
копятся месяцами и живут только в этой базе. Между инсталляциями их переносят
файлом, а внутри одной — страхуются перед опасной правкой. Файл читается
обратно точкой `POST /workflow/import` (см. `ai_workflow_import.py`).

Формат файла объявлен здесь: экспорт — производитель файла, ему и владеть
меткой и версией; импорт ссылается на них, а не заводит свою копию.

Что в файл едет дословно и почему — решать импорту, но производитель обязан
не терять: `id` записей (они зашиты текстом внутрь чужих `metadata`) и
`metadata` шагов — байт в байт: часть шагов в живой базе не разбирается как
JSON, а пересборка через `json.dumps` их необратимо изуродует.

⚠ **Вызов чужого workflow не тянет его в файл** — решение человека: экспорт
строго нода. Ссылка останется битой на принимающей стороне до соседнего
импорта; в вину не молчит — такие ссылки попадают в `warnings`. Родов вызова
два, `workflow_invoke` и `topic_action`, и оба учтены
(`WORKFLOW_SUBFLOW_STEP_TYPES`).

⚠⚠ **Темы ноды едут в файл** — группы, темы и вопросы (`topic_groups`,
`topics`, `topic_questions`). Без них шаг `topic_action` приезжал с номером
группы, который на той стороне не значит ничего: селектор пуст, тем шаг не
поднимает, ошибки нет. Секции появились позже первой версии формата, поэтому
импорт считает их **необязательными**: файл без них — старый, и темы
принимающей стороны он не трогает (`ai_workflow_import.py`).

Что в файл НЕ едет и почему:
- `agent_workflow_step_type` — справочник типов, общий на установку; шаги
  несут `type_name` и сопоставляются по имени;
- `agent_workflow_variable` типа `global` — системные, свои на каждой базе,
  их количество помечается в `warnings`;
- `node_variable_role` — роли установки местные; связи прилетают отдельно
  от переменных только с нодой;
- `agent_workflow_trace*`, `workflow_run` — журнал выполнения, не настройка;
- `browser_workflow*` — отдельная подсистема браузера.
"""

from datetime import datetime, timezone

from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import (WORKFLOW_SUBFLOW_STEP_TYPES,
                                ai_workflow_subflow_refs_find,
                                ai_workflow_topic_group_refs_find)

WORKFLOW_EXPORT_FORMAT = 'rhapsodyai.workflow'
WORKFLOW_EXPORT_VERSION = 1


class AiWorkflowExportError(RuntimeError):
    """Экспорт не удался. HTTP-слой решает, во что превратить это в ответ."""


class AiWorkflowExportNodeMissingError(AiWorkflowExportError):
    """Ноды с таким id нет на этой инсталляции — экспортировать нечего."""


def ai_workflow_export_strip(value):
    """`CHAR(n)` дополняет имя пробелами до ширины — снимаем на границе файла.

    Владение производителя файла: импорт (и его валидатор полей) берёт помощник
    отсюда, как и метку с версией формата, — копия знания не плодится.
    """
    return value.strip() if isinstance(value, str) else value


async def ai_workflow_export_payload(node_pk):
    """Собрать файл узла: строки, шаги, переменные, связи — дословно, с id.

    `node_pk` — id ноды или `None` (псевдонода «Вне нод», `node_id IS NULL`).
    Ответ пригоден для `POST /workflow/import` как есть.
    """
    payload = {
        'format': WORKFLOW_EXPORT_FORMAT,
        'version': WORKFLOW_EXPORT_VERSION,
        'exported_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'node': None,
        'workflows': [],
        'steps': [],
        'variables': [],
        'variable_links': [],
        'node_variables': [],
        'node_variable_links': [],
        'topic_groups': [],
        'topics': [],
        'topic_questions': [],
        'warnings': [],
    }

    async with mysql_get_db_async() as db:
        if node_pk is not None:
            await db.execute('SELECT `name` FROM `node` WHERE `id` = %s', (node_pk,))
            node = await db.fetchone()
            if not node:
                raise AiWorkflowExportNodeMissingError(f'Нода {node_pk} не найдена')
            # `id` ноды в файл не пишем: импорт опознаёт ноду по имени — id
            # на принимающей стороне будет свой, а этот только сбивал бы.
            payload['node'] = {'name': ai_workflow_export_strip(node['name'])}

        workflow_rows = await _workflow_export_fetch_workflows(db, node_pk)
        workflow_ids = [row['id'] for row in workflow_rows]

        for row in workflow_rows:
            payload['workflows'].append({
                'id': row['id'],
                'name': ai_workflow_export_strip(row['name']),
                'title': ai_workflow_export_strip(row['title']),
                'description': ai_workflow_export_strip(row['description']),
                'position': row['position'],
                'group_name': ai_workflow_export_strip(row['group_name']),
                'subflow': row['subflow'],
            })

        if workflow_ids:
            payload['steps'] = await _workflow_export_fetch_steps(db, workflow_ids)
            payload['warnings'].extend(
                _workflow_export_warn_foreign_invokes(payload['steps'], set(workflow_ids)))
            payload['variables'], payload['variable_links'], skipped = \
                await _workflow_export_fetch_variables(db, workflow_ids)
            if skipped:
                # Имена, а не только счёт: на принимающей стороне сразу видно,
                # что проверять, — без похода в базу за списком.
                payload['warnings'].append(
                    f'Глобальные переменные установки не переносятся ({len(skipped)}): '
                    f'{", ".join(skipped)} — они системные, заведите их на принимающей стороне'
                )

        if node_pk is not None:
            payload['node_variables'], payload['node_variable_links'] = \
                await _workflow_export_fetch_node_variables(db, node_pk, workflow_ids)
            payload['topic_groups'], payload['topics'], payload['topic_questions'] = \
                await _workflow_export_fetch_topics(db, node_pk)

        payload['warnings'].extend(
            _workflow_export_warn_foreign_topic_groups(
                payload['steps'], {group['id'] for group in payload['topic_groups']}))

    return payload


def ai_workflow_export_variables_merge(variables_rows, link_rows):
    """Правило идентичности переменной, им и пользуется редактор: (workflow, имя).

    ⚠⚠ Пара была **(имя, тип) по всей базе** — ровно та ошибка, из-за которой
    переменные родителя и подпотока оказывались одной записью. Теперь у
    переменной один владелец, и одинаковые имена в двух workflow — две разные
    записи, обе едут в файл.

    Дубль внутри одного workflow схема больше не допускает (`UNIQUE
    (workflow_id, name)`), так что слияние здесь — страховка на данные, снятые
    до этого индекса: канонической считается строка с меньшим id, связи
    остальных переводятся на неё, чтобы файл не ссылался на невыгруженную
    запись.

    Args:
        variables_rows: строки `agent_workflow_variable` (порядок по id).
        link_rows: строки связей `variable_id`/`workflow_id` тех же id.

    Returns:
        tuple: (variables, links) — канонические записи и объединённые
            связи, где `variable_id` уже указывает на каноническую строку.
    """
    variables, aliases, canonical = [], {}, {}
    for row in variables_rows:
        pair = (row.get('workflow_id'), row['name'])
        if pair not in canonical:
            canonical[pair] = row['id']
            variables.append({
                'id': row['id'],
                'name': ai_workflow_export_strip(row['name']),
                'type': row['type'],
                'default': row['default'],
                'description': ai_workflow_export_strip(row['description']),
            })
        else:
            aliases[row['id']] = canonical[pair]

    merged, seen_pairs = [], set()
    for row in link_rows:
        variable_id = aliases.get(row['variable_id'], row['variable_id'])
        key = (variable_id, row['workflow_id'])
        if key not in seen_pairs:
            seen_pairs.add(key)
            merged.append({'variable_id': variable_id, 'workflow_id': row['workflow_id']})
    return variables, merged


async def _workflow_export_fetch_workflows(db, node_pk):
    """Строки `agent_workflow` узла; для псевдоноды — `node_id IS NULL`."""
    await db.execute('SELECT `id`, `name`, `title`, `description`, `position`, `group_name`, `subflow` '
                     'FROM `agent_workflow` WHERE `node_id` <=> %s ORDER BY `id`', (node_pk,))
    return await db.fetchall() or []


async def _workflow_export_fetch_steps(db, workflow_ids):
    """Шаги узла, `metadata` — дословно; тип приложен именем для чужой базы.

    `type_id` в файл не кладём: на принимающей стороне справочник свой,
    импорт всё равно ищет тип по имени, а чужой id лишь притворялся бы
    значимым.
    """
    placeholders = ','.join(['%s'] * len(workflow_ids))
    await db.execute(
        f'SELECT s.`id`, s.`workflow_id`, t.`name` AS `type_name`, '
        f's.`title`, s.`position`, s.`metadata` '
        f'FROM `agent_workflow_step` s '
        f'LEFT JOIN `agent_workflow_step_type` t ON t.`id` = s.`type_id` '
        f'WHERE s.`workflow_id` IN ({placeholders}) ORDER BY s.`workflow_id`, s.`position`, s.`id`',
        tuple(workflow_ids)
    )
    rows = await db.fetchall() or []
    return [{
        'id': row['id'],
        'workflow_id': row['workflow_id'],
        'type_name': ai_workflow_export_strip(row['type_name']),
        'title': ai_workflow_export_strip(row['title']),
        'position': row['position'],
        'metadata': row['metadata'] if row['metadata'] is not None else '',
    } for row in rows]


async def _workflow_export_fetch_variables(db, workflow_ids):
    """Неглобальные переменные workflow узла и связи «переменная — её workflow».

    У переменной один владелец (`agent_workflow_variable.workflow_id`), поэтому
    связь однозначна и собирается прямо из строки. В файле она всё равно лежит
    отдельным списком `variable_links`: формат заведён при общих переменных и
    менять его незачем — старые файлы читаются тем же импортом.

    Глобальные в файл не идут (свои на каждой базе) — их **имена** возвращаются
    отдельным списком, чтобы сборщик перечислил их в `warnings`.

    ⚠⚠ Глобальные берутся **все, что есть на установке**, а не «привязанные к
    этим workflow»: владельца у глобальной нет и быть не может, движок отдаёт
    их каждому workflow целиком (`ai_workflow_variables_global_get`). Прежняя
    выборка «по связи» опиралась на связку, которая на работу не влияла и
    заполнялась случайно — тем, кто как заводил переменную.
    """
    placeholders = ','.join(['%s'] * len(workflow_ids))
    await db.execute(
        f'SELECT v.`id`, v.`workflow_id`, v.`name`, v.`type`, v.`default`, v.`description` '
        f'FROM `agent_workflow_variable` v '
        f'WHERE v.`workflow_id` IN ({placeholders}) AND v.`type` != %s '
        f'ORDER BY v.`id`',
        tuple(workflow_ids) + ('global',)
    )
    variables_rows = await db.fetchall() or []

    await db.execute(
        'SELECT DISTINCT `name` FROM `agent_workflow_variable` '
        'WHERE `type` = %s ORDER BY `name`', ('global',))
    global_names = [ai_workflow_export_strip(row['name'])
                    for row in (await db.fetchall() or [])]

    link_rows = [{'variable_id': row['id'], 'workflow_id': row['workflow_id']}
                 for row in variables_rows]

    variables, merged = ai_workflow_export_variables_merge(variables_rows, link_rows)
    return variables, merged, global_names


async def _workflow_export_fetch_node_variables(db, node_pk, workflow_ids):
    """Переменные ноды (в них живые промпты и тексты-примеры) и связи с workflow узла."""
    await db.execute(
        'SELECT `id`, `name`, `title`, `type`, `default`, `position`, `description` '
        'FROM `node_variable` WHERE `node_id` <=> %s ORDER BY `id`',
        (node_pk,)
    )
    rows = await db.fetchall() or []
    variables = [{
        'id': row['id'],
        'name': ai_workflow_export_strip(row['name']),
        'title': ai_workflow_export_strip(row['title']),
        'type': row['type'],
        'default': row['default'],
        'position': row['position'],
        'description': ai_workflow_export_strip(row['description']),
    } for row in rows]

    node_variable_ids = [row['id'] for row in rows]
    links = []
    if node_variable_ids and workflow_ids:
        nv_placeholders = ','.join(['%s'] * len(node_variable_ids))
        w_placeholders = ','.join(['%s'] * len(workflow_ids))
        await db.execute(
            f'SELECT `node_variable_id`, `workflow_id` FROM `node_variable_workflow` '
            f'WHERE `node_variable_id` IN ({nv_placeholders}) AND `workflow_id` IN ({w_placeholders})',
            tuple(node_variable_ids) + tuple(workflow_ids)
        )
        links = [{'node_variable_id': row['node_variable_id'], 'workflow_id': row['workflow_id']}
                 for row in (await db.fetchall() or [])]
    return variables, links


async def _workflow_export_fetch_topics(db, node_pk):
    """Темы ноды тремя списками: группы, темы, вопросы — с исходными id.

    ⚠ Группы привязаны к **ноде**, не к workflow, — как переменные ноды.
    Поэтому берутся все группы узла, а не только те, на которые ссылаются шаги:
    группа без шага законна (её заводят до того, как поставят шаг).

    ⚠⚠ `id` групп в файле обязательны: ими ссылается шаг `topic_action`, и без
    них перенос даёт шаг с номером, который на той стороне не значит ничего —
    молча, без единой ошибки. Шапка модуля, `workflow_topic.md` §6a.

    ⚠ У тем и вопросов id служебные: на них не ссылается никто, кроме родителя.
    Едут всё равно — чтобы связь «вопрос → тема» внутри файла читалась без
    догадок.
    """
    await db.execute(
        'SELECT `id`, `name`, `title`, `description`, `is_enabled`, `position` '
        'FROM `agent_workflow_topic_group` WHERE `node_id` = %s ORDER BY `position`, `id`',
        (node_pk,)
    )
    group_rows = await db.fetchall() or []
    groups = [{
        'id': row['id'],
        'name': ai_workflow_export_strip(row['name']),
        'title': ai_workflow_export_strip(row['title']),
        'description': row['description'],
        'is_enabled': row['is_enabled'],
        'position': row['position'],
    } for row in group_rows]

    group_ids = [row['id'] for row in group_rows]
    if not group_ids:
        return groups, [], []

    placeholders = ','.join(['%s'] * len(group_ids))
    await db.execute(
        f'SELECT `id`, `topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, '
        f'`questions_qty_yes_accept`, `instructions`, `is_enabled`, `position` '
        f'FROM `agent_workflow_topic` WHERE `topic_group_id` IN ({placeholders}) '
        f'ORDER BY `topic_group_id`, `position`, `id`',
        tuple(group_ids)
    )
    topic_rows = await db.fetchall() or []
    topics = [{
        'id': row['id'],
        'topic_group_id': row['topic_group_id'],
        'name': ai_workflow_export_strip(row['name']),
        'title': ai_workflow_export_strip(row['title']),
        'tags': row['tags'],
        'tags_qty_accept': row['tags_qty_accept'],
        'questions_qty_yes_accept': row['questions_qty_yes_accept'],
        'instructions': row['instructions'],
        'is_enabled': row['is_enabled'],
        'position': row['position'],
    } for row in topic_rows]

    topic_ids = [row['id'] for row in topic_rows]
    if not topic_ids:
        return groups, topics, []

    placeholders = ','.join(['%s'] * len(topic_ids))
    await db.execute(
        f'SELECT `id`, `topic_id`, `question`, `is_enabled`, `position` '
        f'FROM `agent_workflow_topic_question` WHERE `topic_id` IN ({placeholders}) '
        f'ORDER BY `topic_id`, `position`, `id`',
        tuple(topic_ids)
    )
    questions = [{
        'id': row['id'],
        'topic_id': row['topic_id'],
        'question': row['question'],
        'is_enabled': row['is_enabled'],
        'position': row['position'],
    } for row in (await db.fetchall() or [])]

    return groups, topics, questions


def _workflow_export_warn_foreign_topic_groups(steps, exported_group_ids):
    """Шаг ссылается на группу тем, которой в файле нет.

    Бывает законно (узел «Вне нод» групп не имеет вовсе) и незаконно (группу
    удалили, а шаг остался). В обоих случаях на принимающей стороне шаг не
    поднимет ни одной темы — и молча, поэтому предупреждение обязательно.
    """
    foreign = {}
    for step in steps:
        if step.get('type_name') != 'topic_action':
            continue
        for target in ai_workflow_topic_group_refs_find(step['metadata'] or ''):
            if target not in exported_group_ids:
                foreign[target] = foreign.get(target, 0) + 1
    return [
        f'Шаг темы ссылается на группу вне файла (id {target}, в {count} шаг(ах)) — '
        f'на принимающей стороне он не поднимет ни одной темы'
        for target, count in sorted(foreign.items())
    ]


def _workflow_export_warn_foreign_invokes(steps, exported_workflow_ids):
    """Вызовы подпотоков на workflow вне узла: файл их несёт, но не содержит.

    ⚠⚠ Отбор идёт по **типу шага**, а не по подстроке `workflow_invoke` в
    тексте метаданных. Родов вызова два (`WORKFLOW_SUBFLOW_STEP_TYPES`), и
    подстрока знала один: подпоток, который зовёт `topic_action`, уезжал из узла
    молча — предупреждения не было, а ссылка на принимающей стороне оставалась
    битой.
    """
    foreign = {}
    for step in steps:
        metadata = step['metadata'] or ''
        if step.get('type_name') not in WORKFLOW_SUBFLOW_STEP_TYPES:
            continue
        for target in ai_workflow_subflow_refs_find(metadata):
            if target not in exported_workflow_ids:
                foreign[target] = foreign.get(target, 0) + 1
    return [
        f'Workflow вне узла вызывается как подпоток (id {target}) в {count} шаг(ах) — '
        f'он не в файле; на принимающей стороне ссылка останется битой'
        for target, count in sorted(foreign.items())
    ]

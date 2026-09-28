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

⚠ **`workflow_invoke` на чужой workflow не тянет его в файл** — решение
человека: экспорт строго нода. Ссылка останется битой на принимающей стороне
до соседнего импорта; в вину не молчит — такие ссылки попадают в `warnings`.

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

import re
from datetime import datetime, timezone

from mysql_.mysql_ import mysql_get_db_async

WORKFLOW_EXPORT_FORMAT = 'rhapsodyai.workflow'
WORKFLOW_EXPORT_VERSION = 1


class AiWorkflowExportError(RuntimeError):
    """Экспорт не удался. HTTP-слой решает, во что превратить это в ответ."""


class AiWorkflowExportNodeMissingError(AiWorkflowExportError):
    """Ноды с таким id нет на этой инсталляции — экспортировать нечего."""

# Вызов подпотока: `"workflow_id": 6` или `"workflow_id": "6"` (и плейсхолдеры
# вроде `%test_workflow_id%` — не числа, мимо пробегут).
_WORKFLOW_EXPORT_INVOKE_RE = re.compile(r'"workflow_id"\s*:\s*"?(\d+)"?')


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
                payload['warnings'].append(
                    f'Глобальные переменные не переносятся: {skipped} — заведите их на принимающей стороне'
                )

        if node_pk is not None:
            payload['node_variables'], payload['node_variable_links'] = \
                await _workflow_export_fetch_node_variables(db, node_pk, workflow_ids)

    return payload


def ai_workflow_export_variables_merge(variables_rows, link_rows):
    """Правило идентичности переменной, им и пользуется редактор: пара (имя, тип).

    Уникального индекса на пару в схеме нет, поэтому под одним именем могут
    жить строки с разными id (наследие старых заводов): первой канонической
    считается строка с меньшим id, её и пишем в файл, а связи дублей
    переводим на неё — файл обязан быть непротиворечив относительно пары.

    Args:
        variables_rows: строки `agent_workflow_variable` (порядок по id).
        link_rows: строки связей `variable_id`/`workflow_id` тех же id.

    Returns:
        tuple: (variables, links) — канонические записи и объединённые
            связи, где `variable_id` уже указывает на каноническую строку.
    """
    variables, aliases, canonical = [], {}, {}
    for row in variables_rows:
        pair = (row['name'], row['type'])
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
    """Неглобальные переменные, привязанные к workflow узла, и сами связи.

    Переменная может быть привязана и к чужому workflow (M:N) — на принимающей
    стороне импорт сопоставит её по имени и типу, а чужая связь не пострадает.
    Глобальные в файл не идут (свои на каждой базе) — их количество возвращается
    отдельным числом, чтобы сборщик поставил его в `warnings`. Слияние дублей
    по паре (имя, тип) — не здесь: правило живёт в
    `ai_workflow_export_variables_merge`.
    """
    placeholders = ','.join(['%s'] * len(workflow_ids))
    await db.execute(
        f'SELECT v.`id`, v.`name`, v.`type`, v.`default`, v.`description` '
        f'FROM `agent_workflow_variable` v '
        f'JOIN `agent_workflow_variable_workflow` l ON l.`variable_id` = v.`id` '
        f'WHERE l.`workflow_id` IN ({placeholders}) AND v.`type` != %s '
        f'GROUP BY v.`id`, v.`name`, v.`type`, v.`default`, v.`description` '
        f'ORDER BY v.`id`',
        tuple(workflow_ids) + ('global',)
    )
    variables_rows = await db.fetchall() or []

    await db.execute(
        f'SELECT COUNT(*) AS `cnt` FROM `agent_workflow_variable` v '
        f'JOIN `agent_workflow_variable_workflow` l ON l.`variable_id` = v.`id` '
        f'WHERE l.`workflow_id` IN ({placeholders}) AND v.`type` = %s',
        tuple(workflow_ids) + ('global',)
    )
    global_count = (await db.fetchone() or {}).get('cnt', 0)

    # Связи глобальных переменных не пишутся: самих их в файле нет, а ссылка на
    # отсутствующую запись сделала бы файл битым для импорта.
    await db.execute(
        f'SELECT l.`variable_id`, l.`workflow_id` FROM `agent_workflow_variable_workflow` l '
        f'JOIN `agent_workflow_variable` v ON v.`id` = l.`variable_id` AND v.`type` != %s '
        f'WHERE l.`workflow_id` IN ({placeholders}) '
        f'ORDER BY l.`variable_id`, l.`workflow_id`',
        ('global',) + tuple(workflow_ids)
    )
    link_rows = await db.fetchall() or []

    variables, merged = ai_workflow_export_variables_merge(variables_rows, link_rows)
    return variables, merged, global_count


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


def _workflow_export_warn_foreign_invokes(steps, exported_workflow_ids):
    """Вызовы подпотоков на workflow вне узла: файл их несёт, но не содержит."""
    foreign = {}
    for step in steps:
        metadata = step['metadata'] or ''
        if 'workflow_invoke' not in metadata:
            continue
        for match in _WORKFLOW_EXPORT_INVOKE_RE.finditer(metadata):
            target = int(match.group(1))
            if target not in exported_workflow_ids:
                foreign.setdefault(target, 0)
                foreign[target] += 1
    return [
        f'Workflow вне узла вызывается как подпоток (id {target}) в {count} шаг(ах) — '
        f'он не в файле; на принимающей стороне ссылка останется битой'
        for target, count in sorted(foreign.items())
    ]

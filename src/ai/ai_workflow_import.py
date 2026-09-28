"""
Импорт workflow узла — замена ноды карусели страницы `/admin/workflow`
содержимым файла, созданного `GET /workflow/export` (см. `ai_workflow_export.py`).

⚠ **`id` workflow и шагов в файле — священны.** Внутри
`agent_workflow_step.metadata` чужие id зашиты текстом: переходы
`transitions_before/after[].step_id`, имена результатов инструментов
`{tool}_{step_id}_result_{key}`, вызовы подпотоков
`workflow_invoke.workflow_id`. Поэтому импорт вставляет записи **с исходными
id**, а не полагается на автоинкремент, и `metadata` переносит дословно:
часть шагов в живой базе не разбирается как JSON (чинит фронтенд,
`parseMetadata`), а пересборка через `json.dumps` необратимо их изуродует.
Знание о формах ссылки на шаг — одно на всех: `ai_workflow_step_refs_remap`
(`ai_workflow.py`); политика здесь своя — id сохраняем и переписываем их
только при столкновении с чужими записями.

⚠ **Импорт заменяет только ноды из файла**: чистит workflow этих нод и
вставляет свои. Остальные ноды не трогает. `agent.workflow_id` — внешний ключ
`SET NULL`: импорт снимает привязки агентов и гасит их обратно (агент переживает
замену своего workflow).

Импорт — **одна транзакция**: ошибка на любом шаге откатывает всё, база не
остаётся наполовину вычищенной (пул `mysql_get_db_async` с autocommit=True —
транзакцию приходится открывать явно).
"""

import re

from fastapi import HTTPException

from logging_.logging_ import logger_exception, logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import ai_workflow_step_refs_remap
from src.ai.ai_workflow_export import (
    WORKFLOW_EXPORT_FORMAT,
    WORKFLOW_EXPORT_VERSION,
    ai_workflow_export_strip,
)

# Имя переменной — тот же идентификатор, что требует редактор переменной:
# в промпты оно подставляется как есть.
_VARIABLE_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


async def ai_workflow_import_apply(data, actor):
    """Заменить workflow ноды, чей это файл. Остальные ноды не трогаются.

    Порядок внутри одной транзакции: снимок привязок агентов → чистка ноды →
    вставка workflow и шагов **с исходными id** → переменные → связи →
    обратная привязка агентов. Любая ошибка — откат, база как была.

    Совпадения на чужих записях:
    - `id` или имя workflow занято чужим workflow → 409, файл не импортируется;
    - `id` шага занят чужим workflow → все шаги файла получают новые id,
      ссылки внутри `metadata` переписывает `ai_workflow_step_refs_remap`.
    """
    payload = _validate_import_payload(data)

    async with mysql_get_db_async() as db:
        try:
            await db.connection.begin()

            target_node_id = await _resolve_target_node(db, payload['node'])

            workflows = payload['workflows']
            workflow_ids = [workflow['id'] for workflow in workflows]

            wipe = await _collect_wipe_set(db, target_node_id)

            await _check_collisions(db, payload, workflow_ids, wipe)
            step_mapping = await _assign_step_ids(db, payload, wipe)

            agent_bindings = await _snapshot_agent_bindings(db, wipe)

            await _wipe_node_workflows(db, wipe)

            await _insert_workflows(db, workflows, target_node_id)

            variable_id_map = await _upsert_variables(db, payload['variables'])
            await _insert_variable_links(db, payload['variable_links'], variable_id_map, set(workflow_ids))

            node_variable_id_map = await _upsert_node_variables(db, payload['node_variables'], target_node_id)
            await _insert_node_variable_links(db, payload['node_variable_links'],
                                              node_variable_id_map, set(workflow_ids))

            steps_inserted = await _insert_steps(db, payload['steps'], step_mapping)

            agents_rebound = await _rebind_agents(db, agent_bindings, set(workflow_ids))

            await db.connection.commit()
        except HTTPException:
            # Штатный отказ (400/409): файл отвергнут, журнал ошибок не мажет.
            await db.connection.rollback()
            raise
        except Exception as error:
            await db.connection.rollback()
            logger_exception('Импорт workflow откатан', exc=error)
            raise HTTPException(status_code=500, detail=f'Импорт не удался, изменения отменены: {error}')

    logger_info(f'Импорт workflow: пользователь {actor}, нода '
                f'{payload["node"] and payload["node"]["name"]}, workflow {len(payload["workflows"])}, '
                f'шагов {steps_inserted}')

    notes = []
    if step_mapping:
        notes.append(f'id шагов совпадали с чужими записями — все {len(step_mapping)} '
                     f'шагов файла получили новые id, ссылки внутри шагов переписаны')
    if payload['warnings']:
        notes.extend(payload['warnings'])

    return {
        "node": payload['node']['name'] if payload['node'] else None,
        "workflows_removed": len(wipe),
        "workflows_imported": len(workflows),
        "steps_imported": steps_inserted,
        "variables_upserted": len(variable_id_map),
        "node_variables_upserted": len(node_variable_id_map),
        "agents_rebound": agents_rebound,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Импорт: проверка входных данных
# ---------------------------------------------------------------------------

def _validate_import_payload(data):
    """Форма и допустимость файла. Всё, что можно понять до базы, понято здесь."""
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail='Ожидался JSON-объект')

    if data.get('format') != WORKFLOW_EXPORT_FORMAT:
        raise HTTPException(status_code=400, detail='Файл не похож на экспорт workflow (нет метки формата)')
    if data.get('version') != WORKFLOW_EXPORT_VERSION:
        raise HTTPException(status_code=400,
                            detail=f'Неизвестная версия формата: {data.get("version")} (ожидается {WORKFLOW_EXPORT_VERSION})')

    for key in ('workflows', 'steps', 'variables', 'variable_links',
                'node_variables', 'node_variable_links'):
        if not isinstance(data.get(key), list):
            raise HTTPException(status_code=400, detail=f'Поле «{key}» отсутствует или не список')

    node = data.get('node')
    if node is not None:
        if not isinstance(node, dict) or not ai_workflow_export_strip(node.get('name')):
            raise HTTPException(status_code=400, detail='Поле «node» — объект с именем или null')
        node = {'name': ai_workflow_export_strip(node['name'])[:50]}

    workflows = {}
    for raw in data['workflows']:
        workflow_id = _positive_id(raw.get('id'), 'workflow')
        name = _check_text(ai_workflow_export_strip(raw.get('name')), 'name workflow', max_length=50, required=True)
        title = _check_text(ai_workflow_export_strip(raw.get('title')) or '', 'title workflow', max_length=50)
        if workflow_id in workflows:
            raise HTTPException(status_code=400, detail=f'В файле два workflow с id {workflow_id}')
        workflows[workflow_id] = {
            'id': workflow_id,
            'name': name,
            'title': title,
            'description': _check_text(ai_workflow_export_strip(raw.get('description')) or '',
                                       'description workflow', max_length=200),
            'position': _int_or(raw.get('position'), 0),
            'group_name': _check_text(ai_workflow_export_strip(raw.get('group_name')), 'group_name workflow', max_length=50),
            'subflow': 1 if _int_or(raw.get('subflow'), 0) else 0,
        }
    if not workflows:
        raise HTTPException(status_code=400, detail='В файле нет ни одного workflow')

    seen_names = set()
    for workflow in workflows.values():
        if workflow['name'] in seen_names:
            raise HTTPException(status_code=400, detail=f"В файле два workflow с именем «{workflow['name']}»")
        seen_names.add(workflow['name'])

    steps = []
    for raw in data['steps']:
        step_id = _positive_id(raw.get('id'), 'шаг')
        if raw.get('workflow_id') not in workflows:
            raise HTTPException(status_code=400, detail=f'Шаг {step_id} ссылается на workflow вне файла')
        metadata = raw.get('metadata')
        if not isinstance(metadata, str):
            raise HTTPException(status_code=400,
                                detail=f'metadata шага {step_id} должен быть строкой (переносим дословно)')
        steps.append({
            'id': step_id,
            'workflow_id': raw['workflow_id'],
            'type_name': _check_text(ai_workflow_export_strip(raw.get('type_name')), 'type_name шага', max_length=50),
            'title': _check_text(ai_workflow_export_strip(raw.get('title')) or '', 'title шага', max_length=50),
            'position': _int_or(raw.get('position'), 0),
            'metadata': metadata,
        })

    variables, seen_pairs, seen_ids = [], set(), set()
    for raw in data['variables']:
        # `id` файла — только ключ связей внутри файла: переменные на принимающей
        # стороне опознаются по паре (имя, тип), их собственные id в metadata не зашиты.
        variable_file_id = _positive_id(raw.get('id'), 'переменная')
        if variable_file_id in seen_ids:
            raise HTTPException(status_code=400, detail=f'В файле две переменные с id {variable_file_id}')
        seen_ids.add(variable_file_id)
        name = _check_text(ai_workflow_export_strip(raw.get('name')), 'имя переменной', max_length=50)
        if not name or not _VARIABLE_NAME_RE.match(name):
            raise HTTPException(status_code=400, detail=f'Недопустимое имя переменной: {raw.get("name")!r}')
        var_type = raw.get('type')
        if var_type not in ('input', 'workflow'):
            # Глобальные в файл не пишутся; если пришли из рук — мимо, их заводит принимающая сторона.
            raise HTTPException(status_code=400, detail=f'Переменная {name!r}: недопустимый тип {var_type!r}')
        pair = (name, var_type)
        if pair in seen_pairs:
            raise HTTPException(status_code=400, detail=f'В файле две переменные {name} типа {var_type}')
        seen_pairs.add(pair)
        variables.append({
            'id': variable_file_id,
            'name': name,
            'type': var_type,
            'default': raw.get('default'),
            'description': _check_text(ai_workflow_export_strip(raw.get('description')), 'description переменной', max_length=200),
        })

    variable_links = []
    variable_ids = {variable['id'] for variable in variables}
    link_pairs = set()
    for raw in data['variable_links']:
        variable_id, workflow_id = raw.get('variable_id'), raw.get('workflow_id')
        if variable_id not in variable_ids:
            raise HTTPException(status_code=400, detail=f'Связь переменной {variable_id} — переменной нет в файле')
        if workflow_id not in workflows:
            raise HTTPException(status_code=400, detail=f'Связь переменной на workflow {workflow_id} — его нет в файле')
        if (variable_id, workflow_id) not in link_pairs:
            link_pairs.add((variable_id, workflow_id))
            variable_links.append((variable_id, workflow_id))

    node_variables, seen_nv_names, seen_nv_ids = [], set(), set()
    for raw in data['node_variables']:
        nv_file_id = _positive_id(raw.get('id'), 'переменная ноды')
        if nv_file_id in seen_nv_ids:
            raise HTTPException(status_code=400, detail=f'В файле две переменные ноды с id {nv_file_id}')
        seen_nv_ids.add(nv_file_id)
        name = _check_text(ai_workflow_export_strip(raw.get('name')), 'имя переменной ноды', max_length=50)
        if not name or not _VARIABLE_NAME_RE.match(name):
            raise HTTPException(status_code=400, detail=f'Недопустимое имя переменной ноды: {raw.get("name")!r}')
        if name in seen_nv_names:
            raise HTTPException(status_code=400, detail=f'В файле две переменные ноды с именем {name}')
        seen_nv_names.add(name)
        node_variables.append({
            'id': nv_file_id,
            'name': name,
            'title': _check_text(ai_workflow_export_strip(raw.get('title')) or '', 'title переменной ноды', max_length=100),
            'type': raw.get('type') if raw.get('type') in ('public', 'proxy') else 'public',
            'default': raw.get('default'),
            'position': _int_or(raw.get('position'), 0),
            'description': _check_text(ai_workflow_export_strip(raw.get('description')),
                                       'description переменной ноды', max_length=200),
        })

    node_variable_links, nv_link_pairs = [], set()
    nv_id_to_name = {variable['id']: variable['name'] for variable in node_variables}
    for raw in data['node_variable_links']:
        nv_name = nv_id_to_name.get(raw.get('node_variable_id'))
        if not nv_name:
            raise HTTPException(status_code=400, detail=f'Связь переменной ноды {raw.get("node_variable_id")} — её нет в файле')
        if raw.get('workflow_id') not in workflows:
            raise HTTPException(status_code=400, detail=f'Связь переменной ноды на workflow {raw.get("workflow_id")} — его нет в файле')
        pair = (nv_name, raw['workflow_id'])
        if pair not in nv_link_pairs:
            nv_link_pairs.add(pair)
            node_variable_links.append(pair)

    return {
        'node': node,
        'workflows': list(workflows.values()),
        'steps': steps,
        'variables': variables,
        'variable_links': variable_links,
        'node_variables': node_variables,
        'node_variable_links': node_variable_links,
        'warnings': [str(warning) for warning in data.get('warnings') or []] if isinstance(data.get('warnings'), list) else [],
    }


# ---------------------------------------------------------------------------
# Импорт: шаги вокруг записи
# ---------------------------------------------------------------------------

async def _resolve_target_node(db, node):
    """Целевая нода по имени: имена нод — собственность принимающей стороны."""
    if node is None:
        return None
    await db.execute('SELECT `id`, `name` FROM `node` WHERE `name` = %s ORDER BY `id` LIMIT 1',
                     (node['name'],))
    found = await db.fetchone()
    if not found:
        raise HTTPException(
            status_code=400,
            detail=f"Нода «{node['name']}» не найдена — создайте её на странице нод "
                   f"(имя то же) и настройте ей LLM, затем повторите импорт"
        )
    return found['id']


async def _collect_wipe_set(db, target_node_id):
    """Существующие workflow заменяемой ноды: их id — объём удаления."""
    await db.execute('SELECT `id` FROM `agent_workflow` WHERE `node_id` <=> %s ORDER BY `id`',
                     (target_node_id,))
    return [row['id'] for row in (await db.fetchall() or [])]


async def _check_collisions(db, payload, workflow_ids, wipe):
    """Workflow-совпадения — только стоп: id вшиты в чужие metadata и ссылки агентов."""
    placeholders = ','.join(['%s'] * len(workflow_ids))
    wipe_placeholders = ','.join(['%s'] * len(wipe)) if wipe else None

    excluded = f'AND `id` NOT IN ({wipe_placeholders})' if wipe else ''
    args = tuple(workflow_ids) + tuple(wipe) if wipe else tuple(workflow_ids)

    await db.execute(
        f'SELECT `id`, `name` FROM `agent_workflow` '
        f'WHERE `id` IN ({placeholders}) {excluded} ORDER BY `id`',
        args
    )
    taken = await db.fetchall() or []
    if taken:
        listed = ', '.join(f'#{row["id"]} «{ai_workflow_export_strip(row["name"])}»' for row in taken[:10])
        raise HTTPException(status_code=409,
                            detail=f'id из файла заняты чужими workflow: {listed} — импорт отменён')

    names = [workflow['name'] for workflow in payload['workflows']]
    name_placeholders = ','.join(['%s'] * len(names))
    name_args = tuple(names) + tuple(wipe) if wipe else tuple(names)
    await db.execute(
        f'SELECT `id`, `name` FROM `agent_workflow` '
        f'WHERE `name` IN ({name_placeholders}) {excluded} ORDER BY `id`',
        name_args
    )
    taken_names = await db.fetchall() or []
    if taken_names:
        listed = ', '.join(f'«{ai_workflow_export_strip(row["name"])}» (id {row["id"]})' for row in taken_names[:10])
        raise HTTPException(status_code=409,
                            detail=f'Имена workflow заняты вне заменяемой ноды: {listed} — импорт отменён')


async def _assign_step_ids(db, payload, wipe):
    """Id шагов: исходные, если свободны; иначе — всем шагам файла новые.

    Шаги заменяемой ноды к этому моменту ещё живы, но удалятся; опасны только
    id шагов **чужих** workflow. Однообразный ремап (всем новым, или всем
    старым) держит metadata согласованной: ссылки идут только между шагами
    этого же набора.
    """
    step_ids = [step['id'] for step in payload['steps']]
    if not step_ids:
        return {}

    placeholders = ','.join(['%s'] * len(step_ids))
    excluded = f'AND `workflow_id` NOT IN ({",".join(["%s"] * len(wipe))})' if wipe else ''
    args = tuple(step_ids) + tuple(wipe) if wipe else tuple(step_ids)

    await db.execute(
        f'SELECT `id` FROM `agent_workflow_step` WHERE `id` IN ({placeholders}) {excluded}',
        args
    )
    taken = [row['id'] for row in (await db.fetchall() or [])]
    if not taken:
        return {}

    await db.execute('SELECT COALESCE(MAX(`id`), 0) AS `max_id` FROM `agent_workflow_step` FOR UPDATE')
    next_id = (await db.fetchone() or {}).get('max_id', 0)
    mapping = {}
    for step in payload['steps']:
        next_id += 1
        mapping[step['id']] = next_id
    return mapping


async def _snapshot_agent_bindings(db, wipe):
    """Привязки агентов до чистки: FK `SET NULL` снимет их сам при удалении."""
    if not wipe:
        return []
    placeholders = ','.join(['%s'] * len(wipe))
    await db.execute(f'SELECT `id`, `workflow_id` FROM `agent` WHERE `workflow_id` IN ({placeholders})',
                     tuple(wipe))
    return await db.fetchall() or []


async def _wipe_node_workflows(db, wipe):
    """Удаление ноды: шаги — явно (их FK `SET NULL` оставил бы сирот),
    связи переменных снимает `CASCADE`, строки журнала — `SET NULL`, так и живём."""
    if not wipe:
        return
    placeholders = ','.join(['%s'] * len(wipe))
    args = tuple(wipe)
    await db.execute(f'DELETE FROM `agent_workflow_step` WHERE `workflow_id` IN ({placeholders})', args)
    await db.execute(
        f'DELETE FROM `agent_workflow_variable_workflow` WHERE `workflow_id` IN ({placeholders})', args)
    await db.execute(f'DELETE FROM `node_variable_workflow` WHERE `workflow_id` IN ({placeholders})', args)
    await db.execute(f'DELETE FROM `agent_workflow` WHERE `id` IN ({placeholders})', args)


async def _insert_workflows(db, workflows, target_node_id):
    """Строки `agent_workflow` — с исходными id файла, нода уже известна."""
    if not workflows:
        return
    for workflow in workflows:
        await db.execute(
            'INSERT INTO `agent_workflow` '
            '(`id`, `node_id`, `name`, `title`, `description`, `position`, `group_name`, `subflow`) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (workflow['id'], target_node_id, workflow['name'], workflow['title'],
             workflow['description'], workflow['position'], workflow['group_name'], workflow['subflow'])
        )


async def _upsert_variables(db, variables):
    """Переменные по паре (имя, тип) — так же их опознаёт редактор.

    Существующая может быть общей с чужими workflow — обновляем только
    содержательные поля, `id` остаётся местным.
    """
    resolved = {}
    for variable in variables:
        await db.execute(
            'SELECT `id` FROM `agent_workflow_variable` WHERE `name` = %s AND `type` = %s '
            'ORDER BY `id` LIMIT 1',
            (variable['name'], variable['type'])
        )
        found = await db.fetchone()
        if found:
            variable_id = found['id']
            await db.execute(
                'UPDATE `agent_workflow_variable` SET `default` = %s, `description` = %s WHERE `id` = %s',
                (variable['default'], variable['description'], variable_id)
            )
        else:
            await db.execute(
                'INSERT INTO `agent_workflow_variable` (`name`, `type`, `default`, `description`) '
                'VALUES (%s, %s, %s, %s)',
                (variable['name'], variable['type'], variable['default'], variable['description'])
            )
            variable_id = db.lastrowid
        resolved[variable['id']] = variable_id
    return resolved


async def _insert_variable_links(db, links, variable_id_map, workflow_ids):
    """Связи переменных: только внутрь workflow файла, чужое уже разобрано."""
    for variable_id, workflow_id in links:
        target_variable_id = variable_id_map.get(variable_id)
        if target_variable_id is None or workflow_id not in workflow_ids:
            continue
        await db.execute(
            'INSERT IGNORE INTO `agent_workflow_variable_workflow` (`variable_id`, `workflow_id`) '
            'VALUES (%s, %s)',
            (target_variable_id, workflow_id)
        )


async def _upsert_node_variables(db, node_variables, target_node_id):
    """Переменные ноды по имени внутри ноды.

    Существующая строка правится на месте, а не пересоздаётся: её id носят
    связи ролей (`node_variable_role`), и пересоздание молча бы их сожрало.
    """
    resolved = {}
    if target_node_id is None:
        # Псевдонода «Вне нод» своих переменных не имеет; чужие из файла — мусор.
        return resolved
    for variable in node_variables:
        await db.execute(
            'SELECT `id` FROM `node_variable` WHERE `node_id` = %s AND `name` = %s ORDER BY `id` LIMIT 1',
            (target_node_id, variable['name'])
        )
        found = await db.fetchone()
        if found:
            variable_id = found['id']
            await db.execute(
                'UPDATE `node_variable` SET `title` = %s, `type` = %s, `default` = %s, '
                '`position` = %s, `description` = %s WHERE `id` = %s',
                (variable['title'], variable['type'], variable['default'],
                 variable['position'], variable['description'], variable_id)
            )
        else:
            await db.execute(
                'INSERT INTO `node_variable` (`node_id`, `name`, `title`, `type`, `default`, `position`, `description`) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (target_node_id, variable['name'], variable['title'], variable['type'],
                 variable['default'], variable['position'], variable['description'])
            )
            variable_id = db.lastrowid
        resolved[variable['name']] = variable_id
    return resolved


async def _insert_node_variable_links(db, links, node_variable_id_map, workflow_ids):
    """Связи переменных ноды: пары (имя, workflow файла) уже сверены валидатором."""
    for name, workflow_id in links:
        variable_id = node_variable_id_map.get(name)
        if variable_id is None or workflow_id not in workflow_ids:
            continue
        await db.execute(
            'INSERT IGNORE INTO `node_variable_workflow` (`node_variable_id`, `workflow_id`) '
            'VALUES (%s, %s)',
            (variable_id, workflow_id)
        )


async def _insert_steps(db, steps, step_mapping):
    """Шаги с ремапом ссылок; тип ищется по имени — справочник местные знают свой.

    Ремап — общее знание `ai_workflow_step_refs_remap`; наша политика —
    переписывать id только при столкновении (пустой словарь → дословно).
    """
    if not steps:
        return 0
    await db.execute('SELECT `id`, `name` FROM `agent_workflow_step_type`')
    type_ids = {ai_workflow_export_strip(row['name']): row['id'] for row in (await db.fetchall() or [])}

    for step in steps:
        type_id = type_ids.get(step['type_name'])
        if step['type_name'] and type_id is None:
            raise HTTPException(status_code=400,
                                detail=f'Неизвестный тип шага «{step["type_name"]}» — справочник типов '
                                       f'принимающей стороны его не знает')
        metadata = ai_workflow_step_refs_remap(step['metadata'], step_mapping)
        step_id = step_mapping.get(step['id'], step['id'])
        await db.execute(
            'INSERT INTO `agent_workflow_step` (`id`, `workflow_id`, `type_id`, `title`, `position`, `metadata`) '
            'VALUES (%s, %s, %s, %s, %s, %s)',
            (step_id, step['workflow_id'], type_id, step['title'], step['position'], metadata)
        )
    return len(steps)


async def _rebind_agents(db, bindings, workflow_ids):
    """Агент, чей workflow вернулся из файла под тем же id, привязывается обратно."""
    rebound = 0
    for binding in bindings:
        if binding['workflow_id'] in workflow_ids:
            await db.execute('UPDATE `agent` SET `workflow_id` = %s WHERE `id` = %s',
                             (binding['workflow_id'], binding['id']))
            rebound += 1
    return rebound


# ---------------------------------------------------------------------------
# Мелкое приватное
# ---------------------------------------------------------------------------

def _positive_id(value, label):
    """Id из файла: положительное число, иначе файл недостоверен."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f'«{label}»: id должен быть числом, получено {value!r}')
    if parsed <= 0:
        raise HTTPException(status_code=400, detail=f'«{label}»: id должен быть положительным')
    return parsed


def _int_or(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _check_text(value, label, max_length, required=False):
    if required and not value:
        raise HTTPException(status_code=400, detail=f'«{label}»: обязательно')
    if value and len(value) > max_length:
        raise HTTPException(status_code=400,
                            detail=f'«{label}»: длиннее {max_length} символов ({len(value)})')
    return value

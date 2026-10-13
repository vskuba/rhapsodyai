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

⚠⚠ **Темы ноды — тоже содержимое узла** (группы, темы, вопросы). Их номер
зашит в `metadata` шага `topic_action` (`topic_group_id`), поэтому к ним
применяется та же политика, что к шагам: id сохраняются, а при столкновении с
чужими перенумеровываются все разом, и ссылки переписываются. Секции нет в
файле (он снят до её появления) — темы принимающей стороны не трогаются вовсе.

Импорт — **одна транзакция**: ошибка на любом шаге откатывает всё, база не
остаётся наполовину вычищенной (пул `mysql_get_db_async` с autocommit=True —
транзакцию приходится открывать явно).

Ошибки — доменные (`AiWorkflowImportError` и наследники), без знания про HTTP:
вызвать `ai_workflow_import_apply` может cron, воркер или разовый скрипт с
другой машиной. Чем ответить человеку (400/409/500), решает только HTTP-слой
(`routers/workflow/workflow_import.py`).
"""

import re

from logging_.logging_ import logger_exception, logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow import (ai_workflow_step_refs_remap,
                                ai_workflow_topic_group_refs_remap)
from src.ai.ai_workflow_export import (
    WORKFLOW_EXPORT_FORMAT,
    WORKFLOW_EXPORT_VERSION,
    ai_workflow_export_strip,
)

# Имя переменной — тот же идентификатор, что требует редактор переменной:
# в промпты оно подставляется как есть.
_VARIABLE_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class AiWorkflowImportError(RuntimeError):
    """Импорт не состоялся или отменён на середине; база не осталась наполовину
    вычищенной. Ловится одним `except` тем, кто зовёт, — cron, воркер,
    HTTP-слой; чем именно ответить человеку, решает слой, а не домен.
    """


class AiWorkflowImportRejectedError(AiWorkflowImportError):
    """Файл недостоверен: не читается, противоречит себе или требует того, чего
    на принимающей стороне нет. Ни одного изменения базы не сделано.
    """


class AiWorkflowImportConflictError(AiWorkflowImportError):
    """Файл достоверен, но его `id` или имя workflow занято чужими записями,
    которые импорт не вправе ни перетереть, ни перенумеровать.
    """


class AiWorkflowImportFailedError(AiWorkflowImportError):
    """Запись сорвалась на середине по непредвиденной причине: всё откачено,
    база ровно такая, какой была до импорта.
    """


async def ai_workflow_import_apply(data, actor):
    """Заменить workflow ноды, чей это файл. Остальные ноды не трогаются.

    Порядок внутри одной транзакции: снимок привязок агентов → чистка ноды
    (workflow, а при наличии секции — и группы тем) → вставка workflow и тем
    **с исходными id** → шаги **с исходными id** → переменные (по строке на
    каждый workflow-владелец) → переменные ноды и их связи → обратная привязка
    агентов. Любая ошибка — откат, база как была.

    Совпадения на чужих записях:
    - `id` или имя workflow занято чужим workflow → 409, файл не импортируется;
    - `id` шага занят чужим workflow → все шаги файла получают новые id,
      ссылки внутри `metadata` переписывает `ai_workflow_step_refs_remap`;
    - `id` группы тем занят группой чужой ноды → все группы файла получают
      новые id, ссылки шагов переписывает `ai_workflow_topic_group_refs_remap`.

    ⚠⚠ Темы трогаются **только если файл несёт их секцию**. Файл, снятый до её
    появления, темы принимающей стороны не чистит: иначе перенос workflow
    старым файлом стирал бы чужую работу молча.
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
            topic_group_mapping = await _assign_topic_group_ids(
                db, payload['topic_groups'], target_node_id) if payload['topics_managed'] else {}

            agent_bindings = await _snapshot_agent_bindings(db, wipe)

            await _wipe_node_workflows(db, wipe)
            if payload['topics_managed']:
                await _wipe_node_topics(db, target_node_id)

            await _insert_workflows(db, workflows, target_node_id)

            topics_counted = (0, 0, 0)
            if payload['topics_managed']:
                topics_counted = await _insert_topics(
                    db, payload, target_node_id, topic_group_mapping)

            variable_id_map = await _insert_variables(
                db, payload['variables'], payload['variable_links'], set(workflow_ids))

            node_variable_id_map = await _upsert_node_variables(db, payload['node_variables'], target_node_id)
            await _insert_node_variable_links(db, payload['node_variable_links'],
                                              node_variable_id_map, set(workflow_ids))

            steps_inserted = await _insert_steps(db, payload['steps'], step_mapping,
                                                 topic_group_mapping)

            agents_rebound = await _rebind_agents(db, agent_bindings, set(workflow_ids))

            await db.connection.commit()
        except AiWorkflowImportError:
            # Штатный отказ домена (файл недостоверен или занято чужое): откат
            # и наружу, журнал ошибок не мажем — решать по статусу слою HTTP.
            await db.connection.rollback()
            raise
        except Exception as error:
            await db.connection.rollback()
            logger_exception('Импорт workflow откатан', exc=error)
            raise AiWorkflowImportFailedError(f'Импорт не удался, изменения отменены: {error}') from error

    logger_info(f'Импорт workflow: пользователь {actor}, нода '
                f'{payload["node"] and payload["node"]["name"]}, workflow {len(payload["workflows"])}, '
                f'шагов {steps_inserted}')

    notes = []
    if step_mapping:
        notes.append(f'id шагов совпадали с чужими записями — все {len(step_mapping)} '
                     f'шагов файла получили новые id, ссылки внутри шагов переписаны')
    if topic_group_mapping:
        notes.append(f'id групп тем совпадали с чужими записями — все '
                     f'{len(topic_group_mapping)} групп файла получили новые id, '
                     f'ссылки шагов на них переписаны')
    if not payload['topics_managed']:
        notes.append('В файле нет секции тем (он старше её появления) — '
                     'группы тем принимающей стороны не тронуты')
    if payload['warnings']:
        notes.extend(payload['warnings'])

    return {
        "node": payload['node']['name'] if payload['node'] else None,
        "workflows_removed": len(wipe),
        "workflows_imported": len(workflows),
        "steps_imported": steps_inserted,
        "variables_upserted": len(variable_id_map),
        "node_variables_upserted": len(node_variable_id_map),
        "topic_groups_imported": topics_counted[0],
        "topics_imported": topics_counted[1],
        "topic_questions_imported": topics_counted[2],
        "agents_rebound": agents_rebound,
        "notes": notes,
    }


def ai_workflow_import_topics_validate(data):
    """Секции тем файла — разобранные и сверенные с самим файлом.

    Три списка связаны между собой (вопрос ссылается на тему, тема на группу),
    поэтому и проверяются вместе: порознь каждый из них достоверен, а вместе
    может противоречить себе.

    ⚠⚠ Секции **необязательные**, и это не послабление валидатора. Формат
    родился без них, файлы первой версии лежат у людей на дисках, и версия
    формата та же: будь секция обязательной, старый файл перестал бы читаться.
    Отсюда правило: секции нет — тем в файле нет, и темы принимающей стороны
    импорт не трогает вовсе. Отличает их `managed`.

    ⚠ Присутствие секции проверяется **по списку**, а не по ключу: `null` или
    число в `topic_groups` — испорченный файл, и отвечать на него надо отказом
    на границе, а не падением посреди разбора.

    ⚠ Публичная, потому что читателей файла с темами два: импорт узла целиком
    (`_validate_import_payload` ниже) и импорт одних тем на вкладке «Topic &
    Action» (`ai_workflow_topic_import.py`). Вторая копия этих проверок
    разошлась бы с первой на первом же новом поле темы — и молча: непроверенное
    поле не падает, оно просто приезжает не тем.

    Args:
        data: разобранный JSON файла — своего (`rhapsodyai.workflow_topic`)
            или узлового (`rhapsodyai.workflow`): секции в обоих одни и те же.

    Returns:
        dict: `managed` — несёт ли файл секции вообще, и три проверенных списка
            `topic_groups` / `topics` / `topic_questions`.
    """
    for key in ('topic_groups', 'topics', 'topic_questions'):
        if key in data and not isinstance(data[key], list):
            raise AiWorkflowImportRejectedError(f'Поле «{key}» должно быть списком')

    topic_groups = _validate_topic_groups(data.get('topic_groups') or [])
    topics = _validate_topics(data.get('topics') or [], topic_groups)
    topic_questions = _validate_topic_questions(data.get('topic_questions') or [], topics)

    return {
        'managed': 'topic_groups' in data,
        'topic_groups': topic_groups,
        'topics': topics,
        'topic_questions': topic_questions,
    }


# ---------------------------------------------------------------------------
# Импорт: проверка входных данных
# ---------------------------------------------------------------------------

def _validate_import_payload(data):
    """Голова: форма файла и нода, каждая секция — своим валидатором.

    Всё, что можно понять до базы, понято здесь: на выходе доверенный
    payload — поля stripped и пригнаны к ширине схемы, ссылки сверены
    с самим файлом.
    """
    if not isinstance(data, dict):
        raise AiWorkflowImportRejectedError('Ожидался JSON-объект')

    if data.get('format') != WORKFLOW_EXPORT_FORMAT:
        raise AiWorkflowImportRejectedError('Файл не похож на экспорт workflow (нет метки формата)')
    if data.get('version') != WORKFLOW_EXPORT_VERSION:
        raise AiWorkflowImportRejectedError(
            f'Неизвестная версия формата: {data.get("version")} (ожидается {WORKFLOW_EXPORT_VERSION})')

    for key in ('workflows', 'steps', 'variables', 'variable_links',
                'node_variables', 'node_variable_links'):
        if not isinstance(data.get(key), list):
            raise AiWorkflowImportRejectedError(f'Поле «{key}» отсутствует или не список')

    node = None
    if data.get('node') is not None:
        raw_node = data['node']
        if not isinstance(raw_node, dict) or not ai_workflow_export_strip(raw_node.get('name')):
            raise AiWorkflowImportRejectedError('Поле «node» — объект с именем или null')
        # Имя — единственное, чему верим: id ноды на принимающей стороне свой.
        node = {'name': ai_workflow_export_strip(raw_node['name'])[:50]}

    workflows = _validate_workflows(data['workflows'])
    steps = _validate_steps(data['steps'], workflows)
    variables = _validate_variables(data['variables'])
    variable_links = _validate_variable_links(data['variable_links'], variables, workflows)
    node_variables = _validate_node_variables(data['node_variables'])
    node_variable_links = _validate_node_variable_links(data['node_variable_links'], node_variables, workflows)

    topics = ai_workflow_import_topics_validate(data)

    return {
        'node': node,
        'workflows': list(workflows.values()),
        'steps': steps,
        'variables': variables,
        'variable_links': variable_links,
        'node_variables': node_variables,
        'node_variable_links': node_variable_links,
        'topics_managed': topics['managed'],
        'topic_groups': topics['topic_groups'],
        'topics': topics['topics'],
        'topic_questions': topics['topic_questions'],
        'warnings': [str(warning) for warning in data.get('warnings') or []] if isinstance(data.get('warnings'), list) else [],
    }


def _validate_workflows(raw_workflows):
    """Workflow файла: уникальные id и имя, поля по ширине схемы.

    Returns:
        dict: id → запись в порядке файла; эти id потом вставляются дословно.
    """
    workflows = {}
    for raw in raw_workflows:
        workflow_id = _positive_id(raw.get('id'), 'workflow')
        name = _check_text(ai_workflow_export_strip(raw.get('name')), 'name workflow', max_length=50, required=True)
        title = _check_text(ai_workflow_export_strip(raw.get('title')) or '', 'title workflow', max_length=50)
        if workflow_id in workflows:
            raise AiWorkflowImportRejectedError(f'В файле два workflow с id {workflow_id}')
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
        raise AiWorkflowImportRejectedError('В файле нет ни одного workflow')

    seen_names = set()
    for workflow in workflows.values():
        if workflow['name'] in seen_names:
            raise AiWorkflowImportRejectedError(f"В файле два workflow с именем «{workflow['name']}»")
        seen_names.add(workflow['name'])
    return workflows


def _validate_steps(raw_steps, workflows):
    """Шаги: ссылка только на workflow из файла; metadata — строка, дословно."""
    steps = []
    for raw in raw_steps:
        step_id = _positive_id(raw.get('id'), 'шаг')
        if raw.get('workflow_id') not in workflows:
            raise AiWorkflowImportRejectedError(f'Шаг {step_id} ссылается на workflow вне файла')
        metadata = raw.get('metadata')
        if not isinstance(metadata, str):
            raise AiWorkflowImportRejectedError(
                f'metadata шага {step_id} должен быть строкой (переносим дословно)')
        steps.append({
            'id': step_id,
            'workflow_id': raw['workflow_id'],
            'type_name': _check_text(ai_workflow_export_strip(raw.get('type_name')), 'type_name шага', max_length=50),
            'title': _check_text(ai_workflow_export_strip(raw.get('title')) or '', 'title шага', max_length=50),
            'position': _int_or(raw.get('position'), 0),
            'metadata': metadata,
        })
    return steps


def _validate_variables(raw_variables):
    """Переменные: id файла уникален, имя — идентификатор, тип — input/workflow.

    ⚠⚠ Проверки «две переменные с одним именем и типом» здесь **больше нет**, и
    это не послабление. Переменная принадлежит одному workflow, поэтому файл с
    родителем и подпотоком, объявившими `girl_name`, обязан нести **две**
    записи с этим именем. Прежняя проверка отвергала бы собственный экспорт.

    Имя уникально внутри своего workflow, а какому оно принадлежит — знает
    связь, не запись. Там же уникальность и проверяется
    (`_validate_variable_links`).

    Собственные id в metadata не зашиты — они здесь лишь ключ связей;
    глобальные в файл не пишутся, а пришедшие из рук мимо: их заводит
    принимающая сторона.
    """
    variables, seen_ids = [], set()
    for raw in raw_variables:
        variable_file_id = _positive_id(raw.get('id'), 'переменная')
        if variable_file_id in seen_ids:
            raise AiWorkflowImportRejectedError(f'В файле две переменные с id {variable_file_id}')
        seen_ids.add(variable_file_id)
        name = _check_text(ai_workflow_export_strip(raw.get('name')), 'имя переменной', max_length=50)
        if not name or not _VARIABLE_NAME_RE.match(name):
            raise AiWorkflowImportRejectedError(f'Недопустимое имя переменной: {raw.get("name")!r}')
        var_type = raw.get('type')
        if var_type not in ('input', 'workflow'):
            raise AiWorkflowImportRejectedError(f'Переменная {name!r}: недопустимый тип {var_type!r}')
        variables.append({
            'id': variable_file_id,
            'name': name,
            'type': var_type,
            'default': raw.get('default'),
            'description': _check_text(ai_workflow_export_strip(raw.get('description')), 'description переменной', max_length=200),
        })
    return variables


def _validate_variable_links(raw_links, variables, workflows):
    """Связи переменных: оба конца — внутри файла; повтор пары — один раз.

    ⚠ Здесь же уникальность имени внутри workflow: у переменной один владелец,
    и `UNIQUE (workflow_id, name)` в схеме отверг бы вторую запись посреди
    транзакции. Отказ до базы называет обе стороны, а не «Duplicate entry».
    """
    variable_ids = {variable['id'] for variable in variables}
    name_by_id = {variable['id']: variable['name'] for variable in variables}
    links, link_pairs, seen_names = [], set(), set()
    for raw in raw_links:
        variable_id, workflow_id = raw.get('variable_id'), raw.get('workflow_id')
        if variable_id not in variable_ids:
            raise AiWorkflowImportRejectedError(f'Связь переменной {variable_id} — переменной нет в файле')
        if workflow_id not in workflows:
            raise AiWorkflowImportRejectedError(f'Связь переменной на workflow {workflow_id} — его нет в файле')
        if (variable_id, workflow_id) in link_pairs:
            continue
        name_key = (workflow_id, name_by_id[variable_id])
        if name_key in seen_names:
            raise AiWorkflowImportRejectedError(
                f'У workflow {workflow_id} две переменные с именем '
                f'{name_by_id[variable_id]} — имя внутри workflow одно')
        seen_names.add(name_key)
        link_pairs.add((variable_id, workflow_id))
        links.append((variable_id, workflow_id))
    return links


def _validate_node_variables(raw_node_variables):
    """Переменные ноды: уникальные id и имя внутри файла; тип — public или proxy."""
    node_variables, seen_names, seen_ids = [], set(), set()
    for raw in raw_node_variables:
        nv_file_id = _positive_id(raw.get('id'), 'переменная ноды')
        if nv_file_id in seen_ids:
            raise AiWorkflowImportRejectedError(f'В файле две переменные ноды с id {nv_file_id}')
        seen_ids.add(nv_file_id)
        name = _check_text(ai_workflow_export_strip(raw.get('name')), 'имя переменной ноды', max_length=50)
        if not name or not _VARIABLE_NAME_RE.match(name):
            raise AiWorkflowImportRejectedError(f'Недопустимое имя переменной ноды: {raw.get("name")!r}')
        if name in seen_names:
            raise AiWorkflowImportRejectedError(f'В файле две переменные ноды с именем {name}')
        seen_names.add(name)
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
    return node_variables


def _validate_topic_groups(raw_groups):
    """Группы тем: уникальные id и код внутри файла, поля по ширине схемы.

    Код (`name`) правке не подлежит нигде в проекте — по нему группу находят
    сиды и миграции, — поэтому здесь он обязателен: группа без кода на
    принимающей стороне окажется безымянной и неотличимой от соседней.
    """
    groups, seen_ids, seen_names = [], set(), set()
    for raw in raw_groups:
        group_id = _positive_id(raw.get('id'), 'группа тем')
        if group_id in seen_ids:
            raise AiWorkflowImportRejectedError(f'В файле две группы тем с id {group_id}')
        seen_ids.add(group_id)
        name = _check_text(ai_workflow_export_strip(raw.get('name')), 'код группы тем',
                           max_length=64, required=True)
        if name in seen_names:
            raise AiWorkflowImportRejectedError(f'В файле две группы тем с кодом «{name}»')
        seen_names.add(name)
        groups.append({
            'id': group_id,
            'name': name,
            'title': _check_text(ai_workflow_export_strip(raw.get('title')) or '',
                                 'название группы тем', max_length=255),
            'description': raw.get('description'),
            'is_enabled': 1 if _int_or(raw.get('is_enabled'), 1) else 0,
            'position': _int_or(raw.get('position'), 0),
        })
    return groups


def _validate_topics(raw_topics, topic_groups):
    """Темы: ссылка только на группу из файла, пороги — числа."""
    group_ids = {group['id'] for group in topic_groups}
    topics, seen_ids = [], set()
    for raw in raw_topics:
        topic_id = _positive_id(raw.get('id'), 'тема')
        if topic_id in seen_ids:
            raise AiWorkflowImportRejectedError(f'В файле две темы с id {topic_id}')
        seen_ids.add(topic_id)
        if raw.get('topic_group_id') not in group_ids:
            raise AiWorkflowImportRejectedError(
                f'Тема {topic_id} ссылается на группу вне файла')
        topics.append({
            'id': topic_id,
            'topic_group_id': raw['topic_group_id'],
            'name': _check_text(ai_workflow_export_strip(raw.get('name')), 'код темы',
                                max_length=64, required=True),
            'title': _check_text(ai_workflow_export_strip(raw.get('title')) or '',
                                 'название темы', max_length=255),
            'tags': raw.get('tags') or '',
            'tags_qty_accept': _int_or(raw.get('tags_qty_accept'), 1),
            'questions_qty_yes_accept': _int_or(raw.get('questions_qty_yes_accept'), 1),
            'instructions': raw.get('instructions'),
            'is_enabled': 1 if _int_or(raw.get('is_enabled'), 1) else 0,
            'position': _int_or(raw.get('position'), 0),
        })
    return topics


def _validate_topic_questions(raw_questions, topics):
    """Вопросы темы: ссылка только на тему из файла, текст обязателен."""
    topic_ids = {topic['id'] for topic in topics}
    questions, seen_ids = [], set()
    for raw in raw_questions:
        question_id = _positive_id(raw.get('id'), 'вопрос темы')
        if question_id in seen_ids:
            raise AiWorkflowImportRejectedError(f'В файле два вопроса с id {question_id}')
        seen_ids.add(question_id)
        if raw.get('topic_id') not in topic_ids:
            raise AiWorkflowImportRejectedError(
                f'Вопрос {question_id} ссылается на тему вне файла')
        text = str(raw.get('question') or '').strip()
        if not text:
            raise AiWorkflowImportRejectedError(f'Вопрос {question_id} пуст')
        questions.append({
            'id': question_id,
            'topic_id': raw['topic_id'],
            'question': text,
            'is_enabled': 1 if _int_or(raw.get('is_enabled'), 1) else 0,
            'position': _int_or(raw.get('position'), 0),
        })
    return questions


def _validate_node_variable_links(raw_links, node_variables, workflows):
    """Связи переменных ноды: оба конца — внутри файла; пары — по имени."""
    nv_id_to_name = {variable['id']: variable['name'] for variable in node_variables}
    links, seen_pairs = [], set()
    for raw in raw_links:
        nv_name = nv_id_to_name.get(raw.get('node_variable_id'))
        if not nv_name:
            raise AiWorkflowImportRejectedError(
                f'Связь переменной ноды {raw.get("node_variable_id")} — её нет в файле')
        if raw.get('workflow_id') not in workflows:
            raise AiWorkflowImportRejectedError(
                f'Связь переменной ноды на workflow {raw.get("workflow_id")} — его нет в файле')
        pair = (nv_name, raw['workflow_id'])
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            links.append(pair)
    return links


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
        raise AiWorkflowImportRejectedError(
            f"Нода «{node['name']}» не найдена — создайте её на странице нод "
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
        raise AiWorkflowImportConflictError(f'id из файла заняты чужими workflow: {listed} — импорт отменён')

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
        raise AiWorkflowImportConflictError(f'Имена workflow заняты вне заменяемой ноды: {listed} — импорт отменён')


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
    переменные workflow и связи переменных ноды снимает `CASCADE`, строки
    журнала — `SET NULL`, так и живём.

    ⚠ Переменные workflow больше не удаляются отдельной строкой: с появлением
    владельца (`agent_workflow_variable.workflow_id`) их уносит тот же внешний
    ключ, что и всё остальное на удаляемом workflow.
    """
    if not wipe:
        return
    placeholders = ','.join(['%s'] * len(wipe))
    args = tuple(wipe)
    await db.execute(f'DELETE FROM `agent_workflow_step` WHERE `workflow_id` IN ({placeholders})', args)
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


async def _insert_variables(db, variables, links, workflow_ids):
    """Переменные файла — по своей строке каждому workflow-владельцу.

    ## ⚠⚠ Строка на связь, а не строка на имя

    Раньше запись искалась по паре (имя, тип) **во всей базе**: нашлась —
    правились её поля, и workflow просто привязывался к чужой. Импорт файла с
    родителем и подпотоком сажал их на одну переменную, а с ней — и на общее
    имя: правка в одном месте меняла оба.

    Теперь у переменной один владелец, и цикл идёт **по связям**: сколько
    workflow в файле её объявили, столько строк и заведётся.

    ⚠ Ни поиска, ни обновления: ноды файла к этому моменту вычищены
    (`_wipe_node_workflows`), а внешний ключ `ON DELETE CASCADE` унёс их
    переменные вместе с ними. Чужих строк на этих workflow быть не может — их
    id заняты проверкой `_check_collisions`.

    Args:
        variables: записи файла (ключ — `id` файла).
        links: пары `(variable_id, workflow_id)` из файла.
        workflow_ids: id workflow файла — чужое сюда не попадает.

    Returns:
        dict: `(id файла, workflow_id)` → id заведённой строки.
    """
    by_file_id = {variable['id']: variable for variable in variables}
    resolved = {}
    for variable_id, workflow_id in links:
        variable = by_file_id.get(variable_id)
        if variable is None or workflow_id not in workflow_ids:
            continue
        await db.execute(
            'INSERT INTO `agent_workflow_variable` '
            '(`workflow_id`, `name`, `type`, `default`, `description`) '
            'VALUES (%s, %s, %s, %s, %s)',
            (workflow_id, variable['name'], variable['type'],
             variable['default'], variable['description'])
        )
        resolved[(variable_id, workflow_id)] = db.lastrowid
    return resolved


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


async def _assign_topic_group_ids(db, topic_groups, target_node_id):
    """Id групп тем: исходные, если свободны; иначе — всем группам файла новые.

    Политика та же, что у шагов (`_assign_step_ids`), и по той же причине: на
    номер группы ссылается `metadata` шага `topic_action`, значит номер —
    часть данных, а не служебная мелочь. Группы заменяемой ноды к этому моменту
    ещё живы, но будут удалены; опасны только группы **чужих** нод.

    ⚠ Ремап однообразный — либо все новые, либо все старые: так словарь для
    `ai_workflow_topic_group_refs_remap` остаётся согласованным с файлом.
    """
    group_ids = [group['id'] for group in topic_groups]
    if not group_ids:
        return {}

    placeholders = ','.join(['%s'] * len(group_ids))
    await db.execute(
        f'SELECT `id` FROM `agent_workflow_topic_group` '
        f'WHERE `id` IN ({placeholders}) AND NOT (`node_id` <=> %s)',
        tuple(group_ids) + (target_node_id,)
    )
    if not (await db.fetchall() or []):
        return {}

    await db.execute('SELECT COALESCE(MAX(`id`), 0) AS `max_id` '
                     'FROM `agent_workflow_topic_group` FOR UPDATE')
    next_id = (await db.fetchone() or {}).get('max_id', 0)
    mapping = {}
    for group in topic_groups:
        next_id += 1
        mapping[group['id']] = next_id
    return mapping


async def _wipe_node_topics(db, target_node_id):
    """Группы тем заменяемой ноды: темы и вопросы уносит каскад.

    ⚠ Зовётся только когда файл несёт секцию тем. Старый файл её не несёт — и
    темы принимающей стороны остаются нетронутыми, иначе импорт чужого файла
    первой версии стирал бы их молча.
    """
    if target_node_id is None:
        return
    await db.execute('DELETE FROM `agent_workflow_topic_group` WHERE `node_id` = %s',
                     (target_node_id,))


async def _insert_topics(db, payload, target_node_id, group_mapping):
    """Группы, темы и вопросы файла — в указанном порядке связей.

    Id групп сохраняются (или берутся из `group_mapping` при столкновении) —
    на них ссылаются шаги. Id тем и вопросов местные: на них не ссылается
    никто, кроме родителя, и карта связи строится здесь же.

    Returns:
        tuple: (сколько групп, сколько тем, сколько вопросов).
    """
    if target_node_id is None:
        # Псевдонода «Вне нод» групп не имеет; пришедшие из файла — мусор.
        return 0, 0, 0

    for group in payload['topic_groups']:
        await db.execute(
            'INSERT INTO `agent_workflow_topic_group` '
            '(`id`, `node_id`, `name`, `title`, `description`, `is_enabled`, `position`) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s)',
            (group_mapping.get(group['id'], group['id']), target_node_id, group['name'],
             group['title'], group['description'], group['is_enabled'], group['position'])
        )

    topic_id_map = {}
    for topic in payload['topics']:
        group_id = group_mapping.get(topic['topic_group_id'], topic['topic_group_id'])
        await db.execute(
            'INSERT INTO `agent_workflow_topic` '
            '(`topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, '
            '`questions_qty_yes_accept`, `instructions`, `is_enabled`, `position`) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (group_id, topic['name'], topic['title'], topic['tags'],
             topic['tags_qty_accept'], topic['questions_qty_yes_accept'],
             topic['instructions'], topic['is_enabled'], topic['position'])
        )
        topic_id_map[topic['id']] = db.lastrowid

    questions = 0
    for question in payload['topic_questions']:
        topic_id = topic_id_map.get(question['topic_id'])
        if topic_id is None:
            continue
        await db.execute(
            'INSERT INTO `agent_workflow_topic_question` '
            '(`topic_id`, `question`, `is_enabled`, `position`) VALUES (%s, %s, %s, %s)',
            (topic_id, question['question'], question['is_enabled'], question['position'])
        )
        questions += 1

    return len(payload['topic_groups']), len(topic_id_map), questions


async def _insert_steps(db, steps, step_mapping, topic_group_mapping=None):
    """Шаги с ремапом ссылок; тип ищется по имени — справочник местные знают свой.

    Ремап — общее знание (`ai_workflow_step_refs_remap` для шагов,
    `ai_workflow_topic_group_refs_remap` для групп тем); наша политика —
    переписывать id только при столкновении (пустой словарь → дословно).

    ⚠ Словаря два, и смешивать их нельзя: номер шага и номер группы живут в
    разных пространствах, а совпасть числом могут запросто.
    """
    if not steps:
        return 0
    await db.execute('SELECT `id`, `name` FROM `agent_workflow_step_type`')
    type_ids = {ai_workflow_export_strip(row['name']): row['id'] for row in (await db.fetchall() or [])}

    for step in steps:
        type_id = type_ids.get(step['type_name'])
        if step['type_name'] and type_id is None:
            raise AiWorkflowImportRejectedError(
                f'Неизвестный тип шага «{step["type_name"]}» — справочник типов '
                f'принимающей стороны его не знает')
        metadata = ai_workflow_step_refs_remap(step['metadata'], step_mapping)
        metadata = ai_workflow_topic_group_refs_remap(metadata, topic_group_mapping or {})
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
        raise AiWorkflowImportRejectedError(f'«{label}»: id должен быть числом, получено {value!r}')
    if parsed <= 0:
        raise AiWorkflowImportRejectedError(f'«{label}»: id должен быть положительным')
    return parsed


def _int_or(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _check_text(value, label, max_length, required=False):
    if required and not value:
        raise AiWorkflowImportRejectedError(f'«{label}»: обязательно')
    if value and len(value) > max_length:
        raise AiWorkflowImportRejectedError(f'«{label}»: длиннее {max_length} символов ({len(value)})')
    return value

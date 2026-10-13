"""
Импорт тем в ноду — кнопка «Импорт» вкладки «Topic & Action».

Читает файл тем (`ai_workflow_topic_export.py`) и **узловой** файл
(`ai_workflow_export.py`): секции в обоих одни и те же, и разбирает их общий
валидатор `ai_workflow_import_topics_validate`.

## ⚠⚠ Слияние по коду, а не замена по номеру — и это главное отличие от соседа

Импорт узла заменяет ноду целиком: чистит её workflow, шаги и группы тем и
кладёт пришедшие **с номерами из файла**. Он вправе так делать ровно потому,
что везёт шаги тоже: номер группы зашит в `metadata` шага `topic_action`, и обе
стороны ссылки приезжают из одного файла.

Здесь шагов нет. Снеси мы группу и заведи заново — шаги принимающей стороны
остались бы с номером, которого больше нет: селектор «Группа тем» пуст, шаг не
поднимает ни одной темы, и **ни одной ошибки** — ни при импорте, ни в прогоне.
Ровно эта беда уже была измерена, когда темы вовсе не ехали в файле узла
(`workflow_topic.md` §6a).

Поэтому адресация здесь — **по коду** (`name`), как у переноса между
установками миграцией: номер строки на каждой установке свой, а код один.
Группа с таким кодом есть — правится на месте, со своим номером, и шаги
продолжают смотреть туда же. Нет — заводится, и номер ей даёт автоинкремент
принимающей стороны, а не файл.

⚠⚠ **Импорт ничего не удаляет.** Группа или тема, которой нет в файле,
остаётся как была: файл — это то, что принесли, а не то, что должно остаться.
Обратное правило («чего нет в файле, того нет в ноде») стоило бы ровно тех же
молча оборванных шагов, да ещё и у тем, про которые файл ничего не утверждал.
Единственное исключение — **вопросы темы, пришедшей из файла**: они
переписываются целиком, как и в правке с формы (`_topic_questions_save`), иначе
слияние давало бы тему с двойным набором вопросов.

⚠ Нода выбирается **человеком** (карусель страницы), а не именем из файла:
полезное действие здесь — «перенести темы отсюда туда», в том числе между
нодами одной установки. Имя из файла при этом не выбрасывается: расхождение
показывается в вопросе перед нажатием и в `notes` ответа.

Ошибки — доменные, из семьи `ai_workflow_import.py`: читатель файла один и тот
же, и HTTP-слою незачем знать про два разных набора исключений.
"""

from logging_.logging_ import logger_exception, logger_info
from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow_export import (WORKFLOW_EXPORT_FORMAT,
                                       WORKFLOW_EXPORT_VERSION)
from src.ai.ai_workflow_import import (AiWorkflowImportError,
                                       AiWorkflowImportFailedError,
                                       AiWorkflowImportRejectedError,
                                       ai_workflow_import_topics_validate)
from src.ai.ai_workflow_topic_export import (WORKFLOW_TOPIC_EXPORT_FORMAT,
                                             WORKFLOW_TOPIC_EXPORT_VERSION)

# Сколько поимённых заметок показывать человеку. Дальше — счётчиком: список на
# сорок строк не читают, а ответ он загромождает.
TOPIC_IMPORT_NOTES_MAX = 10


async def ai_workflow_topic_import_apply(data, node_pk, actor):
    """Влить темы файла в ноду, сливая по коду группы и темы.

    Args:
        data: разобранный JSON файла — тем или узлового.
        node_pk: id ноды, выбранной человеком; `None` («Вне нод») — отказ.
        actor: кто импортирует, для журнала.

    Returns:
        dict: сколько групп и тем заведено и обновлено, сколько вопросов
            переписано, и `notes` — то, о чём нельзя молчать.

    Одна транзакция: ошибка на любом шаге откатывает всё.
    """
    payload = _topic_import_validate(data)

    if node_pk is None:
        raise AiWorkflowImportRejectedError(
            'Псевдонода «Вне нод» групп тем не имеет — выберите ноду в карусели')

    async with mysql_get_db_async() as db:
        try:
            await db.connection.begin()

            node_name = await _node_name(db, node_pk)
            groups_local = await _groups_local(db, node_pk)
            topics_local = await _topics_local(db, node_pk)

            group_map, groups_created, groups_updated = await _groups_merge(
                db, payload['topic_groups'], groups_local, node_pk)

            topic_map, topics_created, topics_updated, moved = await _topics_merge(
                db, payload['topics'], topics_local, group_map,
                {group['id']: (group['title'] or group['name'])
                 for group in payload['topic_groups']})

            questions = await _questions_rewrite(
                db, payload['topic_questions'], topic_map)

            await db.connection.commit()
        except AiWorkflowImportError:
            # Штатный отказ домена: откат и наружу, журнал ошибок не мажем —
            # статус выбирает слой HTTP.
            await db.connection.rollback()
            raise
        except Exception as error:
            await db.connection.rollback()
            logger_exception('Импорт тем откатан', exc=error)
            raise AiWorkflowImportFailedError(
                f'Импорт тем не удался, изменения отменены: {error}') from error

    logger_info(f'Импорт тем: пользователь {actor}, нода {node_name}, '
                f'групп {groups_created + groups_updated}, '
                f'тем {topics_created + topics_updated}, вопросов {questions}')

    return {
        'node': node_name,
        'groups_created': groups_created,
        'groups_updated': groups_updated,
        'topics_created': topics_created,
        'topics_updated': topics_updated,
        'questions_written': questions,
        'notes': _topic_import_notes(payload, node_name, groups_local, moved),
    }


# ---------------------------------------------------------------------------
# Проверка файла
# ---------------------------------------------------------------------------

def _topic_import_validate(data):
    """Форма файла и секции тем; оба формата — свой и узловой.

    ⚠ Узловой файл принимается намеренно: темы в нём те же, а у людей на дисках
    лежат именно такие файлы. Workflow из него здесь не читаются вовсе — это
    видно по ответу, где про них нет ни слова.
    """
    if not isinstance(data, dict):
        raise AiWorkflowImportRejectedError('Ожидался JSON-объект')

    known = {
        WORKFLOW_TOPIC_EXPORT_FORMAT: WORKFLOW_TOPIC_EXPORT_VERSION,
        WORKFLOW_EXPORT_FORMAT: WORKFLOW_EXPORT_VERSION,
    }
    expected = known.get(data.get('format'))
    if expected is None:
        raise AiWorkflowImportRejectedError(
            'Файл не похож ни на экспорт тем, ни на экспорт workflow (нет метки формата)')
    if data.get('version') != expected:
        raise AiWorkflowImportRejectedError(
            f'Неизвестная версия формата: {data.get("version")} (ожидается {expected})')

    topics = ai_workflow_import_topics_validate(data)
    if not topics['managed']:
        raise AiWorkflowImportRejectedError(
            'В файле нет секции тем — он снят до её появления; '
            'пересоберите файл на отдающей стороне')

    # ⚠⚠ Два одинаковых кода темы в файле — отказ, и проверка эта **наша**, а не
    # общего валидатора. Там тема адресуется номером, и один код в двух группах
    # переживаем; здесь код и есть адрес: вторая тема молча перетёрла бы первую.
    seen = {}
    for topic in topics['topics']:
        if topic['name'] in seen:
            raise AiWorkflowImportRejectedError(
                f'В файле две темы с кодом «{topic["name"]}» — слияние идёт по коду, '
                f'и различить их нечем')
        seen[topic['name']] = topic['id']

    node = data.get('node')
    return {
        'node_name': (node or {}).get('name') if isinstance(node, dict) else None,
        'topic_groups': topics['topic_groups'],
        'topics': topics['topics'],
        'topic_questions': topics['topic_questions'],
    }


def _topic_import_notes(payload, node_name, groups_local, moved):
    """То, о чём нельзя молчать: чужая нода, переезд темы, нетронутые группы."""
    notes = []

    if payload['node_name'] and payload['node_name'] != node_name:
        notes.append(f'Файл снят с ноды «{payload["node_name"]}», '
                     f'темы влиты в «{node_name}»')

    for topic_name, was, now in moved[:TOPIC_IMPORT_NOTES_MAX]:
        notes.append(f'Тема «{topic_name}» переехала из группы «{was}» в «{now}»')
    if len(moved) > TOPIC_IMPORT_NOTES_MAX:
        notes.append(f'…и ещё {len(moved) - TOPIC_IMPORT_NOTES_MAX} тем сменили группу')

    file_codes = {group['name'] for group in payload['topic_groups']}
    untouched = [name for name in groups_local if name not in file_codes]
    if untouched:
        # ⚠ Не удаляем и говорим об этом: человек, ждавший замены, иначе решил
        # бы, что импорт не сработал, — и нажал бы ещё раз.
        notes.append(f'Групп в ноде, которых нет в файле: {len(untouched)} '
                     f'({", ".join(untouched[:TOPIC_IMPORT_NOTES_MAX])}) — оставлены как были')

    return notes


# ---------------------------------------------------------------------------
# Запись
# ---------------------------------------------------------------------------

async def _node_name(db, node_pk):
    await db.execute('SELECT `name` FROM `node` WHERE `id` = %s', (node_pk,))
    row = await db.fetchone()
    if not row:
        raise AiWorkflowImportRejectedError(f'Нода {node_pk} не найдена')
    return (row['name'] or '').strip()


async def _groups_local(db, node_pk):
    """Группы ноды: код → строка. Код уникален в ноде — им и слияние."""
    await db.execute(
        'SELECT `id`, `name`, `title` FROM `agent_workflow_topic_group` '
        'WHERE `node_id` = %s ORDER BY `id`', (node_pk,))
    return {(row['name'] or '').strip(): row for row in (await db.fetchall() or [])}


async def _topics_local(db, node_pk):
    """Темы ноды: код → строка с группой. Код темы уникален в пределах НОДЫ."""
    await db.execute(
        'SELECT t.`id`, t.`name`, t.`topic_group_id`, g.`title` AS `group_title` '
        '  FROM `agent_workflow_topic` t '
        '  JOIN `agent_workflow_topic_group` g ON g.`id` = t.`topic_group_id` '
        ' WHERE g.`node_id` = %s ORDER BY t.`id`', (node_pk,))
    return {(row['name'] or '').strip(): row for row in (await db.fetchall() or [])}


async def _groups_merge(db, groups, groups_local, node_pk):
    """Группы файла в ноду: по коду — правка на месте, иначе заведение.

    ⚠⚠ Номер из файла при заведении **не используется**: он чужой, занят он
    может быть группой другой ноды, а ссылаются на него только шаги, которых в
    этом файле нет. Новый номер даёт автоинкремент принимающей стороны.

    Returns:
        tuple: (карта «номер в файле → номер в базе», заведено, обновлено).
    """
    mapping, created, updated = {}, 0, 0
    for group in groups:
        found = groups_local.get(group['name'])
        if found:
            await db.execute(
                'UPDATE `agent_workflow_topic_group` SET `title` = %s, `description` = %s, '
                '`is_enabled` = %s, `position` = %s WHERE `id` = %s',
                (group['title'], group['description'], group['is_enabled'],
                 group['position'], found['id'])
            )
            mapping[group['id']] = found['id']
            updated += 1
            continue

        await db.execute(
            'INSERT INTO `agent_workflow_topic_group` '
            '(`node_id`, `name`, `title`, `description`, `is_enabled`, `position`) '
            'VALUES (%s, %s, %s, %s, %s, %s)',
            (node_pk, group['name'], group['title'], group['description'],
             group['is_enabled'], group['position'])
        )
        mapping[group['id']] = db.lastrowid
        created += 1

    return mapping, created, updated


async def _topics_merge(db, topics, topics_local, group_map, group_titles):
    """Темы файла в ноду: по коду — правка на месте, иначе заведение.

    ⚠ Тема, уже живущая в ноде под этим кодом, **переезжает** в группу из файла,
    если та другая. Код темы уникален в пределах ноды (`_topic_name_free`), и
    оставить её на месте значило бы иметь в ноде две записи с одним кодом —
    одну в журнале прогона, другую в файле.

    Returns:
        tuple: (карта «номер темы в файле → номер в базе», заведено, обновлено,
            список переездов `(код, откуда, куда)`).
    """
    mapping, created, updated, moved = {}, 0, 0, []

    for topic in topics:
        group_id = group_map.get(topic['topic_group_id'])
        if group_id is None:
            # Валидатор это уже отверг бы; оставлено на случай, когда группу
            # файла отказались заводить — тогда и тему заводить некуда.
            raise AiWorkflowImportRejectedError(
                f'Тема «{topic["name"]}» ссылается на группу вне файла')

        found = topics_local.get(topic['name'])
        if found:
            if found['topic_group_id'] != group_id:
                moved.append((topic['name'], (found['group_title'] or '').strip(),
                              group_titles.get(topic['topic_group_id'], f'#{group_id}')))
            await db.execute(
                'UPDATE `agent_workflow_topic` SET `topic_group_id` = %s, `title` = %s, '
                '`tags` = %s, `tags_qty_accept` = %s, `questions_qty_yes_accept` = %s, '
                '`instructions` = %s, `is_enabled` = %s, `position` = %s WHERE `id` = %s',
                (group_id, topic['title'], topic['tags'], topic['tags_qty_accept'],
                 topic['questions_qty_yes_accept'], topic['instructions'],
                 topic['is_enabled'], topic['position'], found['id'])
            )
            mapping[topic['id']] = found['id']
            updated += 1
            continue

        await db.execute(
            'INSERT INTO `agent_workflow_topic` '
            '(`topic_group_id`, `name`, `title`, `tags`, `tags_qty_accept`, '
            '`questions_qty_yes_accept`, `instructions`, `is_enabled`, `position`) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (group_id, topic['name'], topic['title'], topic['tags'],
             topic['tags_qty_accept'], topic['questions_qty_yes_accept'],
             topic['instructions'], topic['is_enabled'], topic['position'])
        )
        mapping[topic['id']] = db.lastrowid
        created += 1

    return mapping, created, updated, moved


async def _questions_rewrite(db, questions, topic_map):
    """Вопросы пришедших тем — целиком заново, как при правке с формы.

    ⚠⚠ Чистятся вопросы **только тех тем, что приехали в файле**. Тема, которой
    в файле нет, своих вопросов не теряет: импорт ничего не удаляет (шапка).

    ⚠ Чистка идёт по всем пришедшим темам, а не только по тем, у кого вопросы в
    файле есть: тема без вопросов в файле — это «вопросов у неё нет», и
    оставить старые значило бы собрать тему из двух источников.
    """
    if not topic_map:
        return 0

    placeholders = ','.join(['%s'] * len(topic_map))
    await db.execute(
        f'DELETE FROM `agent_workflow_topic_question` '
        f'WHERE `topic_id` IN ({placeholders})', tuple(topic_map.values()))

    written = 0
    for question in questions:
        topic_id = topic_map.get(question['topic_id'])
        if topic_id is None:
            continue
        await db.execute(
            'INSERT INTO `agent_workflow_topic_question` '
            '(`topic_id`, `question`, `is_enabled`, `position`) VALUES (%s, %s, %s, %s)',
            (topic_id, question['question'], question['is_enabled'], question['position'])
        )
        written += 1
    return written

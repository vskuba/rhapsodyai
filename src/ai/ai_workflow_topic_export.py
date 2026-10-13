"""
Экспорт тем ноды — кнопка «Экспорт» вкладки «Topic & Action».

Зачем отдельный файл, если темы и так едут в файле узла. Узловой файл —
**замена**: он уносит с собой все workflow ноды и все её шаги, и взять из него
одни темы нельзя. А переносят их чаще, чем workflow: группа с десятком тем,
метками-иглами и вопросами — работа ручная и длинная, и она нужна соседней
установке (или соседней ноде) без того, чтобы увозить туда разговор целиком.

Файл свой и меткой отличается от узлового (`rhapsodyai.workflow_topic`). Читает
его `POST /workflow_topic/import` (`ai_workflow_topic_import.py`), и он же
читает узловой файл — секции тем в обоих одни и те же, собирает их общая
`ai_workflow_export_topics_fetch`.

⚠⚠ **Номера групп в файле есть, но принимающая сторона их не использует.**
Темы сливаются по коду (`name`), а не по номеру: номер группы зашит в
`metadata` шага `topic_action`, и подменить его на той стороне значило бы
оборвать живые шаги — молча, без единой ошибки. Почему именно так — в шапке
`ai_workflow_topic_import.py`. Номера едут ради одного: внутри файла по ним
читается связь «вопрос → тема → группа».

⚠ Псевдонода «Вне нод» групп тем не имеет: колонка `node_id` у группы
обязательна. Экспорт для неё — отказ, а не пустой файл: пустой выглядел бы как
«тем нет», хотя вопрос был задан месту, где их не бывает.
"""

from datetime import datetime, timezone

from mysql_.mysql_ import mysql_get_db_async
from src.ai.ai_workflow_export import (ai_workflow_export_strip,
                                       ai_workflow_export_topics_fetch)

WORKFLOW_TOPIC_EXPORT_FORMAT = 'rhapsodyai.workflow_topic'
WORKFLOW_TOPIC_EXPORT_VERSION = 1


class AiWorkflowTopicExportError(RuntimeError):
    """Экспорт тем не удался. HTTP-слой решает, во что это превратить."""


class AiWorkflowTopicExportNodeMissingError(AiWorkflowTopicExportError):
    """Ноды с таким id на этой установке нет — экспортировать нечего."""


async def ai_workflow_topic_export_payload(node_pk):
    """Собрать файл тем ноды: группы, темы, вопросы — тремя списками.

    Args:
        node_pk: id ноды. `None` (псевдонода «Вне нод») — отказ: групп тем
            у неё не бывает.

    Returns:
        dict: пригоден для `POST /workflow_topic/import` как есть.
    """
    if node_pk is None:
        raise AiWorkflowTopicExportNodeMissingError(
            'Псевдонода «Вне нод» групп тем не имеет — экспортировать нечего')

    async with mysql_get_db_async() as db:
        await db.execute('SELECT `name` FROM `node` WHERE `id` = %s', (node_pk,))
        node = await db.fetchone()
        if not node:
            raise AiWorkflowTopicExportNodeMissingError(f'Нода {node_pk} не найдена')

        groups, topics, questions = await ai_workflow_export_topics_fetch(db, node_pk)

    return {
        'format': WORKFLOW_TOPIC_EXPORT_FORMAT,
        'version': WORKFLOW_TOPIC_EXPORT_VERSION,
        'exported_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        # Имя ноды — не адрес, а подпись: импорт кладёт темы в ту ноду, которую
        # человек выбрал в карусели. Имя из файла показывается ему в вопросе,
        # чтобы «не та нода» была видна до нажатия, а не после.
        'node': {'name': ai_workflow_export_strip(node['name'])},
        'topic_groups': groups,
        'topics': topics,
        'topic_questions': questions,
    }

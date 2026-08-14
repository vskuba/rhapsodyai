"""
Цели задачи для workflow QA: взять цель по номеру и отметить её проверенной.

Пара инструментов для цикла «проверь цели по одной»: `task_goal_pick` выдаёт
очередную цель, `task_goal_mark` записывает по ней вердикт. Галочка в колонке
«Цели» на `/admin/task` появляется только здесь — то есть только у цели, по
которой QA дал отдельный ответ с доказательством. Закрывать список целиком
одним махом нельзя: это показывало бы человеку проверку, которой не было.
"""
import json

from mysql_.mysql_ import mysql_get_db_async

# Доказательство пишет живой Claude Code, и в него легко попадает весь вывод
# команды. В JSON целей нужен след проверки, а не лог, поэтому режем.
TASK_GOAL_EVIDENCE_MAX_CHARS = 500


async def task_goal_pick(task_id: int, index: int = 0) -> dict:
    """
    Берёт цель задачи по порядковому номеру — шаг цикла проверки целей.
     - task_id: ID задачи или подзадачи (project_task.id), чьи цели проверяем
     - index: номер цели, считая с нуля
    Returns:
        dict: Очередная цель, содержащая:
            goal_has (str): yes — цель есть, no — цели кончились (или их нет вовсе).
            goal_text (str): формулировка цели.
            goal_index (int): номер цели с нуля — его же передавать в task_goal_mark.
            goal_number (int): номер цели с единицы, для текста промпта.
            goal_total (int): сколько всего целей у задачи.
    """
    task_id, index = int(task_id or 0), int(index or 0)
    goals = await _goals_load(task_id)

    if index < 0 or index >= len(goals):
        return {'goal_has': 'no', 'goal_text': '', 'goal_index': index,
                'goal_number': index + 1, 'goal_total': len(goals)}

    return {'goal_has': 'yes', 'goal_text': str(goals[index].get('text') or ''),
            'goal_index': index, 'goal_number': index + 1, 'goal_total': len(goals)}


async def task_goal_mark(task_id: int, index: int = 0, done: str = '', evidence: str = '') -> dict:
    """
    Отмечает цель проверенной по итогу отдельного ответа QA.
     - task_id: ID задачи или подзадачи (project_task.id)
     - index: номер цели, считая с нуля — тот же, что выдал task_goal_pick
     - done: yes — цель проверена и закрыта; любое другое значение — не закрыта
     - evidence: чем проверена: команда или действие и наблюдаемый результат
    Returns:
        dict: Состояние списка целей после отметки, содержащее:
            goal_done_count (int): сколько целей закрыто.
            goal_open_count (int): сколько целей осталось незакрытыми.
            goal_total (int): сколько всего целей.
            goals_summary (str): весь список целей с отметками — для промпта вердикта.
            goals_open_text (str): незакрытые цели одной строкой — для текста отказа.
    """
    task_id, index = int(task_id or 0), int(index or 0)
    goals = await _goals_load(task_id)

    if 0 <= index < len(goals):
        goals[index]['done'] = str(done or '').strip().lower() in ('yes', 'true', '1', 'да')
        evidence = str(evidence or '').strip()[:TASK_GOAL_EVIDENCE_MAX_CHARS]
        if evidence:
            goals[index]['evidence'] = evidence
        async with mysql_get_db_async() as db:
            await db.execute('UPDATE project_task SET goals = %s WHERE id = %s',
                             (json.dumps(goals, ensure_ascii=False), task_id))

    done_count = sum(1 for g in goals if g.get('done'))
    return {'goal_done_count': done_count, 'goal_open_count': len(goals) - done_count,
            'goal_total': len(goals), 'goals_summary': _goals_summary(goals),
            'goals_open_text': _goals_open_text(goals)}


async def _goals_load(task_id: int) -> list[dict]:
    """Цели задачи как список словарей. Битый и пустой JSON — пустой список."""
    if not task_id:
        return []

    async with mysql_get_db_async() as db:
        await db.execute('SELECT goals FROM project_task WHERE id = %s', (task_id,))
        row = await db.fetchone()

    try:
        goals = json.loads(str((row or {}).get('goals') or '') or '[]')
    except (ValueError, TypeError):
        return []
    if not isinstance(goals, list):
        return []

    return [g if isinstance(g, dict) else {'text': str(g or ''), 'done': False} for g in goals]


def _goals_summary(goals: list[dict]) -> str:
    """Список целей с отметками — вердикту нужен весь итог, а не последняя цель."""
    lines = []
    for i, goal in enumerate(goals, 1):
        mark = 'закрыта' if goal.get('done') else 'НЕ закрыта'
        text = str(goal.get('text') or '').strip()
        evidence = str(goal.get('evidence') or '').strip()
        lines.append(f'{i}. [{mark}] {text}' + (f' — {evidence}' if evidence else ''))
    return '\n'.join(lines)


def _goals_open_text(goals: list[dict]) -> str:
    """
    Незакрытые цели одной строкой.

    Строку подставляют внутрь JSON-ответа workflow, поэтому ни переводов строк,
    ни двойных кавычек в ней быть не должно — иначе отказ QA приедет в конвейер
    битым JSON-ом и подзадача получит «QA вернул не JSON» вместо причины.
    """
    texts = []
    for goal in goals:
        if goal.get('done'):
            continue
        text = ' '.join(str(goal.get('text') or '').replace('"', "'").split()).strip()
        if text:
            texts.append(text)
    return '; '.join(texts)

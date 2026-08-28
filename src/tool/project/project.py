import re

from mysql_.mysql_ import mysql_get_db_async
from src.project.team.team_llm_pool import team_llm_pool_forget
from src.project.team.team_shell_pool import team_shell_pool_forget

_PHASES_CONTEXT_RECENT_COUNT = 2
_PHASES_CONTEXT_OLDER_MAX_CHARS = 1500


async def project_load(project_id: int) -> dict:
    """
    Загружает проект и все завершённые фазы анализа для передачи в LLM-воркфлоу.
     - project_id: ID проекта из таблицы project
    Returns:
        dict: Данные проекта, содержащий:
            idea (str): текст исходной идеи продукта.
            phases_context (str): завершённые фазы в формате Markdown.
                Последние 2 фазы — полный текст; более ранние усечены до 1500 символов.
    """
    project_id = int(project_id)

    async with mysql_get_db_async() as db:
        await db.execute('SELECT idea FROM project WHERE id = %s', (project_id,))
        row = await db.fetchone()
        await db.execute(
            "SELECT phase, result FROM project_planning_phase WHERE project_id = %s AND status = 'complete' ORDER BY id ASC",
            (project_id,)
        )
        phases = await db.fetchall()

    idea = str((row or {}).get('idea', '') or '')

    if not phases:
        return {'idea': idea, 'phases_context': ''}

    total = len(phases)
    parts = []
    for i, p in enumerate(phases):
        phase_name = str(p.get('phase') or '')
        result = str(p.get('result') or '')
        if not result:
            continue
        is_recent = i >= total - _PHASES_CONTEXT_RECENT_COUNT
        if not is_recent and len(result) > _PHASES_CONTEXT_OLDER_MAX_CHARS:
            result = result[:_PHASES_CONTEXT_OLDER_MAX_CHARS] + f'\n\n...(сокращено, полный текст {len(result)} символов)'
        parts.append(f'## Phase: {phase_name}\n\n{result}')

    return {'idea': idea, 'phases_context': '\n\n---\n\n'.join(parts)}


async def project_create(title: str, idea: str) -> dict:
    """
    Создаёт новый проект планирования — сохраняет идею в очередь для AI-анализа.
     - title: краткое название проекта (если пустое — берётся из первых 80 символов идеи)
     - idea: полный текст идеи продукта
    Returns:
        dict: Результат создания, содержащий:
            project_id (int): ID созданного проекта.
            title (str): итоговое название проекта.
    """
    idea = str(idea or '').strip()
    title = str(title or '').strip() or idea[:80]

    if not idea:
        return {'project_id': 0, 'title': ''}

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            INSERT INTO project (node_id, user_id, title, idea, status, phase_current)
            VALUES (9, 1, %s, %s, 'pending', '')
            """,
            (title, idea)
        )
        await db.connection.commit()
        project_id = int(db.lastrowid)

    # Карточки команды заводим сразу: блок проекта на `/admin/team` рисуется по
    # строкам `project_team`, и без них новый проект встретит человека пустыми
    # ролями без команды запуска.
    from src.project.team.team_member import team_member_cards_ensure
    await team_member_cards_ensure(project_id)

    from src.worker.project.planning_worker import planning_worker_enqueue
    planning_worker_enqueue(project_id)

    return {'project_id': project_id, 'title': title}


async def project_delete(project_id: int) -> dict:
    """
    Deletes a planning project and all its phases and documents.
    Returns:
        dict containing:
            deleted (int): 1 if deleted, 0 if not found.
            project_id (int): ID of the deleted project.
            title (str): title of the deleted project.
    """
    project_id_raw = str(project_id or '').strip()
    try:
        project_id = int(project_id_raw)
    except (ValueError, TypeError):
        project_id = 0
    if project_id <= 0 and project_id_raw:
        project_id = await _project_id_by_chip(project_id_raw)
    if project_id <= 0:
        return {'deleted': 0, 'project_id': 0, 'title': ''}

    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, title FROM project WHERE id = %s', (project_id,))
        row = await db.fetchone()

    if not row:
        return {'deleted': 0, 'project_id': project_id, 'title': ''}

    title = str(row.get('title') or '')

    async with mysql_get_db_async() as db:
        await db.execute(
            "UPDATE project_planning_phase SET status='cancelled' WHERE project_id=%s AND status='running'",
            (project_id,)
        )
        await db.execute('DELETE FROM project_planning_phase WHERE project_id = %s', (project_id,))
        await db.execute('DELETE FROM project_planning_document WHERE project_id = %s', (project_id,))
        # Задачи проекта — явно: FK на `project` у `project_task` нет, только на
        # родительскую строку. Иначе задачи остаются числиться за удалённым проектом
        # и не попадают ни в один разрез страницы, которая строится от списка проектов.
        # Номера собираем до удаления: по ним снимаем захваты модели и оболочки —
        # каскад про них не знает (см. `team_llm_pool_forget`).
        await db.execute('SELECT id FROM project_task WHERE project_id = %s', (project_id,))
        task_ids = [int(row['id']) for row in await db.fetchall() or []]
        await db.execute('DELETE FROM project_task WHERE parent_id IS NOT NULL AND project_id = %s',
                         (project_id,))
        await db.execute('DELETE FROM project_task WHERE project_id = %s', (project_id,))
        await db.execute('DELETE FROM project WHERE id = %s', (project_id,))
        await db.connection.commit()

    await team_llm_pool_forget(task_ids)
    await team_shell_pool_forget(task_ids)

    return {'deleted': 1, 'project_id': project_id, 'title': title}


async def _project_id_by_chip(chip_text: str) -> int:
    clean = re.sub(r'^[^\wЀ-ӿ]+', '', chip_text, flags=re.UNICODE).strip()
    clean = re.sub(r'\s*\(\d+%[^)]*\)\s*$', '', clean).strip()
    if not clean:
        return 0
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id FROM project WHERE title = %s LIMIT 1', (clean,))
        row = await db.fetchone()
    return int(row['id']) if row else 0

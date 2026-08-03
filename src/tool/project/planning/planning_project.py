import json
import re

from mysql_.mysql_ import mysql_get_db_async

_TOTAL_PHASES = 7  # analyze, market, product, tech, gtm, financial, blueprint


async def planning_project_list(limit: int = 15) -> dict:
    """
    Returns recent planning projects as clickable title chips with progress info.
    Returns:
        dict containing:
            display_str (str): markdown table with project rows.
            id_chips (str): empty string (kept for output_map compatibility).
            count (int): number of projects returned.
    """
    limit = max(1, min(int(limit or 15), 50))

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            SELECT
                p.id, p.title, p.status, p.created_at,
                COUNT(CASE WHEN ph.status = 'complete'
                           AND ph.phase NOT LIKE 'supplement_%%' THEN 1 END) AS phases_done,
                MAX(CASE WHEN ph.status = 'complete'
                         AND ph.phase NOT LIKE 'supplement_%%' THEN ph.completed_at END) AS last_phase_done
            FROM project p
            LEFT JOIN project_planning_phase ph ON ph.project_id = p.id
            GROUP BY p.id, p.title, p.status, p.created_at
            ORDER BY p.id DESC
            LIMIT %s
            """,
            (limit,)
        )
        rows = await db.fetchall()

    if not rows:
        return {'display_str': '', 'id_chips': '', 'count': 0}

    status_icons = {'pending': '⏳', 'running': '🔄', 'complete': '✅', 'failed': '❌'}
    table_rows = []

    for r in rows:
        icon = status_icons.get(str(r.get('status') or ''), '•')
        title = str(r.get('title') or '')
        status = str(r.get('status') or '')
        phases_done = int(r.get('phases_done') or 0)
        pid = int(r.get('id') or 0)
        chip = f'[[{icon} {title}]]'

        if status == 'complete':
            table_rows.append((pid, chip, '✅ Завершён · 100%'))
            continue

        pct = int(phases_done / _TOTAL_PHASES * 100)
        remaining = _TOTAL_PHASES - phases_done

        eta_str = ''
        if phases_done > 0 and remaining > 0:
            created_at = r.get('created_at')
            last_done = r.get('last_phase_done')
            if created_at and last_done:
                try:
                    elapsed_min = (last_done - created_at).total_seconds() / 60
                    if elapsed_min > 0:
                        avg_min = elapsed_min / phases_done
                        eta_str = f' · {_format_eta(avg_min * remaining)}'
                except Exception:
                    pass

        status_label = {'pending': 'Ожидает', 'running': '🔄 В процессе', 'failed': '❌ Ошибка'}.get(status, status)
        progress_info = f'{status_label} · {pct}%{eta_str}'
        table_rows.append((pid, chip, progress_info))

    header = '| ID | Проект | Статус |\n|:--|:-------|:-------|'
    body = '\n'.join(f'| {pid} | {chip} | {status} |' for pid, chip, status in table_rows)

    return {
        'display_str': f'{header}\n{body}',
        'id_chips': '',
        'count': len(rows),
    }


async def planning_project_status_get(project_id: int) -> dict:
    """
    Возвращает статус проекта, завершённые фазы и список документов.
     - project_id: ID проекта из таблицы project
    Returns:
        dict: Статус проекта, содержащий:
            project (dict): основные поля проекта (id, title, status, phase_current).
            phases (list): список фаз с полями phase, status, completed_at.
            documents (list): список документов с полями doc_type, title, doc_id.
    """
    project_id = int(project_id)

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, title, status, phase_current, created_at FROM project WHERE id = %s',
            (project_id,)
        )
        project = await db.fetchone()

    if not project:
        return {'project': None, 'phases': [], 'documents': []}

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT phase, status, completed_at FROM project_planning_phase WHERE project_id = %s ORDER BY id ASC',
            (project_id,)
        )
        phases = list(await db.fetchall() or [])

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id as doc_id, doc_type, title FROM project_planning_document WHERE project_id = %s ORDER BY id ASC',
            (project_id,)
        )
        documents = list(await db.fetchall() or [])

    return {
        'project': dict(project),
        'phases': [dict(p) for p in phases],
        'documents': [dict(d) for d in documents],
    }


async def planning_project_score_save(project_id: int, score_market, score_feasibility, score_financial,
                              score_verdict: str, score_investment: str,
                              score_time_to_market: str, score_summary: str) -> dict:
    """
    Сохраняет оценки Blueprint в project.
     - project_id: ID проекта
     - score_market: оценка рынка 1-10
     - score_feasibility: оценка реализуемости 1-10
     - score_financial: оценка финансовой модели 1-10
     - score_verdict: go | maybe | no
     - score_investment: строка с оценкой инвестиций
     - score_time_to_market: строка со временем до продаж
     - score_summary: 2-3 предложения с ключевыми инсайтами
    Returns:
        dict: saved (int) 1 — сохранено.
    """
    project_id = int(project_id)
    try:
        sm = max(1, min(10, int(score_market)))
        sf = max(1, min(10, int(score_feasibility)))
        sfi = max(1, min(10, int(score_financial)))
    except (ValueError, TypeError):
        sm = sf = sfi = 5
    total = round((sm + sf + sfi) / 3)
    verdict = str(score_verdict or '').strip().lower()
    if verdict not in ('go', 'maybe', 'no'):
        verdict = 'maybe'
    async with mysql_get_db_async() as db:
        await db.execute(
            """UPDATE project SET
               score_market=%s, score_feasibility=%s, score_financial=%s, score_total=%s,
               score_verdict=%s, score_investment=%s, score_time_to_market=%s, score_summary=%s
               WHERE id=%s""",
            (sm, sf, sfi, total, verdict,
             str(score_investment or '')[:100], str(score_time_to_market or '')[:100],
             str(score_summary or ''), project_id)
        )
        await db.connection.commit()
    return {'saved': 1}


async def planning_project_bot_action(action: str, title: str, idea: str, project_id) -> dict:
    """
    Единый диспетчер действий Planning Bot: создаёт проект или возвращает статус.
     - action: намерение пользователя — create | status | info
     - title: название проекта (для action=create)
     - idea: текст идеи (для action=create)
     - project_id: ID проекта (для action=status)
    Returns:
        dict: Результат, содержащий:
            result_type (str): тип результата — created | status | info.
            project_id (int): ID созданного или запрошенного проекта.
            title (str): название проекта.
            status (str): статус проекта (для action=status).
            phase_current (str): текущая фаза (для action=status).
            phases_summary (str): краткое Markdown-резюме фаз (для action=status).
            documents_summary (str): краткое Markdown-резюме документов (для action=status).
    """
    action = str(action or '').strip().lower()
    title = str(title or '').strip()
    idea = str(idea or '').strip()
    project_id_raw = str(project_id or '').strip()
    try:
        project_id = int(project_id_raw)
    except (ValueError, TypeError):
        project_id = 0

    if action == 'create' and idea:
        result = await project_create(title, idea)
        return {
            'result_type': 'created',
            'project_id': result['project_id'],
            'title': result['title'],
            'status': 'pending',
            'phase_current': '',
            'phases_summary': '',
            'documents_summary': '',
        }

    if action == 'status':
        if project_id <= 0 and project_id_raw:
            project_id = await _planning_project_id_by_chip(project_id_raw)
    if action == 'status' and project_id > 0:
        data = await planning_project_status_get(project_id)
        project = data.get('project') or {}
        phases = data.get('phases') or []
        documents = data.get('documents') or []

        phase_lines = []
        for p in phases:
            icon = {'complete': '✅', 'running': '🔄', 'pending': '⏳', 'failed': '❌'}.get(p.get('status', ''), '•')
            phase_lines.append(f"{icon} {p.get('phase')} — {p.get('status')}")

        doc_lines = [
            f"[[link:/planning/document/{d.get('doc_id')}/download|📄 {d.get('doc_type')}: {d.get('title')}]]"
            for d in documents
        ]

        return {
            'result_type': 'status',
            'project_id': project_id,
            'title': str(project.get('title') or ''),
            'status': str(project.get('status') or ''),
            'phase_current': str(project.get('phase_current') or ''),
            'phases_summary': '\n'.join(phase_lines) if phase_lines else 'Фазы ещё не запущены',
            'documents_summary': '\n'.join(doc_lines) if doc_lines else 'Документы ещё не готовы',
        }

    return {
        'result_type': 'info',
        'project_id': 0,
        'title': '',
        'status': '',
        'phase_current': '',
        'phases_summary': '',
        'documents_summary': '',
    }


def _format_eta(minutes: float) -> str:
    if minutes < 1:
        return '<1мин'
    if minutes < 60:
        return f'~{int(minutes)}мин'
    return f'~{minutes / 60:.1f}ч'


async def _planning_project_id_by_chip(chip_text: str) -> int:
    """Look up project ID from a title chip like '⏳ My Project (57% · ~45мин)'."""
    clean = re.sub(r'^[^\wЀ-ӿ]+', '', chip_text, flags=re.UNICODE).strip()
    clean = re.sub(r'\s*\(\d+%[^)]*\)\s*$', '', clean).strip()
    if not clean:
        return 0
    async with mysql_get_db_async() as db:
        await db.execute('SELECT id FROM project WHERE title = %s LIMIT 1', (clean,))
        row = await db.fetchone()
    return int(row['id']) if row else 0

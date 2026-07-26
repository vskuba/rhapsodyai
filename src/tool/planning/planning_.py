import re

from mysql_.mysql_ import mysql_get_db_async


async def planning_project_load(project_id: int) -> dict:
    """
    Загружает проект и все завершённые фазы анализа для передачи в LLM-воркфлоу.
     - project_id: ID проекта из таблицы planning_project
    Returns:
        dict: Данные проекта, содержащий:
            idea (str): текст исходной идеи продукта.
            phases_context (str): все завершённые фазы в формате Markdown (пустая строка если фаз нет).
    """
    project_id = int(project_id)

    async with mysql_get_db_async() as db:
        await db.execute('SELECT idea FROM planning_project WHERE id = %s', (project_id,))
        row = await db.fetchone()

    idea = str((row or {}).get('idea', '') or '')

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT phase, result FROM planning_phase WHERE project_id = %s AND status = 'complete' ORDER BY id ASC",
            (project_id,)
        )
        phases = await db.fetchall()

    if not phases:
        return {'idea': idea, 'phases_context': ''}

    parts = []
    for p in phases:
        phase_name = str(p.get('phase') or '')
        result = str(p.get('result') or '')
        if result:
            parts.append(f'## Phase: {phase_name}\n\n{result}')

    return {'idea': idea, 'phases_context': '\n\n---\n\n'.join(parts)}


async def planning_phase_save(project_id: int, phase: str, result: str) -> dict:
    """
    Сохраняет результат фазы анализа в таблицу planning_phase.
     - project_id: ID проекта
     - phase: имя фазы (analyze | market | product | tech | gtm | financial | blueprint | supplement_*)
     - result: содержимое фазы (Markdown-текст)
    Returns:
        dict: Результат сохранения, содержащий:
            saved (int): 1 — сохранено, 0 — ошибка.
    """
    project_id = int(project_id)
    phase = str(phase or '').strip()
    result = str(result or '').strip()

    if not phase or not result:
        return {'saved': 0}

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            INSERT INTO planning_phase (project_id, phase, status, result, started_at, completed_at)
            VALUES (%s, %s, 'complete', %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                status = 'complete',
                result = VALUES(result),
                completed_at = NOW()
            """,
            (project_id, phase, result)
        )
        await db.connection.commit()

        # обновить phase_current в проекте
        await db.execute(
            'UPDATE planning_project SET phase_current = %s, updated_at = NOW() WHERE id = %s',
            (phase, project_id)
        )
        await db.connection.commit()

    return {'saved': 1}


async def planning_document_save(project_id: int, doc_type: str, title: str, content: str) -> dict:
    """
    Сохраняет сгенерированный документ (Blueprint или Supplement) в таблицу planning_document.
     - project_id: ID проекта
     - doc_type: тип документа (blueprint | market | product | tech | gtm | financial | launch)
     - title: заголовок документа
     - content: содержимое документа (Markdown)
    Returns:
        dict: Результат сохранения, содержащий:
            saved (int): 1 — сохранено, 0 — ошибка.
            doc_id (int): ID созданного / обновлённого документа.
    """
    project_id = int(project_id)
    doc_type = str(doc_type or '').strip()
    title = str(title or '').strip() or doc_type
    content = str(content or '').strip()

    if not doc_type or not content:
        return {'saved': 0, 'doc_id': 0}

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id FROM planning_document WHERE project_id = %s AND doc_type = %s LIMIT 1',
            (project_id, doc_type)
        )
        existing = await db.fetchone()

        if existing:
            doc_id = int(existing['id'])
            await db.execute(
                "UPDATE planning_document SET title = %s, content = %s, version = version + 1, status = 'final', updated_at = NOW() WHERE id = %s",
                (title, content, doc_id)
            )
        else:
            await db.execute(
                "INSERT INTO planning_document (project_id, doc_type, title, content, status) VALUES (%s, %s, %s, %s, 'final')",
                (project_id, doc_type, title, content)
            )
            doc_id = db.lastrowid

        await db.connection.commit()

        # если blueprint — отметить проект как complete
        if doc_type == 'blueprint':
            await db.execute(
                "UPDATE planning_project SET status = 'complete', updated_at = NOW() WHERE id = %s",
                (project_id,)
            )
            await db.connection.commit()

    return {'saved': 1, 'doc_id': doc_id}


_TOTAL_PHASES = 7  # analyze, market, product, tech, gtm, financial, blueprint


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
        await db.execute('SELECT id FROM planning_project WHERE title = %s LIMIT 1', (clean,))
        row = await db.fetchone()
    return int(row['id']) if row else 0


async def planning_bot_action(action: str, title: str, idea: str, project_id) -> dict:
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
        result = await planning_project_create(title, idea)
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
        data = await planning_status_get(project_id)
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


async def planning_projects_list(limit: int = 15) -> dict:
    """
    Returns recent planning projects as clickable title chips with progress info.
    Returns:
        dict containing:
            display_str (str): always empty (kept for output_map compatibility).
            id_chips (str): newline-separated chips [[icon title (pct% · ETA)]] per project.
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
            FROM planning_project p
            LEFT JOIN planning_phase ph ON ph.project_id = p.id
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
    display_str = f'{header}\n{body}'

    return {
        'display_str': display_str,
        'id_chips': '',
        'count': len(rows),
    }


async def planning_project_delete(project_id: int) -> dict:
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
        project_id = await _planning_project_id_by_chip(project_id_raw)
    if project_id <= 0:
        return {'deleted': 0, 'project_id': 0, 'title': ''}

    async with mysql_get_db_async() as db:
        await db.execute('SELECT id, title FROM planning_project WHERE id = %s', (project_id,))
        row = await db.fetchone()

    if not row:
        return {'deleted': 0, 'project_id': project_id, 'title': ''}

    title = str(row.get('title') or '')

    async with mysql_get_db_async() as db:
        # cancel any running phases so in-flight cronicle jobs fail fast
        await db.execute(
            "UPDATE planning_phase SET status='cancelled' WHERE project_id=%s AND status='running'",
            (project_id,)
        )
        await db.execute('DELETE FROM planning_phase WHERE project_id = %s', (project_id,))
        await db.execute('DELETE FROM planning_document WHERE project_id = %s', (project_id,))
        await db.execute('DELETE FROM planning_project WHERE id = %s', (project_id,))
        await db.connection.commit()

    return {'deleted': 1, 'project_id': project_id, 'title': title}


async def planning_project_create(title: str, idea: str) -> dict:
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
            INSERT INTO planning_project (node_id, user_id, title, idea, status, phase_current)
            VALUES (9, 1, %s, %s, 'pending', '')
            """,
            (title, idea)
        )
        await db.connection.commit()
        project_id = int(db.lastrowid)

    return {'project_id': project_id, 'title': title}


async def planning_status_get(project_id: int) -> dict:
    """
    Возвращает статус проекта, завершённые фазы и список документов.
     - project_id: ID проекта из таблицы planning_project
    Returns:
        dict: Статус проекта, содержащий:
            project (dict): основные поля проекта (id, title, status, phase_current).
            phases (list): список фаз с полями phase, status, completed_at.
            documents (list): список документов с полями doc_type, title, doc_id.
    """
    project_id = int(project_id)

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id, title, status, phase_current, created_at FROM planning_project WHERE id = %s',
            (project_id,)
        )
        project = await db.fetchone()

    if not project:
        return {'project': None, 'phases': [], 'documents': []}

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT phase, status, completed_at FROM planning_phase WHERE project_id = %s ORDER BY id ASC',
            (project_id,)
        )
        phases = list(await db.fetchall() or [])

    async with mysql_get_db_async() as db:
        await db.execute(
            'SELECT id as doc_id, doc_type, title FROM planning_document WHERE project_id = %s ORDER BY id ASC',
            (project_id,)
        )
        documents = list(await db.fetchall() or [])

    return {
        'project': dict(project),
        'phases': [dict(p) for p in phases],
        'documents': [dict(d) for d in documents],
    }

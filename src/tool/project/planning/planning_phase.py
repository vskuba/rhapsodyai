import json
import re

from mysql_.mysql_ import mysql_get_db_async

_SUPPLEMENT_PHASE_MAP = {
    'market':    'market',
    'product':   'product',
    'tech':      'tech',
    'gtm':       'gtm',
    'financial': 'financial',
    'launch':    'analyze',
}


async def planning_phase_blueprint_load(project_id: int) -> dict:
    """
    Загружает Blueprint-документ проекта для передачи в LLM-воркфлоу оценки.
     - project_id: ID проекта из таблицы project
    Returns:
        dict: Данные Blueprint, содержащий:
            blueprint_content (str): полный текст Blueprint (пустая строка если не готов).
            project_title (str): название проекта.
    """
    project_id = int(project_id)
    async with mysql_get_db_async() as db:
        await db.execute("SELECT title FROM project WHERE id = %s", (project_id,))
        proj = await db.fetchone()
        await db.execute(
            "SELECT content FROM project_planning_document WHERE project_id = %s AND doc_type = 'blueprint' ORDER BY id DESC LIMIT 1",
            (project_id,)
        )
        doc = await db.fetchone()
    return {
        'blueprint_content': str((doc or {}).get('content') or ''),
        'project_title': str((proj or {}).get('title') or ''),
    }


async def planning_phase_supplement_context_load(project_id: int, supplement_type: str) -> dict:
    """
    Загружает оптимальный контекст для supplement-агента: blueprint + одна релевантная фаза.
     - project_id: ID проекта из таблицы project
     - supplement_type: тип дополнения (market | product | tech | gtm | financial | launch)
    Returns:
        dict: Контекст для supplement-агента, содержащий:
            blueprint_content (str): полный Blueprint.
            phase_content (str): результат релевантной фазы.
            phase_name (str): имя загруженной фазы.
            idea (str): исходный текст идеи проекта.
            project_title (str): название проекта.
            supplement_type (str): тип дополнения (эхо входного параметра).
            phases_context (str): blueprint + фаза в Markdown (drop-in замена project_load).
    """
    project_id = int(project_id)
    supplement_type = str(supplement_type or '').strip().lower()
    phase_name = _SUPPLEMENT_PHASE_MAP.get(supplement_type, 'analyze')

    async with mysql_get_db_async() as db:
        await db.execute("SELECT title, idea FROM project WHERE id = %s", (project_id,))
        proj = await db.fetchone()

        await db.execute(
            "SELECT content FROM project_planning_document WHERE project_id = %s AND doc_type = 'blueprint' ORDER BY id DESC LIMIT 1",
            (project_id,)
        )
        blueprint_doc = await db.fetchone()

        await db.execute(
            "SELECT result FROM project_planning_phase WHERE project_id = %s AND phase = %s AND status = 'complete' LIMIT 1",
            (project_id, phase_name)
        )
        phase_row = await db.fetchone()

    blueprint_content = str((blueprint_doc or {}).get('content') or '')
    phase_content     = str((phase_row or {}).get('result') or '')
    idea              = str((proj or {}).get('idea') or '')
    project_title     = str((proj or {}).get('title') or '')

    parts = []
    if blueprint_content:
        parts.append(f'## Blueprint (синтез всех фаз)\n\n{blueprint_content}')
    if phase_content:
        parts.append(f'## Phase: {phase_name}\n\n{phase_content}')

    return {
        'idea':              idea,
        'phases_context':    '\n\n---\n\n'.join(parts),
        'blueprint_content': blueprint_content,
        'phase_content':     phase_content,
        'phase_name':        phase_name,
        'project_title':     project_title,
        'supplement_type':   supplement_type,
    }


async def planning_phase_design_context_load(project_id: int) -> dict:
    """
    Загружает контекст для дизайн-агента: Blueprint + Product + Market phases.
     - project_id: ID проекта из таблицы project
    Returns:
        dict: Контекст для дизайн-агента:
            idea (str): исходный текст идеи продукта.
            phases_context (str): Blueprint + product + market в Markdown.
            project_title (str): название проекта.
    """
    project_id = int(project_id)

    async with mysql_get_db_async() as db:
        await db.execute("SELECT title, idea FROM project WHERE id = %s", (project_id,))
        proj = await db.fetchone()

        await db.execute(
            "SELECT content FROM project_planning_document WHERE project_id = %s AND doc_type = 'blueprint' ORDER BY id DESC LIMIT 1",
            (project_id,)
        )
        blueprint_doc = await db.fetchone()

        await db.execute(
            "SELECT phase, result FROM project_planning_phase WHERE project_id = %s AND phase IN ('market', 'product') AND status = 'complete' ORDER BY id ASC",
            (project_id,)
        )
        phase_rows = await db.fetchall()

    idea = str((proj or {}).get('idea') or '')
    project_title = str((proj or {}).get('title') or '')
    blueprint_content = str((blueprint_doc or {}).get('content') or '')

    parts = []
    if blueprint_content:
        parts.append(f'## Blueprint (синтез всех фаз)\n\n{blueprint_content}')
    for row in (phase_rows or []):
        phase_name = str(row.get('phase') or '')
        result = str(row.get('result') or '')
        if result:
            parts.append(f'## Phase: {phase_name}\n\n{result}')

    return {
        'idea':           idea,
        'phases_context': '\n\n---\n\n'.join(parts),
        'project_title':  project_title,
    }


async def planning_phase_save(project_id: int, phase: str, result: str) -> dict:
    """
    Сохраняет результат фазы анализа в таблицу project_planning_phase.
     - project_id: ID проекта
     - phase: имя фазы (analyze | market | product | tech | gtm | financial | blueprint | supplement_*)
     - result: содержимое фазы (Markdown-текст)
    Returns:
        dict: Результат сохранения, содержащий:
            saved (int): 1 — сохранено, 0 — ошибка.
    """
    project_id = int(project_id)
    phase = str(phase or '').strip()
    if isinstance(result, (dict, list)):
        result = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        result = str(result or '').strip()

    if not phase or not result:
        return {'saved': 0}

    first_line = result.split('\n')[0].lstrip('#').strip()
    summary = first_line[:150] if first_line else ''

    async with mysql_get_db_async() as db:
        await db.execute(
            """
            INSERT INTO project_planning_phase (project_id, phase, status, result, summary, started_at, completed_at)
            VALUES (%s, %s, 'complete', %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                status = 'complete',
                result = VALUES(result),
                summary = VALUES(summary),
                completed_at = NOW()
            """,
            (project_id, phase, result, summary)
        )
        await db.connection.commit()
        await db.execute(
            'UPDATE project SET phase_current = %s, updated_at = NOW() WHERE id = %s',
            (phase, project_id)
        )
        await db.connection.commit()

    return {'saved': 1}


async def planning_phase_document_save(project_id: int, doc_type: str, title: str, content: str) -> dict:
    """
    Сохраняет сгенерированный документ (Blueprint или Supplement) в таблицу project_planning_document.
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
            'SELECT id FROM project_planning_document WHERE project_id = %s AND doc_type = %s LIMIT 1',
            (project_id, doc_type)
        )
        existing = await db.fetchone()

        if existing:
            doc_id = int(existing['id'])
            await db.execute(
                "UPDATE project_planning_document SET title = %s, content = %s, version = version + 1, status = 'final', updated_at = NOW() WHERE id = %s",
                (title, content, doc_id)
            )
        else:
            await db.execute(
                "INSERT INTO project_planning_document (project_id, doc_type, title, content, status) VALUES (%s, %s, %s, %s, 'final')",
                (project_id, doc_type, title, content)
            )
            doc_id = db.lastrowid

        await db.connection.commit()

        if doc_type == 'blueprint':
            await db.execute(
                "UPDATE project SET status = 'complete', updated_at = NOW() WHERE id = %s",
                (project_id,)
            )
            await db.connection.commit()

    return {'saved': 1, 'doc_id': doc_id}


async def planning_phase_document_section_save(project_id: int, source_content: str, section_header: str, doc_type: str, title: str) -> dict:
    """
    Извлекает раздел из markdown-документа по заголовку и сохраняет как отдельный project_planning_document.
     - project_id: ID проекта
     - source_content: полный markdown-документ
     - section_header: заголовок раздела (напр. '## UI-компоненты')
     - doc_type: тип документа для сохранения
     - title: заголовок документа
    Returns:
        dict: saved (int), doc_id (int), section_length (int)
    """
    source_content = str(source_content or '')
    section_header = str(section_header or '').strip()
    if not section_header or not source_content:
        return {'saved': 0, 'doc_id': 0, 'section_length': 0}

    normalized = source_content.replace('‑', '-').replace('–', '-').replace('—', '-')
    header_escaped = re.escape(section_header.replace('‑', '-').replace('–', '-').replace('—', '-'))
    level = len(section_header.split()[0])

    match = re.search(
        rf'(?:^|\n)({header_escaped}.*?)(?=\n#{{{1},{level}}} |\Z)',
        normalized, re.DOTALL
    )
    section_content = match.group(1).strip() if match else ''

    if not section_content:
        return {'saved': 0, 'doc_id': 0, 'section_length': 0}

    result = await planning_phase_document_save(project_id, doc_type, title, section_content)
    result['section_length'] = len(section_content)
    return result

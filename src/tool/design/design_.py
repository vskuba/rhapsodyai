import re as _re

from mysql_.mysql_ import mysql_get_db_async

_TAGS_MAP = {
    'navigation': {
        'TopBar', 'Sidebar', 'AdminSidebar', 'Footer', 'NavLink', 'NavItem',
        'Breadcrumb', 'Pagination', 'StepProgress', 'DropdownMenu', 'Drawer',
        'Tabs', 'PageLayout',
    },
    'hero': {
        'Hero', 'HeroImage', 'CTASection', 'HowItWorks',
    },
    'form': {
        'Input', 'Textarea', 'Select', 'Checkbox', 'Radio', 'Toggle',
        'DatePicker', 'FileUpload', 'AvatarUpload', 'SearchInput', 'Form',
    },
    'data-display': {
        'StatCard', 'DataTable', 'Card', 'List', 'Timeline', 'Badge', 'Avatar',
        'Chip', 'ProgressBar', 'BarChart', 'LineChart', 'PieChart', 'DonutChart',
        'SparkLine', 'EmptyState', 'ErrorState', 'Toast', 'Alert', 'Spinner',
        'FeatureGrid', 'LogoStrip', 'PricingCard', 'PricingCards', 'Testimonial',
        'TestimonialGrid', 'StatsRow', 'ArticleList', 'FAQ', 'Accordion',
    },
}


def _tags_for(name: str) -> str:
    return ','.join(tag for tag, names in _TAGS_MAP.items() if name in names)


async def ui_components_sync_from_doc(project_id: int) -> dict:
    """
    Читает project_planning_document (doc_type='design_ui_components') для проекта
    и добавляет отсутствующие компоненты в project_design_ui_component (INSERT IGNORE).

    - project_id: ID проекта
    Returns:
        synced:  количество добавленных компонентов
        skipped: количество уже существующих
        total:   всего компонентов в документе
    """
    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT content FROM project_planning_document "
            "WHERE project_id=%s AND doc_type='design_ui_components' "
            "ORDER BY id DESC LIMIT 1",
            (project_id,)
        )
        row = await db.fetchone()

    if not row:
        return {'synced': 0, 'skipped': 0, 'total': 0,
                'error': 'Документ design_ui_components не найден'}

    content = (row.get('content') or '').replace('\\n', '\n')

    # Парсим строки Markdown-таблицы: | **Name** | variants | sizes | states | tailwind |
    pattern = _re.compile(r'\|\s*\*\*(\w+)\*\*\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|')
    rows_parsed = []
    for m in pattern.finditer(content):
        name = m.group(1).strip()
        variants = _re.sub(r'`', '', m.group(2)).strip()
        sizes = _re.sub(r'`', '', m.group(3)).strip()
        states = _re.sub(r'`', '', m.group(4)).strip()
        tailwind = _re.sub(r'`', '', m.group(5)).strip()
        rows_parsed.append((name, variants, sizes, states, tailwind, _tags_for(name)))

    if not rows_parsed:
        return {'synced': 0, 'skipped': 0, 'total': 0,
                'error': 'Не найдено компонентов в документе'}

    # Получаем уже существующие имена
    async with mysql_get_db_async() as db:
        await db.execute("SELECT name FROM project_design_ui_component")
        existing = {r.get('name') for r in await db.fetchall()}

    synced = 0
    skipped = 0
    to_insert = [(n, v, sz, st, tw, tg) for n, v, sz, st, tw, tg in rows_parsed
                 if n not in existing]

    if to_insert:
        async with mysql_get_db_async() as db:
            await db.executemany(
                "INSERT IGNORE INTO project_design_ui_component "
                "(name, description, variants, sizes, states, tailwind_example, tags) "
                "VALUES (%s, '', %s, %s, %s, %s, %s)",
                to_insert
            )
        synced = len(to_insert)

    skipped = len(rows_parsed) - synced
    return {'synced': synced, 'skipped': skipped, 'total': len(rows_parsed)}


async def ui_components_list_get() -> dict:
    """
    Возвращает список всех допустимых имён UI-компонентов из таблицы project_design_ui_component.
    Returns:
        ui_components_list: строка с именами через запятую (напр. "TopBar, Card, Form, ...")
    """
    async with mysql_get_db_async() as db:
        await db.execute("SELECT name FROM project_design_ui_component ORDER BY name")
        rows = await db.fetchall()
    names = [r.get('name', '') for r in rows if r.get('name')]
    return {'ui_components_list': ', '.join(names)}


async def ui_component_db_get(component_name: str) -> dict:
    """
    Находит UI-компонент по имени в таблице project_design_ui_component.
    Возвращает отформатированную спецификацию и теги для условного рендеринга в промпте.

    - component_name: имя компонента (напр. "TopBar", "Container", "DataTable")
    Returns:
        component_spec:            текстовая спецификация компонента для промпта
        component_tags:            comma-separated теги (напр. "navigation,header")
        component_tag_navigation:  "1" если тег navigation присутствует, иначе ""
        component_tag_hero:        "1" если тег hero присутствует, иначе ""
        component_tag_form:        "1" если тег form присутствует, иначе ""
        component_tag_data_display:"1" если тег data-display присутствует, иначе ""
        component_tag_auth:        "1" если тег auth присутствует, иначе ""
    """
    empty = {
        'component_spec': '',
        'component_tags': '',
        'component_tag_navigation': '',
        'component_tag_hero': '',
        'component_tag_form': '',
        'component_tag_data_display': '',
        'component_tag_auth': '',
    }

    if not component_name:
        return empty

    async with mysql_get_db_async() as db:
        await db.execute(
            "SELECT name, description, variants, sizes, states, tailwind_example, tags "
            "FROM project_design_ui_component WHERE name = %s LIMIT 1",
            (component_name,)
        )
        row = await db.fetchone()

    if not row:
        return {**empty, 'component_spec': f'Компонент "{component_name}" не найден в библиотеке.'}

    name = row.get('name', component_name)
    description = row.get('description', '')
    variants = row.get('variants', '')
    sizes = row.get('sizes', '')
    states = row.get('states', '')
    tailwind = row.get('tailwind_example', '')
    tags = row.get('tags', '')
    tags_list = [t.strip() for t in (tags or '').split(',') if t.strip()]

    spec_parts = [f'**{name}**']
    if description:
        spec_parts.append(f'Описание: {description}')
    if variants:
        spec_parts.append(f'Варианты: {variants}')
    if sizes:
        spec_parts.append(f'Размеры: {sizes}')
    if states:
        spec_parts.append(f'Состояния: {states}')
    if tailwind:
        spec_parts.append(f'Пример Tailwind: {tailwind}')
    if tags_list:
        spec_parts.append(f'Теги: {", ".join(tags_list)}')

    return {
        'component_spec': '\n'.join(spec_parts),
        'component_tags': tags or '',
        'component_tag_navigation': '1' if 'navigation' in tags_list else '',
        'component_tag_hero': '1' if 'hero' in tags_list else '',
        'component_tag_form': '1' if 'form' in tags_list else '',
        'component_tag_data_display': '1' if 'data-display' in tags_list else '',
        'component_tag_auth': '1' if 'auth' in tags_list else '',
    }


async def wireframe_page_extract(page_title: str, wireframes: str) -> dict:
    """
    Извлекает из общего текста вайрфреймов раздел для конкретной страницы.
    Разделы разделены заголовками вида '### /url (Page Title)'.
    Ищет раздел, заголовок которого содержит page_title.

    - page_title: название страницы (напр. "Landing Page", "Страница статьи")
    - wireframes: полный текст вайрфреймов всех страниц
    Returns:
        page_wireframe: текст раздела вайрфрейма для данной страницы, либо исходный
                        текст при отсутствии совпадения
    """
    if not page_title or not wireframes:
        return {'page_wireframe': wireframes or ''}

    lines = wireframes.splitlines()
    search = page_title.lower()

    start_idx = None
    for i, line in enumerate(lines):
        if line.startswith('###') and search in line.lower():
            start_idx = i
            break

    if start_idx is None:
        return {'page_wireframe': wireframes}

    section = []
    for line in lines[start_idx:]:
        if section and line.startswith('###'):
            break
        section.append(line)

    return {'page_wireframe': '\n'.join(section).strip()}

import os
import re

PROTOTYPE_FILES_DIR = '/app/data/planning'

_TRANSLIT_MAP = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh',
    'з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o',
    'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts',
    'ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
}

_KEYWORD_COMPONENT_MAP = {
    'header': 'TopBar', 'topbar': 'TopBar', 'navbar': 'NavigationMenu',
    'navigation': 'NavigationMenu', 'menu': 'NavigationMenu', 'sidebar': 'NavigationMenu',
    'footer': 'Footer',
    'chart': 'DataTable', 'graph': 'DataTable', 'stats': 'DataTable', 'analytics': 'DataTable',
    'table': 'DataTable', 'datatable': 'DataTable', 'list': 'List',
    'form': 'Form', 'auth': 'Form', 'login': 'Form', 'register': 'Form', 'signup': 'Form',
    'search': 'SearchInput', 'filter': 'SearchInput',
    'card': 'Card', 'article': 'Card', 'content': 'Card', 'text': 'Card',
    'image': 'Card', 'photo': 'Carousel', 'carousel': 'Carousel',
    'tab': 'Tabs', 'accordion': 'Accordion',
    'progress': 'ProgressBar', 'step': 'StepProgress',
    'badge': 'Badge', 'alert': 'Alert', 'toast': 'Toast',
    'avatar': 'Avatar', 'user': 'Avatar',
    'button': 'Button', 'action': 'Button',
    'input': 'Input', 'textarea': 'Textarea', 'select': 'Select',
    'modal': 'Modal', 'drawer': 'Drawer', 'sheet': 'Sheet',
    'tree': 'TreeView', 'breadcrumb': 'Breadcrumb',
    'rating': 'Rating', 'slider': 'Slider', 'switch': 'Switch',
    'calendar': 'Calendar', 'date': 'DatePicker',
    'file': 'FileUpload', 'upload': 'FileUpload',
    'empty': 'EmptyState', 'error': 'EmptyState', 'notfound': 'EmptyState',
    'pricing': 'Card', 'plan': 'Card', 'feature': 'Card',
    'hero': 'Card', 'banner': 'Card', 'cta': 'Button',
    'comment': 'List', 'review': 'List',
    'dashboard': 'DataTable', 'summary': 'DataTable',
}


def _prototype_next_version_dir(project_id: int) -> tuple[int, str]:
    design_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id), 'design')
    os.makedirs(design_dir, exist_ok=True)
    existing = [d for d in os.listdir(design_dir) if d.startswith('v') and d[1:].isdigit() and os.path.isdir(os.path.join(design_dir, d))]
    version_num = max((int(d[1:]) for d in existing), default=0) + 1
    return version_num, os.path.join(design_dir, f'v{version_num}')


def _prototype_latest_version(project_id: int) -> tuple[int, str] | tuple[None, None]:
    design_dir = os.path.join(PROTOTYPE_FILES_DIR, str(project_id), 'design')
    if not os.path.isdir(design_dir):
        return None, None
    existing = [d for d in os.listdir(design_dir) if d.startswith('v') and d[1:].isdigit() and os.path.isdir(os.path.join(design_dir, d))]
    if not existing:
        return None, None
    version_num = max(int(d[1:]) for d in existing)
    return version_num, os.path.join(design_dir, f'v{version_num}')


def _transliterate_filename(name: str) -> str:
    slug = ''.join(_TRANSLIT_MAP.get(c, c) for c in name.lower())
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
    return (slug or 'page') + '.html'


def _sitemap_filename(raw: str) -> str:
    raw = raw.strip().strip('`').strip()
    if not raw or raw.lower() in ('файл', 'url', 'страница', 'file', 'page', 'filename', '---', '-'):
        return ''
    raw = raw.split('?')[0].split('#')[0].rstrip('/')
    part = raw.split('/')[-1]
    if not part or part == '.':
        part = 'index'
    part = re.sub(r'[^a-zA-Z0-9_\-]', '_', part).strip('_')
    if not part or not re.search(r'[a-zA-Z0-9]', part):
        return ''
    if not part.endswith('.html'):
        part += '.html'
    return part.lower()


def _extract_md_section(markdown_text: str, heading: str) -> str:
    pattern = r'##\s+' + re.escape(heading) + r'[^\n]*\n(.*?)(?=\n##\s|\Z)'
    m = re.search(pattern, markdown_text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ''


def _parse_sitemap_pages(markdown_text: str) -> list[dict]:
    m = re.search(r'##\s+Карта\s+страниц[^\n]*\n(.*?)(?=\n##\s|\Z)', markdown_text, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    section = m.group(1)
    seen, pages = set(), []
    for line in section.split('\n'):
        line = line.strip()
        if line.startswith('|'):
            cols = [c.strip() for c in line.strip('|').split('|')]
            if len(cols) < 2:
                continue
            filename = _sitemap_filename(cols[0])
            if not filename:
                continue
            title = cols[1].strip()
        elif re.match(r'^[\*\-]\s+', line):
            bullet_m = re.match(r'^[\*\-]\s+`?(\S+?)`?\s+\(([^)]+)\)', line)
            if not bullet_m:
                continue
            filename = _sitemap_filename(bullet_m.group(1))
            if not filename:
                continue
            title = bullet_m.group(2).strip()
        else:
            continue
        if filename not in seen:
            seen.add(filename)
            pages.append({'filename': filename, 'title': title})
    return pages


def _widget_to_ui_component(widget_name: str, block_name: str, known_components: set) -> str:
    if widget_name in known_components:
        return widget_name
    if block_name in known_components:
        return block_name
    tokens = [t.lower() for t in re.findall(r'[A-Z][a-z]+|[a-z]+|[A-Z]+(?=[A-Z]|$)', widget_name or block_name)]
    for token in tokens:
        if token in _KEYWORD_COMPONENT_MAP:
            candidate = _KEYWORD_COMPONENT_MAP[token]
            if candidate in known_components:
                return candidate
    return 'Card'

import io
import re

from mysql_.mysql_ import mysql_get_db_async

_CRONICLE_SCHEDULE_FILE = '/app/data/cronicle/data/global/b6/15/1b/b6151bb3131d88940fa98921f2c8f4f9.json'

_PROTOTYPE_DIR = '/app/data/planning'

_MIME_MAP = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff2': 'font/woff2',
    '.woff': 'font/woff',
}

_WIDGET_SCRIPT = (
    '<script>window.__PROTO_WIDGET__={{projectId:{pid},pageName:"{pn}"}};</script>\n'
    '<script src="/static/js/planning/prototype-editor-widget.js"></script>'
)

# IDs виджет-элементов, которые могли попасть в HTML при сохранении через outerHTML
_WIDGET_ELEMENT_IDS = [
    '__rw_tabbar', '__rw_breadbar', '__rw_overlay_container',
    '__rw_edit_overlay', '__rw_edit_hl', '__rw_edit_actions',
    '__rw_edit_drop_line', '__rw_text_bar', '__rw_ai_panel',
    '__rw_split', '__rw_apply_status', '__rw_style',
]

_DIV_OPEN_RE = re.compile(r'<div[\s>]', re.IGNORECASE)


def _strip_widget_elements(html: str) -> str:
    """Удаляет виджет-элементы, которые могли запечься в HTML при сохранении outerHTML."""
    # <style id="__rw_style"> — текущий формат
    # <style>...#__rw_tabbar...  — старый формат без id
    html = re.sub(r'<style(?:\s[^>]*)?>(?:(?!</style>).)*?#__rw_[a-z](?:(?!</style>).)*?</style>', '', html,
                  flags=re.DOTALL | re.IGNORECASE)
    # Div-элементы: правильно считаем вложенность чтобы не срезать неполный тег
    for eid in _WIDGET_ELEMENT_IDS:
        if eid == '__rw_style':
            continue
        opener = re.compile(r'<div\s[^>]*\bid="' + re.escape(eid) + r'"[^>]*>', re.IGNORECASE)
        while True:
            m = opener.search(html)
            if not m:
                break
            start, pos, depth = m.start(), m.end(), 1
            while depth > 0 and pos < len(html):
                nd = html.find('<div', pos)
                nc = html.find('</div', pos)
                if nc == -1:
                    pos = len(html)
                    break
                if nd != -1 and nd < nc and _DIV_OPEN_RE.match(html[nd:nd + 5]):
                    depth += 1
                    pos = nd + 4
                else:
                    depth -= 1
                    close_end = html.find('>', nc)
                    pos = close_end + 1 if close_end != -1 else len(html)
            html = html[:start] + html[pos:]
    return html


async def _tools_load() -> dict:
    async with mysql_get_db_async() as db:
        await db.execute('SELECT name, path FROM tool WHERE id > 0')
        rows = await db.fetchall()
    return {r['name'].strip(): r['path'].strip() for r in (rows or []) if r.get('name') and r.get('path')}


async def _doc_filename(project_id, doc_type: str | None, doc_title: str, ext: str) -> str:
    from src.tool.text.text_ import text_translit_cyr_to_lat
    from mysql_.repository.project.project_repository import PlanningProjectRepository
    title = doc_title
    if project_id:
        try:
            proj = await PlanningProjectRepository().find(project_id)
            if proj and proj.get('title'):
                title = str(proj['title'])
        except Exception:
            pass
    name = await text_translit_cyr_to_lat(title)
    name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    if doc_type:
        suffix = re.sub(r'[^a-zA-Z0-9_]', '_', doc_type).strip('_')
        name = f'{name[:60]}_{suffix}'
    return (name[:80] or 'document') + '.' + ext


def _markdown_to_pdf(title: str, markdown_text: str) -> bytes:
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    FONT_DIR = '/usr/share/fonts/truetype/dejavu'
    L_MARGIN = 20
    R_MARGIN = 20
    PAGE_W = 210  # A4
    FULL_W = PAGE_W - L_MARGIN - R_MARGIN  # 170mm

    class PDF(FPDF):
        def header(self): pass
        def footer(self):
            self.set_y(-12)
            self.set_font('DejaVu', '', 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 8, f'Стр. {self.page_no()}', align='C')

    pdf = PDF(orientation='P', unit='mm', format='A4')
    pdf.add_font('DejaVu', style='', fname=f'{FONT_DIR}/DejaVuSans.ttf')
    pdf.add_font('DejaVu', style='B', fname=f'{FONT_DIR}/DejaVuSans-Bold.ttf')
    pdf.set_margins(L_MARGIN, L_MARGIN, R_MARGIN)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    _EMOJI_RE = re.compile(
        r'[\U0001F300-\U0001FAFF\U00002702-\U000027B0'
        r'\U0001F1E0-\U0001F1FF️⃣‍]+'
    )

    def _clean(text: str) -> str:
        text = _EMOJI_RE.sub('', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = text.replace('‑', '-')
        text = text.replace('­', '')
        return text.strip()

    def set_h1(): pdf.set_font('DejaVu', 'B', 17); pdf.set_text_color(15, 23, 42)
    def set_h2(): pdf.set_font('DejaVu', 'B', 13); pdf.set_text_color(30, 41, 59)
    def set_h3(): pdf.set_font('DejaVu', 'B', 11); pdf.set_text_color(51, 65, 85)
    def set_body(): pdf.set_font('DejaVu', '', 10); pdf.set_text_color(55, 65, 81)

    def put_line(text: str, h: float = 6):
        pdf.set_x(L_MARGIN)
        pdf.multi_cell(FULL_W, h, text, new_x='LMARGIN', new_y='NEXT')

    def render_table(table_lines: list[str]):
        rows = []
        for ln in table_lines:
            stripped = ln.strip()
            if not stripped or re.match(r'^\|[-:|\s]+\|$', stripped):
                continue
            cells = [_clean(c.strip()) for c in stripped.strip('|').split('|')]
            if cells:
                rows.append(cells)
        if not rows:
            return

        n_cols = max(len(r) for r in rows)
        rows = [r + [''] * (n_cols - len(r)) for r in rows]
        font_size = 8 if n_cols <= 5 else 7
        col_w = FULL_W / n_cols

        pdf.ln(2)
        pdf.set_font('DejaVu', '', font_size)
        pdf.set_text_color(55, 65, 81)

        header_style = FontFace(emphasis='B', size_pt=font_size, color=(15, 23, 42), fill_color=(241, 245, 249))
        try:
            with pdf.table(
                borders_layout='HORIZONTAL_LINES',
                line_height=5,
                col_widths=tuple(col_w for _ in range(n_cols)),
                padding=1,
            ) as table:
                for row_idx, row_data in enumerate(rows):
                    style = header_style if row_idx == 0 else None
                    row = table.row(style=style)
                    for cell_text in row_data:
                        row.cell(cell_text)
        except Exception:
            set_body()
            for row_data in rows:
                put_line('  |  '.join(row_data))
        pdf.ln(2)

    def render_code_block(code_lines: list[str]):
        pdf.set_font('DejaVu', '', 8)
        pdf.set_text_color(30, 41, 59)
        pdf.set_fill_color(248, 250, 252)
        pdf.ln(2)
        for cl in code_lines:
            clean = _clean(cl)
            if not clean:
                pdf.ln(3)
                continue
            pdf.set_x(L_MARGIN)
            pdf.multi_cell(FULL_W, 4.5, clean, fill=True, new_x='LMARGIN', new_y='NEXT')
        pdf.ln(2)

    set_h1()
    put_line(_clean(title), 10)
    pdf.ln(3)
    pdf.set_draw_color(59, 130, 246)
    pdf.set_line_width(0.8)
    pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
    pdf.ln(5)

    lines = markdown_text.split('\n')
    i = 0
    in_code = False
    code_buf: list[str] = []
    table_buf: list[str] = []

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        if line.strip().startswith('```'):
            if in_code:
                render_code_block(code_buf)
                code_buf = []
                in_code = False
            else:
                if table_buf:
                    render_table(table_buf); table_buf = []
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if re.match(r'^\s*\|', line):
            table_buf.append(line)
            i += 1
            continue
        if table_buf:
            render_table(table_buf); table_buf = []

        if line.startswith('# '):
            set_h1(); pdf.ln(3)
            put_line(_clean(line[2:]), 10); pdf.ln(2)
        elif line.startswith('## '):
            set_h2(); pdf.ln(3)
            put_line(_clean(line[3:]), 8); pdf.ln(1)
        elif line.startswith('### '):
            set_h3(); pdf.ln(2)
            put_line(_clean(line[4:]), 7); pdf.ln(1)
        elif line.startswith('#### '):
            set_h3()
            put_line(_clean(line[5:]), 7); pdf.ln(1)
        elif re.match(r'^---+$', line.strip()):
            pdf.set_draw_color(226, 232, 240)
            pdf.set_line_width(0.3)
            pdf.line(L_MARGIN, pdf.get_y(), PAGE_W - R_MARGIN, pdf.get_y())
            pdf.ln(4)
        elif line.startswith('> '):
            set_body()
            pdf.set_text_color(100, 116, 139)
            pdf.set_x(L_MARGIN + 5)
            pdf.multi_cell(FULL_W - 5, 6, _clean(line[2:]), new_x='LMARGIN', new_y='NEXT')
            set_body()
        elif re.match(r'^(\s*)[-*+]\s', line):
            indent = len(line) - len(line.lstrip())
            set_body()
            text = _clean(re.sub(r'^(\s*)[-*+]\s+', '', line))
            x_off = L_MARGIN + min(indent, 8) * 1.5
            prefix_w = 5
            avail = PAGE_W - R_MARGIN - x_off - prefix_w
            pdf.set_x(x_off)
            pdf.cell(prefix_w, 6, '•')
            pdf.set_x(x_off + prefix_w)
            pdf.multi_cell(avail, 6, text, new_x='LMARGIN', new_y='NEXT')
        elif re.match(r'^\d+\.\s', line):
            set_body()
            text = _clean(re.sub(r'^\d+\.\s+', '', line))
            num = re.match(r'^(\d+)\.', line).group(1)
            prefix_w = 8
            pdf.set_x(L_MARGIN)
            pdf.cell(prefix_w, 6, f'{num}.')
            pdf.set_x(L_MARGIN + prefix_w)
            pdf.multi_cell(FULL_W - prefix_w, 6, text, new_x='LMARGIN', new_y='NEXT')
        elif line.strip() == '':
            pdf.ln(3)
        else:
            set_body()
            put_line(_clean(line))

        i += 1

    if table_buf:
        render_table(table_buf)
    if in_code and code_buf:
        render_code_block(code_buf)

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()

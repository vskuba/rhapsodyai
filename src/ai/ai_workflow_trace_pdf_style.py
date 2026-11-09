"""Оформление печатного журнала прогона: лист, типографика, цвета состояний.

Стиль вынесен из сборщика документа отдельным файлом: разметку правят, когда
меняется содержание, а оформление — когда документ плохо выглядит на бумаге;
это разные поводы и разные правки.

⚠⚠ Цвета состояний взяты **с экранной страницы** (`admin/workflow_trace.html`,
`.status-success` и соседи), а не подобраны заново. Журнал смотрят то на
экране, то в выгрузке, и `success` двух разных зелёных читается как разница в
смысле. Расходиться они будут только вручную — общего источника у CSS страницы
и этой строки нет, и завести его нечем: страница раздаётся как статика, а
документ собирается в питоне.

⚠ Единицы листа — миллиметры, единицы текста — пункты. Браузер печатает по
CSS-пикселям, и `px` в `@page` даёт поля, зависящие от плотности; `pt` в тексте
переживает любой масштаб просмотра.
"""

# Поле снизу больше прочих: в нём живёт колонтитул (`position: fixed`), который
# Chrome повторяет на каждой странице печати. Сам колонтитул уезжает в это поле
# отрицательным `bottom` — иначе он встал бы поверх последней строки текста.
AI_WORKFLOW_TRACE_PDF_CSS = """
@page {
    size: A4 portrait;
    margin: 14mm 12mm 18mm 12mm;
}

* { box-sizing: border-box; }

body {
    margin: 0;
    font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif;
    font-size: 8.5pt;
    line-height: 1.45;
    color: #1e293b;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}

a { color: #4338ca; text-decoration: none; }

pre, code, .mono {
    font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
}

pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-wrap: anywhere;
    font-size: 7pt;
    line-height: 1.4;
    color: #0f172a;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 2px solid #cbd5e1;
    border-radius: 3px;
    padding: 5px 7px;
}

/* ── подпись раздела: чей это прогон, на случай печати по частям ────────
   ⚠⚠ Не колонтитул. Колонтитул здесь пробовали сделать `position: fixed` —
   Chrome такой элемент на каждой странице печати действительно повторяет, но
   кладёт его вниз только на страницах, заполненных потоком: на странице,
   начатой принудительным разрывом (`page-break-before`, а здесь так начинается
   каждый раздел), он встаёт ПОД ЗАГОЛОВОК, в начало текста. Воспроизведено на
   отдельной пробе из двух разделов. Поэтому подпись — обычный элемент потока:
   она стоит ровно там, куда её положили, и соврать не может. */
.sheet-mark {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    font-size: 6.5pt;
    color: #94a3b8;
    margin: -4px 0 10px;
}

/* ── обложка ───────────────────────────────────────────────────────────── */
.cover { page-break-after: always; }

.cover-kicker {
    font-size: 8pt;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: #6366f1;
    font-weight: 700;
}

.cover-title {
    font-size: 22pt;
    font-weight: 700;
    line-height: 1.15;
    margin: 6px 0 2px;
    color: #0f172a;
}

.cover-sub { font-size: 10pt; color: #64748b; margin-bottom: 14px; }

.cover-rule {
    height: 3px;
    background: linear-gradient(90deg, #6366f1 0%, #a5b4fc 55%, #e2e8f0 100%);
    border-radius: 2px;
    margin: 0 0 16px;
}

.tiles { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }

/* ⚠ Основа `180px` подобрана кадром, а не на глаз: при меньшей шесть плиток
   встают в один ряд, не умещаются (подписи вроде «ТОКЕНОВ ↑» держат
   min-content и сжиматься не дают) и последняя уезжает за поле листа.
   180px даёт честные два ряда по три. */
.tile {
    flex: 1 1 180px;
    min-width: 0;
    border: 1px solid #e2e8f0;
    border-radius: 5px;
    padding: 7px 9px;
    background: #f8fafc;
}

.tile-value { font-size: 14pt; font-weight: 700; color: #0f172a; }
.tile-label { font-size: 6.5pt; text-transform: uppercase; letter-spacing: .07em; color: #94a3b8; }

/* ── таблица паспорта ──────────────────────────────────────────────────── */
.facts { width: 100%; border-collapse: collapse; }

.facts th, .facts td {
    border-bottom: 1px solid #eef2f7;
    padding: 4px 6px;
    text-align: left;
    vertical-align: top;
}

.facts th {
    width: 32%;
    font-weight: 600;
    color: #64748b;
    font-size: 7.5pt;
}

.facts td { font-size: 7.5pt; word-break: break-word; }

/* ── заголовки разделов ────────────────────────────────────────────────── */
h2 {
    font-size: 12pt;
    margin: 0 0 8px;
    padding-bottom: 4px;
    border-bottom: 2px solid #e2e8f0;
    color: #0f172a;
}

h2 .h2-num { color: #6366f1; margin-right: 6px; }

.section { page-break-before: always; }
.section-tight { page-break-before: auto; }

/* ── содержание ────────────────────────────────────────────────────────── */
.toc-item {
    display: flex;
    align-items: baseline;
    gap: 6px;
    padding: 1.5px 0;
    border-bottom: 1px dotted #e2e8f0;
}

.toc-item .toc-no { color: #94a3b8; font-size: 7pt; min-width: 34px; }
.toc-item .toc-name { flex: 1; word-break: break-word; }
.toc-item .toc-meta { color: #94a3b8; font-size: 7pt; white-space: nowrap; }
.toc-sub .toc-name { color: #7c3aed; font-weight: 600; }

/* ── бейджи ────────────────────────────────────────────────────────────── */
.badge {
    display: inline-block;
    font-size: 6.5pt;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 8px;
    white-space: nowrap;
}

.badge-success { background: #eafaf1; color: #1e8449; }
.badge-error   { background: #fdecea; color: #c0392b; }
.badge-running { background: #fef9e7; color: #b7950b; }
.badge-stopped { background: #eaecee; color: #566573; }
.badge-retry   { background: #fff4e5; color: #b45309; }
.badge-llm     { background: #eef2ff; color: #4338ca; }
.badge-tokens  { background: #f1f5f9; color: #475569; }

/* ── пары «запрос/ответ» и «контракт» ──────────────────────────────────── */
.pair { display: flex; gap: 8px; margin-bottom: 8px; }
.pair > div { flex: 1 1 0; min-width: 0; }

.label {
    font-size: 6.5pt;
    text-transform: uppercase;
    letter-spacing: .07em;
    color: #94a3b8;
    font-weight: 700;
    margin-bottom: 2px;
}

.note { font-size: 7pt; color: #94a3b8; font-style: italic; }

/* ── шаг ───────────────────────────────────────────────────────────────── */
.step {
    border: 1px solid #e2e8f0;
    border-radius: 5px;
    margin-bottom: 7px;
    page-break-inside: avoid;
}

/* ⚠ Шаг длиннее листа разрывать ПРИХОДИТСЯ: `page-break-inside: avoid` на
   блоке выше листа Chrome молча игнорирует, и запрет на вложенных значениях
   оставил бы пустые страницы перед каждым длинным шагом. */
.step-long { page-break-inside: auto; }

.step-head {
    display: flex;
    align-items: baseline;
    gap: 6px;
    padding: 5px 8px;
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    border-radius: 4px 4px 0 0;
}

.step-no { font-weight: 700; color: #475569; font-size: 7.5pt; white-space: nowrap; }
.step-icon { font-size: 9pt; }
.step-name { flex: 1; font-weight: 600; color: #0f172a; word-break: break-word; }
.step-time { color: #64748b; font-size: 7pt; white-space: nowrap; }
.step-time-slow { color: #c0392b; font-weight: 700; }
.step-up { font-size: 6.5pt; color: #a5b4fc; white-space: nowrap; }

.step-body { padding: 7px 8px; }
.step-body .label { margin-top: 6px; }
.step-body .label:first-child { margin-top: 0; }

.err pre { background: #fdf2f1; border-color: #f5c6c0; border-left-color: #e74c3c; color: #922b21; }

/* ── переход ───────────────────────────────────────────────────────────── */
.transition {
    display: flex;
    align-items: center;
    gap: 7px;
    background: #f5f3ff;
    border: 1px solid #ddd6fe;
    border-radius: 4px;
    padding: 5px 7px;
}

.transition-card {
    flex: 1 1 0;
    min-width: 0;
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 3px;
    padding: 3px 6px;
    font-size: 7pt;
    word-break: break-word;
}

.transition-mid { text-align: center; font-size: 7pt; color: #6d28d9; white-space: nowrap; }
.transition-arrow { font-size: 11pt; line-height: 1; color: #7c3aed; }
.transition-cond { font-family: "DejaVu Sans Mono", monospace; font-size: 6.5pt; }

/* ── подпоток ──────────────────────────────────────────────────────────── */
.child {
    border-left: 3px solid #c4b5fd;
    background: #faf9ff;
    border-radius: 0 5px 5px 0;
    padding: 7px 9px;
    margin: 0 0 8px 10px;
    page-break-inside: avoid;
}

.child-head { display: flex; align-items: baseline; gap: 6px; margin-bottom: 5px; }
.child-kicker { font-size: 6.5pt; text-transform: uppercase; letter-spacing: .07em; color: #7c3aed; font-weight: 700; }
.child-name { font-weight: 700; color: #0f172a; }

/* ── переменные ────────────────────────────────────────────────────────── */
.vars { width: 100%; border-collapse: collapse; }

.vars th {
    text-align: left;
    font-size: 6.5pt;
    text-transform: uppercase;
    letter-spacing: .07em;
    color: #94a3b8;
    border-bottom: 1px solid #e2e8f0;
    padding: 3px 5px;
}

.vars td {
    border-bottom: 1px solid #f1f5f9;
    padding: 3px 5px;
    vertical-align: top;
    font-size: 7pt;
    word-break: break-word;
}

.vars tr { page-break-inside: avoid; }
.vars .v-name { font-family: "DejaVu Sans Mono", monospace; color: #0f172a; width: 24%; }
.vars .v-from { color: #94a3b8; width: 12%; white-space: nowrap; }
.vars .v-value { color: #334155; }
.vars .v-empty { color: #cbd5e1; font-style: italic; }

.cut { color: #b45309; font-style: italic; font-size: 6.5pt; }
"""

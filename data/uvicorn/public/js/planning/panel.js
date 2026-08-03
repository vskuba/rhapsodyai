// Project detail panel — renderPanel, patchPanelDynamic, renderScore

/* ── Phase collapse (localStorage) ─────────────────────── */
const _PHASE_COLLAPSE_LS = 'project_planning_phase_collapse';

function _collapseRead() {
    try { return JSON.parse(localStorage.getItem(_PHASE_COLLAPSE_LS) || '{}'); } catch { return {}; }
}

function togglePhaseRow(phaseKey) {
    const st = _collapseRead();
    st[phaseKey] = !st[phaseKey];
    localStorage.setItem(_PHASE_COLLAPSE_LS, JSON.stringify(st));
    applyPhaseCollapseState();
}

function applyPhaseCollapseState() {
    const tbody = document.getElementById('phasesTableBody');
    if (!tbody) return;
    const st = _collapseRead();
    tbody.querySelectorAll('tr[data-phase-key]').forEach(mainRow => {
        const key = mainRow.dataset.phaseKey;
        const subRows = tbody.querySelectorAll(`tr[data-phase-parent="${key}"]`);
        if (!subRows.length) return;

        let toggle = mainRow.querySelector('.phase-toggle');
        if (!toggle) {
            toggle = document.createElement('span');
            toggle.className = 'phase-toggle';
            toggle.style.cssText = 'cursor:pointer;margin-right:5px;font-size:10px;color:#94a3b8;user-select:none;transition:transform 0.15s;display:inline-block;';
            toggle.onclick = e => { e.stopPropagation(); togglePhaseRow(key); };
            const nameCell = mainRow.querySelector('.phase-name');
            if (nameCell) nameCell.prepend(toggle);
        }

        const collapsed = !!st[key];
        toggle.textContent = collapsed ? '▶' : '▼';
        subRows.forEach(r => { r.style.display = collapsed ? 'none' : ''; });
    });
}

const ALL_PHASES = ['analyze','market','product','tech','gtm','financial','blueprint','score','supplement'];

const FUTURE_PHASES = new Set([]);

const PHASE_REQUIRES = {
    analyze: [], market: ['analyze'], product: ['market'],
    tech: ['product'], gtm: ['tech'], financial: ['gtm'],
    blueprint: ['financial'], score: ['blueprint'], supplement: ['blueprint'],
};

const PHASE_CHILDREN_MAP = {};

// Фазы запускаемые вручную по запросу (не автоматически) — показывать "по запросу" вместо "ожидает"
const PHASE_ON_DEMAND = new Set(['prototype', 'refine']);

// Зависимости дочерних фаз (ключ: phase → список phase, которые должны быть complete)
const PHASE_CHILD_REQUIRES = {
    design_wireframe: ['design'],
    prototype:        ['design_wireframe'],
    sitemap_check:    ['prototype'],
    refine:           ['sitemap_check'],
};

// Переопределения меток для дочерних фаз
const PHASE_CHILD_LABELS = {
    design_pages:     'Карта страниц',
    design_wireframe: 'Вайрфреймы',
    prototype:        'Прототип',
    sitemap_check:    'Проверка карты',
    refine:           'Доработка',
};

// 'waiting' и 'complete' — оба считаются выполненными для проверки prereqs
function isPhaseComplete(ph) {
    return ph && (ph.status === 'complete' || ph.status === 'waiting');
}

// Загружается с /planning/phase-sections — titles и sections из project_project_planning_phase_source + docs/planning/
let _phaseSections = {};
let _phaseTitles = {};

async function loadPhaseSections() {
    try {
        const data = await fetch('/planning/phase-sections').then(r => r.json());
        const result = data.result || {};
        _phaseSections = result.sections || {};
        _phaseTitles = result.titles || {};
    } catch {}
}

function renderScore(proj) {
    if (!proj.score_verdict) return '';
    const vClass = { go: 'verdict-go', maybe: 'verdict-maybe', no: 'verdict-no' }[proj.score_verdict] || 'verdict-maybe';
    const vLabel = { go: 'GO ✓', maybe: 'Maybe', no: 'NO ✗' }[proj.score_verdict] || proj.score_verdict;

    function meter(label, val) {
        if (!val) return '';
        const cls = val >= 7 ? 'fill-high' : val >= 5 ? 'fill-mid' : 'fill-low';
        return `<div class="score-meter">
        <div class="score-meter-label">${label}</div>
        <div class="score-meter-bar"><div class="score-meter-fill ${cls}" style="width:${val * 10}%"></div></div>
        <div class="score-meter-val">${val}/10</div></div>`;
    }

    const totalCls = proj.score_total >= 7 ? 'verdict-go' : proj.score_total >= 5 ? 'verdict-maybe' : 'verdict-no';
    return `<div class="score-block">
    <div class="score-header">
        <span class="score-verdict-lg ${vClass}">${vLabel}</span>
        <span class="score-verdict ${totalCls}">Итого ${proj.score_total}/10</span>
    </div>
    <div class="score-meters">
        ${meter('Рынок', proj.score_market)}${meter('Реализуемость', proj.score_feasibility)}${meter('Финансы', proj.score_financial)}
    </div>
    ${(proj.score_investment || proj.score_time_to_market) ? `<div class="score-meta">
        ${proj.score_investment ? `<span>💰 <b>${escHtml(proj.score_investment)}</b></span>` : ''}
        ${proj.score_time_to_market ? `<span>⏱ <b>${escHtml(proj.score_time_to_market)}</b></span>` : ''}
    </div>` : ''}
    ${proj.score_summary ? `<div class="score-summary">${escHtml(proj.score_summary)}</div>` : ''}
</div>`;
}

function buildPhaseRows(proj, phases, docs) {
    const phaseByKey = {};
    phases.forEach(ph => { phaseByKey[ph.phase] = ph; });

    /* Агрегируем supplement sub-фазы (supplement_market, supplement_tech, …) */
    const supplementSubs = phases.filter(p => p.phase.startsWith('supplement_'));
    if (supplementSubs.length > 0) {
        const anyRunning  = supplementSubs.some(p => p.status === 'running');
        const anyFailed   = supplementSubs.some(p => p.status === 'failed');
        const allComplete = supplementSubs.every(p => p.status === 'complete');
        const aggStatus   = anyRunning ? 'running' : allComplete ? 'complete' : anyFailed ? 'failed' : 'processing';
        const tokIn  = supplementSubs.reduce((s, p) => s + (Number(p.tokens_input)  || 0), 0);
        const tokOut = supplementSubs.reduce((s, p) => s + (Number(p.tokens_output) || 0), 0);
        phaseByKey['supplement'] = {
            phase: 'supplement',
            status: aggStatus,
            started_at: supplementSubs[0]?.started_at,
            completed_at: allComplete ? supplementSubs[supplementSubs.length - 1]?.completed_at : null,
            tokens_input: tokIn || null,
            tokens_output: tokOut || null,
            _subs: supplementSubs,
        };
    }

    const projSlug = translitLat(proj.title || proj.id).slice(0, 60) || 'document';

    const docsByPhase = {};
    docs.forEach(d => {
        let phase = d.doc_type;
        if (phase === 'prototype' || phase === 'design_tokens' || phase === 'design_ui_components' || phase === 'design_wireframes' || phase === 'design_sitemap' || phase === 'design_specs') phase = 'design';
        else if (!ALL_PHASES.includes(phase)) phase = 'supplement';
        if (!docsByPhase[phase]) docsByPhase[phase] = [];
        docsByPhase[phase].push(d);
    });

    function makePhaseDocBtns(phaseKey) {
        let extra = '';
        if (phaseKey === 'design_pages') {
            extra = `<a class="btn-view" href="/admin/design?project_id=${proj.id}#blocks" target="_blank" style="text-decoration:none;display:inline-block">Блоки</a>`
                  + `<a class="btn-view" href="/admin/design?project_id=${proj.id}#pages" target="_blank" style="text-decoration:none;display:inline-block;margin-left:4px;background:#ede9fe;color:#6d28d9;border-color:#c4b5fd">Страницы</a>`;
        }
        if (phaseKey === 'design_wireframe') {
            extra = `<a class="btn-view" href="/admin/design?project_id=${proj.id}#pages" target="_blank" style="text-decoration:none;display:inline-block;background:#ede9fe;color:#6d28d9;border-color:#c4b5fd">Конструктор</a>`;
        }
        return extra + (docsByPhase[phaseKey] || []).map(d => {
            const fileSlug = projSlug + (d.doc_type ? '_' + d.doc_type : '');
            const docLabel = escHtml(d.title || d.doc_type);
            if (d.doc_type === 'prototype') {
                return '';
            }
            return `<div><button class="btn-view" onclick="showDocumentContent('${escAttr(d.title || d.doc_type)}', ${d.id})">${docLabel}</button>`
                + `<a class="btn-download" href="/planning/document/${d.id}/download" download="${escAttr(fileSlug)}.md" title="Скачать .md">.md</a></div>`;
        }).join('');
    }

    function phaseWillRunNext(phaseKey) {
        return (PHASE_REQUIRES[phaseKey] || []).every(r => isPhaseComplete(phaseByKey[r]));
    }

    function childPhaseRunInfo(childKey) {
        const reqs = PHASE_CHILD_REQUIRES[childKey] || [];
        const missing = reqs.filter(r => !isPhaseComplete(phaseByKey[r]));
        const missingLabel = missing.map(r => PHASE_CHILD_LABELS[r] || _phaseTitles[r] || r).join(', ');
        return { canRun: missing.length === 0, missingLabel };
    }

    function makeChildRunBtn(childKey, projectId, hasRun) {
        if (childKey === 'design_pages') return '';
        const { canRun, missingLabel } = childPhaseRunInfo(childKey);
        const icon = hasRun ? '↻' : '▶';
        const baseStyle = 'font-size:0.8em;padding:2px 6px';
        if (canRun) {
            return `<button class="btn-retry-phase" style="${baseStyle}" onclick="retryPhase(${projectId},'${childKey}')" title="${hasRun ? 'Перезапустить' : 'Запустить'}">${icon}</button>`;
        }
        return `<button class="btn-retry-phase" style="${baseStyle};opacity:0.35;cursor:not-allowed" disabled title="Недоступно: требуется «${missingLabel}»">${icon}</button>`;
    }

    function phaseSectionTagsHtml(phaseKey) {
        const sections = _phaseSections[phaseKey];
        if (!sections || !sections.length) return '';
        const tags = sections.map(s => `<span class="phase-section-tag">${escHtml(s)}</span>`).join('');
        return `<div class="phase-section-tags">${tags}</div>`;
    }

    return ALL_PHASES.map(phaseKey => {
        const ph = phaseByKey[phaseKey];
        const label = ph?.title || _phaseTitles[phaseKey] || phaseKey;
        const phaseDocBtns = makePhaseDocBtns(phaseKey);
        const sectionTagsHtml = phaseSectionTagsHtml(phaseKey);
        if (!ph) {
            if (FUTURE_PHASES.has(phaseKey)) {
                const prereqsDone = phaseWillRunNext(phaseKey);
                const rowStyle = prereqsDone ? 'opacity:0.55' : 'opacity:0.3';
                const badge = `<span class="badge" style="background:#f8fafc;color:#94a3b8;border:1px solid #e2e8f0;font-style:italic">след. этап</span>`;
                return `<tr data-phase-key="${phaseKey}" style="${rowStyle}">
                <td class="phase-name" style="color:#94a3b8;font-style:italic">${escHtml(label)}${sectionTagsHtml}</td>
                <td>${badge}</td>
                <td class="phase-time" colspan="3" style="color:#cbd5e1;font-size:0.8em">Запускается вручную после утверждения Blueprint</td>
                <td>${phaseDocBtns}</td>
                <td></td><td></td>
            </tr>`;
            }
            return `<tr data-phase-key="${phaseKey}" style="opacity:0.45">
            <td class="phase-name" style="color:#94a3b8">${escHtml(label)}${sectionTagsHtml}</td>
            <td><span class="badge" style="background:#f1f5f9;color:#94a3b8;border:1px solid #e2e8f0">ожидает</span></td>
            <td class="phase-time">—</td><td class="phase-time">—</td><td class="phase-time">—</td>
            <td>${phaseDocBtns || '—'}</td>
            <td></td><td></td>
        </tr>`;
        }
        const dur = ph.started_at && ph.completed_at
            ? Math.round((new Date(ph.completed_at) - new Date(ph.started_at)) / 1000) + 's' : '—';
        const tokIn  = ph.tokens_input  ? Number(ph.tokens_input).toLocaleString()  : '—';
        const tokOut = ph.tokens_output ? Number(ph.tokens_output).toLocaleString() : '—';
        const hasResult = ph.result && ph.result.length > 10;
        const canRetry = ph.status !== 'running';
        const retryBtn = canRetry ? `<button class="btn-retry-phase" onclick="retryPhase(${proj.id},'${phaseKey}')" title="Сбросить фазу">↻</button>` : '';

        // childKeys must be defined before errorRow to determine if error collapses with children
        const childKeys = PHASE_CHILDREN_MAP[phaseKey] || [];
        const hasChildRows = !!(ph._subs?.length || childKeys.length);
        const errorParentAttr = hasChildRows ? ` data-phase-parent="${phaseKey}"` : '';
        const errorRow = ph.error ? `<tr class="phase-error-row"${errorParentAttr}><td colspan="8"><div class="phase-error-box">${escHtml(ph.error)}</div></td></tr>` : '';

        let subRows = '';
        if (phaseKey === 'supplement' && ph._subs?.length) {
            subRows = ph._subs.map(sub => {
                const typeKey = sub.phase.replace('supplement_', '');
                const typeLabel = sub.title || _phaseTitles[sub.phase] || typeKey;
                const subDur = sub.started_at && sub.completed_at
                    ? Math.round((new Date(sub.completed_at) - new Date(sub.started_at)) / 1000) + 's' : '—';
                const subTokIn  = sub.tokens_input  ? Number(sub.tokens_input).toLocaleString()  : '—';
                const subTokOut = sub.tokens_output ? Number(sub.tokens_output).toLocaleString() : '—';
                const subHasResult = sub.result && sub.result.length > 10;
                const subCanRetry = sub.status !== 'running';
                const runningPulse = sub.status === 'running'
                    ? ' style="animation:pulse 2s infinite;background:#fffdf0"' : '';
                const subRetryBtn = subCanRetry
                    ? `<button class="btn-retry-phase" style="font-size:0.8em;padding:2px 6px" onclick="retryPhase(${proj.id},'${sub.phase}')" title="Перезапустить дополнение">↻</button>`
                    : '';
                const subSummaryHtml = sub.summary
                    ? `<div style="font-size:0.75em;color:#94a3b8;margin-top:1px">${escHtml(sub.summary)}</div>` : '';
                return `<tr class="supplement-sub-row" data-phase-parent="supplement"${runningPulse}>
                    <td class="phase-name" style="padding-left:28px;font-size:0.88em;color:#64748b">↳ ${escHtml(typeLabel)}${subSummaryHtml}</td>
                    <td><span class="badge badge-${sub.status}" style="font-size:0.8em">${sub.status}</span></td>
                    <td class="phase-time" style="font-size:0.85em">${subDur}</td>
                    <td class="phase-time" style="font-size:0.85em">${subTokIn}</td>
                    <td class="phase-time" style="font-size:0.85em">${subTokOut}</td>
                    <td></td>
                    <td>${subHasResult ? `<button class="btn-view" style="font-size:0.8em;padding:2px 7px" onclick="showPhaseResult('Дополнение: ${escAttr(typeLabel)}',${proj.id},'${sub.phase}')">Просмотр</button>` : ''}</td>
                    <td>${subRetryBtn}</td>
                </tr>`;
            }).join('');
        }

        // Рендер дочерних фаз (prototype, sitemap_check для design)
        if (childKeys.length) {
            subRows += childKeys.map(childKey => {
                const sub = phaseByKey[childKey];
                const childLabel = PHASE_CHILD_LABELS[childKey] || sub?.title || _phaseTitles[childKey] || childKey;
                if (!sub) {
                    // Дочерняя фаза ещё не запускалась
                    const parentDone = isPhaseComplete(ph);
                    const onDemand = PHASE_ON_DEMAND.has(childKey);
                    const waitBadge = onDemand
                        ? `<span class="badge" style="background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;font-size:0.8em">по запросу</span>`
                        : `<span class="badge" style="background:#f1f5f9;color:#94a3b8;border:1px solid #e2e8f0;font-size:0.8em">ожидает</span>`;
                    const childRunBtn = makeChildRunBtn(childKey, proj.id, false);
                    return `<tr data-phase-parent="${phaseKey}" style="opacity:${parentDone ? 0.7 : 0.4}">
                        <td class="phase-name" style="padding-left:28px;font-size:0.88em;color:#94a3b8">↳ ${escHtml(childLabel)}</td>
                        <td>${waitBadge}</td>
                        <td class="phase-time">—</td><td class="phase-time">—</td><td class="phase-time">—</td>
                        <td>${makePhaseDocBtns(childKey) || ''}</td><td></td><td>${childRunBtn}</td>
                    </tr>`;
                }
                const subDur = sub.started_at && sub.completed_at
                    ? Math.round((new Date(sub.completed_at) - new Date(sub.started_at)) / 1000) + 's' : '—';
                const subTokIn  = sub.tokens_input  ? Number(sub.tokens_input).toLocaleString()  : '—';
                const subTokOut = sub.tokens_output ? Number(sub.tokens_output).toLocaleString() : '—';
                const subHasResult = sub.result && sub.result.length > 10;
                const runningPulse = sub.status === 'running'
                    ? ' style="animation:pulse 2s infinite;background:#fffdf0"' : '';
                const subRetryBtn = sub.status !== 'running' ? makeChildRunBtn(childKey, proj.id, true) : '';
                const subDocBtns = makePhaseDocBtns(childKey);
                const subErrRow = sub.error
                    ? `<tr class="phase-error-row" data-phase-parent="${phaseKey}"><td colspan="8" style="padding-left:28px"><div class="phase-error-box">${escHtml(sub.error)}</div></td></tr>` : '';
                const childSummaryHtml = sub.summary
                    ? `<div style="font-size:0.75em;color:#94a3b8;margin-top:1px">${escHtml(sub.summary)}</div>` : '';
                return `<tr class="supplement-sub-row" data-phase-parent="${phaseKey}"${runningPulse}>
                    <td class="phase-name" style="padding-left:28px;font-size:0.88em;color:#64748b">↳ ${escHtml(childLabel)}${childSummaryHtml}</td>
                    <td><span class="badge badge-${sub.status}" style="font-size:0.8em">${sub.status}</span></td>
                    <td class="phase-time" style="font-size:0.85em">${subDur}</td>
                    <td class="phase-time" style="font-size:0.85em">${subTokIn}</td>
                    <td class="phase-time" style="font-size:0.85em">${subTokOut}</td>
                    <td>${subDocBtns || ''}</td>
                    <td>${subHasResult ? `<button class="btn-view" style="font-size:0.8em;padding:2px 7px" onclick="showPhaseResult('${escAttr(childLabel)}',${proj.id},'${childKey}')">Просмотр</button>` : ''}</td>
                    <td>${subRetryBtn}</td>
                </tr>${subErrRow}`;
            }).join('');
        }

        return `<tr data-phase-key="${phaseKey}">
            <td class="phase-name">${escHtml(label)}${sectionTagsHtml}</td>
            <td><span class="badge badge-${ph.status}">${ph.status}</span></td>
            <td class="phase-time">${dur}</td>
            <td class="phase-time">${tokIn}</td>
            <td class="phase-time">${tokOut}</td>
            <td>${phaseDocBtns || '—'}</td>
            <td>${hasResult ? `<button class="btn-view" onclick="showPhaseResult('${escAttr(label)}',${proj.id},'${ph.phase}')">Просмотр</button>` : ''}</td>
            <td>${retryBtn}</td>
        </tr>${errorRow}${subRows}`;
    }).join('');
}

function _infoBlueprintHtml(docs) {
    const d = docs.find(doc => doc.doc_type === 'blueprint');
    return d
        ? `<button class="btn-view" style="font-size:11px;padding:2px 10px" onclick="showDocumentContent('${escAttr(d.title || 'Blueprint')}', ${d.id})">Просмотр</button>`
        : '—';
}

function _infoPrototypeHtml(docs) {
    const prototypes = docs.filter(doc => doc.doc_type === 'prototype').sort((a, b) => (b.version || 0) - (a.version || 0));
    if (!prototypes.length) return '—';
    return prototypes.map(d => {
        const vLabel = d.version ? `v${d.version}` : 'v1';
        return `<span style="display:inline-flex;align-items:center;gap:4px;margin:1px 0">` +
            `<a class="btn-retry-phase" href="/planning/document/${d.id}/view" target="_blank" style="text-decoration:none;background:#ede9fe;color:#7c3aed;border-color:#ddd6fe;font-size:11px;padding:2px 8px">${vLabel}</a>` +
            `<button class="btn-delete" style="font-size:10px;padding:1px 6px;line-height:1.4" onclick="deletePrototypeVersion(currentProjectId,${d.version || 1})" title="Удалить ${vLabel}">✕</button>` +
            `</span>`;
    }).join('');
}

// Точечное обновление динамических элементов без перерисовки всей панели.
// Возвращает false если панель ещё не отрисована (нет #projStatusBadge).
function patchPanelDynamic(proj, phases, docs) {
    const statusBadge = document.getElementById('projStatusBadge');
    if (!statusBadge) return false;

    statusBadge.className = `badge badge-${proj.status}`;
    statusBadge.textContent = proj.status;

    const phaseCurrentEl = document.getElementById('projPhaseCurrent');
    if (phaseCurrentEl) {
        phaseCurrentEl.textContent = proj.phase_current || '—';
        phaseCurrentEl.className = proj.status === 'processing' ? 'info-value phase-current-pulsing' : 'info-value';
    }

    const updatedAtEl = document.getElementById('projUpdatedAt');
    if (updatedAtEl) updatedAtEl.textContent = tzFmt(proj.updated_at);

    const scoreBlockEl = document.getElementById('projScoreBlock');
    if (scoreBlockEl) scoreBlockEl.innerHTML = renderScore(proj);

    const blueprintEl = document.getElementById('projInfoBlueprint');
    if (blueprintEl) blueprintEl.innerHTML = _infoBlueprintHtml(docs);

    const protoEl = document.getElementById('projInfoPrototype');
    if (protoEl) protoEl.innerHTML = _infoPrototypeHtml(docs);

    const tbody = document.getElementById('phasesTableBody');
    if (tbody) { tbody.innerHTML = buildPhaseRows(proj, phases, docs); applyPhaseCollapseState(); }

    return true;
}

function renderPanel(proj, phases, docs) {
    const panel = document.getElementById('mainPanel');
    const refreshVal = document.getElementById('autoRefreshSelect')?.value || '12';

    panel.innerHTML = `
        <div class="editor-topbar">
            <input class="title-input" id="titleInput" value="${escHtml(proj.title || '')}" data-proj-id="${proj.id}" data-orig="${escHtml(proj.title || '')}" placeholder="Название">
            <select id="autoRefreshSelect" class="auto-refresh-select" title="Автообновление" onchange="autoRefreshStart()">
                <option value="0"${refreshVal === '0' ? ' selected' : ''}>Выкл</option>
                <option value="12"${refreshVal === '12' ? ' selected' : ''}>12 сек</option>
                <option value="30"${refreshVal === '30' ? ' selected' : ''}>30 сек</option>
                <option value="60"${refreshVal === '60' ? ' selected' : ''}>60 сек</option>
            </select>
            <span class="badge badge-${proj.status}" id="projStatusBadge">${proj.status}</span>
            <button class="btn-retry" onclick="retryProject(${proj.id})">↻ Сначала</button>
            <button class="btn-delete" onclick="deleteProject(${proj.id})">✕</button>
        </div>
        <div class="editor-body">
            <div class="info-grid">
                <div class="info-card"><label>ID</label><div class="info-value">#${proj.id}</div></div>
                <div class="info-card"><label>Фаза</label><div class="info-value${proj.status === 'processing' ? ' phase-current-pulsing' : ''}" id="projPhaseCurrent">${escHtml(proj.phase_current || '—')}</div></div>
                <div class="info-card"><label>Создан</label><div class="info-value">${tzFmt(proj.created_at)}</div></div>
                <div class="info-card"><label>Обновлён</label><div class="info-value" id="projUpdatedAt">${tzFmt(proj.updated_at)}</div></div>
                <div class="info-card"><label>Blueprint</label><div class="info-value" id="projInfoBlueprint">${_infoBlueprintHtml(docs)}</div></div>
                <div class="info-card"><label>Прототип</label><div class="info-value" id="projInfoPrototype">${_infoPrototypeHtml(docs)}</div></div>
            </div>
            <div class="section-title">Идея</div>
            <textarea class="idea-block" id="ideaInput" rows="4" data-proj-id="${proj.id}" data-orig="${escHtml(proj.idea || '')}">${escHtml(proj.idea || '')}</textarea>
            <div id="projScoreBlock">${renderScore(proj)}</div>
            <div class="section-title">Фазы</div>
            <table class="phases-table"><thead><tr>
                <th>Фаза</th><th>Статус</th><th>Длительность</th><th>↓ Вход</th><th>↑ Выход</th><th>Документы</th><th></th><th></th>
            </tr></thead><tbody id="phasesTableBody">${buildPhaseRows(proj, phases, docs)}</tbody></table>
        </div>`;
    autoRefreshStart();
    applyPhaseCollapseState();
}

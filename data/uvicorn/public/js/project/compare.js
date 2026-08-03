// Compare tab — multi-project scoring overview

function renderCompare() {
    const panel = document.getElementById('mainPanel');
    let projects = [...allProjects];

    if (compareFilter !== 'all') {
        if (compareFilter === 'scored') projects = projects.filter(p => p.score_verdict);
        else projects = projects.filter(p => p.score_verdict === compareFilter);
    }

    projects.sort((a, b) => {
        const av = a[compareSortKey] ?? -1;
        const bv = b[compareSortKey] ?? -1;
        if (av < bv) return compareSortDir;
        if (av > bv) return -compareSortDir;
        return 0;
    });

    function th(label, key, width = '') {
        const sorted = compareSortKey === key;
        const arrow = sorted ? (compareSortDir === -1 ? '↓' : '↑') : '↕';
        const cls = sorted ? 'sorted' : '';
        return `<th class="${cls}" onclick="sortCompare('${key}')" ${width ? `style="width:${width}"` : ''}>${label} <span class="sort-arrow">${arrow}</span></th>`;
    }

    function miniBar(val) {
        if (!val) return '<span style="color:#94a3b8;font-size:11px">—</span>';
        const cls = val >= 7 ? 'fill-high' : val >= 5 ? 'fill-mid' : 'fill-low';
        return `<div class="mini-bar">
            <div class="mini-bar-track"><div class="mini-bar-fill ${cls}" style="width:${val * 10}%"></div></div>
            <span class="mini-bar-val">${val}</span>
        </div>`;
    }

    const rows = projects.map(p => {
        const noScore = !p.score_verdict;
        const vBadge = p.score_verdict
            ? `<span class="score-verdict verdict-${p.score_verdict}">${p.score_verdict.toUpperCase()}</span>`
            : `<span class="badge badge-${p.status}">${p.status}</span>`;
        const total = p.score_total
            ? `<span class="cmp-score" style="color:${p.score_total >= 7 ? '#15803d' : p.score_total >= 5 ? '#b45309' : '#dc2626'}">${p.score_total}</span>`
            : '—';
        return `<tr class="${noScore ? 'no-score' : ''}" onclick="onCompareRowClick(${p.id})">
            <td class="cmp-title">${escHtml(p.title || (p.idea || '').slice(0, 50) || '—')}</td>
            <td>${vBadge}</td>
            <td>${total}</td>
            <td>${miniBar(p.score_market)}</td>
            <td>${miniBar(p.score_feasibility)}</td>
            <td>${miniBar(p.score_financial)}</td>
            <td class="cmp-meta">${escHtml(p.score_investment || '—')}</td>
            <td class="cmp-meta">${escHtml(p.score_time_to_market || '—')}</td>
            <td class="cmp-meta">${tzFmt(p.created_at).slice(0, 10)}</td>
        </tr>`;
    }).join('');

    const filters = [
        ['all', 'Все'], ['scored', 'Оценённые'], ['go', 'GO'], ['maybe', 'Maybe'], ['no', 'NO']
    ].map(([v, l]) => `<button class="filter-btn f-${v} ${compareFilter === v ? 'active' : ''}" onclick="setCompareFilter('${v}')">${l}</button>`).join('');

    panel.innerHTML = `<div class="compare-wrap">
        <div class="compare-filters">
            <span>Фильтр:</span>${filters}
            <span style="margin-left:auto;color:#94a3b8;font-size:12px">${projects.length} проектов</span>
        </div>
        ${projects.length ? `
        <table class="compare-table">
            <thead><tr>
                ${th('Проект', 'title', '220px')}
                ${th('Вердикт', 'score_verdict', '80px')}
                ${th('Итого', 'score_total', '60px')}
                ${th('Рынок', 'score_market', '90px')}
                ${th('Реализ.', 'score_feasibility', '90px')}
                ${th('Финансы', 'score_financial', '90px')}
                ${th('Инвестиции', 'score_investment')}
                ${th('Срок', 'score_time_to_market')}
                ${th('Создан', 'created_at', '90px')}
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>` : '<div class="empty-hint">Нет проектов для сравнения</div>'}
    </div>`;
}

function sortCompare(key) {
    if (compareSortKey === key) compareSortDir *= -1;
    else { compareSortKey = key; compareSortDir = -1; }
    renderCompare();
}

function setCompareFilter(f) {
    compareFilter = f;
    renderCompare();
}

function onCompareRowClick(id) {
    switchTab('projects');
    const el = document.querySelector(`.project-item[data-id="${id}"]`);
    selectProject(id, el);
}

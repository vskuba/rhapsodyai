// Project list, auto-refresh, project selection, field editing

let _dndSrc = null;
let _dndDragged = false;

async function loadProjects(keepSelection = false) {
    const list = document.getElementById('projectList');
    try {
        const data = await fetch('/planning/project/list').then(r => r.json());
        allProjects = data.result || [];
        if (!allProjects.length) {
            list.innerHTML = '<div class="empty-hint" style="padding:20px;text-align:center">Нет проектов</div>';
            return;
        }
        list.innerHTML = '';
        allProjects.forEach(p => {
            const div = document.createElement('div');
            div.className = 'project-item' + (p.id === currentProjectId ? ' active' : '');
            div.dataset.id = p.id;
            div.draggable = true;
            const date = tzFmt(p.created_at).slice(0, 10);
            let badgeHtml;
            if (p.status === 'processing' || p.status === 'running' || p.status === 'error' || p.status === 'failed') {
                badgeHtml = `<span class="badge badge-${p.status}">${p.status}</span>`;
            } else if (p.score_verdict) {
                badgeHtml = `<span class="score-verdict verdict-${p.score_verdict}">${p.score_verdict.toUpperCase()} ${p.score_total || ''}</span>`;
            } else if (p.status && p.status !== 'complete') {
                badgeHtml = `<span class="badge badge-${p.status}">${p.status}</span>`;
            } else {
                badgeHtml = '';
            }
            div.innerHTML = `
            <div class="project-item-top">
                <span class="project-drag-handle" draggable="false">⠿</span>
                <span class="project-item-title">${escHtml(p.title || (p.idea || '').slice(0, 60) || '—')}</span>
            </div>
            <div class="project-item-meta">
                <span class="project-item-date">${date}</span>${badgeHtml}
            </div>`;
            div.onclick = () => {
                if (_dndDragged) return;
                if (currentTab !== 'projects') switchTab('projects');
                selectProject(p.id, div);
            };
            _attachDndHandlers(div, list);
            list.appendChild(div);
        });
        if (!keepSelection && !currentProjectId && allProjects.length) {
            const firstDiv = list.querySelector('.project-item');
            selectProject(allProjects[0].id, firstDiv);
        }
        if (currentTab === 'compare') renderCompare();
        scheduleRefresh(allProjects.some(p => p.status === 'processing'));
    } catch {
        list.innerHTML = '<div class="empty-hint" style="padding:20px;text-align:center">Ошибка загрузки</div>';
    }
}

function _attachDndHandlers(div, list) {
    div.addEventListener('dragstart', function(e) {
        _dndSrc = div;
        _dndDragged = false;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', div.dataset.id);
        setTimeout(() => div.classList.add('dnd-dragging'), 0);
    });

    div.addEventListener('dragend', function() {
        div.classList.remove('dnd-dragging');
        list.querySelectorAll('.project-item').forEach(el => {
            el.classList.remove('dnd-over-top', 'dnd-over-bottom');
        });
        _dndSrc = null;
        setTimeout(() => { _dndDragged = false; }, 50);
    });

    div.addEventListener('dragover', function(e) {
        if (!_dndSrc || _dndSrc === div) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        const rect = div.getBoundingClientRect();
        const midY = rect.top + rect.height / 2;
        list.querySelectorAll('.project-item').forEach(el => {
            el.classList.remove('dnd-over-top', 'dnd-over-bottom');
        });
        div.classList.add(e.clientY < midY ? 'dnd-over-top' : 'dnd-over-bottom');
    });

    div.addEventListener('dragleave', function() {
        div.classList.remove('dnd-over-top', 'dnd-over-bottom');
    });

    div.addEventListener('drop', async function(e) {
        if (!_dndSrc || _dndSrc === div) return;
        e.preventDefault();
        _dndDragged = true;
        div.classList.remove('dnd-over-top', 'dnd-over-bottom');

        const rect = div.getBoundingClientRect();
        const insertBefore = e.clientY < rect.top + rect.height / 2;
        if (insertBefore) {
            list.insertBefore(_dndSrc, div);
        } else {
            list.insertBefore(_dndSrc, div.nextSibling);
        }

        const ids = Array.from(list.querySelectorAll('.project-item')).map(el => parseInt(el.dataset.id));
        try {
            await fetch('/planning/project/reorder', {
                method: 'PUT',
                credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ ids }),
            });
        } catch {}
    });
}

function autoRefreshStart() {
    clearInterval(autoRefreshTimer);
    const el = document.getElementById('autoRefreshSelect');
    const interval = el ? parseInt(el.value) * 1000 : 12000;
    if (!interval) return;
    autoRefreshTimer = setInterval(async () => {
        if (autoRefreshRunning) return;
        autoRefreshRunning = true;
        try { await _softRefresh(); } finally { autoRefreshRunning = false; }
    }, interval);
}

// Лёгкий авторефреш: обновляет только статусы в сайдбаре и динамические элементы
// в открытой панели — без перерисовки структуры страницы.
async function _softRefresh() {
    const data = await fetch('/planning/project/list').then(r => r.json());
    allProjects = data.result || [];
    _patchSidebarBadges(allProjects);
    if (currentProjectId && currentTab === 'projects' && document.getElementById('projStatusBadge')) {
        const [projRes, phasesRes, docsRes] = await Promise.all([
            fetch(`/planning/project/${currentProjectId}`).then(r => r.json()),
            fetch(`/planning/project/${currentProjectId}/phases`).then(r => r.json()),
            fetch(`/planning/project/${currentProjectId}/documents`).then(r => r.json()),
        ]);
        const proj = projRes.result || {};
        patchPanelDynamic(proj, phasesRes.result || [], docsRes.result || []);
        const idx = allProjects.findIndex(p => p.id === currentProjectId);
        if (idx !== -1) Object.assign(allProjects[idx], proj);
    }
    if (currentTab === 'compare') renderCompare();
}

// Патчит только бейджи статуса в сайдбаре — не трогает структуру списка.
function _patchSidebarBadges(projects) {
    projects.forEach(p => {
        const item = document.querySelector(`.project-item[data-id="${p.id}"]`);
        if (!item) return;
        const metaEl = item.querySelector('.project-item-meta');
        if (!metaEl) return;
        let badgeHtml = '';
        if (p.status === 'processing' || p.status === 'running' || p.status === 'error' || p.status === 'failed') {
            badgeHtml = `<span class="badge badge-${p.status}">${p.status}</span>`;
        } else if (p.score_verdict) {
            badgeHtml = `<span class="score-verdict verdict-${p.score_verdict}">${p.score_verdict.toUpperCase()} ${p.score_total || ''}</span>`;
        } else if (p.status && p.status !== 'complete') {
            badgeHtml = `<span class="badge badge-${p.status}">${p.status}</span>`;
        }
        const badgeEl = metaEl.querySelector('.badge, .score-verdict');
        if (badgeEl) {
            if (badgeHtml) { badgeEl.outerHTML = badgeHtml; } else { badgeEl.remove(); }
        } else if (badgeHtml) {
            metaEl.insertAdjacentHTML('beforeend', badgeHtml);
        }
    });
}

function scheduleRefresh(_active) { /* placeholder — handled by autoRefreshStart */ }

async function selectProject(id, el) {
    currentProjectId = id;
    document.querySelectorAll('.project-item').forEach(i => i.classList.remove('active'));
    if (el) el.classList.add('active');
    const panel = document.getElementById('mainPanel');
    panel.innerHTML = '<div class="placeholder-panel">Загрузка...</div>';
    try {
        const [projRes, phasesRes, docsRes] = await Promise.all([
            fetch(`/planning/project/${id}`).then(r => r.json()),
            fetch(`/planning/project/${id}/phases`).then(r => r.json()),
            fetch(`/planning/project/${id}/documents`).then(r => r.json()),
        ]);
        const proj = projRes.result || {};
        renderPanel(proj, phasesRes.result || [], docsRes.result || []);
        attachEditHandlers(id);
        // Синхронно обновляем карточку в сайдбаре по только что полученным данным
        const card = document.querySelector(`.project-item[data-id="${id}"]`);
        if (card) {
            const badgeEl = card.querySelector('.badge, .score-verdict');
            if (badgeEl) {
                const s = proj.status;
                if (s === 'processing' || s === 'running' || s === 'error' || s === 'failed') {
                    badgeEl.className = `badge badge-${s}`;
                    badgeEl.textContent = s;
                } else if (proj.score_verdict) {
                    badgeEl.className = `score-verdict verdict-${proj.score_verdict}`;
                    badgeEl.textContent = `${proj.score_verdict.toUpperCase()} ${proj.score_total || ''}`;
                } else if (s && s !== 'complete') {
                    badgeEl.className = `badge badge-${s}`;
                    badgeEl.textContent = s;
                } else {
                    badgeEl.className = '';
                    badgeEl.textContent = '';
                }
            }
        }
        // Обновляем allProjects чтобы следующий loadProjects не перетёр изменения
        const idx = allProjects.findIndex(p => p.id === id);
        if (idx !== -1) Object.assign(allProjects[idx], proj);
    } catch {
        panel.innerHTML = '<div class="placeholder-panel">Ошибка загрузки</div>';
    }
}

async function saveField(projId, field, value, origValue, el) {
    value = value.trim();
    if (!value || value === origValue.trim()) return;
    try {
        const res = await fetch(`/planning/project/${projId}`, {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({[field]: value}),
        });
        if (!res.ok) throw new Error(await res.text());
        el.dataset.orig = value;
        if (field === 'title') {
            const item = document.querySelector(`.project-item[data-id="${projId}"] .project-item-title`);
            if (item) item.textContent = value;
            const proj = allProjects.find(p => p.id === projId);
            if (proj) proj.title = value;
        }
    } catch (e) {
        el.value = origValue;
        alert('Ошибка: ' + e.message);
    }
}

function attachEditHandlers(projId) {
    const t = document.getElementById('titleInput');
    const i = document.getElementById('ideaInput');
    if (t) {
        t.addEventListener('blur', () => saveField(projId, 'title', t.value, t.dataset.orig, t));
        t.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); t.blur(); } });
    }
    if (i) i.addEventListener('blur', () => saveField(projId, 'idea', i.value, i.dataset.orig, i));
}

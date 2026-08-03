// Ideas generator — tab-based (no modal)

async function generateIdeas() {
    const niche = document.getElementById('ideasNiche').value.trim();
    const context = document.getElementById('ideasContext').value.trim();
    if (!niche) { alert('Введите нишу или тему'); return; }

    const btn = document.getElementById('btnGenerate');
    btn.disabled = true;
    btn.textContent = 'Генерируем...';

    const step2 = document.getElementById('ideasStep2');
    step2.style.display = '';
    document.getElementById('ideasContent').innerHTML = '<div class="ideas-loading">⏳ AI генерирует идеи... (~15–30 секунд)</div>';
    document.getElementById('ideasActions').style.display = 'none';

    try {
        const fullNiche = context ? `${niche}\n\nДополнительно: ${context}` : niche;
        const res = await fetch('/planning/ideas/generate', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({niche: fullNiche}),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        generatedIdeas = (data.result || []).map((item, i) => ({...item, selected: true, idx: i}));
        _saveIdeaBatch(niche, generatedIdeas);
        renderIdeas();
    } catch (e) {
        document.getElementById('ideasContent').innerHTML =
            `<div class="empty-hint" style="color:#dc2626">Ошибка: ${escHtml(e.message)}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Генерировать идеи';
    }
}

function renderIdeas() {
    const el = document.getElementById('ideasContent');
    if (!generatedIdeas.length) { el.innerHTML = '<div class="empty-hint">Нет идей</div>'; return; }
    const n = generatedIdeas.length;
    el.innerHTML = `
    <div style="margin-bottom:10px;display:flex;align-items:center;gap:10px;justify-content:space-between">
        <div style="font-size:13px;font-weight:600;color:#1e293b">✅ Сгенерировано ${n} идей — отметьте нужные и нажмите «Запустить»:</div>
        <button onclick="generateIdeas()" style="flex-shrink:0;padding:4px 10px;font-size:12px;border:1px solid #cbd5e1;border-radius:6px;background:#f8fafc;color:#475569;cursor:pointer;white-space:nowrap" title="Сгенерировать новый список идей">↻ Повторить</button>
    </div>
    <div class="ideas-list">${generatedIdeas.map((idea, i) => `
        <div class="idea-item ${idea.selected ? 'selected' : ''}" onclick="toggleIdea(${i})">
            <input type="checkbox" ${idea.selected ? 'checked' : ''} onchange="toggleIdea(${i})" onclick="event.stopPropagation()">
            <div class="idea-item-body">
                <div class="idea-item-title">${escHtml(idea.title || 'Без названия')}</div>
                <div class="idea-item-desc">${escHtml(idea.idea || '')}</div>
            </div>
        </div>`).join('')}
    </div>`;
    document.getElementById('ideasActions').style.display = 'flex';
    updateSelCount();
}

function toggleIdea(i) {
    generatedIdeas[i].selected = !generatedIdeas[i].selected;
    renderIdeas();
}

function selectAllIdeas() { generatedIdeas.forEach(i => i.selected = true); renderIdeas(); }
function clearAllIdeas()  { generatedIdeas.forEach(i => i.selected = false); renderIdeas(); }

function updateSelCount() {
    const n = generatedIdeas.filter(i => i.selected).length;
    document.getElementById('selCount').textContent = `Выбрано: ${n} из ${generatedIdeas.length}`;
}

async function launchIdeas() {
    const selected = generatedIdeas.filter(i => i.selected);
    if (!selected.length) { alert('Выберите хотя бы одну идею'); return; }
    const btn = document.getElementById('btnLaunch');
    btn.disabled = true;
    btn.textContent = 'Запускаем...';
    try {
        const res = await fetch('/planning/ideas/bulk-create', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ideas: selected}),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        generatedIdeas = [];
        document.getElementById('ideasStep2').style.display = 'none';
        await loadProjects(false);
        switchTab('projects');
        const created = data.result || [];
        if (created.length) {
            const el = document.querySelector(`.project-item[data-id="${created[0].id}"]`);
            selectProject(created[0].id, el);
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '🚀 Запустить выбранные';
    }
}

// ─── History ────────────────────────────────────────────────────────────────

function _saveIdeaBatch(niche, ideas) {
    const batch = {
        ts: new Date().toISOString(),
        niche,
        ideas: ideas.map(i => ({title: i.title || '', idea: i.idea || ''})),
    };
    ideaHistory.unshift(batch);
    if (ideaHistory.length > 30) ideaHistory = ideaHistory.slice(0, 30);
    localStorage.setItem('planningIdeaHistory', JSON.stringify(ideaHistory));
    renderIdeasHistory();
}

function clearIdeaHistory() {
    if (!ideaHistory.length) return;
    if (!confirm('Очистить всю историю генераций?')) return;
    ideaHistory = [];
    localStorage.removeItem('planningIdeaHistory');
    renderIdeasHistory();
}

function deleteIdeaBatch(idx) {
    ideaHistory.splice(idx, 1);
    localStorage.setItem('planningIdeaHistory', JSON.stringify(ideaHistory));
    renderIdeasHistory();
}

function renderIdeasHistory() {
    const el = document.getElementById('ideasHistorySection');
    if (!el) return;
    if (!ideaHistory.length) {
        el.innerHTML = '<div class="empty-hint" style="margin-top:20px">История генераций пуста</div>';
        return;
    }

    const fmt = ts => {
        try {
            const d = new Date(ts);
            const pad = n => String(n).padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
        } catch { return ts; }
    };

    el.innerHTML = `
    <div class="idea-history-section-title">
        <span style="font-size:13px;font-weight:600;color:#64748b">История генераций (${ideaHistory.length})</span>
        <button class="btn-icon-sm" onclick="clearIdeaHistory()" style="color:#dc2626;border-color:#fecaca">🗑 Очистить всё</button>
    </div>
    ${ideaHistory.map((batch, idx) => `
    <div class="idea-history-batch">
        <div class="idea-history-batch-header">
            <span>
                <span class="idea-history-batch-niche">${escHtml(batch.niche)}</span>
                · ${batch.ideas.length} идей · ${fmt(batch.ts)}
            </span>
            <button class="btn-delete-sm" onclick="deleteIdeaBatch(${idx})" title="Удалить">✕</button>
        </div>
        <div class="idea-history-items">
            ${batch.ideas.map(i => `<div class="idea-history-item">${escHtml(i.title)}</div>`).join('')}
        </div>
    </div>`).join('')}`;
}

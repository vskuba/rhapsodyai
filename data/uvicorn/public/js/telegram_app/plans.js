import { getData, postData, deleteData } from '/static/js/api.js';
import { state } from './state.js';
import { escapeHtml, confirmDialog } from './utils.js';
import { createVoiceRecorder } from './voice.js';
import { setSidebarPlanMode, updateInputBarsVisibility } from './sidebar.js';

let _listEl = null;
let _detailEl = null;
let _titleEl = null;
let _contentEl = null;

export function initPlans({ bar, textarea, sendBtn, micBtn, micCancel, progress, createBar }) {
    _listEl    = document.getElementById('plansListView');
    _detailEl  = document.getElementById('plansDetailView');
    _titleEl   = document.getElementById('planDetailTitle');
    _contentEl = document.getElementById('planDetailContent');

    document.getElementById('planBackIconBtn').addEventListener('click', closePlanDetail);
    document.getElementById('planDeleteIconBtn').addEventListener('click', deleteCurrentPlan);

    sendBtn.addEventListener('click', () => sendPlanEdit({ textarea, progress }));
    textarea.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendPlanEdit({ textarea, progress });
        }
    });

    createVoiceRecorder({
        micBtn,
        cancelBtn: micCancel,
        progressEl: progress,
        onError: () => showPlanError('Не удалось распознать голос'),
        onTranscript: async text => {
            textarea.value = text;
            await sendPlanEdit({ textarea, progress });
        },
    });

    createVoiceRecorder({
        micBtn: createBar.micBtn,
        cancelBtn: createBar.micCancel,
        progressEl: createBar.progress,
        onError: () => showPlansListError('Не удалось распознать голос'),
        onTranscript: createPlanFromInstruction,
    });
}

export async function loadPlans() {
    _listEl.innerHTML = '<div class="empty-state">Загрузка...</div>';
    try {
        const res = await getData('/telegram-app/plans');
        renderPlansList(res.result || []);
    } catch {
        _listEl.innerHTML = '<div class="denied-state">⚠️ Не удалось загрузить планы</div>';
    }
}

function renderPlansList(plans) {
    _listEl.innerHTML = plans.length
        ? plans.map(p => `<div class="plan-list-item" data-id="${p.id}">${escapeHtml(p.title)}</div>`).join('')
        : '<div class="empty-state">Планов пока нет. Надиктуйте новый план в микрофон внизу</div>';

    _listEl.querySelectorAll('.plan-list-item').forEach(el =>
        el.addEventListener('click', () => openPlanDetail(Number(el.dataset.id))));
}

async function openPlanDetail(planId) {
    const res = await getData(`/telegram-app/plans/${planId}`);
    state.currentPlanId = planId;
    _titleEl.textContent = res.result.title;
    renderPlanContent(res.result.content);
    _listEl.style.display = 'none';
    _detailEl.style.display = 'block';
    setSidebarPlanMode(true);
    updateInputBarsVisibility();
}

export function closePlanDetail() {
    state.currentPlanId = null;
    _detailEl.style.display = 'none';
    _listEl.style.display = 'block';
    setSidebarPlanMode(false);
    updateInputBarsVisibility();
}

async function deleteCurrentPlan() {
    if (!state.currentPlanId) return;
    const confirmed = await confirmDialog('Удалить этот план?');
    if (!confirmed) return;
    try {
        await deleteData(`/telegram-app/plans/${state.currentPlanId}`);
        closePlanDetail();
        await loadPlans();
    } catch (err) {
        showPlanError(err.message || 'Не удалось удалить план');
    }
}

async function sendPlanEdit({ textarea, progress }) {
    const instruction = textarea.value.trim();
    if (!instruction || !state.currentPlanId) return;
    textarea.value = '';
    progress.classList.add('active');
    try {
        const data = await postData(`/telegram-app/plans/${state.currentPlanId}/edit`, { instruction });
        renderPlanContent(data.result.content);
    } catch (err) {
        showPlanError(err.message || 'Ошибка правки плана');
    } finally {
        progress.classList.remove('active');
    }
}

async function createPlanFromInstruction(instruction) {
    // progress управляется voice recorder через progressEl
    try {
        const data = await postData('/telegram-app/plans', { instruction });
        await loadPlans();
        await openPlanDetail(data.result.id);
    } catch (err) {
        showPlansListError(err.message || 'Не удалось создать план');
    }
}

function showPlanError(message) {
    const banner = document.createElement('div');
    banner.className = 'denied-state';
    banner.style.color = '#e74c3c';
    banner.textContent = '⚠️ ' + message;
    _contentEl.prepend(banner);
}

function showPlansListError(message) {
    const banner = document.createElement('div');
    banner.className = 'denied-state';
    banner.style.color = '#e74c3c';
    banner.textContent = '⚠️ ' + message;
    _listEl.prepend(banner);
}

function renderPlanContent(markdown) {
    const lines = String(markdown || '').split('\n');
    const html = lines.map(line => {
        const escaped = escapeHtml(line).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
        const checkbox = line.match(/^\s*-\s\[([ xX])]\s(.*)$/);
        if (checkbox) {
            const checked = checkbox[1].toLowerCase() === 'x';
            const label = escapeHtml(checkbox[2]).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
            return `<div class="plan-line plan-checkbox"><input type="checkbox" disabled ${checked ? 'checked' : ''}><span>${label}</span></div>`;
        }
        if (/^#{1,3}\s/.test(line)) return `<div class="plan-heading">${escaped.replace(/^#{1,3}\s/, '')}</div>`;
        if (/^\s*-\s/.test(line)) return `<div class="plan-line">• ${escaped.replace(/^\s*-\s/, '')}</div>`;
        if (!line.trim()) return '<div class="plan-line-empty"></div>';
        return `<div class="plan-line">${escaped}</div>`;
    }).join('');
    _contentEl.innerHTML = html;
}

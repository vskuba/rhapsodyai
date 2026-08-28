import { getData, postData } from '/static/js/api.js';
import { state } from './state.js';
import { escapeHtml, confirmDialog } from './utils.js';
import { updateInputBarsVisibility } from './sidebar.js';

// Фаза -> имена типов задач (project_task_type.name). Тот же справочник, что на
// админской странице задач (admin/project/task.html, PHASE_TYPE_NAMES): расхождение
// здесь развело бы список мини-приложения и вкладки админки по разным местам.
const PHASE_TYPE_NAMES = {
    planning:    ['plan', 'research'],
    development: ['dev'],
    testing:     ['test'],
    bugs:        ['bug'],
};

const PHASE_KEYS = ['planning', 'development', 'testing', 'bugs'];

// Подпись состояния конвейера для чипа в карточке. Состояний больше — в карточке
// остаются только те, что встречаются; ключи без подписи получают своё имя как есть.
const PIPELINE_LABELS = {
    new: 'Ждёт плана',
    plan_approval: 'На утверждении',
    approved: 'Разложен',
    processing: 'В работе',
    reviewing: 'Пересмотр',
    testing: 'На проверке',
    done: 'Готово',
    failed: 'Сорвалась',
    blocked: 'Нужен человек',
};

let _listEl = null;
let _detailEl = null;
let _titleEl = null;
let _bodyEl = null;

let _tasks = [];
let _taskTypes = [];
let _phase = 'planning';
let _currentTaskId = null;

export function initTasks() {
    _listEl    = document.getElementById('tasksListView');
    _detailEl  = document.getElementById('tasksDetailView');
    _titleEl   = document.getElementById('taskDetailTitle');
    _bodyEl    = document.getElementById('taskDetailBody');

    document.getElementById('tabBtnTasks').addEventListener('click', () => {
        if (state.currentTab === 'tasks') loadTasks();
    });
}

export async function loadTasks() {
    _listEl.innerHTML = '<div class="empty-state">Загрузка...</div>';
    try {
        const [tasksRes, typesRes] = await Promise.all([
            getData('/telegram-app/tasks'),
            getData('/telegram-app/task-types'),
        ]);
        _tasks = tasksRes.tasks || [];
        _taskTypes = typesRes.task_types || [];
        renderList();
    } catch {
        _listEl.innerHTML = '<div class="denied-state">⚠️ Не удалось загрузить задачи</div>';
    }
}

function renderList() {
    // Внутренние вкладки фаз — шапка списка, по образцу stat-tabs админки.
    const counts = {};
    for (const phase of PHASE_KEYS) counts[phase] = _tasks.filter(t => taskMatchesPhase(t, phase)).length;

    const tabs = PHASE_KEYS.map(phase =>
        `<button class="task-phase-tab${phase === _phase ? ' active' : ''}" data-phase="${phase}">`
        + `${PHASE_LABEL[phase]} <span class="task-phase-n">${counts[phase]}</span></button>`
    ).join('');

    const items = _tasks.filter(t => taskMatchesPhase(t, _phase))
        .sort(taskCompare)
        .map(taskCardHtml).join('');

    _listEl.innerHTML =
        `<div class="task-phase-tabs">${tabs}</div>`
        + (items || '<div class="empty-state">В этой фазе задач нет</div>');

    _listEl.querySelectorAll('.task-phase-tab').forEach(btn =>
        btn.addEventListener('click', () => {
            _phase = btn.dataset.phase;
            renderList();
        }));
    _listEl.querySelectorAll('.task-card').forEach(el => {
        el.addEventListener('click', () => openTaskDetail(Number(el.dataset.id)));
        el.querySelector('.task-card-btn').addEventListener('click', e => {
            e.stopPropagation();
            cardAction(Number(el.dataset.id), e.currentTarget.dataset.action, el.dataset.id);
        });
    });
}

function taskCardHtml(t) {
    const done = isDone(t);
    const goalsHtml = goalProgressHtml(t);
    const pipe = t.pipeline_state
        ? `<span class="task-pipe-chip pipe-${escapeAttr(t.pipeline_state)}">${escapeHtml(PIPELINE_LABELS[t.pipeline_state] || t.pipeline_state)}</span>`
        : '';
    let actionBtn = '';
    if (t.pipeline_state === 'plan_approval' && !t.parent_id)
        actionBtn = `<button class="task-card-btn" data-action="approve" data-id="${t.id}" title="Утвердить план">✓</button>`;
    else if (t.pipeline_state === 'failed')
        actionBtn = `<button class="task-card-btn" data-action="retry" data-id="${t.id}" title="Перезапустить">↻</button>`;
    else if (!t.pipeline_state && !t.parent_id && !done)
        actionBtn = `<button class="task-card-btn" data-action="start" data-id="${t.id}" title="В конвейер">▶</button>`;

    return `<div class="task-card${done ? ' done' : ''}" data-id="${t.id}">
                <div class="task-card-head">
                    <span class="task-card-title">${escapeHtml(t.title || `Задача #${t.id}`)}</span>
                    ${actionBtn}
                </div>
                <div class="task-card-meta">
                    <span class="task-status-chip">${escapeHtml(STATUS_LABELS[t.status] || t.status || '')}</span>
                    ${pipe}
                </div>
                ${goalsHtml}
            </div>`;
}

function goalProgressHtml(t) {
    const goals = goalList(t);
    if (!goals.length) return '';
    const doneN = goals.filter(g => g.done).length;
    const pct = Math.round(doneN / goals.length * 100);
    return `<div class="task-goals-progress">
                <div class="task-goals-bar"><div class="task-goals-fill" style="width:${pct}%"></div></div>
                <span class="task-goals-count">${doneN}/${goals.length} целей</span>
            </div>`;
}

// Фаза строки — тот же разбор, что `taskMatchesPhase` админки: готовая работа уходит
// с вкладки своего типа на «Тестирование» (у бага инстанция своя), иначе задача
// висела бы сразу на двух вкладках.
function taskMatchesPhase(t, phase) {
    const name = typeNameOf(t) || 'dev'; // NULL → dev по умолчанию
    if (isDone(t)) return name === 'bug' ? phase === 'bugs' : phase === 'testing';
    return (PHASE_TYPE_NAMES[phase] || []).includes(name);
}

function typeNameOf(t) {
    const type = _taskTypes.find(x => x.id === t.task_type_id);
    return type ? type.name : null;
}

function isDone(t) {
    return t.status === 'done' || t.pipeline_state === 'done';
}

function goalList(t) {
    const goals = (typeof t.goals === 'string' && t.goals.trim()) ? JSON.parse(t.goals) : t.goals;
    if (Array.isArray(goals)) return goals;
    // В метаданных ответа `metadata.goals` — список целей. Сюда не заглядываем: у
    // плана задачи цели лежат в `pipeline_plan` (JSON), а корневой список мы в
    // бэкенде не подмешиваем.
    return [];
}

function taskCompare(a, b) {
    // Сначала незакрытые, в верхней части — те, что идёт прямо сейчас. Закрытое
    // место наверху занимать не должно, а растёт список именно им.
    const ai = isDone(a) ? 1 : 0;
    const bi = isDone(b) ? 1 : 0;
    if (ai !== bi) return ai - bi;
    const pa = parseInt(a.position, 10) || 0;
    const pb = parseInt(b.position, 10) || 0;
    if (pa !== pb) return pa - pb;
    return String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
}

async function openTaskDetail(taskId) {
    state.currentTaskId = taskId;
    _currentTaskId = taskId;
    const t = _tasks.find(x => x.id === taskId);
    _titleEl.textContent = t ? (t.title || `Задача #${taskId}`) : `Задача #${taskId}`;
    _listEl.style.display = 'none';
    _detailEl.style.display = 'block';
    updateInputBarsVisibility();
    renderDetail(t);
    await refreshQuestion(taskId);
}

export async function closeTaskDetail() {
    state.currentTaskId = null;
    _currentTaskId = null;
    _detailEl.style.display = 'none';
    _listEl.style.display = 'block';
    updateInputBarsVisibility();
}

function renderDetail(t) {
    if (!t) return;
    const goals = goalList(t);
    const goalsHtml = goals.length
        ? `<div class="task-detail-section">Цели${goals.map(g =>
            `<div class="task-goal${g.done ? ' done' : ''}">${g.done ? '✓' : '○'} ${escapeHtml(g.text)}</div>`).join('')}</div>`
        : '<div class="task-detail-section task-detail-muted">Целей нет</div>';

    const pipe = t.pipeline_state
        ? `<span class="task-pipe-chip pipe-${escapeAttr(t.pipeline_state)}">${escapeHtml(PIPELINE_LABELS[t.pipeline_state] || t.pipeline_state)}</span>`
        : '<span class="task-detail-muted">Вне конвейера</span>';

    const meta = `<div class="task-detail-meta"><span class="task-status-chip">${escapeHtml(STATUS_LABELS[t.status] || t.status || '')}</span> ${pipe}</div>`;

    let planText = '';
    if (t.pipeline_plan) {
        try {
            const parsed = JSON.parse(t.pipeline_plan);
            planText = String(parsed.plan_text || '');
        } catch {
            planText = String(t.pipeline_plan);
        }
    }
    const planHtml = planText.trim()
        ? `<div class="task-detail-section task-detail-plan">${planLinesHtml(planText)}</div>`
        : '';

    let actions = '';
    if (t.pipeline_state === 'plan_approval' && !t.parent_id) {
        actions = `<div class="task-detail-actions">
                <button class="task-action-btn ok" data-action="approve">✓ Утвердить</button>
                <button class="task-action-btn no" data-action="reject">✕ Отклонить</button>
            </div>`;
    } else if (t.pipeline_state === 'failed') {
        actions = `<div class="task-detail-actions">
                <button class="task-action-btn primary" data-action="retry">↻ Перезапустить</button>
            </div>`;
    } else if (!t.pipeline_state && !t.parent_id) {
        actions = `<div class="task-detail-actions">
                <button class="task-action-btn primary" data-action="start">▶ В конвейер</button>
            </div>`;
    }

    const errorHtml = t.pipeline_error
        ? `<div class="task-detail-error">${escapeHtml(t.pipeline_error)}</div>` : '';

    const questionBlock = '<div class="task-detail-question" id="taskQuestionBlock"></div>';

    _bodyEl.innerHTML =
        meta + errorHtml + planHtml + goalsHtml
        + (t.description ? `<div class="task-detail-section task-detail-desc">${escapeHtml(t.description)}</div>` : '')
        + questionBlock + actions;

    _bodyEl.querySelectorAll('.task-action-btn').forEach(btn =>
        btn.addEventListener('click', () => detailAction(btn.dataset.action)));
}

function planLinesHtml(markdown) {
    return String(markdown).split('\n').map(line => {
        const escaped = escapeHtml(line).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
        if (/^#{1,3}\s/.test(line)) return `<div class="plan-heading">${escaped.replace(/^#{1,3}\s/, '')}</div>`;
        if (/^\s*-\s/.test(line)) return `<div class="plan-line">• ${escaped.replace(/^\s*-\s/, '')}</div>`;
        if (!line.trim()) return '<div class="plan-line-empty"></div>';
        return `<div class="plan-line">${escaped}</div>`;
    }).join('');
}

async function refreshQuestion(taskId) {
    const el = document.getElementById('taskQuestionBlock');
    if (!el || _currentTaskId !== taskId) return;
    try {
        const res = await getData(`/telegram-app/task/${taskId}/question`);
        const q = res.question || {};
        if (!q.text) {
            el.innerHTML = res.decisions && res.decisions.length
                ? '<div class="task-detail-section">Решения</div>' + res.decisions.map(d =>
                    `<div class="task-question-decision"><b>${escapeHtml(d.question || '')}</b><br>${escapeHtml(d.answer)}</div>`).join('')
                : '';
            return;
        }
        const optionsHtml = (q.options || []).map(o =>
            `<label class="task-question-option"><input type="${q.multi ? 'checkbox' : 'radio'}" name="qopt" value="${escapeAttr(o.key)}"> ${escapeHtml(o.label)}${o.hint ? `<div class="task-question-hint">${escapeHtml(o.hint)}</div>` : ''}</label>`
        ).join('');
        el.innerHTML =
            `<div class="task-detail-section task-question">
                <div class="task-question-title">Вопрос агента</div>
                <div class="task-question-text">${escapeHtml(q.text)}</div>
                ${optionsHtml}
                <textarea class="task-question-note" id="taskQuestionNote" rows="2" placeholder="Свой ответ..."></textarea>
                <button class="task-action-btn primary" id="taskQuestionSend">Ответить</button>
                <div class="task-question-err" id="taskQuestionErr"></div>
            </div>`;
        el.querySelector('#taskQuestionSend').addEventListener('click', () => sendAnswer(taskId));
    } catch {
        el.innerHTML = '<div class="task-detail-muted">Не удалось загрузить вопрос</div>';
    }
}

async function sendAnswer(taskId) {
    const el = document.getElementById('taskQuestionBlock');
    const sendBtn = el.querySelector('#taskQuestionSend');
    const errEl = el.querySelector('#taskQuestionErr');
    errEl.textContent = '';
    const answers = [...el.querySelectorAll('input[name="qopt"]:checked')].map(i => i.value);
    const note = el.querySelector('#taskQuestionNote').value.trim();
    if (!answers.length && !note) {
        errEl.textContent = 'Выберите вариант или напишите ответ';
        return;
    }
    sendBtn.disabled = true;
    try {
        await postData(`/telegram-app/task/${taskId}/question`, { answers, note });
        await loadTasksSafe();
        await openTaskDetail(taskId);
    } catch (err) {
        errEl.textContent = err.message || 'Не удалось отправить ответ';
        sendBtn.disabled = false;
    }
}

async function cardAction(taskId, action) {
    try {
        await pipelineCall(taskId, action);
        await loadTasksSafe();
    } catch (err) {
        _listEl.prepend(notice(err.message || 'Не удалось выполнить действие'));
    }
}

async function detailAction(action) {
    const taskId = _currentTaskId;
    if (!taskId) return;
    try {
        await pipelineCall(taskId, action);
        await loadTasksSafe();
        await openTaskDetail(taskId);
    } catch (err) {
        const body = document.getElementById('taskDetailBody');
        if (body) body.prepend(notice(err.message || 'Не удалось выполнить действие'));
    }
}

async function pipelineCall(taskId, action) {
    const res = await postData(`/telegram-app/task/${taskId}/pipeline/${action}`, {});
    // Обновляем карточку из свежего ответа, если строка ещё на экране.
    if (res.task) {
        const i = _tasks.findIndex(x => x.id === taskId);
        if (i >= 0) _tasks[i] = res.task;
    }
    return res;
}

// Перечитать список и перерисовать текущую фазу. После действия строка могла уйти
// с вкладки (утверждённая — на «Разработку»), поэтому список обновляем целиком.
async function loadTasksSafe() {
    try {
        const res = await getData('/telegram-app/tasks');
        _tasks = res.tasks || [];
        renderList();
    } catch {
        _listEl.innerHTML = '<div class="denied-state">⚠️ Не удалось обновить список</div>';
    }
}

function notice(text) {
    const div = document.createElement('div');
    div.className = 'denied-state';
    div.style.color = '#e74c3c';
    div.textContent = '⚠️ ' + text;
    return div;
}

function escapeAttr(s) {
    return String(s || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const STATUS_LABELS = {
    active: 'В работе',
    queued: 'В очереди',
    pending: 'Ожидает',
    blocked: 'Заблокировано',
    cancelled: 'Отменено',
    done: 'Готово',
};

const PHASE_LABEL = {
    planning: 'Планирование',
    development: 'Разработка',
    testing: 'Тестирование',
    bugs: 'Баги',
};
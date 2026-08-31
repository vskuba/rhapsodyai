/**
 * questions.js — панель вопросов и ответа задачи
 *
 * Эндпоинты из telegram_app_task.py:
 *   GET /telegram-app/task/{id}/question
 *   POST /telegram-app/task/{id}/question/answer
 *
 * Формат вопроса — зеркало task.html askOpen (строка 4619):
 *   { question: { text, role, auto, options: [{key,label,hint}], answer: {text,keys} } }
 *   { questions: [...], answers: [...] }          — пачка (batch)
 *   { goals: [] }, decisions: [], attempts: {}
 */

import { getData, postData } from '/static/js/api.js';
import { escapeHtml as esc } from './utils.js';
import { loadTasks } from './tasks.js';

const API_QUESTION = (id) => `/telegram-app/task/${id}/question`;
const API_ANSWER = (id) => `/telegram-app/task/${id}/question/answer`;

// --- Состояние панели ---

let _barEl = null;              // taskQuestionPanel в шаблоне вкладки, заводим сами, если его нет
let _askTaskId = null;
let _askData = null;            // сырой ответ от сервера
let _askIndex = 0;              // индекс текущего вопроса в пачке

// Глобальные callback-и для вызова из HTML-строк шаблонов
window._qnsCallbacks = {};

// Кнопки панели рисуются строкой (`onclick="askSend()"`), поэтому обработчики живут на
// window. `closeQuestionPanel` — экспорт модуля, сама по себе глобальной не является:
// без этой строки «Закрыть» жал бы ReferenceError на каждом нажатии.
window.closeQuestionPanel = closeQuestionPanel;

/** Зарегистрировать коллбек для загрузки вопросов извне (вызывается из tasks.js) */
export function registerLoadCallback(cb) {
    window._qnsCallbacks.loadFromOutside = cb;
}

/**
    Полоса вопросов: внешний слой `.task-bar` (им переключается видимость),
    отступы — внутреннему `.task-question-panel`.
    */
function ensureBar() {
    if (_barEl && _barEl.isConnected) return _barEl;

    _barEl = document.getElementById('taskQuestionPanel') || document.getElementById('taskQuestionBar');
    if (!_barEl) {
        // Шаблона с панелью может и не быть — вкладку рисует соседняя подзадача, а
        // панель обязана появиться на любом каркасе: вставляем её в оболочку сами.
        _barEl = document.createElement('div');
        _barEl.id = 'taskQuestionPanel';
        (document.querySelector('.app-shell') || document.body).appendChild(_barEl);
    }
    _barEl.classList.add('task-bar');
    _barEl.classList.remove('task-question-panel');   // отступы належат внутреннему слою
    return _barEl;
}

/** Положить разметку в панель: одним движением, чтобы старый вопрос не мигал под новым */
function renderBar(inner) {
    const bar = ensureBar();
    if (!bar) return;
    bar.innerHTML = `<div class="task-question-panel">${inner}</div>`;
    bar.classList.add('chat-visible');
}

// Вызов из задач.js при клике на карточку
export async function openQuestionPanel(taskId) {
    ensureBar();
    _askTaskId = taskId;
    _askData = null;
    _askIndex = 0;

    showLoading();
    try {
        _askData = await getData(API_QUESTION(taskId));
        renderAsk();
    } catch (e) {
        showError(e.message || 'Не удалось открыть вопрос');
    }
}

export function closeQuestionPanel() {
    _askTaskId = null;
    _askData = null;
    _askIndex = 0;
    hideBar();
}

// --- Рендер панели ---

function showLoading() {
    renderBar('<div class="task-no-questions">Загружаю…</div>');
}

function showError(message) {
    renderBar(`<div class="task-no-questions">⚠️ ${esc(message)}</div>`);
}

function hideBar() {
    if (!_barEl || !_barEl.isConnected) return;
    _barEl.classList.remove('chat-visible');
    _barEl.innerHTML = '';
}

/** Заголовок роли вопроса — по образцу task.html _askRoleTitle */
function _roleTitle(role, auto) {
    if (auto) return 'Конвейер';
    switch (role) {
        case 'manager': return 'Менеджер';
        case 'developer': return 'Разработчик';
        case 'tester': return 'Тестировщик';
        case 'bugfixer': return 'Багфиксер';
        case 'orchestrator': return 'Оркестратор';
        default: return role || 'Система';
    }
}

/** Варианты действий над целями — ключи, требующие выбора целей */
const ASK_GOAL_ACTIONS = ['goals_split', 'goals_drop'];

function renderAsk() {
    const data = _askData || {};
    const batch = data.questions || [];
    const q = batch.length ? (batch[_askIndex] || batch[0] || {}) : (data.question || {});
    const left = batch.filter(item => !item.answer?.text).length;

    let parts = [];

    // Полоса переключения вопросов пачки
    if (batch.length > 1) {
        parts.push(askTabsHtml(batch));
    }

    // Заголовок
    const titleText = batch.length > 1
        ? `Вопросы по задаче #${_askTaskId}: ${batch.length - left} из ${batch.length}`
        : `Вопрос по задаче #${_askTaskId}`;
    parts.push(`<div class="task-question-header">${titleText}</div>`);

    // Нет вопросов
    if (!q.text) {
        parts.push('<div class="task-no-questions">Вопросов по этой задаче нет — она идёт своим ходом.</div>');
        renderBar(parts.join(''));
        return;
    }

    // Текст вопроса
    parts.push(`<div class="task-question-text"><span class="task-question-role">Спрашивает: ${_roleTitle(q.role, q.auto)}</span>${esc(q.text)}</div>`);

    // Варианты ответа
    const options = q.options || [];
    if (options.length) {
        const type = q.multi ? 'checkbox' : 'radio';
        let optHtml = '<div class="task-question-options">';
        options.forEach(o => {
            optHtml += `<label class="task-option-label" onclick="askPick()">`
                + `<input type="${type}" name="askOpt" value="${esc(o.key)}">`
                + `<span>${esc(o.label)}`
                + `${o.hint ? `<span class="task-option-hint">${esc(o.hint)}</span>` : ''}</span></label>`;
        });
        optHtml += '</div>';
        parts.push(optHtml);
    }

    // Поле уточнения
    parts.push(`<textarea class="task-question-note" id="askNote"`
        + ` placeholder="${options.length ? 'Необязательно: условие или оговорка к выбранному варианту' : 'Ответ своими словами'}"`
        + `>${esc(q.answer?.note || '')}</textarea>`);

    // Кнопки
    const last = (left <= 1 && !!q.answer?.text === false) || (left === 1 && !q.answer?.text);
    const btnLabel = batch.length ? (last ? 'Ответить на всё и принять решения' : 'Сохранить ответ') : 'Ответить и вернуть в работу';

    let hint = '';
    if (batch.length && left) {
        hint = `<div style="font-size:11px;color:#a0aec0;margin-top:6px;">Без ответа: ${left} из ${batch.length}. Решения запишутся, когда ответите на все.</div>`;
    }

    parts.push(`<div class="task-question-actions">
        <button class="task-btn" onclick="closeQuestionPanel()">Закрыть</button>
        <button class="task-btn task-btn-primary" id="askSendBtn" onclick="askSend()">${btnLabel}</button>
    </div>`);
    parts.push(hint);

    // Принятые решения
    const kept = data.decisions || [];
    if (kept.length) {
        let decHtml = '<div style="margin-top:12px;padding-top:8px;border-top:1px solid #edf2f7;">';
        decHtml += '<div style="font-size:12px;font-weight:600;color:#4a5568;margin-bottom:4px;">Принятые решения (' + kept.length + ')</div>';
        kept.slice().reverse().forEach(d => {
            decHtml += `<div class="task-decision"><b>${esc(d.question || '')}</b><br>${esc(d.answer)}`
                + `<span class="task-decision-meta">${esc(d.at || '')}${d.by ? ' · ' + esc(d.by) : ''}</span></div>`;
        });
        decHtml += '</div>';
        parts.push(decHtml);
    }

    renderBar(parts.join(''));

    // Восстанавливаем выбранные варианты
    const picked = q.answer?.keys || [];
    if (picked.length) {
        setTimeout(() => {
            picked.forEach(key => {
                const input = _barEl.querySelector(`#askBody input[name="askOpt"][value="${key}"], [name="askOpt"][value="${key}"]`);
                if (input) input.checked = true;
            });
            askPick();
        }, 0);
    }
}

/** Полоса вопросов — номер, признак ответа и переключение */
function askTabsHtml(batch) {
    let html = '<div class="task-question-batch-tabs">';
    batch.forEach((item, n) => {
        const done = !!item.answer?.text;
        const cls = 'task-question-batch-tab'
            + (n === _askIndex ? ' current' : '')
            + (done ? ' done' : '');
        html += `<button class="${cls}" onclick="askGo(${n})" title="${esc(item.text || '')}">`
            + `${done ? '✓' : ''}${n + 1}</button>`;
    });
    html += '</div>';
    return html;
}

// Переключение между вопросами пачки
window.askGo = async function(index) {
    if (index === _askIndex) return;
    await askDraftSave();
    _askIndex = index;
    renderAsk();
};

// Подсветка выбранного варианта
window.askPick = function() {
    setTimeout(() => {
        if (!_barEl || !_barEl.isConnected) return;
        _barEl.querySelectorAll('.task-option-label').forEach(label => {
            const input = label.querySelector('input');
            if (input) {
                label.classList.toggle('picked', !!input.checked);
            }
        });
        // Показ/скрытие списка целей при действиях над ними
        const pickedKeys = [..._barEl.querySelectorAll('[name="askOpt"]:checked')]
            .map(i => i.value);
        const hasGoalAction = pickedKeys.some(k => ASK_GOAL_ACTIONS.includes(k));
    }, 0);
};

// Форма: что набрано прямо сейчас
function askFormRead() {
    return {
        answers: [...(_barEl?.querySelectorAll('[name="askOpt"]:checked') || [])].map(i => i.value),
        note: ((_barEl?.getElementById('askNote'))?.value || '').trim(),
    };
}

// Сохранить черновик текущего вопроса пачки
async function askDraftSave() {
    const batch = (_askData || {}).questions || [];
    if (!batch.length) return;

    const form = askFormRead();
    if (!form.answers.length && !form.note) return;

    try {
        await postData(API_ANSWER(_askTaskId), { ...form, index: _askIndex });
        // Обновляем данные, но не перерисовываем — пользователь должен видеть свой текст
    } catch { /* черновик не сохранился — набранное остаётся в форме */ }
}

/** Отправить ответ */
window.askSend = async function() {
    const btn = _barEl?.querySelector('#askSendBtn');
    const batch = (_askData || {}).questions || [];

    if (batch.length) {
        const form = askFormRead();
        if (!form.answers.length && !form.note) { alert('Выберите вариант или напишите ответ'); return; }

        btn.disabled = true;
        btn.textContent = 'Сохраняю…';
        try {
            const result = await postData(API_ANSWER(_askTaskId), { ...form, index: _askIndex });
            if (result.done) {
                closeQuestionPanel();
                await loadTasks();
                return;
            }
            // Ответили не на всё — переключаемся на первый неотвеченный
            _askData = await getData(API_QUESTION(_askTaskId));
            const rest = (_askData.questions || []).findIndex(item => !item.answer?.text);
            _askIndex = rest >= 0 ? rest : _askIndex;
            renderAsk();
        } catch (e) {
            alert(e.message || 'Не отправилось');
            btn.disabled = false;
        }
        return;
    }

    // Одиночный вопрос — тоже читаем форму заново
    const answers = [...(_barEl?.querySelectorAll('[name="askOpt"]:checked') || [])].map(i => i.value);
    const note = ((_barEl?.getElementById('askNote'))?.value || '').trim();
    if (!answers.length && !note) { alert('Выберите вариант или напишите ответ'); return; }

    btn.disabled = true;
    btn.textContent = 'Отправляю…';
    try {
        await postData(API_ANSWER(_askTaskId), { answers, note, goal_indexes: [] });
        closeQuestionPanel();
        await loadTasks();
    } catch (e) {
        alert(e.message || 'Не отправилось');
        btn.disabled = false;
        btn.textContent = 'Ответить и вернуть в работу';
    }
};

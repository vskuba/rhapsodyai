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
 *
 * Нумерация целей. `goal_indexes` — место цели в списке, и сервер применяет их к
 * списку, ещё раз прогнанному через `task_plan_goals_normalize`
 * (`task_goal_scope.py:63` и `:103`), а не к тому, что принесли с карточки. Поэтому
 * отметка цели ведётся по GET-у вопроса: он отдаёт уже схлопнутый список, и его номер
 * совпадает с серверным до строки. Цели строки списка — подстраховка: подставляются,
 * только когда GET целей не принёс (`_withRowGoals`), чтобы панель не оставалась вовсе
 * без целей и не звала бы «отметь цель», которую не показала (`_goalChoices`).
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
let _askRowGoals = [];          // цели строки списка: подстраховка показа, не для отметки
let _askIndex = 0;              // индекс текущего вопроса в пачке

// Кнопки панели рисуются строкой (`onclick="askSend()"`), поэтому обработчики живут на
// window. `closeQuestionPanel` — экспорт модуля, сама по себе глобальной не является:
// без этой строки «Закрыть» жал бы ReferenceError на каждом нажатии.
window.closeQuestionPanel = closeQuestionPanel;

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

/**
    Вызов из задач.js при клике на карточку.

    `taskRow` — строка задачи из уже загруженного списка. С ней панель показывает
    вопрос сразу: сам вопрос живёт в `metadata`, а список (`/telegram-app/tasks`)
    отдаёт его разобранным — иными словами материал для панели уже в руках.
    GET `/telegram-app/task/{id}/question` — уточнение, а не единственный источник:
    он дорисовывает принятые решения и попытки, но без него панель остаётся рабочей,
    потому что ответ уходит на POST, который от GET не зависит.
    */
export async function openQuestionPanel(taskId, taskRow = null) {
    ensureBar();
    _askTaskId = taskId;
    _askRowGoals = _goalsFromRow(taskRow);
    _askData = questionFromRow(taskRow);
    _askIndex = 0;

    if (_askData) {
        renderAsk();
    } else {
        showLoading();
    }
    try {
        const fresh = await getData(API_QUESTION(taskId));
        if (_askTaskId === taskId) {
            _askData = _withRowGoals(fresh);
            renderAsk();
        }
    } catch (e) {
        // Уже показали вопрос из списка — показывать поверх него ошибку смысла нет:
        // ответ всё равно уходит на POST и дойдёт.
        if (!_askData || _askTaskId !== taskId) showError(e.message || 'Не удалось открыть вопрос');
    }
}

/**
    Открытый вопрос задачи — тем же видом, что кладёт в мешок `task_question_ask`
    (`task_question.py:39`, ключ `question`), и таким, каким его рисует GET вопроса.

    Список задач отдаёт вопрос прямо в `metadata` строки, поэтому панель открывается
    сразу, не дожидаясь второго запроса: до него человек видит вопрос, пачку разведки
    и принятые решения. GET дублирует то же самое — и когда он не успел, и когда его
    нет вовсе, карточка обязана оставаться рабочей, а не пустой.

    Вызывается до `openQuestionPanel` и из неё самой, поэтому export-а нет: снаружи
    вопрос открывают одной точкой — `openQuestionPanel`.
    */
function questionFromRow(row) {
    const meta = row && typeof row.metadata === 'object' && row.metadata ? row.metadata : null;
    if (!meta) return null;

    return {
        question: meta.question || null,
        // Пачка разведки живёт отдельным ключом (`TASK_QUESTION_KEY_QUEUE`), черновики
        // ответов едут внутри неё — панель по ней листает вопросы.
        questions: Array.isArray(meta.questions) ? meta.questions : [],
        // Цели — колонка задачи, а не ключ metadata: без них ответ «раздробить/убрать»
        // упирался бы в запрет отметить цель, которой панель не видела (см. _goalChoices).
        goals: _goalsFromRow(row),
        decisions: Array.isArray(meta.decisions) ? meta.decisions : [],
    };
}

/** Свернуть панель: состояние сбрасываем, чтобы следующий клик открыл свою задачу */
export function closeQuestionPanel() {
    _askTaskId = null;
    _askData = null;
    _askRowGoals = [];
    _askIndex = 0;
    hideBar();
}

/**
    Цели строки списка — к тому же виду `[{text, done}]`, что отдаёт GET вопроса.

    Колонка `goals` приезжает то списком словарей, то списком строк, то JSON-строкой
    (из MySQL — именно строкой): как её ни отдай, панель получает одно и то же.
    Закрытая цель остаётся `disabled`: вычеркнуть принятую работу нельзя.

    Здесь только показ до ответа на вопрос, а не список для отметки, поэтому цели и не
    схлопываются: сервер перед применением `goal_indexes` прогоняет колонку через
    `task_plan_goals_normalize` (`task_plan.py:101`, порог похожести 0.85), и повторять
    норму на клиенте значило бы завести второй источник истины, разъезжающийся при
    каждом изменении Python-функции. Нумерация — серверная, см. `_withRowGoals`.

    Текст берётся из словаря по ключу, а не через `String(item)`: иначе `{}` или
    `{done: true}` под номером рисовали бы `[object Object]` с подписью `undefined`.
    */
function _goalsFromRow(row) {
    let raw = row && row.goals;
    if (typeof raw === 'string') {
        try { raw = JSON.parse(raw || '[]'); } catch { return []; }
    }
    if (raw && !Array.isArray(raw) && Array.isArray(raw.goals)) raw = raw.goals;
    if (!Array.isArray(raw)) return [];

    return raw
        .map(item => ({
            text: String((item && typeof item === 'object' ? item.text : item) ?? '').trim(),
            done: !!(item && typeof item === 'object' && item.done),
        }))
        .filter(g => g.text);
}

/**
    Ответ GET, дополненный целями строки списка — только когда своих нет.

    `goal_indexes` сервер применяет к своему списку целей, поэтому отметка ведётся по
    серверной нумерации: GET-овские цели имеют приоритет, а цели карточки подставляются
    лишь когда ответа нет или он их не принёс. Иначе панель рисовала бы отметку по
    собственному счёту ровно там, где сервер пересчитывает список.
    */
function _withRowGoals(fresh) {
    const data = (fresh && typeof fresh === 'object') ? { ...fresh } : {};
    if (!Array.isArray(data.goals) || !data.goals.length) data.goals = _askRowGoals;
    return data;
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

    // Текст вопроса. Кто спрашивает — отдельной строкой над ним, как в `task.html:4663`:
    // роль отвечает за смысл развилки, а не за формулировку, и в одном потоке с текстом
    // она читалась бы началом вопроса.
    parts.push(`<div class="task-question-role">Спрашивает: ${esc(_roleTitle(q.role, q.auto))}</div>`);
    parts.push(`<div class="task-question-text">${esc(q.text)}</div>`);

    // Варианты ответа
    const options = q.options || [];
    if (options.length) {
        const type = q.multi ? 'checkbox' : 'radio';
        let optHtml = '<div class="task-question-label">Варианты ответа</div><div class="task-question-options">';
        options.forEach(o => {
            optHtml += `<label class="task-option-label" onclick="askPick()">`
                + `<input type="${type}" name="askOpt" value="${esc(o.key)}">`
                + `<span>${esc(o.label)}`
                + `${o.hint ? `<span class="task-option-hint">${esc(o.hint)}</span>` : ''}</span></label>`;
        });
        optHtml += '</div>';
        parts.push(optHtml);
    }

    // Цели спрятаны, пока не выбрано действие над ними: список чекбоксов, показанный
    // сразу, читается как «отметь цели», хотя ответ может быть и не про них.
    // Скрыт до выбора действия над целями — см. `task.html:4678`
    parts.push(`<div class="task-question-goals" id="askGoals" style="display:none">${askGoalsHtml(data.goals || [])}</div>`);

    parts.push('<div class="task-question-label">Уточнение</div>'
        + `<textarea class="task-question-note" id="askNote"`
        + ` placeholder="${options.length ? 'Необязательно: условие или оговорка к выбранному варианту' : 'Ответ своими словами'}"`
        + `>${esc(q.answer?.note || '')}</textarea>`);

    // Кнопки
    const last = (left <= 1 && !!q.answer?.text === false) || (left === 1 && !q.answer?.text);
    const btnLabel = batch.length ? (last ? 'Ответить на всё и принять решения' : 'Сохранить ответ') : 'Ответить и вернуть в работу';

    let hint = '';
    if (batch.length && left) {
        hint = `<div class="task-question-hint">Без ответа: ${left} из ${batch.length}. Решения запишутся, когда ответите на все.</div>`;
    }

    parts.push(`<div class="task-question-actions">
        <button class="task-btn" onclick="closeQuestionPanel()">Закрыть</button>
        <button class="task-btn task-btn-primary" id="askSendBtn" onclick="askSend()">${btnLabel}</button>
    </div>`);
    parts.push(hint);

    // Принятые решения
    const kept = data.decisions || [];
    if (kept.length) {
        // Классы те же, что в админке (`ask-decision`), только под своим префиксом:
        // порядок обратный — свежие решения выше, как их оставил `task.html:4710`.
        parts.push('<div class="task-decisions">'
            + `<div class="task-question-label">Принятые решения (${kept.length})</div>`
            + kept.slice().reverse().map(d => `<div class="task-decision">`
                + (d.question ? `<b>${esc(d.question)}</b><br>` : '')
                + `${esc(d.answer)}<span class="task-decision-meta">${esc(d.at || '')}${d.by ? ' · ' + esc(d.by) : ''}</span></div>`).join('')
            + '</div>');
    }

    renderBar(parts.join(''));

    // Восстанавливаем выбранные варианты
    const picked = q.answer?.keys || [];
    if (picked.length) {
        setTimeout(() => {
            picked.forEach(key => {
                // Ищем внутри панели, а не по `#askBody` страницы: в мини-приложении
                // своим контейнером она не обзаводится.
                const input = _barEl.querySelector(`input[name="askOpt"][value="${key}"]`);
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
        _showGoals(pickedKeys.some(k => ASK_GOAL_ACTIONS.includes(k)));
    }, 0);
};

// Форма: что набрано прямо сейчас
function askFormRead() {
    return {
        answers: [...(_barEl?.querySelectorAll('[name="askOpt"]:checked') || [])].map(i => i.value),
        note: _noteValue(),
    };
}

/**
    Набранное в поле уточнения.

    `getElementById` ищет по всему документу и есть только у самого документа: у
    узла панели его нет, а `?.` на отсутствующий метод не спасает. Ищем по
    документу и проверяем, что поле принадлежит панели — иначе взяли бы чужое,
    когда на странице заведётся второе `askNote`.
    */
function _noteValue() {
    if (!_barEl || !_barEl.isConnected) return '';
    const note = document.getElementById('askNote');
    return (note && _barEl.contains(note) ? note.value : '').trim();
}

/**
    Список целей под задачей — по образцу `askGoalsHtml` из task.html:4753.

    Номер цели — её место в списке, им же ответ уходит на сервер (`goal_indexes`),
    поэтому отмечать приходится чекбоксом, а не кликом по тексту. Закрытую цель
    оставить нельзя: вычеркнуть уже принятую работу значит потерять то, что подтвердил QA.
    */
function askGoalsHtml(goals) {
    if (!goals.length) return '<div class="task-no-questions">Целей у задачи нет — делить нечего.</div>';

    return '<div class="task-question-label">Какие цели</div><div class="task-question-options">'
        + goals.map((g, n) => `<label class="task-option-label${g.done ? ' task-option-done' : ''}">`
            + `<input type="checkbox" name="askGoal" value="${n}"${g.done ? ' disabled' : ''}>`
            + `<span>${esc(g.text)}`
            + `${g.done ? '<span class="task-option-hint">закрыта — не трогаем</span>' : ''}</span></label>`).join('')
        + '</div>';
}

/** Показать или убрать список целей: он нужен только действиям над ними */
function _showGoals(on) {
    const goals = _barEl && _barEl.querySelector('#askGoals');
    if (goals) goals.style.display = on ? '' : 'none';
}

/**
    Есть ли чем отметить цель: закрытые (`disabled`) не считаются.

    Нужен там, где решение зависит от наличия выбора. Спросить «отметь цель»,
    когда панель не получила целей, — то же самое, что отказать в ответе.
    */
function _goalChoices() {
    return !!_barEl && _barEl.querySelectorAll('[name="askGoal"]:not(:disabled)').length > 0;
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
            _askData = _withRowGoals(await getData(API_QUESTION(_askTaskId)));
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
    const goalIndexes = [...(_barEl?.querySelectorAll('[name="askGoal"]:checked') || [])]
        .map(i => parseInt(i.value, 10));
    const note = _noteValue();
    if (!answers.length && !note) { alert('Выберите вариант или напишите ответ'); return; }
    // Ответ «раздробить/убрать» без отмеченных целей не о чём: роль получила бы ключ
    // действия и гадала бы, о какой цели речь. Но требовать отметку можно, только
    // когда отмечать вообще чем: список целей приходит с GET вопроса, а панель
    // рисуется и из строки списка, где целей нет. Запрет на пустом списке запер бы
    // вопрос — человек жал бы «Ответить» и получал предупреждение вместо ответа.
    if (_goalChoices() && answers.some(k => ASK_GOAL_ACTIONS.includes(k)) && !goalIndexes.length) {
        alert('Отметьте цели, которых касается ответ'); return;
    }

    btn.disabled = true;
    btn.textContent = 'Отправляю…';
    try {
        await postData(API_ANSWER(_askTaskId), { answers, note, goal_indexes: goalIndexes });
        closeQuestionPanel();
        await loadTasks();
    } catch (e) {
        alert(e.message || 'Не отправилось');
        btn.disabled = false;
        btn.textContent = 'Ответить и вернуть в работу';
    }
};

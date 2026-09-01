/**
 * tasks.js — список задач с вкладками по ролям
 *
 * Фазы и типы из task.html (строки 2003-2015):
 *   PHASE_TAB_TITLES = {planning:'Менеджер', development:'Разработчик', testing:'Тестировщик', bugs:'Багфиксер'}
 *   PHASE_TYPE_NAMES = {planning:['research','plan'], development:['dev'], testing:['test'], bugs:['bug']}
 *   PIPELINE_STATE_LABELS для чипса состояния конвейера
 *   STATUS_LABELS     для чипса статуса
 *
 * Строка задачи приходит из `task_metadata_row_apply`, которая разбирает `metadata`
 * и ничего про имена типов не знает: в выдаче есть `task_type_id`, а имени типа нет.
 * Поэтому вкладки сверяются по номеру типа — `PHASE_TYPE_IDS`, та же карта, что
 * задокументирована комментарием к `PHASE_TYPE_NAMES` в task.html:2010-2015
 * (dev=1, bug=2, test=3, research=4, plan=5). Имя оставлено запасным путём: если
 * роутер когда-нибудь начнёт отдавать `task_type_name`, список не ослепнет.
 */

import { getData } from '/static/js/api.js';
import { state } from './state.js';
import { escapeHtml } from './utils.js';
import { renderRootFlags, approvePlan } from './flags.js';
import { openQuestionPanel, closeQuestionPanel } from './questions.js';

// --- Константы — зеркало task.html ---

// Подписи вкладок — ролями, теми же словами, что на админской странице
// (`PHASE_TAB_TITLES`, task.html:2003-2008): человек переключается между двумя
// интерфейсами и должен видеть одни и те же имена. Ключи же — `key`, их тесты и
// разметка держат стабильными (`data-phase="bugs"`), подпись на них не влияет.
const PHASE_TABS = [
    { key: 'planning',    label: 'Менеджер' },
    { key: 'development', label: 'Разработчик' },
    { key: 'testing',     label: 'Тестировщик' },
    { key: 'bugs',        label: 'Багфиксер' },
];

const PHASE_TYPE_NAMES = {
    planning:    ['research', 'plan'],
    development: ['dev'],
    testing:     ['test'],
    bugs:        ['bug'],
};

// Номера типов из `project_task_type` — те же строки, что комментарий к
// `PHASE_TYPE_NAMES` в task.html:2010-2015. Сверка по ним, а не по имени: у строки
// задачи имени типа нет, а номер есть всегда (см. шапку файла).
const PHASE_TYPE_IDS = {
    planning:    [4, 5],
    development: [1],
    testing:     [3],
    bugs:        [2],
};

const STATUS_LABELS = {
    active:    'В работе',
    queued:    'В очереди',
    pending:   'Ожидает',
    blocked:   'Заблокировано',
    cancelled: 'Отменено',
    done:      'Готово',
};

const STATUS_COLORS = {
    active:    '#3182ce',
    queued:    '#d69e2e',
    pending:   '#a0aec0',
    blocked:   '#c53030',
    cancelled: '#718096',
    done:      '#38a169',
};

const PIPELINE_LABELS = {
    none:       '(нет плана)',
    plan_approval: 'Утвердить план',
    qa_pending:  'Ждёт QA',
    review:      'Обзор',
    resolved:    'Решено',
    failed:      'Сбой',
};

// Эндпоинты прокси-роутера — см. telegram_app_task.py. Здесь только список;
// вопрос/ответ/metadata/approve живут в questions.js и flags.js.

const API_TASKS = '/telegram-app/tasks';

// --- Состояние ---

let _listEl = null;
let _headEl = null;         // вкладки фаз + селектора проекта (выше списка)
let _currentPhase = 'planning';
let _projectFilter = '';    // '' = все задачи
let _projects = [];         // [{id, name}]
let _allTasks = [];         // что пришла от роутера: фильтр по фазе и проекту — на клиенте
let _selectedTaskId = null; // задача с открытой панелью вопросов

export function initTasks() {
    // Контейнер рисует шаблон вкладки (`tasksListView`), имя из плана задачи.
    _listEl = document.getElementById('tasksListView');
    if (!_listEl) return;   // нет контейнера — вкладка не заведена, молча выходим

    // Вкладки и селектор живут в отдельном div над списком: он не перекрашивается
    // при каждой перезагрузке, и при клике по вкладке не нужно пересобирать его заново.
    _headEl = document.createElement('div');
    _headEl.className = 'task-head';
    _listEl.parentNode.insertBefore(_headEl, _listEl);

    // Флаги (flags.js) и панель вопросов (questions.js) перезагружают список через этот
    // коллбек — прямой импорт закрутил бы циклическую зависимость modules друг с другом.
    window._tg_reload_tasks = () => loadTasks();

    renderPhaseTabs();
    loadTasks();
}

// --- Вкладки фаз + селектор проекта ---

function renderPhaseTabs() {
    if (!_headEl) return;
    _headEl.innerHTML = '';

    // Селектор проекта над вкладками
    const filterRow = document.createElement('div');
    filterRow.className = 'task-project-row';

    const selLabel = document.createElement('label');
    selLabel.textContent = 'Проект:';
    filterRow.appendChild(selLabel);

    const sel = document.createElement('select');
    sel.className = 'task-project-select';
    const optAll = document.createElement('option');
    optAll.value = '';
    optAll.textContent = 'Все проекты';
    sel.appendChild(optAll);
    _projects.forEach(prj => {
        const o = document.createElement('option');
        o.value = prj.id;
        o.textContent = prj.name || String(prj.id);
        sel.appendChild(o);
    });
    sel.value = _projectFilter;
    sel.addEventListener('change', () => {
        _projectFilter = sel.value;
        state.taskProjectId = _projectFilter;
        loadTasks();
    });
    filterRow.appendChild(sel);
    _headEl.appendChild(filterRow);

    // Вкладки фаз
    const tabs = document.createElement('div');
    tabs.className = 'task-phase-tabs';
    PHASE_TABS.forEach(p => {
        const btn = document.createElement('button');
        btn.className = 'task-phase-tab' + (p.key === _currentPhase ? ' active' : '');
        btn.dataset.phase = p.key;
        btn.textContent = p.label;
        btn.addEventListener('click', () => {
            if (_currentPhase === p.key) return;
            _currentPhase = p.key;
            renderPhaseTabs();
            loadTasks();
        });
        tabs.appendChild(btn);
    });
    _headEl.appendChild(tabs);
}

// --- Загрузка задач ---

export async function loadTasks() {
    _listEl.innerHTML = '<div class="empty-state">Загрузка...</div>';
    try {
        const res = await getData(API_TASKS);
        // Роутер отдаёт задачи вложенно — `{'result': {'tasks': [...]}}`; плоский
        // `{'result': [...]}` остаётся запасным путём на случай, если точку решат
        // упростить. Гадать по одному полю нельзя: `result.tasks` бывает и списком.
        const raw = (res.result && Array.isArray(res.result.tasks)) ? res.result.tasks
                  : Array.isArray(res.result) ? res.result : [];
        const tasks = raw.map(normalizeTaskRow);
        _projects = dedupeProjects(tasks);
        // Проектов в выдаче сотни, а тащат они за собой только номер: отсекаем
        // здесь же, где фильтруем вкладки, — второго запроса на селектор нет.
        _allTasks = tasks;
        // Селектор строится до первой загрузки — на пустом списке, поэтому options
        // приходится наполнять здесь: иначе в нём навеки остаётся один пункт.
        renderPhaseTabs();
        renderTaskList();
    } catch (e) {
        _listEl.innerHTML = `<div class="denied-state">⚠️ Не удалось загрузить задачи${e.message ? ': ' + escapeHtml(e.message) : ''}</div>`;
    }
}

/** Нормализовать строку ответа в формат карточки — минимально: id, title, status, pipeline_state */
function normalizeTaskRow(row) {
    return {
        id: row.id,
        title: row.title || '(без названия)',
        status: row.status || 'pending',
        pipeline_state: row.pipeline_state || 'none',
        metadata: row.metadata || {},
        task_type_id: row.task_type_id ?? null,
        task_type_name: row.task_type_name || null,
        parent_id: row.parent_id || null,
        // Цели — колонка задачи, не metadata: панель вопросов рисует их из строки
        // списка, чтобы ответ о целях не ждал ответа на GET вопроса.
        goals: row.goals ?? null,
        // Дополнительные поля, которые может отдать роутер
        project_id: row.project_id,
    };
}

function dedupeProjects(tasks) {
    const map = new Map();
    tasks.forEach(t => {
        if (t.project_id && !map.has(t.project_id)) {
            map.set(t.project_id, { id: t.project_id, name: t.project_name || ('#' + t.project_id) });
        }
    });
    return Array.from(map.values());
}

// --- Рендер списка ---

export function renderTaskList() {
    const filtered = _allTasks.filter(taskInPhase).filter(taskInProject);

    // Без проекта — в начало
    const withNoProject = filtered.filter(t => !t.project_id);
    const withProject = filtered.filter(t => t.project_id);

    const sorted = [...withNoProject, ...withProject].sort(sortByStatus);

    // #tasksListView — сам контейнер-скролл (.task-list-view, его рисует шаблон вкладки);
    // карточки кладём внутрь
    if (!sorted.length) {
        _listEl.innerHTML = `<div class="empty-state">Нет задач на «${escapeHtml(phaseTabTitle(_currentPhase))}»</div>`;
        return;
    }
    _listEl.innerHTML = sorted.map(renderTaskCard).join('');

    // Привязка кликов
    _listEl.querySelectorAll('.task-card').forEach(card => {
        card.addEventListener('click', (e) => {
            // Не открывать панель, если клик был по кнопке или флажку
            if (e.target.closest('.task-btn') || e.target.closest('.task-flag') || e.target.closest('input')) return;
            openTaskDetail(Number(card.dataset.id));
        });
    });

    // Список перерисован с нуля — кнопка «Утвердить» прежней задачи снеслась вместе
    // с карточкой: возвращаем её, если открытая задача всё ещё на этой вкладке.
    renderApprovalButton();
}

/**
    Задача на активной вкладке — по типу, а готовая работа уходит на «Тестировщика».

    Порядок заимствован из `taskMatchesPhase` (`task.html:2348`) и он же причина, по
    которой одной сверки по типу мало: закрытая задача остаётся висеть на вкладке своего
    типа, и принять её там нечем — кнопок приёмки у «Разработчика» нет. Тестировщик
    последняя инстанция и единственное место, где закрытую задачу смотрят и вливают.
    У бага инстанция своя: вкладка «Багфиксер» — полный цикл от заведения до принятой ветки,
    уводить закрытый баг от того, кто его завёл, — значит прятать его.

    Имя типа — запасной путь: у строки из роутера имени нет (см. шапку файла), но если
    появится, список не ослепнет.
    */
function taskInPhase(t) {
    if (taskIsDone(t)) {
        return _isBugType(t) ? _currentPhase === 'bugs' : _currentPhase === 'testing';
    }
    const ids = PHASE_TYPE_IDS[_currentPhase] || [];
    if (ids.includes(Number(t.task_type_id))) return true;
    // Тип без номера (задача заведена до справочника или строка после `ON DELETE SET
    // NULL`) достаётся менеджеру — см. `TASK_ROLE_DEFAULT` в task_role.py:97.
    if (t.task_type_id === null && _currentPhase === 'planning') return true;
    return !!t.task_type_name && (PHASE_TYPE_NAMES[_currentPhase] || []).includes(t.task_type_name);
}

function taskInProject(t) {
    if (!_projectFilter) return true;
    return String(t.project_id || '') === String(_projectFilter);
}

/** Открыть панель вопроса для задачи */
export function openTaskDetail(taskId) {
    _selectedTaskId = taskId;
    state.taskCurrentQuestionId = taskId;
    renderApprovalButton();
    closeQuestionPanel();   // закрыть панель прежней задачи, прежде чем открывать новую
    // Строку из уже отрисованного списка — панель покажет вопрос сразу, не дожидаясь ответа
    openQuestionPanel(taskId, _allTasks.find(t => Number(t.id) === taskId) || null);
}

/** Кнопка «Утвердить план» — в карточке задачи при pipeline_state=plan_approval */
export function renderApprovalButton() {
    if (!_listEl || !_selectedTaskId) return;
    // Старую кнопку сносим, если она осталась в карточке
    const old = _listEl.querySelector('.task-approve-btn');
    if (old) old.remove();

    const card = _listEl.querySelector(`.task-card[data-id="${_selectedTaskId}"]`);
    if (!card) return;

    // Показываем только при pipeline_state=plan_approval
    const chip = card.querySelector('.task-pipeline-chip');
    if (!chip || !chip.dataset.state || chip.dataset.state !== 'plan_approval') return;

    const actions = card.querySelector('.task-actions');
    if (!actions) return;

    const btn = document.createElement('button');
    btn.className = 'task-btn task-btn-primary task-approve-btn';
    btn.textContent = 'Утвердить план';
    btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        btn.disabled = true;
        btn.textContent = 'Утверждаю…';
        try {
            await approvePlan(_selectedTaskId);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Утвердить план';
        }
    });
    actions.appendChild(btn);
}

function sortByStatus(a, b) {
    const orderA = STATUS_ORDER[a.status] ?? 9;
    const orderB = STATUS_ORDER[b.status] ?? 9;
    return orderA - orderB;
}

const STATUS_ORDER = { active: 0, queued: 1, pending: 2, blocked: 3, cancelled: 4, done: 5 };

function phaseTabTitle(key) {
    return PHASE_TABS.find(p => p.key === key)?.label || key;
}

// --- Карточка задачи ---

function renderTaskCard(t) {
    const statusChip = statusChipHtml(t.status);
    const stateChip = pipelineChipHtml(t.pipeline_state);
    const subtask = t.parent_id ? `<span class="task-subtask">подзадача #${t.parent_id}</span>` : '';

    return `<div class="task-card" data-id="${t.id}">
        <div class="task-header">
            <span class="task-title">#${t.id}: ${esc(t.title)}</span>
            <div class="task-badges">${statusChip}${stateChip}</div>
        </div>
        ${subtask}
        <div class="task-actions"></div>
        <div class="task-flags">${rootFlagsHtml(t)}</div>
    </div>`;
}

/** Обёртка над renderRootFlags — локальная, чтобы не мешать глобальному namespace */
function rootFlagsHtml(task) {
    // Передаём задачу напрямую: там внутри читает metadata и parent_id
    return renderRootFlags(task);
}

function esc(val) {
    return escapeHtml(val || '').replace(/\n/g, '<br>');
}

function statusChipHtml(status) {
    const label = STATUS_LABELS[status] || status;
    const color = STATUS_COLORS[status] || '#4a5568';
    return `<span class="task-status-chip" style="background:${color}18;color:${color};border:1px solid ${color}30">${esc(label)}</span>`;
}

function pipelineChipHtml(state) {
    if (state === 'none') return '';
    const label = PIPELINE_LABELS[state] || state;
    // data-state — для кнопки «Утвердить план»: сверяем с plan_approval по значению, не по тексту
    return `<span class="task-pipeline-chip" data-state="${esc(state)}">${esc(label)}</span>`;
}

/**
    Закрыта ли задача по любой из двух осей — зеркало `taskIsDone` (task.html:2329).

    Человеческое «Готово» ставят руками, конвейерный `done` — сам конвейер, и совпадают
    они не всегда: строку закрывают в кабинете, не дожидаясь конвейера, и наоборот.
    Поэтому достаточно одной.
    */
function taskIsDone(t) {
    return t?.status === 'done' || t?.pipeline_state === 'done';
}

/** Баг ли это: номер 2 из `project_task_type`, имя — запасной путь (см. шапку файла) */
function _isBugType(t) {
    return Number(t?.task_type_id) === 2
        || (!!t?.task_type_name && String(t.task_type_name).toLowerCase() === 'bug');
}

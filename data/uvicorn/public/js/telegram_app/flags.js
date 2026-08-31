/**
 * flags.js — чекбоксы фаз: to_planning, to_development, to_testing + approve
 *
 * Ключи metadata из task.html (строки 3676-3678):
 *   'to_planning' — включить задачу у менеджера; умолчание: нет ключа = включено
 *   'to_development' — одноразовый триггер утверждения плана; true = согласен
 *   'to_testing' — автоматически отправить на QA; умолчание: нет ключа = включено
 */

import { postData } from '/static/js/api.js';

const ENDPOINT = (id) => `/telegram-app/task/${id}/metadata`;
const APPROVE_ENDPOINT = (id) => `/telegram-app/task/${id}/pipeline/approve`;

// --- Метка флажка по ключу ---

function flagLabel(key) {
    switch (key) {
        case 'flag_plan': return 'В планирование';
        case 'flag_dev': return 'В разработку';
        case 'flag_test': return 'В тестирование';
        default: return key;
    }
}

// --- HTML одного флажка ---

function flagChipHtml(id, key, checked, handler, title) {
    // title идёт в attribute — экранируем кавычки, чтобы заголовок не сломал разметку
    const safeTitle = (title || '').replace(/"/g, '&quot;');
    const cls = checked ? '' : 'task-flag-off';
    return `<label class="task-flag ${cls}" data-flag="${key}" onclick="event.stopPropagation()" title="${safeTitle}">
        <input type="checkbox" ${checked ? 'checked' : ''}
               onchange="${handler}(this)" data-handler="${handler}">
        <span>${flagLabel(key)}</span>
    </label>`;
}

// --- Собрать все флажки корневой задачи ---

export function renderRootFlags(task) {
    if (task.parent_id) return '';   // флаги только у корневой задачи — подзадача едет с родителем
    const meta = task.metadata || {};
    const parts = [];
    // «в планирование» — умолчание включено; выключенное хранится явным false
    parts.push(flagChipHtml(
        task.id, 'flag_plan', meta['to_planning'] !== false,
        '_tg_flag_plan',
        'Задача у менеджера. Снять — планирование прекратится'
    ));
    // «в разработку» — одноразовый триггер: план утверждать не потребуется,
    // как только он будет готов, задача сменит тип и уйдёт в работу. Умолчание — выключено
    parts.push(flagChipHtml(
        task.id, 'flag_dev', meta['to_development'] === true,
        '_tg_flag_dev',
        'План утверждать не потребуется: задача сама уйдёт в разработку, когда план будет готов'
    ));
    // «в тестирование» — умолчание включено; выключенное хранится явным false
    parts.push(flagChipHtml(
        task.id, 'flag_test', meta['to_testing'] !== false,
        '_tg_flag_test',
        'Готовую работу отправить на QA автоматически'
    ));
    return parts.join('');
}

// --- Callbacks, навешиваемые на inline-обработчики in HTML ---

window._tg_flag_plan = async function(inputEl) {
    const card = inputEl.closest('.task-card');
    const id = Number(card?.dataset.id);
    if (!id) return;

    inputEl.disabled = true;
    try {
        const val = inputEl.checked ? null : false;
        await postData(ENDPOINT(id), { patch: { to_planning: val } });
        window._tg_reload_tasks?.();
    } catch (e) {
        console.error('[flags] cannot save to_planning:', e.message || e);
    } finally {
        inputEl.disabled = false;
    }
};

window._tg_flag_dev = async function(inputEl) {
    const card = inputEl.closest('.task-card');
    const id = Number(card?.dataset.id);
    if (!id) return;

    inputEl.disabled = true;
    try {
        // Одноразовый триггер: включено — явный true, выключено — стираем ключ (null).
        // Зеркально task.html toggleDevFlag: `checked ? true : null`.
        const val = inputEl.checked ? true : null;
        await postData(ENDPOINT(id), { patch: { to_development: val } });
        window._tg_reload_tasks?.();
    } catch (e) {
        console.error('[flags] cannot save to_development:', e.message || e);
    } finally {
        inputEl.disabled = false;
    }
};

window._tg_flag_test = async function(inputEl) {
    const card = inputEl.closest('.task-card');
    const id = Number(card?.dataset.id);
    if (!id) return;

    inputEl.disabled = true;
    try {
        const val = inputEl.checked ? null : false;
        await postData(ENDPOINT(id), { patch: { to_testing: val } });
        window._tg_reload_tasks?.();
    } catch (e) {
        console.error('[flags] cannot save to_testing:', e.message || e);
    } finally {
        inputEl.disabled = false;
    }
};

// --- Утвердить план (pipeline/approve) ---

export async function approvePlan(id) {
    try {
        await postData(APPROVE_ENDPOINT(id));
    } catch (e) {
        alert(e.message || 'Не удалось утвердить план');
        throw e;
    }
}

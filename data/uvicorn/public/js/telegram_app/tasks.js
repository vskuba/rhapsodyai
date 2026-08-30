import { getData } from '/static/js/api.js';
import { state } from './state.js';

let _listEl = null;

export function initTasks() {
    _listEl = document.getElementById('tasksListView');
}

export async function loadTasks() {
    _listEl.innerHTML = '<div class="empty-state">Загрузка...</div>';
    try {
        const res = await getData('/telegram-app/tasks');
        renderTasksList(res.result || []);
    } catch {
        _listEl.innerHTML = '<div class="denied-state">⚠️ Не удалось загрузить задачи</div>';
    }
}

function renderTasksList(tasks) {
    _listEl.innerHTML = '';
    if (!tasks.length) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = 'Задач пока нет';
        _listEl.appendChild(empty);
        return;
    }
    for (const t of tasks) {
        const item = document.createElement('div');
        item.className = 'task-list-item';
        item.dataset.id = t.id;
        item.textContent = String(t.title);
        item.addEventListener('click', () => {
            openTaskDetailView(Number(t.id));
        });
        _listEl.appendChild(item);
    }
}

export function openTaskDetailView(taskId) {
    state.currentTaskId = taskId;
    // TODO: открыть панель вопроса к задаче
}

export function closeTaskDetailView() {
    state.currentTaskId = null;
    // TODO: закрыть панель вопроса
}

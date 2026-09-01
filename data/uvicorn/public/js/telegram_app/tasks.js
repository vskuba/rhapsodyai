import { state } from './state.js';

let _listEl = null;

export function initTasks() {
    _listEl = document.getElementById('tasksListView');
}

// Каркас вкладки: роутер /telegram-app/tasks и загрузка списка — отдельная
// подзадача, здесь рисуем пустое состояние без запроса несуществующего эндпоинта.
export function loadTasks() {
    renderTasksList([]);
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

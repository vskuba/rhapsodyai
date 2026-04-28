import {postData, getData, putData} from './api.js';

export const agentSelect = document.getElementById('agentSelect'); // Для чата
export const userSelect = document.getElementById('userSelect');
export const agentListContainer = document.getElementById('agentList'); // Для менеджера
export const saveBtn = document.getElementById('saveBtn');

const sessionDisplay = document.getElementById('sessionDisplay');

let currentSessionId = null;

/**
 * Загрузка агентов в выпадающий список (для страницы ЧАТА)
 */
export async function loadAgents(showLoading) {
    if (!agentSelect) return;
    showLoading(true);
    try {
        const data = await postData('/agent/list');
        agentSelect.innerHTML = '';
        data.result.forEach(agent => {
            const option = document.createElement('option');
            option.value = agent;
            option.textContent = agent;
            agentSelect.appendChild(option);
        });
        if (data.result.length > 0) agentSelect.selectedIndex = 0;
    } catch (e) {
        console.error("Ошибка загрузки агентов для чата:", e);
    } finally {
        showLoading(false);
    }
}

/**
 * Инициализация страницы УПРАВЛЕНИЯ агентами (Список + Редактор)
 */
export async function initAgentsManager(editor) {
    if (!agentListContainer) return;

    try {
        const data = await postData('/agent/list');
        agentListContainer.innerHTML = '';

        data.result.forEach(name => {
            const div = document.createElement('div');
            div.className = 'agent-item';
            div.textContent = name;
            div.onclick = () => selectAgentForEdit(name, div, editor);
            agentListContainer.appendChild(div);
        });
    } catch (e) {
        console.error("Ошибка загрузки списка в менеджер:", e);
    }
}

/**
 * Выбор агента и загрузка его YAML в редактор
 */
async function selectAgentForEdit(name, element, editor) {
    // Подсветка активного в списке
    document.querySelectorAll('.agent-item').forEach(el => el.classList.remove('active'));
    element.classList.add('active');

    try {
        const data = await getData(`/agent/${name}`);
        // Используем raw_yaml, который пришлет обновленный Python роутер
        editor.setValue(data.raw_yaml || "");

        // Очищаем историю правок, чтобы Ctrl+Z не возвращал к коду прошлого агента
        editor.clearHistory();

        document.getElementById('currentAgentName').textContent = `${name}.yml`;
        saveBtn.disabled = false;
        saveBtn.dataset.currentAgent = name; // Сохраняем имя для функции сохранения
    } catch (e) {
        console.error("Ошибка загрузки YAML:", e);
        alert("Не удалось загрузить конфиг агента");
    }
}

/**
 * Сохранение изменений из редактора на сервер
 */
export async function saveAgentConfig(editor) {
    const agentName = saveBtn.dataset.currentAgent;
    const content = editor.getValue();
    const statusLabel = document.getElementById('statusLabel');

    if (!agentName) return;

    saveBtn.disabled = true;
    if (statusLabel) statusLabel.textContent = '⏳ Сохранение...';

    try {
        await putData(`/agent/${agentName}`, {yaml_content: content});
        if (statusLabel) {
            statusLabel.textContent = '✅ Сохранено';
            setTimeout(() => statusLabel.textContent = '', 3000);
        }
    } catch (e) {
        console.error("Ошибка сохранения:", e);
        if (statusLabel) statusLabel.textContent = `❌ Ошибка: ${e.message}`;
    } finally {
        saveBtn.disabled = false;
    }
}

export async function getAgentSessionLastEntry() {
    const agent = agentSelect.value;
    const userId = userSelect.value;

    if (!agent || !userId) return;

    try {
        const response = await fetch(`/agent/${agent}/user/${userId}/session_last_entry`);
        const data = await response.json();

        // API возвращает {"result": "uuid-строка"} или {"result": null}
        updateSessionUI(data.result);
    } catch (e) {
        console.error("Ошибка получения сессии:", e);
        updateSessionUI(null);
    }
}

function updateSessionUI(memory_short_entry) {
    currentSessionId = memory_short_entry.session_uuid;
    if (currentSessionId) {
        sessionDisplay.innerText = currentSessionId.substring(0, 8) + '...';
        sessionDisplay.title = currentSessionId; // Полный ID при наведении
    } else {
        sessionDisplay.innerText = 'Нет сессии';
    }
}
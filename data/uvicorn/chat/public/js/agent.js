import { postData } from './api.js';

export const agentSelect = document.getElementById('agentSelect');

export async function loadAgents(showLoading) {
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
        console.error("Ошибка загрузки агентов:", e);
    } finally {
        showLoading(false);
    }
}
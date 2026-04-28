import {getData} from './api.js';

const llmModelSelect = document.getElementById('llmModelSelect');

export async function loadLLMs() {
    if (!llmModelSelect) return;
    try {
        const data = await getData('/llm/list');
        llmModelSelect.innerHTML = '';
        data.result.forEach(llm => {
            const option = document.createElement('option');
            option.value = llm;
            option.textContent = llm;
            llmModelSelect.appendChild(option);
        });
        if (data.result.length > 0) llmModelSelect.selectedIndex = 0;
    } catch (e) {
        console.error("Ошибка загрузки llm для чата:", e);
    }
}
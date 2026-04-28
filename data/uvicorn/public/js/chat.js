import {postData} from './api.js';

export const chatMessages = document.getElementById('chatMessages');
export const userInput = document.getElementById('userInput');
export const agentSelect = document.getElementById('agentSelect');
export const userSelect = document.getElementById('userSelect');
export const progressBar = document.getElementById('topProgressBar');
export const llmModelSelect = document.getElementById('llmModelSelect');

export function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = `message ${role === 'user' ? 'user-msg' : 'ai-msg'}`;
    div.textContent = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

export async function sendMessage(showLoading) {
    const text = userInput.value.trim();
    if (!text) return;

    addMessage(text, 'user');
    userInput.value = '';
    showLoading(true);

    try {
        const data = await postData('/chat/ask', {
            question: text,
            user_id: userSelect.value,
            agent: agentSelect.value,
            llm: llmModelSelect.value
        });
        addMessage(data.result, 'ai');
    } catch (e) {
        console.error("Ошибка чата:", e);
        addMessage("Ошибка сервера", 'ai');
    } finally {
        showLoading(false);
    }
}

// Единая функция индикации загрузки
export function toggleLoading(show) {
    progressBar.classList.toggle('progress-active', show);
}
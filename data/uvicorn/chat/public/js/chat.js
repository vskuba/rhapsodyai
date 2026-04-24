import { postData } from './api.js';

const chatMessages = document.getElementById('chatMessages');
const userInput = document.getElementById('userInput');
const agentSelect = document.getElementById('agentSelect');

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
            agent: agentSelect.value
        });
        addMessage(data.result, 'ai');
    } catch (e) {
        console.error("Ошибка чата:", e);
        addMessage("Ошибка сервера", 'ai');
    } finally {
        showLoading(false);
    }
}
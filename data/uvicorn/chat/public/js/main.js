import { loadAgents } from './agent.js';
import { sendMessage, addMessage } from './chat.js';
import { initVoice } from './voice.js';
import {loadUsers} from "./user.js";

const progressBar = document.getElementById('topProgressBar');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');

// Единая функция индикации загрузки
function toggleLoading(show) {
    progressBar.classList.toggle('progress-active', show);
}

document.addEventListener('DOMContentLoaded', () => {
    // 1. Инициализация агентов
    loadAgents(toggleLoading);
    loadUsers(toggleLoading);

    // 2. Инициализация голоса (передаем функцию, что делать с текстом)
    initVoice(toggleLoading, (text) => {
        userInput.value = text;
        sendMessage(toggleLoading);
    });

    // 3. Обработчики текста
    sendBtn.addEventListener('click', () => sendMessage(toggleLoading));

    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage(toggleLoading);
        }
    });
});
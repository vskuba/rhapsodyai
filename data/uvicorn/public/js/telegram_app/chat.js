import { postData } from '/static/js/api.js';
import { state } from './state.js';
import { appendBubble, linkify } from './utils.js';
import { createVoiceRecorder } from './voice.js';

export function initChat({ bar, textarea, sendBtn, micBtn, micCancel, progress }) {
    sendBtn.addEventListener('click', () => sendChatMessage({ textarea, progress }));
    textarea.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage({ textarea, progress });
        }
    });

    createVoiceRecorder({
        micBtn,
        cancelBtn: micCancel,
        progressEl: progress,
        onError: () => appendBubble('assistant', '⚠️ Не удалось распознать голос', false,
            document.getElementById('chatMessages')),
        onTranscript: async text => {
            textarea.value = text;
            await sendChatMessage({ textarea, progress });
        },
    });
}

async function sendChatMessage({ textarea, progress }) {
    const message = textarea.value.trim();
    if (!message) return;

    const container = document.getElementById('chatMessages');
    textarea.value = '';
    appendBubble('user', message, false, container);
    const pending = appendBubble('assistant', '...', true, container);

    progress.classList.add('active');
    try {
        const data = await postData('/telegram-app/chat/ask', {
            message,
            session_uuid: state.chatSessionUuid,
        });
        state.chatSessionUuid = data.session_uuid || state.chatSessionUuid;
        pending.innerHTML = linkify(data.result);
        pending.classList.remove('pending');
    } catch (err) {
        pending.textContent = '⚠️ ' + (err.message || 'Ошибка');
        pending.classList.remove('pending');
    } finally {
        progress.classList.remove('active');
    }
}

import { postData } from './api.js';

let mediaRecorder;
let audioChunks = [];
const micBtn = document.getElementById('micBtn');

export async function initVoice(showLoading, onTranscriptionReady) {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);

        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
            audioChunks = [];

            const formData = new FormData();
            formData.append("file", audioBlob, "voice.wav");

            showLoading(true);
            try {
                const data = await postData('/chat/voice', formData);
                if (data.result) onTranscriptionReady(data.result);
            } catch (err) {
                console.error("Ошибка голоса:", err);
            } finally {
                showLoading(false);
            }
        };

        // События кнопок
        micBtn.addEventListener('mousedown', () => {
            audioChunks = [];
            mediaRecorder.start();
            micBtn.classList.add('recording');
        });

        micBtn.addEventListener('mouseup', () => {
            if (mediaRecorder.state === "recording") {
                mediaRecorder.stop();
                micBtn.classList.remove('recording');
            }
        });

    } catch (err) {
        console.error("Микрофон недоступен:", err);
        micBtn.style.opacity = '0.5';
    }
}
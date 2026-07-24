import { postData } from '/static/js/api.js';

export function createVoiceRecorder({ micBtn, cancelBtn, progressEl, onError, onTranscript }) {
    const MIN_RECORD_MS = 1000;
    let mediaRecorder = null;
    let audioChunks = [];
    let micStream = null;
    let recordCancelled = false;
    let recordStartedAt = 0;

    if (!navigator.mediaDevices?.getUserMedia) {
        micBtn.disabled = true;
        micBtn.title = 'Микрофон недоступен в этом клиенте';
        return;
    }

    async function startRecording() {
        if (mediaRecorder && mediaRecorder.state === 'recording') return;
        if (!micStream) micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(micStream);
        audioChunks = [];
        mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
        mediaRecorder.onstop = onRecordingStop;
        mediaRecorder.start();
        recordStartedAt = performance.now();
        micBtn.classList.add('recording');
    }

    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
        micBtn.classList.remove('recording');
        cancelBtn.classList.remove('visible');
    }

    async function onRecordingStop() {
        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
        audioChunks = [];
        const tooShort = performance.now() - recordStartedAt < MIN_RECORD_MS;
        if (audioBlob.size === 0 || recordCancelled || tooShort) return;

        const formData = new FormData();
        formData.append('file', audioBlob, 'voice.wav');
        progressEl.classList.add('active');
        try {
            const data = await postData('/telegram-app/chat/voice', formData);
            if (data.result) await onTranscript(data.result);
        } catch (err) {
            onError?.(err);
        } finally {
            progressEl.classList.remove('active');
        }
    }

    micBtn.addEventListener('click', async () => {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            stopRecording();
            return;
        }
        recordCancelled = false;
        cancelBtn.classList.add('visible');
        await startRecording();
    });

    cancelBtn.addEventListener('click', () => {
        recordCancelled = true;
        stopRecording();
    });
}

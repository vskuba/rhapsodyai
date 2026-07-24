export function createInputBar({ id, progressId, placeholder = '', hasQuickCmd = false }) {
    const progress = document.createElement('div');
    progress.className = 'chat-progress';
    progress.id = progressId;
    progress.innerHTML = '<div class="chat-progress-fill"></div>';

    const bar = document.createElement('div');
    bar.className = 'chat-input-bar';
    bar.id = id;
    bar.innerHTML = `
        <div class="mic-wrap">
            <button class="mic-cancel">✕</button>
            <button class="mic-btn">🎤</button>
        </div>
        <textarea class="chat-text-input plan-text-input" rows="4" placeholder="${placeholder}"></textarea>
        ${hasQuickCmd
            ? `<div class="send-btn-col">
                   <button class="quick-cmd-btn">☰</button>
                   <button class="chat-send-btn">➤</button>
               </div>`
            : `<button class="chat-send-btn">➤</button>`
        }
    `;

    return {
        progress,
        bar,
        textarea: bar.querySelector('textarea'),
        sendBtn:  bar.querySelector('.chat-send-btn'),
        micBtn:   bar.querySelector('.mic-btn'),
        micCancel: bar.querySelector('.mic-cancel'),
        quickCmdBtn: bar.querySelector('.quick-cmd-btn') || null,
    };
}

export function createMicOnlyBar({ id, progressId }) {
    const progress = document.createElement('div');
    progress.className = 'chat-progress';
    progress.id = progressId;
    progress.innerHTML = '<div class="chat-progress-fill"></div>';

    const bar = document.createElement('div');
    bar.className = 'mic-only-bar';
    bar.id = id;
    bar.innerHTML = `
        <div class="mic-wrap">
            <button class="mic-cancel">✕</button>
            <button class="mic-btn">🎤</button>
        </div>
    `;

    return {
        progress,
        bar,
        micBtn:    bar.querySelector('.mic-btn'),
        micCancel: bar.querySelector('.mic-cancel'),
    };
}

const tg = window.Telegram?.WebApp;

export function escapeHtml(t) {
    return String(t || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function linkify(text) {
    return escapeHtml(text).replace(/(https?:\/\/[^\s<>"]+)/g, url =>
        `<a href="${url}" class="chat-link">${url}</a>`
    );
}

export function confirmDialog(message) {
    return new Promise(resolve => {
        if (tg?.showConfirm) {
            // Вне Telegram showConfirm бросает WebAppMethodUnsupported (showPopup
            // недоступен) — ловим и падаем на нативный confirm, как в else.
            try {
                tg.showConfirm(message, resolve);
            } catch {
                resolve(window.confirm(message));
            }
        } else {
            resolve(window.confirm(message));
        }
    });
}

export function appendBubble(role, text, pending = false, container, wrapInRow = false) {
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble ${role}${pending ? ' pending' : ''}`;

    if (pending) {
        bubble.textContent = text;
    } else {
        bubble.innerHTML = linkify(text);
        bubble.querySelectorAll('a.chat-link').forEach(a => {
            a.addEventListener('click', e => {
                e.preventDefault();
                const url = a.getAttribute('href');
                if (tg?.openLink) tg.openLink(url);
                else window.open(url, '_blank');
            });
        });
    }

    if (role === 'user' && wrapInRow) {
        const row = document.createElement('div');
        row.className = 'user-msg-row';
        row.appendChild(bubble);
        container.appendChild(row);
        container.scrollTop = container.scrollHeight;
        return bubble;
    }

    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
    return bubble;
}

export function appendTypingIndicator(container) {
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble assistant';
    bubble.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
    return bubble;
}

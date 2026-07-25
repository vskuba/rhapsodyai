import { getData, postData } from '/static/js/api.js';
import { state } from './state.js';
import { appendBubble, appendTypingIndicator, linkify, confirmDialog } from './utils.js';
import { createVoiceRecorder } from './voice.js';
import { setSidebarPageMode, updateInputBarsVisibility } from './sidebar.js';

const tg = window.Telegram?.WebApp;

let _claudeEl = null;
let _sessionListEl = null;
let _quickCmdPopup = null;

export function initClaude({ bar, textarea, sendBtn, micBtn, micCancel, progress, quickCmdBtn }) {
    _claudeEl = document.getElementById('claudeMessages');
    _sessionListEl = document.getElementById('claudeSessionListView');
    _quickCmdPopup = document.getElementById('claudeQuickCmdPopup');

    sendBtn.addEventListener('click', () => sendClaudeMessage({ textarea, progress }));
    textarea.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendClaudeMessage({ textarea, progress });
        }
    });

    quickCmdBtn.addEventListener('click', e => {
        e.stopPropagation();
        const rect = quickCmdBtn.getBoundingClientRect();
        _quickCmdPopup.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
        _quickCmdPopup.style.right = (window.innerWidth - rect.right) + 'px';
        _quickCmdPopup.classList.toggle('visible');
    });

    _quickCmdPopup.querySelectorAll('.quick-cmd-item').forEach(item => {
        item.addEventListener('click', () => {
            textarea.value = item.dataset.text;
            _quickCmdPopup.classList.remove('visible');
            sendClaudeMessage({ textarea, progress });
        });
    });

    document.addEventListener('click', () => _quickCmdPopup.classList.remove('visible'));

    createVoiceRecorder({
        micBtn,
        cancelBtn: micCancel,
        progressEl: progress,
        onError: () => appendBubble('assistant', '⚠️ Не удалось распознать голос', false, _claudeEl),
        onTranscript: async text => {
            textarea.value = text;
            await sendClaudeMessage({ textarea, progress });
        },
    });

    document.getElementById('claudeBackToListIconBtn').addEventListener('click', closeClaudeSessionView);
    document.getElementById('claudeQuotaChipBtn').addEventListener('click', requestQuotaCheck);
    document.getElementById('claudeStatusIconBtn').addEventListener('click', restartClaudeProcesses);
    document.getElementById('claudeClearMessagesIconBtn').addEventListener('click', clearCurrentClaudeMessages);
    document.getElementById('claudeDeleteSessionIconBtn').addEventListener('click', deleteCurrentClaudeSession);
}

export async function loadClaudeSessionList() {
    _sessionListEl.innerHTML = '<div class="empty-state">Загрузка...</div>';
    try {
        const res = await getData('/telegram-app/claude/sessions/active');
        renderClaudeSessionList(res.result || []);
    } catch {
        _sessionListEl.innerHTML = '<div class="denied-state">⚠️ Не удалось загрузить сессии</div>';
    }
}

function renderClaudeSessionList(sessions) {
    const escHtml = s => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    _sessionListEl.innerHTML = sessions.length
        ? sessions.map(s => {
            const preview = (s.last_message || s.summary || '').trim();
            const subtitle = preview.length > 80 ? preview.slice(0, 80) + '…' : (preview || 'Нет сообщений');
            return `
            <div class="claude-session-item" data-uuid="${escHtml(s.session_uuid)}"
                 data-role="${escHtml(s.role)}" data-project="${escHtml(s.project_label)}">
                <div class="session-title">
                    <span class="session-status-dot"></span>
                    ${escHtml(s.role)} — ${escHtml(s.project_label)}
                </div>
                <div class="session-subtitle">${escHtml(subtitle)}</div>
            </div>`;
        }).join('')
        : '<div class="empty-state">Активных сессий нет. Запустите терминал в проекте, чтобы зарегистрировать сессию</div>';

    _sessionListEl.querySelectorAll('.claude-session-item').forEach(el =>
        el.addEventListener('click', () =>
            openClaudeSession(el.dataset.uuid, el.dataset.role, el.dataset.project)));
}

export async function openClaudeSession(sessionUuid, role, projectLabel) {
    state.claude.sessionUuid = sessionUuid;
    state.claude.sessionLabel = `${role} — ${projectLabel}`;
    state.claude.sessionUnreachable = false;
    state.claude.renderedUserIds = new Set();
    state.claude.renderedResponses = new Map();
    state.claude.pendingUserCount = 0;
    state.claude.typingBubble = null;
    _claudeEl.innerHTML = '';

    _sessionListEl.style.display = 'none';
    _claudeEl.style.display = 'block';
    setSidebarPageMode(true);
    updateInputBarsVisibility();

    await loadClaudeMessages(true);
    updateClaudePolling();
    updateClaudeStatusPolling();
}

export function closeClaudeSessionView() {
    state.claude.sessionUuid = null;
    state.claude.sessionLabel = '';
    state.claude.sessionUnreachable = false;
    if (state.claude.pollTimer) { clearInterval(state.claude.pollTimer); state.claude.pollTimer = null; }
    const chip = document.getElementById('claudeQuotaChipBtn');
    if (chip) chip.textContent = '—%';

    _claudeEl.style.display = 'none';
    _sessionListEl.style.display = 'block';
    setSidebarPageMode(true);
    updateInputBarsVisibility();
    loadClaudeSessionList();
    updateClaudeStatusPolling();
}

async function sendClaudeMessage({ textarea, progress }) {
    const message = textarea.value.trim();
    if (!message || !state.claude.sessionUuid) return;
    textarea.value = '';

    const row = document.createElement('div');
    row.className = 'user-msg-row';

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble user sending';
    bubble.innerHTML = linkify(message);

    const countdown = document.createElement('span');
    countdown.className = 'send-countdown';
    countdown.textContent = 'отправка через 7с';

    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;flex-direction:column;align-items:flex-end;';
    wrap.appendChild(bubble);
    wrap.appendChild(countdown);

    const delBtn = document.createElement('button');
    delBtn.className = 'del-msg-btn visible';
    delBtn.textContent = '✕';

    row.appendChild(delBtn);
    row.appendChild(wrap);
    _claudeEl.appendChild(row);
    _claudeEl.scrollTop = _claudeEl.scrollHeight;

    let secondsLeft = 7;
    const countdownInterval = setInterval(() => {
        countdown.textContent = secondsLeft > 0 ? `отправка через ${secondsLeft}с` : 'отправка…';
        secondsLeft--;
    }, 1000);

    const sendTimer = setTimeout(async () => {
        clearInterval(countdownInterval);
        bubble.classList.remove('sending');
        wrap.removeChild(countdown);
        delBtn.remove();

        state.claude.pendingUserCount++;
        state.claude.typingBubble?.remove();
        state.claude.typingBubble = appendTypingIndicator(_claudeEl);

        progress.classList.add('active');
        try {
            await postData('/telegram-app/claude/ask', { message, session_uuid: state.claude.sessionUuid });
            updateClaudePolling();
        } catch (err) {
            state.claude.typingBubble?.remove();
            state.claude.typingBubble = null;
            appendBubble('assistant', '⚠️ ' + (err.message || 'Ошибка'), false, _claudeEl);
        } finally {
            progress.classList.remove('active');
        }
    }, 8000);

    delBtn.addEventListener('click', () => {
        clearTimeout(sendTimer);
        clearInterval(countdownInterval);
        row.remove();
    });
}

export async function loadClaudeMessages(isInitialLoad = false) {
    if (!state.claude.sessionUuid) return;
    try {
        const res = await getData(`/telegram-app/claude/messages?session_uuid=${encodeURIComponent(state.claude.sessionUuid)}`);
        const rows = res.result || [];
        let newResponsesAdded = false;

        for (const row of rows) {
            if (row.dynamic) {
                // dynamic-строки: user content скрыт, response показывается как assistant-bubble
                if (row.response && !state.claude.renderedResponses.has(row.id)) {
                    const { displayText, quotaData } = _parseQuotaResponse(row.response);
                    if (quotaData) _updateQuotaChip(quotaData);
                    newResponsesAdded = true;
                    const el = appendBubble('assistant', displayText, false, _claudeEl);
                    state.claude.renderedResponses.set(row.id, { text: row.response, el });
                }
                continue;
            }

            if (row.content && !state.claude.renderedUserIds.has(row.id)) {
                state.claude.renderedUserIds.add(row.id);
                if (isInitialLoad) {
                    appendBubble('user', row.content, false, _claudeEl, true);
                } else if (state.claude.pendingUserCount > 0) {
                    state.claude.pendingUserCount--;
                }
            }
            if (row.response) {
                const existing = state.claude.renderedResponses.get(row.id);
                if (!existing) {
                    newResponsesAdded = true;
                    const el = appendBubble('assistant', row.response, false, _claudeEl);
                    state.claude.renderedResponses.set(row.id, { text: row.response, el });
                } else if (existing.text !== row.response) {
                    existing.el.innerHTML = linkify(row.response);
                    existing.el.querySelectorAll('a.chat-link').forEach(a => {
                        a.target = '_blank';
                        a.rel = 'noopener noreferrer';
                    });
                    existing.text = row.response;
                    _claudeEl.scrollTop = _claudeEl.scrollHeight;
                }
            }
        }

        // Удаляем из DOM пузыри, которых больше нет в БД (напр. старые «Принял»).
        const serverIds = new Set(rows.map(r => r.id));
        for (const [id, entry] of state.claude.renderedResponses) {
            if (!serverIds.has(id)) {
                entry.el.remove();
                state.claude.renderedResponses.delete(id);
            }
        }

        // Пузырь управляется ПОСЛЕ цикла — один раз, на основе реального состояния.
        // Так не возникает нескольких пузырей при нескольких pending-сообщениях.
        const stillPending = rows.some(r => !r.dynamic && r.content && !r.response) || state.claude.pendingUserCount > 0;

        if (stillPending) {
            if (!state.claude.typingBubble || !_claudeEl.contains(state.claude.typingBubble)) {
                state.claude.typingBubble = appendTypingIndicator(_claudeEl);
            } else if (newResponsesAdded) {
                // Сдвинуть пузырь в конец, если между ним и концом появились новые ответы
                _claudeEl.appendChild(state.claude.typingBubble);
            }
        } else {
            state.claude.typingBubble?.remove();
            state.claude.typingBubble = null;
        }
    } catch { /* тихо, следующий тик попробует снова */ }
}

export function updateClaudePolling() {
    if (state.claude.pollTimer) { clearInterval(state.claude.pollTimer); state.claude.pollTimer = null; }
    if (state.currentTab === 'claude' && state.claude.sessionUuid) {
        state.claude.pollTimer = setInterval(loadClaudeMessages, 4000);
    }
}

export function updateClaudeStatusPolling() {
    if (state.claude.statusPollTimer) { clearInterval(state.claude.statusPollTimer); state.claude.statusPollTimer = null; }
    if (state.currentTab === 'claude') {
        state.claude.statusPollTimer = setInterval(refreshClaudeSessionStatus, 5000);
    }
}

async function refreshClaudeSessionStatus() {
    let sessions;
    try {
        const res = await getData('/telegram-app/claude/sessions/active');
        sessions = res.result || [];
    } catch { return; }

    if (!state.claude.sessionUuid) {
        renderClaudeSessionList(sessions);
        return;
    }

    const stillReachable = sessions.some(s => s.session_uuid === state.claude.sessionUuid);
    if (!stillReachable && !state.claude.sessionUnreachable) {
        state.claude.sessionUnreachable = true;
        appendBubble('assistant', '⚠️ Терминал недоступен (сессия закрыта)', false, _claudeEl);
    } else if (stillReachable) {
        state.claude.sessionUnreachable = false;
    }
}

async function restartClaudeProcesses() {
    if (!state.claude.sessionUuid) return;
    const btn = document.getElementById('claudeStatusIconBtn');
    btn.disabled = true;

    const statusBubble = document.createElement('div');
    statusBubble.className = 'chat-bubble assistant';
    statusBubble.textContent = '⟳ Отправляю команду перезапуска Claude Client…';
    _claudeEl.appendChild(statusBubble);
    _claudeEl.scrollTop = _claudeEl.scrollHeight;

    let initialStatus;
    try {
        const data = await postData('/telegram-app/claude/session/restart-processes', { session_uuid: state.claude.sessionUuid });
        initialStatus = data.result;
    } catch {
        statusBubble.textContent = '⚠️ Не удалось отправить команду перезапуска';
        btn.disabled = false;
        return;
    }

    statusBubble.textContent = '⟳ Команда перезапуска отправлена. Проверяю статус через 5с…';
    await new Promise(r => setTimeout(r, 5000));

    let freshStatus = null;
    try {
        const data = await getData(`/telegram-app/claude/session/process-status?session_uuid=${encodeURIComponent(state.claude.sessionUuid)}`);
        freshStatus = data.result;
    } catch { /* используем initialStatus */ }

    const s = freshStatus || initialStatus;
    const icon = s.watch_alive ? '✅' : '🔴';
    const secsAgo = s.seconds_ago != null ? `${s.seconds_ago}с назад` : 'нет данных';
    statusBubble.textContent = [
        '⟳ Статус после перезапуска',
        `${icon} Claude Code  (heartbeat: ${secsAgo})`,
        `${s.project_label || ''} / ${s.role || ''}`,
        s.watch_alive ? `${icon} Клиент перезапущен и активен` : '🔴️ Клиент не отвечает — проверьте терминал или нажмите ещё раз',
    ].join('\n');

    btn.disabled = false;
}

async function clearCurrentClaudeMessages() {
    if (!state.claude.sessionUuid) return;
    const confirmed = await confirmDialog('Очистить все сообщения текущей сессии?');
    if (!confirmed) return;
    try {
        await postData('/telegram-app/claude/session/clear-messages', { session_uuid: state.claude.sessionUuid });
    } catch {
        appendBubble('assistant', '⚠️ Не удалось очистить сообщения', false, _claudeEl);
        return;
    }
    _claudeEl.innerHTML = '';
    state.claude.renderedUserIds = new Set();
    state.claude.renderedResponses = new Map();
    state.claude.pendingUserCount = 0;
    state.claude.typingBubble?.remove();
    state.claude.typingBubble = null;
}

async function deleteCurrentClaudeSession() {
    if (!state.claude.sessionUuid) return;
    const confirmed = await confirmDialog(`Удалить сессию "${state.claude.sessionLabel}"? Терминал начнёт с чистого листа при следующем запуске.`);
    if (!confirmed) return;
    try {
        await postData('/telegram-app/claude/session/delete-request', { session_uuid: state.claude.sessionUuid });
    } catch { /* тихо */ }
    closeClaudeSessionView();
}

async function requestQuotaCheck() {
    if (!state.claude.sessionUuid) return;
    const btn = document.getElementById('claudeQuotaChipBtn');
    btn.classList.add('loading');
    try {
        await postData('/telegram-app/claude/quota-check', { session_uuid: state.claude.sessionUuid });
    } catch { /* тихо — ответ придёт через polling */ } finally {
        btn.classList.remove('loading');
    }
}

function _parseQuotaResponse(response) {
    try {
        const data = JSON.parse(response);
        if (data.quota === true) {
            const lines = ['📊 Квота Claude'];
            if (data.error) {
                lines.push('⚠️ ' + data.error);
                return { displayText: lines.join('\n'), quotaData: null };
            }
            if (data.five_hour != null) lines.push(`5ч: ${data.five_hour}%`);
            if (data.seven_day != null) lines.push(`7д: ${data.seven_day}%`);
            if (data.reset_time) lines.push(`Сброс: ${data.reset_time}`);
            return { displayText: lines.join('\n'), quotaData: data };
        }
    } catch { /* не JSON или не quota */ }
    return { displayText: response, quotaData: null };
}

function _updateQuotaChip(data) {
    const btn = document.getElementById('claudeQuotaChipBtn');
    if (!btn) return;
    const h5 = data.five_hour != null ? Math.round(data.five_hour) + '%' : null;
    const d7 = data.seven_day != null ? Math.round(data.seven_day) + '%' : null;
    const parts = [h5, d7].filter(Boolean);
    btn.textContent = parts.length ? parts.join('\n') : '?%';
}

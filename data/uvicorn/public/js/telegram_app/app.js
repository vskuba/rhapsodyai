import { postData } from '/static/js/api.js';
import { state } from './state.js';
import { createInputBar, createMicOnlyBar } from './input_bar.js';
import { initSidebar, setSidebarPageMode, updateInputBarsVisibility } from './sidebar.js';
import { loadEvents, shouldReloadEvents } from './events.js';
import { initChat } from './chat.js';
import { initClaude, loadClaudeSessionList, updateClaudePolling, updateClaudeStatusPolling, closeClaudeSessionView } from './claude.js';
import { initTasks, loadTasks, openTaskDetailView, closeTaskDetailView } from './tasks.js';

const tg = window.Telegram?.WebApp;

async function init() {
    tg?.ready();
    tg?.expand();

    const initData   = tg?.initData || '';
    const accessToken = new URLSearchParams(window.location.search).get('access_token') || '';

    try {
        await postData('/telegram-app/auth', { init_data: initData, access_token: accessToken });
    } catch {
        document.getElementById('tab-events').innerHTML = '<div class="denied-state">⛔ Доступ запрещён</div>';
        return;
    }

    // --- создаём input bars программно и вешаем на app-wrapper ---
    const appWrapper = document.querySelector('.app-wrapper');

    const claudeBar = createInputBar({ id: 'claudeInputBar',  progressId: 'claudeProgress',  placeholder: 'Сообщение для Claude Code...', hasQuickCmd: true });
    const chatBar   = createInputBar({ id: 'chatInputBar',    progressId: 'chatProgress',    placeholder: 'Сообщение...' });
    const taskBar   = createInputBar({ id: 'taskInputBar',    progressId: 'taskProgress',    placeholder: 'Вопрос по задаче...'});

    // progress вставляется перед bar (анимация над полем ввода)
    for (const { progress, bar } of [claudeBar, chatBar, taskBar]) {
        appWrapper.appendChild(progress);
        appWrapper.appendChild(bar);
    }

    // --- quick cmd popup тоже вставляем в appWrapper (он уже в HTML, оставляем) ---

    const inputBars = {
        claude: { bar: claudeBar.bar,     progress: claudeBar.progress },
        chat:   { bar: chatBar.bar,       progress: chatBar.progress },
        task:   { bar: taskBar.bar,       progress: taskBar.progress },
    };

    initSidebar({
        inputBars,
        onTabChange(tab) {
            if (tab === 'tasks') loadTasks();
            if (tab === 'claude' && !state.claude.sessionUuid) loadClaudeSessionList();
            updateClaudePolling();
            updateClaudeStatusPolling();
        },
        onGoHome: goHome,
    });

    initChat(chatBar);
    initClaude(claudeBar);
    initTasks();

    // click handlers
    document.getElementById('tasksListView').addEventListener('click', e => {
        const item = e.target.closest('.task-list-item');
        if (!item) return;
        closeTaskDetailView();
        openTaskDetailView(Number(item.dataset.id));
    });
    initHomePing();

    await loadEvents();
    // После очистки событий (events.js) обновление приостанавливается на 30 секунд —
    // иначе новые записи event_log мгновенно возвращают список на экран.
    setInterval(() => { if (shouldReloadEvents()) loadEvents(); }, 5000);
}

function goHome() {
    if (state.currentTaskId !== null) closeTaskDetailView();
    if (state.claude.sessionUuid !== null) closeClaudeSessionView();

    document.querySelectorAll('.icon-btn[data-tab]').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-view').forEach(v => v.classList.remove('active'));
    document.getElementById('tabBtnEvents').classList.add('active');
    document.getElementById('tab-events').classList.add('active');
    state.currentTab = 'events';
    setSidebarPageMode(false);
    updateInputBarsVisibility();
    updateClaudePolling();
    updateClaudeStatusPolling();
}

function initHomePing() {
    pingServer();
    setInterval(pingServer, 5000);
}

async function pingServer() {
    const homeBtn = document.getElementById('homeIconBtn');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 1000);
    try {
        await fetch('/telegram-app/ping', { signal: controller.signal });
        state.pingFailCount = 0;
        homeBtn.classList.remove('pulsing');
    } catch {
        state.pingFailCount++;
        if (state.pingFailCount >= 2) homeBtn.classList.add('pulsing');
    } finally {
        clearTimeout(timeout);
    }
}

init();

import { state } from './state.js';
import { loadConfig } from './config.js';

const PAGE_TITLES = { events: 'События', claude: 'Claude', chat: 'Чат', plans: 'Планы' };

const tg = window.Telegram?.WebApp;

let _inputBars = {};
let _onTabChange = null;
let _onGoHome = null;

export function initSidebar({ inputBars, onTabChange, onGoHome }) {
    _inputBars = inputBars;
    _onTabChange = onTabChange;
    _onGoHome = onGoHome;

    document.querySelectorAll('.icon-btn[data-tab]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.icon-btn[data-tab]').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-view').forEach(v => v.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
            state.currentTab = btn.dataset.tab;
            setSidebarPageMode(true);
            updateInputBarsVisibility();
            _onTabChange?.(state.currentTab);
        });
    });

    document.getElementById('homeIconBtn').addEventListener('click', _onGoHome);
    document.getElementById('pageBackIconBtn').addEventListener('click', () => setSidebarPageMode(false));

    document.getElementById('dasboardRemote').addEventListener('click', async () => {
        const config = await loadConfig();
        const url = config.SITE_LOGIN_REMOTE_URL || 'https://92.5.17.195.sslip.io/login';
        if (tg?.openLink) tg.openLink(url);
        else window.open(url, '_blank');
    });
    document.getElementById('dasboardLocal').addEventListener('click', async () => {
        const config = await loadConfig();
        const url = config.SITE_LOGIN_LOCAL_URL || 'https://93.175.229.252.sslip.io:44152/login';
        if (tg?.openLink) tg.openLink(url);
        else window.open(url, '_blank');
    });
    // Запасного адреса, в отличие от соседей, нет: те ведут на свою же установку и
    // угадываются, а этот — внешний сервис из `.env`. Пустая переменная означает, что
    // адрес не задан, и открывать вместо него выдуманный URL нельзя.
    document.getElementById('deepseekHarness').addEventListener('click', async () => {
        const config = await loadConfig();
        const url = config.DEEPSEEK_HARNESS_GX10;
        if (!url) {
            alert('Адрес DeepSeek не задан: переменная DEEPSEEK_HARNESS_GX10 пуста');
            return;
        }
        if (tg?.openLink) tg.openLink(url);
        else window.open(url, '_blank');
    });
}

export function setSidebarPageMode(isInPage) {
    const isClaudeOpen = state.currentTab === 'claude' && state.claude.sessionUuid !== null;
    document.getElementById('sidebarDefaultIcons').classList.toggle('active-group', !isInPage);
    document.getElementById('sidebarPageIcons').classList.toggle('active-group', isInPage && !isClaudeOpen);
    document.getElementById('sidebarClaudeIcons').classList.toggle('active-group', isInPage && isClaudeOpen);
    document.getElementById('pageHeader').classList.toggle('visible', isInPage);
    document.getElementById('pageHeaderTitle').textContent =
        isClaudeOpen ? state.claude.sessionLabel : (PAGE_TITLES[state.currentTab] || '');
}

export function setSidebarPlanMode(isPlanOpen) {
    document.getElementById('sidebarPageIcons').classList.toggle('active-group', !isPlanOpen);
    document.getElementById('sidebarPlanIcons').classList.toggle('active-group', isPlanOpen);
}

export function updateInputBarsVisibility() {
    const { chat, claude, plan, planCreate } = _inputBars;
    const tab = state.currentTab;

    const isChatTab = tab === 'chat';
    chat.bar.classList.toggle('chat-visible', isChatTab);
    chat.progress.classList.toggle('chat-visible', isChatTab);

    const isClaudeOpen = tab === 'claude' && state.claude.sessionUuid !== null;
    claude.bar.classList.toggle('chat-visible', isClaudeOpen);
    claude.progress.classList.toggle('chat-visible', isClaudeOpen);

    const isPlanDetail = tab === 'plans' && state.currentPlanId !== null;
    plan.bar.classList.toggle('chat-visible', isPlanDetail);
    plan.progress.classList.toggle('chat-visible', isPlanDetail);

    const isPlansList = tab === 'plans' && state.currentPlanId === null;
    planCreate.bar.classList.toggle('chat-visible', isPlansList);
    planCreate.progress.classList.toggle('chat-visible', isPlansList);
}

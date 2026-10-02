// Страница «Сессии»: оболочка. Переключает вкладки и заводит каждую один раз.
//
// Сам разбор сессий лежит в модулях вкладок — у «Агентов» и «Чата» общего
// только раскладка: первая читает журнал вызовов LLM, вторая — разговоры пары.
// Соседняя вкладка добавляется кнопкой в `admin/session.html`, панелью
// `#tab-<имя>` и строкой в `tabStarters` ниже.
//
// Устройство страницы — `.claude/docs/session.md`.

import {sessionAgentInit} from './agent.js';
import {sessionChatInit} from './chat.js';

const SESSION_TAB_KEY = 'session_tab';

// Кто заводит вкладку. Ключ — `data-tab` кнопки и хвост `id` панели.
const tabStarters = {
    agent: sessionAgentInit,
    chat: sessionChatInit,
};

// Какие вкладки уже заведены. Инициализация ленивая: каждая вкладка тянет свои
// справочники и свой список, и платить за обе при заходе незачем — открыта
// всегда одна.
const tabStarted = {};

function tabSwitch(name) {
    document.querySelectorAll('.page-tab').forEach(one => {
        one.classList.toggle('active', one.dataset.tab === name);
    });
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === `tab-${name}`);
    });

    if (!tabStarted[name] && tabStarters[name]) {
        tabStarted[name] = true;
        tabStarters[name]();
    }
}

document.querySelectorAll('.page-tab').forEach(tab => {
    tab.onclick = () => {
        localStorage.setItem(SESSION_TAB_KEY, tab.dataset.tab);
        tabSwitch(tab.dataset.tab);
    };
});

// ⚠ `loadTz()` до первой отрисовки: без него `fmtTz` покажет UTC, а настройка
// `timezone` сдвигает время на всех страницах админки. Здесь, а не в модулях
// вкладок, — сдвиг один на страницу, и второй вызов был бы лишним запросом.
await loadTz();

// Запомненная вкладка, если она ещё существует: кнопку могли убрать, и тогда
// открывается первая — пустая страница вместо сессий хуже забытого выбора.
const tabRemembered = localStorage.getItem(SESSION_TAB_KEY);
const tabKnown = [...document.querySelectorAll('.page-tab')].map(one => one.dataset.tab);

tabSwitch(tabKnown.includes(tabRemembered) ? tabRemembered : tabKnown[0]);

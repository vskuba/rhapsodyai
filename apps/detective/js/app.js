// Точка входа PWA detective: guest-сессия + чат с detective_bot/подозреваемыми
// через /chat/ask, переключение агента по чипсу с именем подозреваемого.

const DETECTIVE_BOT_AGENT_ID = 30;
// Как шаги бота и подозреваемых зовут игрока: сосед больше не подставляет
// `companion_title` из запроса по умолчанию — PWA кладёт его переменой сам
// (то же значение, что лежало в реестре: companion.title у записи 4).
const COMPANION_TITLE = 'Игрок';
const SESSION_STORAGE_KEY = 'detective_session_uuid';

const messagesEl = document.getElementById('messages');
const formEl = document.getElementById('inputForm');
const inputEl = document.getElementById('userInput');
const sendButtonEl = document.getElementById('sendButton');
const micButtonEl = document.getElementById('micButton');

if ('serviceWorker' in navigator) {
    // register() требует secure context (https или localhost) - на голом
    // HTTP (прод сейчас без сертификата) молча отклонится, ловим, чтобы не
    // сыпать unhandled promise rejection в консоль
    navigator.serviceWorker.register('/play/detective/sw.js').catch(() => {});
}

// crypto.randomUUID() тоже требует secure context - на голом HTTP (прод
// сейчас без сертификата) его просто нет в объекте crypto. Свой генератор
// не завязан на Crypto API - работает в любом контексте, криптостойкость
// тут не нужна, только уникальность игровой сессии.
function uuidV4() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// Текущий собеседник: detective_bot по умолчанию, подозреваемый/сержант - после клика по чипсу
let currentAgentId = DETECTIVE_BOT_AGENT_ID;
let currentAgentTitle = 'Детектив-бот';

// Интерактивные фрагменты сообщений AI:
// [[link:URL|текст]] — ссылка, [[текст]] — чипс (имя подозреваемого или обычная подсказка)
const MESSAGE_TOKEN_REGEX = /\[\[link:([\s\S]+?)\]\]|\[\[([\s\S]+?)\]\]/g;

function renderMessageContent(container, text) {
    let lastIndex = 0;

    for (const match of text.matchAll(MESSAGE_TOKEN_REGEX)) {
        if (match.index > lastIndex) {
            container.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
        }

        if (match[1] !== undefined) {
            const [url, label] = match[1].split('|');
            const link = document.createElement('a');
            link.className = 'chat-link';
            link.href = url.trim();
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = (label ?? url).trim();
            container.appendChild(link);
        } else {
            const suggestion = match[2];
            const chip = document.createElement('span');
            chip.className = 'chat-suggestion';
            chip.textContent = suggestion;
            chip.onclick = () => onChipClick(suggestion);
            container.appendChild(chip);
        }

        lastIndex = match.index + match[0].length;
    }

    if (lastIndex < text.length) {
        container.appendChild(document.createTextNode(text.slice(lastIndex)));
    }
}

function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = `message ${role}-msg`;
    if (role === 'ai') {
        renderMessageContent(div, text);
    } else {
        div.textContent = text;
    }
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
}

// Индикатор "печатает" - три пульсирующие точки вместо статичного текста,
// генерация дела занимает заметное время (большой LLM-промпт), нужно
// показать, что процесс идет, а не завис
function addTypingIndicator() {
    const div = document.createElement('div');
    div.className = 'message ai-msg loading';
    div.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
}

function getSessionUuid() {
    let sessionUuid = localStorage.getItem(SESSION_STORAGE_KEY);
    if (!sessionUuid) {
        sessionUuid = uuidV4();
        localStorage.setItem(SESSION_STORAGE_KEY, sessionUuid);
    }
    return sessionUuid;
}

async function guestLoginEnsure() {
    const res = await fetch('/auth/guest', { method: 'POST', credentials: 'same-origin' });
    if (!res.ok) {
        throw new Error(`Guest login failed: ${res.status}`);
    }
    return res.json();
}

// Подозреваемые/сержант текущего дела - для резолва чипса с именем в agent_id
async function caseAgentsFetch() {
    const res = await fetch(`/detective/case_agents?session_uuid=${encodeURIComponent(getSessionUuid())}`, {
        credentials: 'same-origin',
    });
    if (!res.ok) return { suspects: [], sergeant: null };
    const data = await res.json();
    return data.result;
}

function switchToDetectiveBot() {
    currentAgentId = DETECTIVE_BOT_AGENT_ID;
    currentAgentTitle = 'Детектив-бот';
    addMessage('🔙 Вернулись к делу', 'system');
    renderBackChip();
}

function switchToCaseAgent(agentId, title, greeting) {
    currentAgentId = agentId;
    currentAgentTitle = title;
    addMessage(`🔎 Допрос: ${title}`, 'system');
    if (greeting) {
        addMessage(greeting, 'ai');
    }
    renderBackChip();
}

// Чипс "назад к детективу" виден, только пока собеседник — не сам detective_bot
function renderBackChip() {
    const existing = document.getElementById('backChip');
    if (existing) existing.remove();

    if (currentAgentId === DETECTIVE_BOT_AGENT_ID) return;

    const div = document.createElement('div');
    div.className = 'message system-msg';
    div.id = 'backChip';
    const chip = document.createElement('span');
    chip.className = 'chat-suggestion';
    chip.textContent = '🔙 Вернуться к делу';
    chip.onclick = () => switchToDetectiveBot();
    div.appendChild(chip);
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

// Клик по чипсу в сообщении: если текст совпадает с именем подозреваемого/сержанта
// текущего дела - переключаем собеседника, иначе отправляем как обычное сообщение
async function onChipClick(text) {
    const { suspects, sergeant } = await caseAgentsFetch();
    const candidates = sergeant ? [...suspects, sergeant] : suspects;
    const match = candidates.find((a) => a.title.trim() === text.trim());

    if (match) {
        switchToCaseAgent(match.id, match.title, match.greeting);
        return;
    }

    sendMessage(text);
}

// Пока запрос в полете - блокируем ВСЕ чипсы (не только кнопку отправки):
// иначе можно кликнуть "Начать новое дело" (или чипс подозреваемого) второй
// раз до ответа сервера и открыть несколько дел параллельно
let requestInFlight = false;

async function sendMessage(text, displayText) {
    if (requestInFlight) return;

    const question = (text ?? inputEl.value).trim();
    if (!question) return;

    requestInFlight = true;
    messagesEl.classList.add('busy');
    inputEl.value = '';
    sendButtonEl.disabled = true;
    // displayText === null - явно скрыть пузырь "пользователь написал"
    // (например, клик по кнопке "Начать новое дело" не должен ничего показывать)
    if (displayText !== null) {
        addMessage(displayText ?? question, 'user');
    }

    const loadingDiv = addTypingIndicator();

    try {
        const res = await fetch('/chat/ask', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                agent_id: currentAgentId,
                variables: { companion_title: COMPANION_TITLE },
                session_uuid: getSessionUuid(),
            }),
        });

        loadingDiv.remove();

        if (!res.ok) {
            const errBody = await res.json().catch(() => ({}));
            addMessage(`⚠️ Ошибка: ${errBody.detail || res.status}`, 'ai');
            return;
        }

        const data = await res.json();
        addMessage(data.result || '(пустой ответ)', 'ai');

        // /new_case создает новых подозреваемых - чипс "назад" мог устареть
        // (например, до этого шел допрос уже нерелевантного подозреваемого)
        if (currentAgentId === DETECTIVE_BOT_AGENT_ID) {
            renderBackChip();
        }
    } catch (e) {
        loadingDiv.remove();
        addMessage(`⚠️ Не удалось связаться с сервером: ${e.message}`, 'ai');
    } finally {
        requestInFlight = false;
        messagesEl.classList.remove('busy');
        sendButtonEl.disabled = false;
        inputEl.focus();
    }
}

formEl.addEventListener('submit', (e) => {
    e.preventDefault();
    sendMessage();
});

// Восстанавливает переписку текущей сессии после перезагрузки страницы
// (та же сессия живет в localStorage - см. getSessionUuid). Возвращает true,
// если история была и отрисована - тогда приветствие/кнопка "Начать новое
// дело" не нужны, игрок и так посреди дела.
async function restoreHistory() {
    try {
        const res = await fetch('/chat/messages', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_uuid: getSessionUuid(), limit: 50 }),
        });
        if (!res.ok) return false;

        const data = await res.json();
        const rows = data.result || [];
        if (!rows.length) return false;

        for (const row of rows) {
            addMessage(row.content, row.role === 'user' ? 'user' : 'ai');
        }
        return true;
    } catch (e) {
        return false;
    }
}

async function init() {
    sendButtonEl.disabled = true;

    try {
        await guestLoginEnsure();
    } catch (e) {
        addMessage(`⚠️ Не удалось начать сессию: ${e.message}`, 'system');
        return;
    }

    sendButtonEl.disabled = false;

    const historyRestored = await restoreHistory();
    if (!historyRestored) {
        addMessage('Добро пожаловать в детективное агентство!', 'system');

        const startDiv = document.createElement('div');
        startDiv.className = 'message system-msg';
        const startChip = document.createElement('span');
        startChip.className = 'chat-suggestion';
        startChip.textContent = 'Начать новое дело';
        startChip.onclick = () => sendMessage('/new_case', null);
        startDiv.appendChild(startChip);
        messagesEl.appendChild(startDiv);
    }

    voiceInit();
}

// Голосовой ввод: зажать - говорить, отпустить - расшифровка (Faster Whisper,
// /chat/voice - тот же эндпоинт, что у веб-чата в админке) подставляется в
// поле ввода на проверку, а не отправляется сразу. getUserMedia требует
// secure context (https или localhost) - на голом HTTP кнопка скрывается,
// а не падает с ошибкой.
function voiceInit() {
    if (!navigator.mediaDevices?.getUserMedia) {
        micButtonEl.hidden = true;
        return;
    }

    let mediaRecorder = null;
    let audioChunks = [];
    let stream = null;

    async function recordingStart() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
            addMessage(`⚠️ Микрофон недоступен: ${e.message}`, 'system');
            return;
        }
        audioChunks = [];
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
        mediaRecorder.onstop = async () => {
            stream.getTracks().forEach((t) => t.stop());
            const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });

            const formData = new FormData();
            formData.append('file', audioBlob, 'voice.wav');

            micButtonEl.disabled = true;
            try {
                const res = await fetch('/chat/voice', { method: 'POST', credentials: 'same-origin', body: formData });
                if (res.ok) {
                    const data = await res.json();
                    if (data.result) {
                        inputEl.value = data.result;
                        inputEl.focus();
                    }
                }
            } catch (e) {
                addMessage(`⚠️ Не удалось расшифровать голос: ${e.message}`, 'system');
            } finally {
                micButtonEl.disabled = false;
            }
        };
        mediaRecorder.start();
        micButtonEl.classList.add('recording');
    }

    function recordingStop() {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }
        micButtonEl.classList.remove('recording');
    }

    // pointerdown/up вместо mousedown/up - единый обработчик для мыши,
    // тача и стилуса (мобильный PWA - основная площадка использования)
    micButtonEl.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        recordingStart();
    });
    micButtonEl.addEventListener('pointerup', recordingStop);
    micButtonEl.addEventListener('pointerleave', recordingStop);
}

init();

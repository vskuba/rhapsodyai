let tabId = null;

const HTML_DEFAULTS = {
    'aiUrl': "http://localhost:8011",
    'accessToken': "8fd15581-36ae-48ed-812f-3b3d11d427f0",
    'delaySelect': "5",
    'agentResponse': "0",
    'agentRequest': "",
    'querySelectorMessageIn': ".bubble.is-in .message .translatable-message",
    'querySelectorMessageOut': ".bubble.is-out .bubble-content .message",
    'querySelectorMessageOutInputBox': ".input-message-input",
    'querySelectorCompanionId': ".chat-info .person .user-title .peer-title::attr(data-peer-id)",
    'querySelectorCompanionTitle': ".chat-info .person .user-title .peer-title",
    'companionId': "",
    'companionTitle': "",
    'companionIdPrefix': "companion_",
    'pluginEnabled': false
};

function storage_get() {
    const storage = typeof chrome !== 'undefined' && chrome.storage ? chrome.storage : browser.storage;

    if (!storage || !storage.local) {
        alert("Ошибка прав: Перезапустите расширение на странице about:debugging!");
        return;
    }

    return storage;
}

// Получить ключ, уникальный для текущей активной вкладки браузера
function getScopedKey(key) {
    return tabId ? `tab_${tabId}_${key}` : key;
}

// Функция получения ID активной вкладки
async function getActiveTabId() {
    const tabsApi = typeof chrome !== 'undefined' && chrome.tabs ? chrome.tabs : browser.tabs;
    if (!tabsApi) return null;
    try {
        const [tab] = await tabsApi.query({ active: true, currentWindow: true });
        return tab ? tab.id : null;
    } catch (e) {
        console.error("Не удалось получить activeTabId:", e);
        return null;
    }
}

// Функция внедрения content.js во вкладку для обеспечения работы сканеров
async function injectContentScript(targetTabId) {
    const tabsApi = typeof chrome !== 'undefined' && chrome.tabs ? chrome.tabs : browser.tabs;
    const scriptingApi = typeof chrome !== 'undefined' && chrome.scripting ? chrome.scripting : browser.scripting;

    if (tabsApi && scriptingApi && targetTabId) {
        try {
            const tab = await tabsApi.get(targetTabId);
            if (tab && tab.url && !tab.url.startsWith('chrome://') && !tab.url.startsWith('about:')) {
                // Проверяем, запущен ли уже скрипт на этой вкладке (через тестовое сообщение ping)
                let isAlreadyRunning = false;
                try {
                    const response = await tabsApi.sendMessage(targetTabId, { action: "ping" });
                    if (response && response.status === "pong") {
                        isAlreadyRunning = true;
                    }
                } catch (e) {
                    // Ошибка означает, что контент-скрипт еще не был запущен во вкладке
                }

                if (!isAlreadyRunning) {
                    await scriptingApi.executeScript({
                        target: { tabId: targetTabId },
                        files: ["content.js"]
                    });
                    console.log(`🚀 content.js успешно внедрен во вкладку ID: ${targetTabId}`);
                } else {
                    console.log(`🤖 content.js уже запущен во вкладке ${targetTabId}, повторное внедрение не требуется.`);
                }
            }
        } catch (error) {
            console.warn(`Не удалось внедрить контент-скрипт во вкладку ${targetTabId}:`, error);
        }
    }
}

// Функция добавления логов в logContainer с меткой времени в UI
function addLog(message, isError = false) {
    const logContainer = document.getElementById('logContainer');
    if (!logContainer) return;

    const now = new Date();
    const timeStr = now.toTimeString().split(' ')[0]; // Формат HH:MM:SS
    
    const logItem = document.createElement('div');
    logItem.className = 'log-item';
    const prefix = isError ? '<span style="color: #f56565;">[Ошибка]</span> ' : '';
    logItem.innerHTML = `<span class="log-time">[${timeStr}]</span>${prefix}${message}`;
    
    logContainer.appendChild(logItem);

    // Ограничиваем количество отображаемых логов в UI до 50
    while (logContainer.children.length > 50) {
        logContainer.removeChild(logContainer.firstChild);
    }

    logContainer.scrollTop = logContainer.scrollHeight; // Прокрутка вниз
}

// Функция сохранения лога в хранилище и отображения в UI
async function saveAndAddLog(message, isError = false) {
    addLog(message, isError);

    const storage = storage_get();
    if (storage) {
        const logKey = getScopedKey('pluginLogs');
        const result = await storage.local.get(logKey);
        const pluginLogs = result[logKey] || [];
        
        const now = new Date();
        const timeStr = now.toTimeString().split(' ')[0];
        
        pluginLogs.push({
            time: timeStr,
            message: message,
            isError: isError
        });
        
        // Ограничиваем историю логов 50 записями
        if (pluginLogs.length > 50) {
            pluginLogs.shift();
        }
        
        await storage.local.set({ [logKey]: pluginLogs });
    }
}

// Функция обновления состояния нижнего статус-бара
function updateStatusBar(isEnabled, isError = false) {
    const statusBar = document.querySelector('.status');
    if (!statusBar) return;

    if (isEnabled) {
        statusBar.className = 'status active';
    } else if (isError) {
        statusBar.className = 'status error';
    } else {
        statusBar.className = 'status';
    }
}

// Асинхронная функция запуска ручного ответа ИИ на выбранное сообщение (Делегирует исполнение в content.js через сообщение)
async function triggerManualReply(cleanText) {
    const tabsApi = typeof chrome !== 'undefined' && chrome.tabs ? chrome.tabs : browser.tabs;
    if (tabsApi && tabId) {
        await saveAndAddLog(`Запуск ручного ответа на сообщение: "${cleanText.slice(0, 25)}..."`);
        
        // Отправляем сообщение контент-скрипту на выполнение ИИ-ответа через универсальную функцию
        tabsApi.sendMessage(tabId, { action: "triggerReply", text: cleanText });
    } else {
        console.error("Не найден активный TabID вкладки.");
    }
}

// Функция отрисовки истории сообщений в виде диалога на вкладке 4
function renderChatHistory(chatHistory) {
    const container = document.getElementById('chatDialogueContainer');
    if (!container) return;

    container.innerHTML = ""; // Очищаем контейнер

    if (!chatHistory || chatHistory.length === 0) {
        container.innerHTML = `<div style="text-align: center; color: #a0aec0; font-size: 11px; margin-top: 100px;">Сообщений пока нет</div>`;
        return;
    }

    chatHistory.forEach(msg => {
        const msgRow = document.createElement('div');
        msgRow.className = `chat-message ${msg.sender}`; // "chat-message in" или "chat-message out"

        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';

        const textDiv = document.createElement('div');
        textDiv.innerText = msg.text;

        const metaDiv = document.createElement('div');
        metaDiv.className = 'chat-meta';
        
        const senderLabel = msg.sender === 'in' ? 'Входящее' : 'Исходящее';
        
        const labelSpan = document.createElement('span');
        labelSpan.innerText = senderLabel;

        const timeSpan = document.createElement('span');
        timeSpan.innerText = msg.time;

        metaDiv.appendChild(labelSpan);

        // Если это входящее сообщение, добавляем кнопку ручного ответа "Ответить"
        if (msg.sender === 'in') {
            const replyBtn = document.createElement('button');
            replyBtn.innerText = 'Ответить';
            replyBtn.style.fontSize = '8px';
            replyBtn.style.padding = '1px 5px';
            replyBtn.style.backgroundColor = '#3182ce';
            replyBtn.style.color = 'white';
            replyBtn.style.border = 'none';
            replyBtn.style.borderRadius = '3px';
            replyBtn.style.cursor = 'pointer';
            replyBtn.style.fontWeight = 'bold';
            replyBtn.style.marginLeft = '8px';
            replyBtn.style.lineHeight = '1';
            replyBtn.style.display = 'inline-block';
            
            replyBtn.addEventListener('click', async (e) => {
                e.stopPropagation(); // Исключаем срабатывание кликов по родительскому бабблу
                await triggerManualReply(msg.text);
            });

            metaDiv.appendChild(replyBtn);
        }

        metaDiv.appendChild(timeSpan);

        bubble.appendChild(textDiv);
        bubble.appendChild(metaDiv);
        msgRow.appendChild(bubble);
        container.appendChild(msgRow);
    });

    container.scrollTop = container.scrollHeight; // Прокрутка чата вниз
}

// Функция для получения и заполнения списка агентов
async function fetchAndPopulateAgents(aiUrl, accessToken, agentResponseSelect) {
    const storage = storage_get();
    let savedAgentId = "0";
    if (storage) {
        const agentKey = getScopedKey('agentResponse');
        const result = await storage.local.get(agentKey);
        savedAgentId = result[agentKey] || "0";
    }

    const response = await fetch(`${aiUrl}/agent/list`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-API-KEY': accessToken
        },
        body: JSON.stringify({
            find_by: {}
        })
    });

    if (!response.ok) {
        throw new Error(`Ошибка HTTP: ${response.status}`);
    }

    const data = await response.json();
    const agents = data.result || [];

    // Очищаем текущий список select
    agentResponseSelect.innerHTML = "";

    if (agents.length === 0) {
        const opt = document.createElement('option');
        opt.value = "0";
        opt.innerText = "Нет агентов";
        agentResponseSelect.appendChild(opt);
    } else {
        // Добавляем опцию "Не выбран"
        const defaultOpt = document.createElement('option');
        defaultOpt.value = "0";
        defaultOpt.innerText = "Не выбран";
        agentResponseSelect.appendChild(defaultOpt);

        // Наполняем элементами из ответа
        agents.forEach(agent => {
            const opt = document.createElement('option');
            opt.value = agent.id;
            opt.innerText = agent.title || agent.name;
            agentResponseSelect.appendChild(opt);
        });
    }

    // Восстанавливаем выбранное значение, если оно присутствует в новом списке
    if (savedAgentId !== "0") {
        const hasOption = Array.from(agentResponseSelect.options).some(opt => opt.value === String(savedAgentId));
        if (hasOption) {
            agentResponseSelect.value = savedAgentId;
        } else {
            agentResponseSelect.value = "0";
        }
    } else {
        agentResponseSelect.value = "0";
    }

    // Сохраняем итоговое значение в storage
    if (storage) {
        const agentKey = getScopedKey('agentResponse');
        storage.local.set({ [agentKey]: agentResponseSelect.value });
    }
}

// Универсальная функция перезагрузки контекста попапа для конкретной вкладки (вызывается на старте и при переключении вкладок)
async function reloadPopupContext(newTabId) {
    if (!newTabId) return;
    tabId = newTabId;
    console.log(`🔄 Переключение контекста на вкладку ID: ${tabId}`);

    const storage = storage_get();
    if (!storage) return;

    // Внедряем content.js на активную вкладку, чтобы гарантировать запуск сканеров при смене вкладки
    await injectContentScript(tabId);

    // Находим элементы настроек интерфейса (включая pluginEnabled!)
    const data = {
        'aiUrl': document.getElementById('aiUrl'),
        'accessToken': document.getElementById('accessToken'),
        'delaySelect': document.getElementById('delaySelect'),
        'agentResponse': document.getElementById('agentResponse'),
        'agentRequest': document.getElementById('agentRequest'),
        'querySelectorMessageIn': document.getElementById('querySelectorMessageIn'),
        'querySelectorMessageOut': document.getElementById('querySelectorMessageOut'),
        'querySelectorMessageOutInputBox': document.getElementById('querySelectorMessageOutInputBox'),
        'querySelectorCompanionId': document.getElementById('querySelectorCompanionId'),
        'querySelectorCompanionTitle': document.getElementById('querySelectorCompanionTitle'),
        'companionId': document.getElementById('companionId'),
        'companionTitle': document.getElementById('companionTitle'),
        'companionIdPrefix': document.getElementById('companionIdPrefix'),
        'pluginEnabled': document.getElementById('pluginEnabled')
    }

    // Инициализируем список ключей
    const keys = Object.keys(data).filter(key => data[key] !== null);
    
    // Списком запрашиваем и глобальные параметры по умолчанию для новых вкладок
    const globalDefaultKeys = [
        'global_default_aiUrl',
        'global_default_accessToken',
        'global_default_querySelectorMessageIn',
        'global_default_querySelectorMessageOut',
        'global_default_querySelectorMessageOutInputBox',
        'global_default_querySelectorCompanionId',
        'global_default_querySelectorCompanionTitle',
        'global_default_companionIdPrefix'
    ];
    const scopedKeysToGet = keys.map(key => getScopedKey(key)).concat(globalDefaultKeys);

    // Считываем и восстанавливаем сохраненные значения
    storage.local.get(scopedKeysToGet, (result) => {
        if (!result) return;

        const defaultsToSave = {};

        keys.forEach(key => {
            const scopedKey = getScopedKey(key);
            const savedValue = result[scopedKey];

            if (savedValue !== undefined) {
                const element = data[key];
                if (element.type === 'checkbox') {
                    element.checked = savedValue;
                    if (key === 'pluginEnabled') {
                        updateStatusBar(savedValue);
                    }
                } else {
                    element.value = savedValue;
                }
            } else {
                // Если пусто в хранилище текущей вкладки, проверяем, есть ли глобальное значение по умолчанию
                const element = data[key];
                let value = HTML_DEFAULTS[key];

                const globalDefaultKey = `global_default_${key}`;
                if (result[globalDefaultKey] !== undefined) {
                    value = result[globalDefaultKey];
                }
                
                // Принудительно сбрасываем состояние элемента в DOM согласно вычисленным значениям
                if (element.type === 'checkbox') {
                    element.checked = value;
                } else {
                    element.value = value;
                }

                if (value !== undefined && value !== "") {
                    defaultsToSave[scopedKey] = value;
                    
                    // Также запишем в global_default, чтобы принудительно инициализировать глобальные дефолты при первом запуске
                    const globalDefaultKeysList = [
                        'aiUrl',
                        'accessToken',
                        'querySelectorMessageIn',
                        'querySelectorMessageOut',
                        'querySelectorMessageOutInputBox',
                        'querySelectorCompanionId',
                        'querySelectorCompanionTitle',
                        'companionIdPrefix'
                    ];
                    if (globalDefaultKeysList.includes(key)) {
                        defaultsToSave[`global_default_${key}`] = value;
                    }
                }
                if (key === 'pluginEnabled') {
                    updateStatusBar(value === true);
                }
            }
        });

        // Записываем дефолты в storage, если их не было
        if (Object.keys(defaultsToSave).length > 0) {
            storage.local.set(defaultsToSave);
        }
    });

    // Очищаем и восстанавливаем логи текущей вкладки в лог-боксе
    const logContainer = document.getElementById('logContainer');
    if (logContainer) {
        logContainer.innerHTML = "";
    }
    const logKey = getScopedKey('pluginLogs');
    storage.local.get(logKey, (result) => {
        if (logContainer && result[logKey]) {
            result[logKey].forEach(log => {
                const logItem = document.createElement('div');
                logItem.className = 'log-item';
                const prefix = log.isError ? '<span style="color: #f56565;">[Ошибка]</span> ' : '';
                logItem.innerHTML = `<span class="log-time">[${log.time}]</span>${prefix}${log.message}`;
                logContainer.appendChild(logItem);
            });
            logContainer.scrollTop = logContainer.scrollHeight;
        }
    });

    // Восстанавливаем историю диалога текущей вкладки на вкладке 4
    const chatKey = getScopedKey('chatHistory');
    storage.local.get(chatKey, (result) => {
        renderChatHistory(result[chatKey] || []);
    });
}

// Функция переключения вкладок
document.querySelectorAll('.tab-btn').forEach(button => {
    button.addEventListener('click', () => {
        const tabIdAttr = button.getAttribute('data-tab');

        // Удаляем активный класс со всех кнопок и контентов
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

        // Добавляем активный класс на выбранную кнопку и контент
        button.classList.add('active');
        document.getElementById(tabIdAttr).classList.add('active');

        // Прокручиваем диалог чата вниз при переключении на вкладку 4
        if (tabIdAttr === 'tab-4') {
            const container = document.getElementById('chatDialogueContainer');
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
        }
    });
});

document.addEventListener('DOMContentLoaded', async () => {
    const storage = storage_get();
    if (!storage) return;

    // Сначала получаем ID активной вкладки
    const activeId = await getActiveTabId();
    console.log(`🔌 popup.js открыт для вкладки ID: ${activeId}`);

    // При каждом открытии плагина сбрасываем состояние активности текущей вкладки в false (пользователь включает вручную)
    const pluginEnabledCheckbox = document.getElementById('pluginEnabled');
    if (pluginEnabledCheckbox) {
        pluginEnabledCheckbox.checked = false;
        updateStatusBar(false);
        const enabledKey = getScopedKey('pluginEnabled');
        await storage.local.set({ [enabledKey]: false });
    }

    // При каждом открытии плагина очищаем логи текущей вкладки в хранилище
    const logKey = getScopedKey('pluginLogs');
    await storage.local.set({ [logKey]: [] });

    // Инициализируем и подгружаем контекст активной вкладки
    await reloadPopupContext(activeId);

    // Находим элементы настроек интерфейса для автосохранения
    const data = {
        'aiUrl': document.getElementById('aiUrl'),
        'accessToken': document.getElementById('accessToken'),
        'delaySelect': document.getElementById('delaySelect'),
        'agentResponse': document.getElementById('agentResponse'),
        'agentRequest': document.getElementById('agentRequest'),
        'querySelectorMessageIn': document.getElementById('querySelectorMessageIn'),
        'querySelectorMessageOut': document.getElementById('querySelectorMessageOut'),
        'querySelectorMessageOutInputBox': document.getElementById('querySelectorMessageOutInputBox'),
        'querySelectorCompanionId': document.getElementById('querySelectorCompanionId'),
        'querySelectorCompanionTitle': document.getElementById('querySelectorCompanionTitle'),
        'companionId': document.getElementById('companionId'),
        'companionTitle': document.getElementById('companionTitle'),
        'companionIdPrefix': document.getElementById('companionIdPrefix')
    }

    // Фильтруем объект: удаляем ключи, для которых элементы не были найдены на текущей вкладке HTML
    const keys = Object.keys(data).filter(key => data[key] !== null);

    // АВТОСОХРАНЕНИЕ: Слушаем изменения в полях настроек и сразу записываем в scoped-ключ памяти
    keys.forEach(key => {
        const element = data[key];
        const elementTagName = element.tagName.toLowerCase();

        // Определяем тип события
        const eventType = (elementTagName === 'select' || element.type === 'checkbox') ? 'change' : 'input';

        element.addEventListener(eventType, async () => {
            const currentStorage = storage_get();
            if (currentStorage && currentStorage.local) {
                const scopedElementKey = getScopedKey(element.id);

                // Если элемент — чекбокс, сохраняем его состояние (true/false), иначе — строку текста
                const value = element.type === 'checkbox' ? element.checked : element.value;

                // Сохраняем в scoped-ключ вкладки
                const dataToSave = { [scopedElementKey]: value };

                // Если это один из общих параметров, также сохраняем его как глобальный дефолт для новых вкладок
                const globalDefaultKeysList = [
                    'aiUrl',
                    'accessToken',
                    'querySelectorMessageIn',
                    'querySelectorMessageOut',
                    'querySelectorMessageOutInputBox',
                    'querySelectorCompanionId',
                    'querySelectorCompanionTitle',
                    'companionIdPrefix'
                ];
                if (globalDefaultKeysList.includes(element.id)) {
                    dataToSave[`global_default_${element.id}`] = value;
                }

                await new Promise((resolve) => {
                    currentStorage.local.set(dataToSave, resolve);
                });
            }
        });
    });

    // Обработка чекбокса pluginEnabled с валидацией соединения для ТЕКУЩЕЙ вкладки
    if (pluginEnabledCheckbox) {
        pluginEnabledCheckbox.addEventListener('change', async () => {
            const currentStorage = storage_get();
            if (!currentStorage) return;

            const isChecked = pluginEnabledCheckbox.checked;

            if (isChecked) {
                await saveAndAddLog("Активация плагина. Проверка соединения с AI API...");

                const aiUrlInput = document.getElementById('aiUrl');
                const accessTokenInput = document.getElementById('accessToken');
                const agentResponseSelect = document.getElementById('agentResponse');

                if (!aiUrlInput || !accessTokenInput || !agentResponseSelect) {
                    await saveAndAddLog("Ошибка активации: Не найдены элементы настроек API.", true);
                    pluginEnabledCheckbox.checked = false;
                    const enabledKey = getScopedKey('pluginEnabled');
                    await currentStorage.local.set({ [enabledKey]: false });
                    updateStatusBar(false, true);
                    return;
                }

                const aiUrl = aiUrlInput.value.trim();
                const accessToken = accessTokenInput.value.trim();

                if (!aiUrl || !accessToken) {
                    await saveAndAddLog("Ошибка активации: Не заполнены URL API или Access Token. Не хватает значений.", true);
                    pluginEnabledCheckbox.checked = false;
                    const enabledKey = getScopedKey('pluginEnabled');
                    await currentStorage.local.set({ [enabledKey]: false });
                    updateStatusBar(false, true);
                    //alert("Пожалуйста, заполните URL API и Access Token перед включением плагина.");
                    return;
                }

                try {
                    await fetchAndPopulateAgents(aiUrl, accessToken, agentResponseSelect);
                    await saveAndAddLog("Соединение успешно, список агентов вернулся.");
                } catch (error) {
                    await saveAndAddLog(`Ошибка неверного соединения: ${error.message}. Не удалось получить список агентов.`, true);
                    await saveAndAddLog("Активация отклонена: плагин выключен.");
                    pluginEnabledCheckbox.checked = false;
                    const enabledKey = getScopedKey('pluginEnabled');
                    await currentStorage.local.set({ [enabledKey]: false });
                    updateStatusBar(false, true);
                    return;
                }

                // Шаг 3 & 4. Проверяем, выбран ли конкретный агент в селекторе
                const selectedAgentId = agentResponseSelect.value;
                if (selectedAgentId === "0" || !selectedAgentId) {
                    await saveAndAddLog("Ошибка активации: Агент ответа не выбран в настройках.", true);
                    await saveAndAddLog("Активация отклонена: плагин выключен.");
                    pluginEnabledCheckbox.checked = false;
                    const enabledKey = getScopedKey('pluginEnabled');
                    await currentStorage.local.set({ [enabledKey]: false });
                    updateStatusBar(false); // Сброс в обычный серый отключенный статус
                    //alert("Для активации плагина необходимо выбрать конкретного Агента ответа из списка.");
                    return;
                }

                // ПРОВЕРКА СОБЕСЕДНИКА С ПОМОЩЬЮ smartQuerySelector В content.js
                const titleSelectorEl = document.getElementById('querySelectorCompanionTitle');
                const idSelectorEl = document.getElementById('querySelectorCompanionId');

                if (!titleSelectorEl || !idSelectorEl) {
                    await saveAndAddLog("Ошибка активации: Не найдены селекторы собеседника в DOM.", true);
                    pluginEnabledCheckbox.checked = false;
                    const enabledKey = getScopedKey('pluginEnabled');
                    await currentStorage.local.set({ [enabledKey]: false });
                    updateStatusBar(false, true);
                    return;
                }

                const titleSelector = titleSelectorEl.value.trim();
                const idSelector = idSelectorEl.value.trim();

                if (!titleSelector || !idSelector) {
                    await saveAndAddLog("Ошибка активации: Не заполнены селекторы Companion ID или Companion Title.", true);
                    pluginEnabledCheckbox.checked = false;
                    const enabledKey = getScopedKey('pluginEnabled');
                    await currentStorage.local.set({ [enabledKey]: false });
                    updateStatusBar(false, true);
                    alert("Пожалуйста, заполните Companion ID и Companion Title селекторы в настройках.");
                    return;
                }

                await saveAndAddLog("Попытка получить данные собеседника со страницы...");

                // Запрашиваем данные у контент-скрипта через sendMessage
                const companionRes = await new Promise((resolve) => {
                    const tabsApi = typeof chrome !== 'undefined' && chrome.tabs ? chrome.tabs : browser.tabs;
                    if (tabsApi && tabId) {
                        tabsApi.sendMessage(tabId, {
                            action: "getCompanionInfo",
                            titleSelector: titleSelector,
                            idSelector: idSelector
                        }, (response) => {
                            // Игнорируем lastError на случай, если контент-скрипт не запущен
                            const err = typeof chrome !== 'undefined' && chrome.runtime ? chrome.runtime.lastError : browser.runtime.lastError;
                            resolve(response);
                        });
                    } else {
                        resolve(null);
                    }
                });

                if (!companionRes || !companionRes.success || !companionRes.title || !companionRes.id) {
                    let failReason = "Не удалось связаться со вкладкой или контент-скрипт не ответил.";
                    if (companionRes) {
                        if (!companionRes.success) {
                            failReason = companionRes.error || "Ошибка выполнения smartQuerySelector.";
                        } else {
                            failReason = `Элементы не найдены на странице. Проверьте правильность селекторов. Собеседник: ${companionRes.title ? "ОК" : "НЕ НАЙДЕН"}, ID: ${companionRes.id ? "ОК" : "НЕ НАЙДЕН"}`;
                        }
                    }

                    await saveAndAddLog(`Ошибка активации: ${failReason}`, true);
                    await saveAndAddLog("Активация отклонена: плагин выключен.");
                    pluginEnabledCheckbox.checked = false;
                    const enabledKey = getScopedKey('pluginEnabled');
                    await currentStorage.local.set({ [enabledKey]: false });
                    updateStatusBar(false, true);
                    alert(`Не удалось определить Собеседника или ID по указанным селекторам.\nПричина: ${failReason}`);
                    return;
                }

                // Вставляем полученные данные в DOM элементы companionTitle и companionId
                const companionTitleInput = document.getElementById('companionTitle');
                const companionIdInput = document.getElementById('companionId');
                
                if (companionTitleInput) {
                    companionTitleInput.value = companionRes.title;
                    await currentStorage.local.set({ [getScopedKey('companionTitle')]: companionRes.title });
                }
                if (companionIdInput) {
                    companionIdInput.value = companionRes.id;
                    await currentStorage.local.set({ [getScopedKey('companionId')]: companionRes.id });
                }

                await saveAndAddLog(`Собеседник успешно определен: "${companionRes.title}" (ID: ${companionRes.id})`);

                // Шаг 6. Если агент выбран, плагин успешно активируется
                const agentText = agentResponseSelect.options[agentResponseSelect.selectedIndex].text;
                await saveAndAddLog(`Плагин успешно активирован. Выбран агент: "${agentText}".`);
                const enabledKey = getScopedKey('pluginEnabled');
                await currentStorage.local.set({ [enabledKey]: true });
                updateStatusBar(true);

                // Даем команду контент-скрипту на ЗАПУСК сканеров
                if (tabsApi && tabId) {
                    tabsApi.sendMessage(tabId, { action: "startScanners" });
                }

            } else {
                await saveAndAddLog("Плагин деактивирован пользователем.");
                const enabledKey = getScopedKey('pluginEnabled');
                await currentStorage.local.set({ [enabledKey]: false });
                updateStatusBar(false);

                // Даем команду контент-скрипту ОСТАНОВИТЬ сканеры (очистить интервалы)
                const tabsApi = typeof chrome !== 'undefined' && chrome.tabs ? chrome.tabs : browser.tabs;
                if (tabsApi && tabId) {
                    tabsApi.sendMessage(tabId, { action: "stopScanners" });
                }
            }
        });
    }

    const sendMessageOutBtn = document.getElementById('sendMessageOutBtn');
    const testMessageOutInput = document.getElementById('testMessageOut');

    if (sendMessageOutBtn && testMessageOutInput) {
        sendMessageOutBtn.addEventListener('click', async () => {
            const currentStorage = storage_get();
            if (!currentStorage) return;

            const text = testMessageOutInput.value ? testMessageOutInput.value.trim() : "";
            console.log("✈ Нажата кнопка отправить тестовое сообщение ", text);
            if (!text) return; // Игнорируем пустые сообщения

            // Считываем текущую актуальную очередь для ТЕКУЩЕЙ вкладки
            const outKey = getScopedKey('historyMessagesOut');
            const result = await currentStorage.local.get(outKey);
            const historyMessagesOut = result[outKey] || [];

            // Добавляем новое сообщение в конец очереди массива
            historyMessagesOut.push(text);

            // Сохраняем обновленный массив в хранилище расширения
            await currentStorage.local.set({ [outKey]: historyMessagesOut });
            console.log("✈️ Сообщение добавлено в очередь отправки:", text);
        });
    }

    const testConnectionBtn = document.getElementById('testConnectionBtn');
    if (testConnectionBtn) {
        testConnectionBtn.addEventListener('click', async () => {
            const aiUrlInput = document.getElementById('aiUrl');
            const accessTokenInput = document.getElementById('accessToken');
            const agentResponseSelect = document.getElementById('agentResponse');

            if (!aiUrlInput || !accessTokenInput || !agentResponseSelect) {
                console.error("Не найдены необходимые элементы формы.");
                return;
            }

            const aiUrl = aiUrlInput.value.trim();
            const accessToken = accessTokenInput.value.trim();

            if (!aiUrl || !accessToken) {
                alert("Пожалуйста, заполните URL API и Access Token.");
                return;
            }

            testConnectionBtn.disabled = true;
            testConnectionBtn.innerText = "Загрузка...";

            try {
                await saveAndAddLog("Запуск проверки соединения через кнопку...");
                await fetchAndPopulateAgents(aiUrl, accessToken, agentResponseSelect);
                await saveAndAddLog("Проверка соединения: ОК. Список агентов успешно обновлен.");
                alert("Список агентов успешно обновлен!");
            } catch (error) {
                console.error("Ошибка при запросе агентов:", error);
                await saveAndAddLog(`Ошибка проверки соединения через кнопку: ${error.message}`, true);
                alert(`Не удалось получить список агентов: ${error.message}`);
            } finally {
                testConnectionBtn.disabled = false;
                testConnectionBtn.innerText = "Запрос агентов";
            }
        });
    }

    const clearChatHistoryBtn = document.getElementById('clearChatHistoryBtn');
    if (clearChatHistoryBtn) {
        clearChatHistoryBtn.addEventListener('click', async () => {
            const currentStorage = storage_get();
            if (currentStorage && currentStorage.local) {
                const chatKey = getScopedKey('chatHistory');
                // Очищаем историю в Local Storage
                await currentStorage.local.set({ [chatKey]: [] });
                // Очищаем историю в интерфейсе
                renderChatHistory([]);
                await saveAndAddLog("История диалога очищена.");
            }
        });
    }

    // Слушаем лог-сообщения и обновления диалога от контент-скрипта (content.js) в реальном времени
    const runtimeApi = typeof chrome !== 'undefined' && chrome.runtime ? chrome.runtime : browser.runtime;
    if (runtimeApi && runtimeApi.onMessage) {
        runtimeApi.onMessage.addListener((message, sender, sendResponse) => {
            // Чтобы логи от одной вкладки не засоряли интерфейс попапа при открытии на другой,
            // проверяем соответствие ID вкладки отправителя с текущим активным tabId в popup!
            const senderTabId = sender.tab ? sender.tab.id : null;
            if (senderTabId && senderTabId !== tabId) {
                return; // Игнорируем логи от других (фоновых) вкладок в открытом попапе
            }

            if (message && message.action === 'log') {
                addLog(message.message, message.isError);
            } else if (message && message.action === 'chatUpdate') {
                renderChatHistory(message.chatHistory || []);
            }
        });
    }

    // СЛУШАЕМ ПЕРЕКЛЮЧЕНИЕ ВКЛАДОК В БРАУЗЕРЕ: Перезагружаем контекст плагина в реальном времени при смене активной вкладки
    const tabsApi = typeof chrome !== 'undefined' && chrome.tabs ? chrome.tabs : browser.tabs;
    if (tabsApi && tabsApi.onActivated) {
        tabsApi.onActivated.addListener(async (activeInfo) => {
            console.log(`🔄 Активная вкладка браузера переключена на ID: ${activeInfo.tabId}`);
            await reloadPopupContext(activeInfo.tabId);
        });
    }

    // Слушаем изменение URL или перезагрузку вкладки
    if (tabsApi && tabsApi.onUpdated) {
        tabsApi.onUpdated.addListener(async (tabIdAttr, changeInfo, tab) => {
            if (changeInfo.status === 'complete' && tabIdAttr === tabId) {
                console.log(`🔄 Активная вкладка обновилась (статус complete). Перезапускаем контекст...`);
                await reloadPopupContext(tabIdAttr);
            }
        });
    }

    // Находим активную вкладку и внедряем туда наш контент-скрипт при старте
    const scriptingApi = typeof chrome !== 'undefined' && chrome.scripting ? chrome.scripting : browser.scripting;

    if (tabsApi && scriptingApi) {
        try {
            const [tab] = await tabsApi.query({active: true, currentWindow: true});
            if (tab && tab.url && !tab.url.startsWith('chrome://') && !tab.url.startsWith('about:')) {
                await scriptingApi.executeScript({
                    target: {tabId: tab.id},
                    files: ["content.js"]
                });
            }
        } catch (error) {
            console.warn("Не удалось внедрить контент-скрипт (возможно, служебная страница браузера):", error);
        }
    }
});
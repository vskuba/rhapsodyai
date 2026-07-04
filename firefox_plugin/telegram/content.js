let tabId = null;

function storageGet() {
    const storage = typeof chrome !== 'undefined' && chrome.storage ? chrome.storage : browser.storage;

    if (!storage || !storage.local) {
        console.error("❌ Ошибка прав: Доступ к chrome.storage.local запрещен.");
        return null;
    }

    return storage;
}

// Получить ключ, уникальный для текущей вкладки браузера
function getScopedKey(key) {
    return tabId ? `tab_${tabId}_${key}` : key;
}

// Инициализация ID вкладки на старте (с защитным таймаутом на 200мс)
async function initTabId() {
    return new Promise((resolve) => {
        const runtime = typeof chrome !== 'undefined' && chrome.runtime ? chrome.runtime : browser.runtime;

        // Защитный таймаут, чтобы сканеры гарантированно запускались даже при сбое фонового скрипта
        const timeoutId = setTimeout(() => {
            console.warn("⚠️ Превышено время ожидания getTabId, запускаем сканеры без TabID.");
            resolve();
        }, 200);

        if (runtime && runtime.sendMessage) {
            try {
                runtime.sendMessage({action: "getTabId"}, (response) => {
                    clearTimeout(timeoutId);
                    if (response && response.tabId) {
                        tabId = response.tabId;
                        console.log(`🤖 content.js запущен на вкладке ID: ${tabId}`);
                    }
                    resolve();
                });
            } catch (e) {
                clearTimeout(timeoutId);
                console.error("Ошибка при отправке getTabId:", e);
                resolve();
            }
        } else {
            clearTimeout(timeoutId);
            resolve();
        }
    });
}

// Универсальная функция добавления логов в локальное хранилище и ретрансляции в popup
async function addPluginLog(message, isError = false) {
    const prefix = isError ? "❌" : "ℹ️";
    console.log(`${prefix} ${message}`);

    const storage = storageGet();
    if (storage) {
        // Записываем лог в массив в хранилище, чтобы сохранить историю при закрытом popup
        const logKey = getScopedKey('pluginLogs');
        const result = await storage.local.get(logKey);
        const pluginLogs = result[logKey] || [];

        const now = new Date();
        const timeStr = now.toTimeString().split(' ')[0]; // HH:MM:SS

        pluginLogs.push({
            time: timeStr,
            message: message,
            isError: isError
        });

        // Ограничиваем историю логов последними 50 записями
        if (pluginLogs.length > 50) {
            pluginLogs.shift();
        }

        await storage.local.set({[logKey]: pluginLogs});
    }

    // Отправляем лог-сообщение в открытый popup в реальном времени
    const runtime = typeof chrome !== 'undefined' && chrome.runtime ? chrome.runtime : browser.runtime;
    if (runtime && runtime.sendMessage) {
        runtime.sendMessage({
            action: 'log',
            message: message,
            isError: isError
        }, () => {
            // Подавляем ошибку "Receiving end does not exist" в консоли, если popup закрыт
            const err = runtime.lastError;
        });
    }
}

async function saveMessagesToStorage(message) {
    const storage = storageGet();
    if (!storage) return;

    // Правильный асинхронный запрос данных из хранилища
    const historyKey = getScopedKey('historyMessagesIn');
    const result = await storage.local.get(historyKey);
    const historyMessagesIn = result[historyKey] || [];

    // Добавляем новый ответ с меткой времени
    historyMessagesIn.push({
        text: message,
        timestamp: new Date().toLocaleTimeString()
    });

    // Ограничиваем историю 20 последними записями
    if (historyMessagesIn.length > 20) {
        historyMessagesIn.shift();
    }

    // Сохраняем обратно в хранилище расширения
    await storage.local.set({[historyKey]: historyMessagesIn});
}

// Функция добавления сообщений в историю диалога и ретрансляции в popup
async function addMessageToChatHistory(sender, text) {
    const storage = storageGet();
    if (!storage) return;

    const chatKey = getScopedKey('chatHistory');
    const result = await storage.local.get(chatKey);
    const chatHistory = result[chatKey] || [];

    // ПРОВЕРКА НА ДУБЛИКАТЫ: Проверяем последнее сохраненное сообщение в истории
    if (chatHistory.length > 0) {
        const lastMsg = chatHistory[chatHistory.length - 1];
        if (lastSavedTextEquals(lastMsg, sender, text)) {
            return;
        }
    }

    const now = new Date();
    const timeStr = now.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); // Формат HH:MM

    chatHistory.push({
        sender: sender, // "in" или "out"
        text: text,
        time: timeStr,
        timestamp: now.getTime()
    });

    // Сохраняем только последние 20 сообщений
    if (chatHistory.length > 20) {
        chatHistory.shift();
    }

    await storage.local.set({[chatKey]: chatHistory});

    // Ретранслируем обновление диалога в открытый popup в реальном времени
    const runtime = typeof chrome !== 'undefined' && chrome.runtime ? chrome.runtime : browser.runtime;
    if (runtime && runtime.sendMessage) {
        runtime.sendMessage({
            action: 'chatUpdate',
            chatHistory: chatHistory
        }, () => {
            const err = runtime.lastError; // Подавляем ошибку, если popup закрыт
        });
    }
}

// Вспомогательная функция сравнения для дедупликации сообщений
function hasSameContent(a, b) {
    return a.trim() === b.trim();
}

function hasSameSender(sender1, sender2) {
    return sender1 === sender2;
}

// Проверяем совпадение текста и отправителя
function lastSavedTextEquals(lastMsg, sender, text) {
    return hasSameSender(lastMsg.sender, sender) && hasSameContent(lastMsg.text, text);
}

// ЕДИНАЯ УНИВЕРСАЛЬНАЯ ФУНКЦИЯ: Запуск цепочки получения ИИ-ответа на сообщение (используется для автоответа и ручного ответа)
async function processAiResponse(cleanText) {
    try {
        const storage = storageGet();
        if (!storage) return;

        const urlKey = getScopedKey('aiUrl');
        const tokenKey = getScopedKey('accessToken');
        const agentKey = getScopedKey('agentResponse');

        const status = await storage.local.get([urlKey, tokenKey, agentKey]);
        const aiUrl = status[urlKey] || "";
        const accessToken = status[tokenKey] || "";
        const agent_id = status[agentKey] || "0";

        if (!aiUrl || !accessToken || agent_id === "0") {
            await addPluginLog("Ошибка ИИ-ответа: Не настроены URL API, Access Token или Агент.", true);
            return;
        }

        await addPluginLog("Запуск цепочки ИИ-ответа: получение user_id и companion_id...");
        // 1. Получаем user_id
        const userRes = await fetch(`${aiUrl}/user`, {
            headers: {'X-API-KEY': accessToken}
        });
        if (!userRes.ok) {
            throw new Error(`Ошибка GET /user: ${userRes.status}`);
        }
        const userData = await userRes.json();
        const user_id = userData.result.id;

        // Получаем имя собеседника со страницы или из локального хранилища
        const compIdKey = getScopedKey('companionId');
        const compIdRes = await storage.local.get(compIdKey);
        const rawCompanionId = compIdRes[compIdKey] || "tg_companion";

        // Получаем префикс companionIdPrefix из локального хранилища
        const compPrefixKey = getScopedKey('companionIdPrefix');
        const compPrefixRes = await storage.local.get(compPrefixKey);
        const companionPrefix = compPrefixRes[compPrefixKey] !== undefined ? compPrefixRes[compPrefixKey] : "telegram_";

        const companionName = companionPrefix + rawCompanionId;

        // Считываем также имя собеседника из хранилища для передачи в качестве title
        const compTitleKey = getScopedKey('companionTitle');
        const compTitleRes = await storage.local.get(compTitleKey);
        const companionTitle = compTitleRes[compTitleKey] || companionName;

        // Запрашиваем Companion ID из API (POST)
        const compRes = await fetch(`${aiUrl}/companion`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-KEY': accessToken
            },
            body: JSON.stringify({
                name: companionName,
                title: companionTitle
            })
        });
        if (!compRes.ok) {
            throw new Error(`Ошибка POST /companion: ${compRes.status}`);
        }
        const compData = await compRes.json();
        const companionId = compData.result.id;

        await addPluginLog(`user_id: ${user_id}, companion_id: ${companionId}. Получение session_uuid...`);

        // 2. Получаем session_uuid
        const sessRes = await fetch(`${aiUrl}/session/last/uuid`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-KEY': accessToken
            },
            body: JSON.stringify({
                agent_id: parseInt(agent_id),
                user_id: user_id
            })
        });
        if (!sessRes.ok) {
            throw new Error(`Ошибка POST /session/last/uuid: ${sessRes.status}`);
        }
        const sessData = await sessRes.json();
        let session_uuid = sessData.result;

        // Если session_uuid пустой/отсутствует, генерируем новый UUIDv4
        if (!session_uuid) {
            session_uuid = self.crypto.randomUUID();
            await addPluginLog(`Создан новый UUID сессии: ${session_uuid}`);
        } else {
            await addPluginLog(`Используется существующая сессия: ${session_uuid}`);
        }

        // 3. Отправляем запрос на /chat/ask
        await addPluginLog("Запрос ответа у AI...");
        const chatRes = await fetch(`${aiUrl}/chat/ask`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-KEY': accessToken
            },
            body: JSON.stringify({
                question: cleanText,
                agent_id: parseInt(agent_id),
                companion_id: companionId,
                session_uuid: session_uuid
            })
        });
        if (!chatRes.ok) {
            let errorMsg = `Ошибка POST /chat/ask: ${chatRes.status}`;
            if (chatRes.status === 429 || chatRes.status === 500) {
                try {
                    const errData = await chatRes.json();
                    if (errData) {
                        errorMsg = errData.message || errData.detail || errorMsg;
                    }
                } catch (e) {}
            }
            throw new Error(errorMsg);
        }
        const chatData = await chatRes.json();
        const aiAnswer = chatData.result;

        await addPluginLog(`Ответ AI получен: "${aiAnswer.slice(0, 30)}...". Рассчитываем задержку...`);

        // Получаем значение задержки (delaySelect) из хранилища (диапазон или число)
        const delayKey = getScopedKey('delaySelect');
        const delayResult = await storage.local.get(delayKey);
        const delayRaw = delayResult[delayKey] !== undefined ? String(delayResult[delayKey]).trim() : "15-45";

        let delaySeconds = 5;
        if (delayRaw.includes('-')) {
            const parts = delayRaw.split('-');
            const min = parseInt(parts[0]) || 0;
            const max = parseInt(parts[1]) || 0;
            if (max >= min) {
                // Рандомная задержка в промежутке [min, max]
                delaySeconds = Math.floor(Math.random() * (max - min + 1)) + min;
            }
        } else {
            delaySeconds = parseInt(delayRaw) || 5;
        }

        if (delaySeconds > 0) {
            await addPluginLog(`Ожидание согласно Delay Select (${delayRaw}): выбран случайный интервал ${delaySeconds} сек...`);
            await new Promise(resolve => setTimeout(resolve, delaySeconds * 1000));
            await addPluginLog("Ожидание завершено. Отправка сообщения...");
        }

        // 4. Отправляем ответ как исходящее сообщение (кладем его в очередь отправки)
        const outKey = getScopedKey('historyMessagesOut');
        const outResult = await storage.local.get(outKey);
        const historyMessagesOut = outResult[outKey] || [];
        historyMessagesOut.push(aiAnswer);
        await storage.local.set({[outKey]: historyMessagesOut});
        await addPluginLog("Ответ AI добавлен в очередь отправки плагина.");
        await addMessageToChatHistory('out', aiAnswer);

    } catch (error) {
        console.error("Ошибка в цепочке автоответа:", error);
        await addPluginLog(`Ошибка автоответа: ${error.message}`, true);
    }
}

function listeningForMessagesIn() {
    if (window.messagesInInterval) {
        clearInterval(window.messagesInInterval);
        window.messagesInInterval = null;
    }

    addPluginLog("Сканнер входящих сообщений запущен.");

    window.messagesInInterval = setInterval(async () => {
        const storage = storageGet();
        if (!storage) return;

        const enabledKey = getScopedKey('pluginEnabled');
        const status = await storage.local.get(enabledKey);
        if (status[enabledKey] === false || status[enabledKey] === undefined) return;

        const selectorKey = getScopedKey('querySelectorMessageIn');
        const settings = await storage.local.get(selectorKey);
        const selectorIn = settings[selectorKey] || null;

        if (!selectorIn) return;

        const currentMessages = document.querySelectorAll(selectorIn);
        if (currentMessages.length === 0) return;

        const latestMessageEl = currentMessages[currentMessages.length - 1];
        const cleanText = latestMessageEl.textContent ? latestMessageEl.textContent.trim() : "";

        // Защита от пустых строк, точек загрузки и анимации "typing..."
        if (!cleanText || cleanText.includes('...')) return;

        // Считываем историю входящих из persistent storage для точной проверки на дубликаты (выживает при F5)
        const historyKey = getScopedKey('historyMessagesIn');
        const historyResult = await storage.local.get(historyKey);
        const historyMessagesIn = historyResult[historyKey] || [];

        let lastSavedText = null;
        if (historyMessagesIn.length > 0) {
            lastSavedText = historyMessagesIn[historyMessagesIn.length - 1].text;
        }

        // Если этот текст уже совпадает с последним сохраненным, пропускаем тик
        if (cleanText === lastSavedText) {
            return;
        }

        await addPluginLog(`Обнаружено входящее сообщение: "${cleanText.slice(0, 30)}..."`);

        await saveMessagesToStorage(cleanText);
        await addMessageToChatHistory('in', cleanText);

        // Проверяем, если это не первое сообщение в истории, то запускаем цепочку автоответа
        if (historyMessagesIn.length > 0) {
            // --- Автоматическая отправка ответа AI (Вызываем универсальную функцию) ---
            setTimeout(async () => {
                await processAiResponse(cleanText);
            }, 100);
        }
    }, 600);
}

function listeningForMessagesOut() {
    if (window.messagesOutInterval) {
        clearInterval(window.messagesOutInterval);
        window.messagesOutInterval = null;
    }

    const storage = storageGet();
    if (!storage) return;

    addPluginLog("Сканнер отправки исходящих сообщений запущен.");

    window.messagesOutInterval = setInterval(async () => {
        // Блокируем интервал на время выполнения асинхронной операции
        if (window.isProcessingOutMessage) return;

        const storage = storageGet();
        if (!storage) return;

        const enabledKey = getScopedKey('pluginEnabled');
        const status = await storage.local.get(enabledKey);
        if (status[enabledKey] === false || status[enabledKey] === undefined) return;

        // Инициализируем правильный запрос к хранилищу
        const outKey = getScopedKey('historyMessagesOut');
        const result = await storage.local.get(outKey);
        const historyMessagesOut = result[outKey] || [];

        if (historyMessagesOut.length > 0) {
            window.isProcessingOutMessage = true; // Блокируем интервал

            const selectorKey = getScopedKey('querySelectorMessageOutInputBox');
            const settings = await storage.local.get(selectorKey);
            const selectorOut = settings[selectorKey] || null;

            if (!selectorOut) {
                await addPluginLog("Селектор отправки (querySelectorMessageOutInputBox) не задан в настройках.", true);
                window.isProcessingOutMessage = false;
                return;
            }

            const textToSend = historyMessagesOut[0];

            if (!textToSend || textToSend.trim() === "") {
                await addPluginLog("Пустое сообщение в очереди отправки. Пропускаем.", true);
                // Удаляем пустое сообщение из очереди
                historyMessagesOut.shift();
                await storage.local.set({[outKey]: historyMessagesOut});
                window.isProcessingOutMessage = false;
                return;
            }

            const textarea = document.querySelector(selectorOut);
            if (!textarea) {
                await addPluginLog(`Элемент ввода по селектору "${selectorOut}" не найден.`, true);
                window.isProcessingOutMessage = false;
                return;
            }

            textarea.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}));
            textarea.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
            textarea.click();

            textarea.focus();
            textarea.textContent = "";

            // Эмулируем написание и стирание текста (10 итераций)
            await addPluginLog("Эмулируем активность набора текста перед отправкой (10 итераций)...");
            const delayInterval = textToSend.length * 350;
            const delayQtyIteration = 10;

            for (let i = 0; i < delayQtyIteration; i++) {
                document.execCommand('insertText', false, "..");
                textarea.dispatchEvent(new Event('input', {bubbles: true}));
                await new Promise(resolve => setTimeout(resolve, delayInterval/delayQtyIteration));


                // textarea.dispatchEvent(new Event('input', {bubbles: true}));
                // await new Promise(resolve => setTimeout(resolve, delayInterval/delayQtyIteration));
            }

            document.execCommand('selectAll', false, null);

            // Эмулируем нативный ввод текста для обновления стейта (React/Vue/Telegraf)
            document.execCommand('insertText', false, textToSend);

            // Trigger события изменений для Telegram Web
            textarea.dispatchEvent(new Event('input', {bubbles: true}));
            textarea.dispatchEvent(new Event('change', {bubbles: true}));

            const shortText = textToSend.slice(0, 15);
            await addPluginLog(`Сообщение "${shortText}..." подготовлено в Telegram. Эмулируем отправку Enter...`);

            // Пауза перед нажатием Enter (даем интерфейсу синхронизироваться)
            setTimeout(async () => {
                const enterEventConfig = {
                    key: "Enter",
                    code: "Enter",
                    keyCode: 13,
                    which: 13,
                    bubbles: true,
                    cancelable: true
                };

                const keydownEvent = new KeyboardEvent("keydown", enterEventConfig);
                textarea.dispatchEvent(keydownEvent);

                await addPluginLog("Эмуляция нажатия Enter выполнена.");

                // берем актуальную очередь сообщений из хранилища, чтобы не потерять данные при параллельных изменениях
                const outKeyFresh = getScopedKey('historyMessagesOut');
                const freshHistoryMessagesOutBox = await storage.local.get(outKeyFresh);
                const freshHistoryMessagesOut = freshHistoryMessagesOutBox[outKeyFresh] || [];
                // Удаляем отправленное сообщение из актуальной очереди
                freshHistoryMessagesOut.shift();

                // Обновляем хранилище БЕЗ отправленного сообщения
                await storage.local.set({[outKeyFresh]: freshHistoryMessagesOut});

                // Снимаем блокировку для следующего сообщения в очереди
                window.isProcessingOutMessage = false;
            }, 400);
        }
    }, 600);
}

// Функция принудительной остановки всех сканеров
function stopScanners() {
    if (window.messagesInInterval) {
        clearInterval(window.messagesInInterval);
        window.messagesInInterval = null;
        addPluginLog("Сканнер входящих сообщений принудительно остановлен.");
    }
    if (window.messagesOutInterval) {
        clearInterval(window.messagesOutInterval);
        window.messagesOutInterval = null;
        addPluginLog("Сканнер отправки исходящих сообщений принудительно остановлен.");
    }
}

/**
 * Умная функция для извлечения данных из DOM по текстовой строке
 * @param {string} inputString - Строка из инпута, например ".peer-title::attr(data-peer-id)" или просто ".peer-title"
 * @returns {string|null} - Значение атрибута или текстовый контент элемента
 */
function smartQuerySelector(inputString) {
    if (!inputString) return null;

    const trimmedInput = inputString.trim();
    let selector = trimmedInput;
    let attributeName = null;

    // Проверяем, содержит ли строка маркер атрибута ::attr(имя_атрибута)
    if (trimmedInput.includes('::attr(')) {
        const parts = trimmedInput.split('::attr(');
        selector = parts[0].trim(); // Часть ДО маркера (сам CSS селектор)

        // Вытаскиваем то, что внутри скобок (имя атрибута)
        attributeName = parts[1].replace(')', '').trim();
    }

    // Ищем элемент на странице
    const element = document.querySelector(selector);
    if (!element) {
        console.warn(`[SmartSelector] Элемент по селектору "${selector}" не найден.`);
        return null;
    }

    // Если в строке был указан конкретный атрибут — извлекаем его
    if (attributeName) {
        const attrValue = element.getAttribute(attributeName);
        console.log(`[SmartSelector] Извлечен атрибут "${attributeName}":`, attrValue);
        return attrValue;
    }

    // Если имя атрибута не было указанно (например, в инпут ввели просто ".peer-title")
    // по умолчанию возвращаем чистый текстовый контент элемента
    const textValue = element.textContent ? element.textContent.trim() : "";
    console.log(`[SmartSelector] Извлечен текст элемента:`, textValue);
    return textValue;
}

(async function () {
    await initTabId();

    // Слушаем тестовые пинг-сообщения от popup.js и команды управления сканерами / ручного ответа ИИ
    const runtime = typeof chrome !== 'undefined' && chrome.runtime ? chrome.runtime : browser.runtime;
    if (runtime && runtime.onMessage) {
        runtime.onMessage.addListener((message, sender, sendResponse) => {
            if (message) {
                if (message.action === "ping") {
                    sendResponse({status: "pong"});
                } else if (message.action === "triggerReply") {
                    processAiResponse(message.text);
                } else if (message.action === "startScanners") {
                    listeningForMessagesIn();
                    listeningForMessagesOut();
                } else if (message.action === "stopScanners") {
                    stopScanners();
                } else if (message.action === "getCompanionInfo") {
                    try {
                        const title = smartQuerySelector(message.titleSelector);
                        const id = smartQuerySelector(message.idSelector);
                        sendResponse({ success: true, title: title, id: id });
                    } catch (e) {
                        sendResponse({ success: false, error: e.message });
                    }
                    return true;
                }
            }
        });
    }

    // На старте запускаем сканеры только если плагин уже был активирован на этой вкладке ранее
    const storage = storageGet();
    if (storage) {
        const enabledKey = getScopedKey('pluginEnabled');
        const status = await storage.local.get(enabledKey);
        if (status[enabledKey] === true) {
            listeningForMessagesIn();
            listeningForMessagesOut();
        } else {
            addPluginLog("Плагин выключен. Сканеры ожидают ручной активации через CheckBox.");
        }
    }
})();
function storageGet() {
    const storage = typeof chrome !== 'undefined' && chrome.storage ? chrome.storage : browser.storage;

    if (!storage || !storage.local) {
        console.error("❌ Ошибка прав: Доступ к chrome.storage.local запрещен.");
        return null;
    }

    return storage;
}

async function saveMessagesToStorage(message) {
    const storage = storageGet();
    if (!storage) return;

    // Правильный асинхронный запрос данных из хранилища
    const result = await storage.local.get('historyMessagesIn');
    const historyMessagesIn = result.historyMessagesIn || [];

    // Добавляем новый ответ с меткой времени
    historyMessagesIn.push({
        text: message,
        timestamp: new Date().toLocaleTimeString()
    });

    // Сохраняем обратно в хранилище расширения
    await storage.local.set({historyMessagesIn: historyMessagesIn});
}

function listeningForMessagesIn() {
    if (window.messagesInInterval) {
        clearInterval(window.messagesInInterval);
        window.messagesInInterval = null;
    }

    window.historyMessagesIn = window.historyMessagesIn || [];
    console.log("👀 Начинаем следить за входящими сообщениями ...");

    window.messagesInInterval = setInterval(async () => {
        const storage = storageGet();
        if (!storage) return;

        const status = await storage.local.get('pluginEnabled');
        if (status.pluginEnabled === false) return;

        const settings = await storage.local.get('querySelectorMessageIn');
        const selectorIn = settings.querySelectorMessageIn || null;

        if (!selectorIn) return;

        const currentMessages = document.querySelectorAll(selectorIn);
        if (currentMessages.length === 0) return;

        const latestMessageEl = currentMessages[currentMessages.length - 1];
        const cleanText = latestMessageEl.textContent ? latestMessageEl.textContent.trim() : "";

        // Защита от пустых строк, точек загрузки и анимации "typing..."
        if (!cleanText || cleanText.includes('...')) return;

        const lastSavedText = window.historyMessagesIn[window.historyMessagesIn.length - 1];

        // Если этот текст уже совпадает с последним сохраненным, пропускаем тик
        if (cleanText === lastSavedText) {
            return;
        }

        console.log("🤖 Сканнер зафиксировал сообщение:", cleanText);

        window.historyMessagesIn.push(cleanText);
        await saveMessagesToStorage(cleanText);
    }, 600);
}

function listeningForMessagesOut() {
    if (window.messagesOutInterval) {
        clearInterval(window.messagesOutInterval);
        window.messagesOutInterval = null;
    }

    const storage = storageGet();
    if (!storage) return;

    console.log("👀 Начинаем следить за исходящими сообщениями ...");

    window.messagesOutInterval = setInterval(async () => {
        // Блокируем интервал на время выполнения асинхронной операции
        if (window.isProcessingOutMessage) return;

        const storage = storageGet();
        if (!storage) return;

        const status = await storage.local.get('pluginEnabled');
        if (status.pluginEnabled === false) return;

        // Инициализируем правильный запрос к хранилищу
        const result = await storage.local.get('historyMessagesOut');
        const historyMessagesOut = result.historyMessagesOut || [];

        if (historyMessagesOut.length > 0) {
            window.isProcessingOutMessage = true; // Блокируем интервал

            const settings = await storage.local.get('querySelectorMessageOut');
            const selectorOut = settings.querySelectorMessageOut || null;

            if (!selectorOut) {
                console.log("⚠️ Селектор отправки (querySelectorMessageOut) не задан в настройках.");
                window.isProcessingOutMessage = false;
                return;
            }

            const textToSend = historyMessagesOut[0];

            const textarea = document.querySelector(selectorOut);
            if (!textarea) {
                console.log(`❌ Элемент ввода по селектору "${selectorOut}" не найден.`);
                window.isProcessingOutMessage = false;
                return;
            }


            textarea.focus();
            textarea.textContent = "";

            // Эмулируем нативный ввод текста для обновления стейта (React/Vue/Telegraf)
            document.execCommand('insertText', false, textToSend);

            // Триггерим события изменений для Telegram Web
            textarea.dispatchEvent(new Event('input', {bubbles: true}));
            textarea.dispatchEvent(new Event('change', {bubbles: true}));

            const shortText = textToSend.slice(0, 15);
            console.log(`✅ Сообщение '${shortText}' в стейте Telegram. Ожидаем отправки...`);

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

                console.log("🚀 Эмуляция Enter успешно выполнена!");

                //берем актуальную очередь сообщений из хранилища, чтобы не потерять данные при параллельных изменениях
                const freshHistoryMessagesOutBox = await storage.local.get('historyMessagesOut');
                const freshHistoryMessagesOut = freshHistoryMessagesOutBox.historyMessagesOut || [];
                // Удаляем отправленное сообщение из актуальной очереди
                freshHistoryMessagesOut.shift();

                // Обновляем хранилище БЕЗ отправленного сообщения
                await storage.local.set({historyMessagesOut: freshHistoryMessagesOut});

                // Снимаем блокировку для следующего сообщения в очереди
                window.isProcessingOutMessage = false;
            }, 400);
        }
    }, 600);
}

(async function () {
    listeningForMessagesIn();
    listeningForMessagesOut();
})();
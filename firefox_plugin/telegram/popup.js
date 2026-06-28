function storage_get() {
    const storage = typeof chrome !== 'undefined' && chrome.storage ? chrome.storage : browser.storage;

    if (!storage || !storage.local) {
        alert("Ошибка прав: Перезапустите расширение на странице about:debugging!");
        return;
    }

    return storage;
}

// Функция переключения вкладок
document.querySelectorAll('.tab-btn').forEach(button => {
    button.addEventListener('click', () => {
        const tabId = button.getAttribute('data-tab');

        // Удаляем активный класс со всех кнопок и контентов
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

        // Добавляем активный класс на выбранную кнопку и контент
        button.classList.add('active');
        document.getElementById(tabId).classList.add('active');
    });
});

document.addEventListener('DOMContentLoaded', async () => {
    const storage = storage_get();
    if (!storage) return;

    // Находим элементы интерфейса
    const data = {
        'aiUrl': document.getElementById('aiUrl'),
        'accessToken': document.getElementById('accessToken'),
        'delaySelect': document.getElementById('delaySelect'),
        'agentResponse': document.getElementById('agentResponse'),
        'agentRequest': document.getElementById('agentRequest'),
        'querySelectorMessageIn': document.getElementById('querySelectorMessageIn'),
        'querySelectorMessageOut': document.getElementById('querySelectorMessageOut'),
        'pluginEnabled': document.getElementById('pluginEnabled')
    }

    // Фильтруем объект: удаляем ключи, для которых элементы не были найдены на текущей вкладке HTML
    const keys = Object.keys(data).filter(key => data[key] !== null);

    //ЗАГРУЗКА ДАННЫХ: Читаем сохраненные значения из хранилища при открытии попапа
    storage.local.get(keys, (result) => {
        if (!result) return;

        keys.forEach(key => {
            if (result[key] !== undefined) {
                const element = data[key];
                // Если элемент чекбокс — восстанавливаем свойство checked, иначе — value
                if (element.type === 'checkbox') {
                    element.checked = result[key];
                } else {
                    element.value = result[key];
                }
            }
        });
    });

    // АВТОСОХРАНЕНИЕ: Слушаем изменения в полях и сразу записываем в память
    keys.forEach(key => {
        const element = data[key];
        const elementTagName = element.tagName.toLowerCase();

        // Определяем тип события
        const eventType = (elementTagName === 'select' || element.type === 'checkbox') ? 'change' : 'input';

        element.addEventListener(eventType, async () => {
            const currentStorage = storage_get();
            if (currentStorage && currentStorage.local) {
                const elementKey = element.id;

                // Если элемент — чекбокс, сохраняем его состояние (true/false), иначе — строку текста
                const value = element.type === 'checkbox' ? element.checked : element.value;

                await new Promise((resolve) => {
                    currentStorage.local.set({[elementKey]: value}, resolve);
                });
            }
        });
    });

    const sendMessageOutBtn = document.getElementById('sendMessageOut');
    const testMessageOutInput = document.getElementById('testMessageOut');

    if (sendMessageOutBtn && testMessageOutInput) {
        sendMessageOutBtn.addEventListener('click', async () => {
            const currentStorage = storage_get();
            if (!currentStorage) return;

            const text = testMessageOutInput.value ? testMessageOutInput.value.trim() : "";
            if (!text) return; // Игнорируем пустые сообщения

            // Считываем текущую актуальную очередь, чтобы не затереть параллельные данные
            const result = await currentStorage.local.get('historyMessagesOut');
            const historyMessagesOut = result.historyMessagesOut || [];

            // Добавляем новое сообщение в конец очереди массива
            historyMessagesOut.push(text);

            // Сохраняем обновленный массив в хранилище расширения
            await currentStorage.local.set({historyMessagesOut: historyMessagesOut});
            console.log("✈️ Сообщение добавлено в очередь отправки:", text);
        });
    }

    // Находим активную вкладку и внедряем туда наш контент-скрипт
    const tabsApi = typeof chrome !== 'undefined' && chrome.tabs ? chrome.tabs : browser.tabs;
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


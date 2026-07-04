const runtimeApi = typeof chrome !== 'undefined' && chrome.runtime ? chrome.runtime : browser.runtime;
const actionApi = typeof chrome !== 'undefined' && chrome.action ? chrome.action : browser.action;
const scriptingApi = typeof chrome !== 'undefined' && chrome.scripting ? chrome.scripting : browser.scripting;
const tabsApi = typeof chrome !== 'undefined' && chrome.tabs ? chrome.tabs : browser.tabs;
const storageApi = typeof chrome !== 'undefined' && chrome.storage ? chrome.storage.local : (browser.storage ? browser.storage.local : null);
const windowsApi = typeof chrome !== 'undefined' && chrome.windows ? chrome.windows : browser.windows;

if (runtimeApi && runtimeApi.onInstalled) {
    runtimeApi.onInstalled.addListener(() => {
        console.log("[Background] Extension installed or reloaded. Resetting pluginEnabled state for all tabs.");
        if (storageApi) {
            storageApi.get(null, (items) => {
                const keysToReset = {};
                for (const key in items) {
                    if (key.endsWith('_pluginEnabled')) {
                        keysToReset[key] = false;
                    }
                }
                if (Object.keys(keysToReset).length > 0) {
                    storageApi.set(keysToReset, () => {
                        console.log("[Background] Reset pluginEnabled state to false for keys:", Object.keys(keysToReset));
                    });
                }
            });
        }
    });
}

if (actionApi && scriptingApi) {
    actionApi.onClicked.addListener((tab) => {
        scriptingApi.executeScript({
            target: { tabId: tab.id },
            files: ["content.js"]
        });
    });
}

if (runtimeApi && runtimeApi.onMessage) {
    runtimeApi.onMessage.addListener((message, sender, sendResponse) => {
        if (message && message.action === "getTabId") {
            sendResponse({ tabId: sender.tab ? sender.tab.id : null });
            return true; // Держим соединение открытым для асинхронного ответа
        }
    });
}

// Отслеживание изменения тайтлов неактивных вкладок
if (tabsApi && tabsApi.onUpdated) {
    tabsApi.onUpdated.addListener((tabId, changeInfo, tab) => {
        // Проверяем, изменился ли тайтл вкладки
        if (changeInfo.title) {
            // Проверяем, что вкладка в данный момент неактивна
            if (tab && !tab.active) {
                const pluginEnabledKey = `tab_${tabId}_pluginEnabled`;
                if (storageApi) {
                    storageApi.get(pluginEnabledKey, (result) => {
                        const isEnabled = result && result[pluginEnabledKey];
                        if (isEnabled === true) {
                            console.log(`[Background] Обнаружено изменение тайтла на неактивной вкладке ${tabId}: "${changeInfo.title}". Переключаемся...`);
                            tabsApi.update(tabId, { active: true });
                            if (tab.windowId && windowsApi) {
                                windowsApi.update(tab.windowId, { focused: true });
                            }
                        }
                    });
                }
            }
        }
    });
}
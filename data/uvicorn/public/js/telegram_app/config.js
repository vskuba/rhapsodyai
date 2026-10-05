// Конфигурационные переменные для Telegram Mini App
// Загружаются из API /telegram-app/config
//
// Не из `/api/setting/config`: тот закрыт правом роли, а у Mini App своя авторизация —
// в сессии только `telegram_owner_id`. Пока запрос шёл туда, он всегда получал
// «Not authenticated», `_config` кэшировался пустым (см. `_fetchConfig`) и оставался
// таким до перезагрузки страницы — то есть конфиг не работал ни разу.

let _config = null;
let _loadPromise = null;

/**
 * Загрузить конфигурацию из API
 * @returns {Promise<Object>} Конфигурационный объект
 */
export async function loadConfig() {
    if (_config) return _config;
    if (_loadPromise) return _loadPromise;

    _loadPromise = _fetchConfig();
    return _loadPromise;
}

/**
 * Получить значение конфигурации
 * @param {string} key - Ключ переменной
 * @param {string} [defaultValue=''] - Значение по умолчанию
 * @returns {string} Значение переменной
 */
export function getConfig(key, defaultValue = '') {
    return _config?.[key] ?? defaultValue;
}

/**
 * Проверить, загрузилась ли конфигурация
 * @returns {boolean}
 */
export function isConfigLoaded() {
    return _config !== null;
}

/**
 * Сбросить конфигурацию (для тестирования)
 */
export function resetConfig() {
    _config = null;
    _loadPromise = null;
}

/**
 * Получить все конфигурационные значения
 * @returns {Object}
 */
export function getAllConfig() {
    return { ...(_config || {}) };
}

// Внутренняя функция загрузки
async function _fetchConfig() {
    try {
        const response = await fetch('/telegram-app/config');
        // Отказ (нет сессии, сервер перезапускается) — это не «конфига нет», а «пока
        // не знаем». Кэшировать такой ответ нельзя: `_config` живёт до перезагрузки
        // страницы, и одна неудачная попытка навсегда оставила бы приложение с пустыми
        // значениями. Поэтому на ошибке ничего не запоминаем — следующий вызов
        // попробует снова.
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        _config = data.result || {};
    } catch (e) {
        console.error('[Config] Ошибка загрузки конфигурации:', e);
        _loadPromise = null;
        return {};
    } finally {
        _loadPromise = null;
    }
    return _config;
}

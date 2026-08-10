// Конфигурационные переменные для Telegram Mini App
// Загружаются из API /setting/config

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
        const response = await fetch('/setting/config');
        const data = await response.json();
        _config = data.result || {};
    } catch (e) {
        console.error('[Config] Ошибка загрузки конфигурации:', e);
        _config = {};
    } finally {
        _loadPromise = null;
    }
    return _config;
}

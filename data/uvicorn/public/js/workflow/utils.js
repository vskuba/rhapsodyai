// Чистые хелперы редактора workflow

import {state} from './state.js';

export function parseMetadata(metadataFieldValue) {
    if (!metadataFieldValue) return {};
    if (typeof metadataFieldValue !== 'string') return metadataFieldValue;

    try {
        // Пробуем распарсить напрямую
        return JSON.parse(metadataFieldValue);
    } catch (e) {
        try {
            // Если упало, лечим неэкранированные управляющие символы (переносы строк, табы)
            let fixedStr = metadataFieldValue
                .replace(/[\n\u000a]/g, '\\n')
                .replace(/[\r\u000d]/g, '\\r')
                .replace(/[\t\u0009]/g, '\\t');

            return JSON.parse(fixedStr);
        } catch (innerErr) {
            console.warn("Критический сбой JSON. parse не справился, применен фоллбек {}:", innerErr);
            return {}; // Полный фоллбек, гарантирующий, что интерфейс не упадет
        }
    }
}

// Очистка текста для label mermaid: кавычки и спецсимволы ломают синтаксис диаграммы
export function graphLabelEscape(text) {
    return String(text || '').replace(/["`#;]/g, "'").replace(/\s+/g, ' ').trim();
}

// Извлекает выходящие ключи инструмента по его названию (структура args.output).
// Список инструментов приходит параметром: у трассы прогона (`/admin/workflow_trace`)
// он свой, а не глобальный стейт редактора.
export function getToolOutputKeys(toolName, tools = state.allAvailableTools) {
    const tool = (tools || []).find(t => String(t.name) === String(toolName));
    if (!tool) return [];

    const argsObj = parseMetadata(tool.args);
    if (!argsObj || !argsObj.output) return [];

    const output = argsObj.output;
    if (typeof output === 'object') {
        if (output.keys) return Object.keys(output.keys);
        if (output.type) return [output.type];
        return Object.keys(output);
    }
    if (typeof output === 'string') return [output];
    return [];
}

// Ключ выбранной вкладки. ⚠ `sessionStorage`, а не `localStorage`: выбор живёт
// столько же, сколько и выбранный workflow (он лежит там же), и вкладка, открытая
// неделю назад, не должна встречать человека в новой сессии.
const WORKFLOW_TAB_KEY = 'workflow_selected_view';

// Вкладка, с которой страница открывается, когда ничего не запомнено.
const WORKFLOW_TAB_DEFAULT = 'tabSteps';

/**
 * Переключить вкладку редактора и запомнить выбор на перезагрузку.
 *
 * ⚠⚠ **Единственная дверь к смене вкладки.** Пометить кнопку активной можно и
 * руками — двумя строками, — и так уже было сделано в `graph.js`: щелчок по узлу
 * графа уводил на «Шаги» в обход. Пока запоминания не было, разницы не
 * чувствовалось; теперь такой обход **молча теряет** выбор, и страница после
 * перезагрузки открывается не там, где человек её оставил.
 *
 * @param {string} tabId id кнопки вкладки: tabSteps, tabSettings, tabGraph.
 */
export function activateTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

    const tab = document.getElementById(tabId);
    if (!tab) return;

    tab.classList.add('active');
    sessionStorage.setItem(WORKFLOW_TAB_KEY, tabId);
}

/**
 * Вкладка, на которой страницу оставили в прошлый раз.
 *
 * ⚠ Читать её нужно **до** того, как откроется workflow: открытие показывает
 * «Шаги» и тем самым перезаписывает память. Иначе восстанавливать будет нечего —
 * в хранилище уже будет лежать `tabSteps`.
 *
 * @returns {string} id кнопки; `tabSteps`, если ничего не запомнено.
 */
export function savedTab() {
    const got = sessionStorage.getItem(WORKFLOW_TAB_KEY);

    return document.getElementById(got) ? got : WORKFLOW_TAB_DEFAULT;
}

// Позиция вставки при drag-and-drop шагов
export function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.step-item-block:not(.dragging)')];
    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) return {offset: offset, element: child};
        else return closest;
    }, {offset: Number.NEGATIVE_INFINITY}).element;
}

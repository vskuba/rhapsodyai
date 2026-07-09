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

// Извлекает выходящие ключи инструмента по его названию (из state.allAvailableTools, структура args.output)
export function getToolOutputKeys(toolName) {
    const tool = state.allAvailableTools.find(t => String(t.name) === String(toolName));
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

// Чистые хелперы редактора workflow.
//
// ⚠ Модуль ничего не импортирует: его тянет к себе `variable-group.js`, а тот
// обязан оставаться чистым — стейт страницы сюда заводить нельзя.

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

/**
 * Идентификатор workflow, открытого в редакторе, — из скрытой закладки страницы.
 *
 * ## ⚠⚠ Одна дверь к одному вопросу
 *
 * `document.getElementById('workflowId').value` стоял на странице тринадцатью
 * копиями по пяти модулям, и часть из них — без `?.`: на странице без закладки
 * такой вызов ронял обработчик, а соседний рядом отдавал `undefined` и уходил
 * строить `/workflow/undefined/steps`. Теперь ответ один и он пустая строка,
 * а уйти по ней молча — дело зовущего: `if (!workflowId) return;`.
 *
 * ⚠ Наружу отдаётся **значение**, не элемент. Двум местам нужен сам узел —
 * `fillWorkflowForm` и сброс формы в `main.js` пишут в него, — и они спрашивают
 * DOM сами: это запись, а не вопрос «какой workflow открыт».
 *
 * ⚠ Живёт здесь, а не в `variable-undefined.js`, где появилось впервые: тот
 * модуль про сеть и кэш индекса, а «какой workflow открыт» — вопрос страницы,
 * и спрашивают его те, кто про индекс не знает вовсе.
 *
 * @returns {string} id закладки; пустая строка, если закладки на странице нет.
 */
export function editorWorkflowId() {
    return document.getElementById('workflowId')?.value || '';
}

/**
 * Метка времени для имени файла — в UTC.
 *
 * ⚠ Имя файла пересылают между машинами, и местный пояс в нём только путает:
 * два снимка одного часа с разных установок выглядели бы разными.
 *
 * @returns {string} `2026-10-13_11:22:33`.
 */
export function fileStamp() {
    return new Date().toISOString().replace('T', '_').slice(0, 19);
}

/**
 * Отдать объект человеку файлом: Blob, щелчок по ссылке, освобождение ссылки.
 *
 * ⚠ Живёт здесь, а не у того, кто первым это написал (`main.js`, экспорт
 * workflow): кнопок «скачать файлом» на странице уже две — узел и темы, — и
 * вторая копия этих восьми строк разошлась бы с первой на первой же правке
 * (тип содержимого, отступ в JSON, забытый `revokeObjectURL`).
 *
 * @param {object} payload что сохраняем.
 * @param {string} name имя файла.
 */
export function fileDownloadJson(payload, name) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = name;
    link.click();
    URL.revokeObjectURL(link.href);
}

/**
 * Перед кем встанет перетаскиваемое: ближайший сосед, чья середина ниже курсора.
 *
 * ⚠ Отбор доводом, а умолчание — шаги: тащат на этой странице и шаги, и темы
 * дерева «Topic & Action». Арифметика у них одна до знака, и вторая копия
 * разошлась бы с этой молча — перетаскивание просто стало бы «мазать» на
 * границе элементов.
 *
 * @param {HTMLElement} container где ищем соседей.
 * @param {number} y курсор по вертикали (`clientY`).
 * @param {string} selector кого считать соседом; перетаскиваемый исключается
 *     самим селектором (`:not(.dragging)`).
 */
export function getDragAfterElement(container, y, selector = '.step-item-block:not(.dragging)') {
    const draggableElements = [...container.querySelectorAll(selector)];
    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) return {offset: offset, element: child};
        else return closest;
    }, {offset: Number.NEGATIVE_INFINITY}).element;
}

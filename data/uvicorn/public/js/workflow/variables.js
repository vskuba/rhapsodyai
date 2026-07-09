// Панель переменных редактора workflow: группы/аккордеон, подсветки использования,
// tool/workflow-подсветки выбранного шага, входящие переменные формы настроек

import {getData, putData, postData, deleteData} from '../api.js';
import {showNotification} from '../notification.js';
import {state} from './state.js';
import {parseMetadata, getToolOutputKeys} from './utils.js';

/**
 * Собирает имена всех переменных, используемых в шагах workflow,
 * и сохраняет их в state.allUsedVariables.
 */
export function extractVariablesFromSteps(steps) {
    const usedVariables = new Set();
    const stepsArray = Array.isArray(steps) ? steps : [];

    // Вхождения по паттерну %varname% в произвольном тексте
    const collectFromText = (text) => {
        if (typeof text !== 'string') return;
        for (const match of text.matchAll(/%([a-zA-Z_][a-zA-Z0-9_]*)%/g)) {
            usedVariables.add(match[1]);
        }
    };

    stepsArray.forEach(step => {
        const metadata = parseMetadata(step.metadata);
        const typeName = state.allWorkflowStepsType[step.type_id]?.name;

        // return_response_llm / return_response_text / llm_to_json: %varname% в prompt_user
        if (['return_response_llm', 'return_response_text', 'llm_to_json'].includes(typeName)) {
            collectFromText(metadata.prompt_user);
        }

        // llm_to_json: массив объектов с ключом "variable"
        if (typeName === 'llm_to_json' && Array.isArray(metadata.llm_to_json_variable)) {
            metadata.llm_to_json_variable.forEach(item => {
                if (item?.variable) usedVariables.add(item.variable);
            });
        }

        // tool_invoke: значения inputs_map — имена переменных
        if (typeName === 'tool_invoke') {
            const inputsMap = metadata.inputs_map || metadata.tool_invoke?.inputs_map;
            if (inputsMap && typeof inputsMap === 'object') {
                Object.values(inputsMap).forEach(value => {
                    if (typeof value === 'string' && value) usedVariables.add(value);
                });
            }
        }

        // variable_conversion: %varname% в поле "text" каждого объекта
        if (typeName === 'variable_conversion' && Array.isArray(metadata.variable_conversion)) {
            metadata.variable_conversion.forEach(item => collectFromText(item?.text));
        }

        // Переходы (у всех типов шагов): ключ "variable" в условиях
        ['transitions_before', 'transitions_after'].forEach(key => {
            if (Array.isArray(metadata[key])) {
                metadata[key].forEach(transition => {
                    if (transition?.variable) usedVariables.add(transition.variable);
                });
            }
        });
    });

    state.allUsedVariables = Array.from(usedVariables);
    markUnusedWorkflowVariables();
}

/**
 * Помечает переменные группы "Переменные workflow", не используемые ни в одном шаге.
 */
function markUnusedWorkflowVariables() {
    document.querySelectorAll('.variables-accordion-section[data-key="workflow"] .variable-item')
        .forEach(item => {
            item.classList.toggle('unused-variable', !state.allUsedVariables.includes(item.dataset.name));
        });
}


export async function loadWorkflowVariables(workflowId) {
    const container = document.getElementById('variablesContainer');
    if (!container) return;

    try {
        // 1. Делаем асинхронный запрос к выделенному эндпоинту переменных
        const data = await getData(`/workflow/${workflowId}/variables`);

        // 2. Сохраняем полученные переменные в глобальные стейты модуля.
        // Это позволит функциям генерации полей и автодополнения видеть актуальный список.
        state.allCurrentVariables = data.result || data || [];
        window.allCurrentVariables = state.allCurrentVariables; // Дублируем для генератора динамических полей

        // 3. Отрисовываем переменные в интерфейсе
        renderWorkflowVariables(state.allCurrentVariables);

        // 4. Отрисовываем входящие переменные в форме настроек workflow
        renderInputVariables();

    } catch (e) {
        console.error("Ошибка загрузки переменных:", e);
        state.allCurrentVariables = [];
        window.allCurrentVariables = [];
        container.innerHTML = ''; // Очищаем контейнер при ошибке
        renderInputVariables();
    }
}

// ===== Входящие переменные (type === 'input') в форме "Редактирование задачи" =====

function renderInputVariables() {
    const container = document.getElementById('inputVariablesContainer');
    if (!container) return;
    container.innerHTML = '';

    const variablesArray = Array.isArray(state.allCurrentVariables) ? state.allCurrentVariables : [];
    variablesArray.filter(v => v.type === 'input').forEach(variable => {
        createInputVariableRow(variable);
    });
}

function createInputVariableRow(variable = null) {
    const container = document.getElementById('inputVariablesContainer');
    if (!container) return;

    const row = document.createElement('div');
    row.className = 'variable-row input-variable-row';
    if (variable) {
        row.dataset.id = variable.id;
        // Исходные значения — чтобы при сохранении отправлять PUT только для измененных строк
        row.dataset.originalName = variable.name;
        row.dataset.originalDefault = variable.default ?? '';
    }

    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'form-control var-key';
    nameInput.placeholder = 'Имя переменной';
    nameInput.value = variable ? variable.name : '';

    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'form-control var-value';
    valInput.placeholder = 'Значение по умолчанию';
    valInput.value = variable ? (variable.default ?? '') : '';

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn-del-var';
    delBtn.title = 'Удалить переменную';
    delBtn.innerHTML = '&times;';
    delBtn.onclick = async () => {
        // Новая (еще не сохраненная) строка — просто убираем из DOM
        if (!variable) {
            row.remove();
            return;
        }

        const workflowId = document.getElementById('workflowId')?.value;
        if (!confirm(`Удалить переменную "${variable.name}"?`)) return;

        try {
            await deleteData(`/workflow/${workflowId}/variable/${variable.id}`);
            showNotification('Переменная успешно удалена', 'success');
            await loadWorkflowVariables(workflowId);
        } catch (err) {
            console.error("Ошибка удаления переменной:", err);
            showNotification(`Ошибка удаления: ${err.message}`, 'error');
        }
    };

    row.append(nameInput, valInput, delBtn);
    container.appendChild(row);
}

/**
 * Сохраняет входящие переменные: новые строки (без data-id) создаются через POST
 * с type='input', измененные существующие обновляются через PUT.
 */
export async function saveInputVariables(workflowId) {
    const rows = document.querySelectorAll('#inputVariablesContainer .input-variable-row');

    for (const row of rows) {
        const name = row.querySelector('.var-key').value.trim();
        const value = row.querySelector('.var-value').value.trim();
        const variableId = row.dataset.id;

        if (!name) continue;

        if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name)) {
            showNotification(`Недопустимое имя переменной: "${name}"`, 'error');
            continue;
        }

        if (variableId) {
            // Существующая переменная: обновляем только если имя или значение изменились
            const isChanged = name !== row.dataset.originalName
                || value !== (row.dataset.originalDefault || '');

            if (isChanged) {
                await putData(`/agent_workflow_variable/${variableId}`, {
                    name: name,
                    "default": value === '' ? null : value
                });
            }
        } else {
            await postData(`/workflow/${workflowId}/variable`, {
                name: name,
                "default": value === '' ? null : value,
                type: 'input'
            });
        }
    }
}


// Распределяет переменные по группам (общие / ноды / tool / workflow) — единая логика
// для списка #variablesContainer и селектов переменных
function groupWorkflowVariables(variables) {
    const variablesArray = Array.isArray(variables) ? variables : [];
    const commonGroup = [];
    const nodeGroup = [];
    const workflowGroup = [];
    const toolGroup = [];
    const inputGroup = [];

    variablesArray.forEach(variable => {
        if (variable.type === 'input') {
            inputGroup.push(variable);
        } else if (variable.type === 'global') {
            commonGroup.push(variable);
        } else if (variable.type === 'node') {
            nodeGroup.push(variable);
        } else {
            workflowGroup.push(variable);
        }
    });

    // Динамические переменные из инструментов:
    // имена формируются по шаблону '{tool_name}_{step_id}_result_{output_key}' — ID шага
    // делает имя уникальным при повторных вызовах одного инструмента
    const foundToolVariables = new Set();
    if (typeof state.allCurrentStepsData !== 'undefined' && Array.isArray(state.allCurrentStepsData)) {
        state.allCurrentStepsData.forEach(step => {
            let metadata = parseMetadata(step.metadata);
            if (metadata && metadata.tool_invoke && metadata.tool_invoke.tool_name) {
                const tool_name = metadata.tool_invoke.tool_name;
                getToolOutputKeys(tool_name).forEach(key => {
                    foundToolVariables.add(tool_name + '_' + step.id + '_result_' + key);
                });
            }
            // Результат шага workflow_invoke: {имя_sub_workflow}_{step_id}_result_str
            if (metadata && metadata.workflow_invoke && metadata.workflow_invoke.workflow_id) {
                const wf = (state.allWorkflows || []).find(w => String(w.id) === String(metadata.workflow_invoke.workflow_id));
                const childName = wf ? wf.name : ('workflow_' + metadata.workflow_invoke.workflow_id);
                foundToolVariables.add(childName + '_' + step.id + '_result_str');
            }
        });
    }

    foundToolVariables.forEach(varName => {
        toolGroup.push({
            id: -2, // Отрицательный ID чтобы не появилась кнопка удаления
            name: varName,
            default: null,
        });
    });

    return {commonGroup, nodeGroup, workflowGroup, toolGroup, inputGroup};
}

// Порядок и названия групп — единые для списка #variablesContainer и селектов переменных
function workflowVariableSections(groups) {
    return [
        ['📥 Входящие переменные', groups.inputGroup, 'input'],
        ['🇬 Глобальные переменные', groups.commonGroup, 'common'],
        ['🇳 Публичные переменные', groups.nodeGroup, 'node'],
        ['⚙️ Tool переменные', groups.toolGroup, 'tool'],
        ['🇼 Workflow переменные ', groups.workflowGroup, 'workflow'],
    ];
}

// Заполняет селект опциями переменных из window.allCurrentVariables,
// сгруппированными через optgroup так же, как в списке #variablesContainer
export function fillVariablesSelectOptions(sel, selectedVal = '', placeholder = '-- Переменная --') {
    sel.innerHTML = '<option value="">' + placeholder + '</option>';

    const groups = groupWorkflowVariables(window.allCurrentVariables);
    workflowVariableSections(groups).forEach(([label, items]) => {
        if (items.length === 0) return;
        const optgroup = document.createElement('optgroup');
        optgroup.label = label;
        items.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.name;
            opt.textContent = '%' + v.name + '%';
            if (v.name === selectedVal) opt.selected = true;
            optgroup.appendChild(opt);
        });
        sel.appendChild(optgroup);
    });
}

export function renderWorkflowVariables(variables) {
    const container = document.getElementById('variablesContainer');
    if (!container) return;
    container.innerHTML = '';

    const variablesArray = Array.isArray(variables) ? variables : [];

    if (variablesArray.length === 0) {
        container.innerHTML = '<div class="empty-text">Нет переменных</div>';
        return;
    }

    // 1. Распределяем переменные по группам
    const {commonGroup, nodeGroup, workflowGroup, toolGroup, inputGroup} = groupWorkflowVariables(variablesArray);

    // 2. Функция создания DOM-элемента отдельной переменной
    function createVariableElement(variable) {
        const div = document.createElement('div');
        div.className = 'variable-item';
        if (variable.type === 'global') {
            div.className += ' variable-item-common';
        }
        if (variable.id === -2) {
            div.className += ' variable-item-tool';
        }
        if (variable.type === 'node') {
            div.className += ' variable-item-node';
        }
        if (variable.type === 'input') {
            div.className += ' variable-item-input';
        }
        div.setAttribute('data-name', variable.name);
        div.setAttribute('data-id', variable.id);

        // Имя переменной
        const nameSpan = document.createElement('span');
        nameSpan.className = 'variable-name';
        nameSpan.title = 'Нажмите, чтобы скопировать';
        const varText = `%${variable.name}%`;
        nameSpan.textContent = varText;
        nameSpan.onclick = async () => {
            try {
                await navigator.clipboard.writeText(varText);
                showNotification(`Переменная ${varText} скопирована в буфер`, 'success');
            } catch (err) {
                showNotification('Не удалось скопировать переменную', 'error');
            }
        };
        div.appendChild(nameSpan);

        // Проверяем наличие значения по умолчанию
        if (variable.default !== undefined && variable.default !== null && variable.default !== '') {
            div.classList.add('has-default');

            const badgeSpan = document.createElement('span');
            badgeSpan.className = 'variable-badge';
            badgeSpan.title = `${variable.default}`;
            badgeSpan.textContent = String(variable.default).slice(0, 10);

            div.appendChild(badgeSpan);
        }

        // Кнопка удаления переменной.
        // Публичные (node) и глобальные переменные живут в других таблицах —
        // из редактора workflow их удалять нельзя
        if (variable.id > 0 && variable.type !== 'node' && variable.type !== 'global') {
            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'btn-delete-var';
            deleteBtn.title = 'Удалить переменную';
            deleteBtn.innerHTML = '&times;';

            deleteBtn.onclick = async () => {
                const workflowId = document.getElementById('workflowId')?.value;

                const cleanLocalState = () => {
                    if (typeof state.allCurrentVariables !== 'undefined') {
                        state.allCurrentVariables = state.allCurrentVariables.filter(v => v !== variable);
                    }
                    window.allCurrentVariables = (window.allCurrentVariables || []).filter(v => v !== variable);
                    div.remove();
                    renderWorkflowVariables(typeof state.allCurrentVariables !== 'undefined' ? state.allCurrentVariables : window.allCurrentVariables);
                };

                if (!workflowId) {
                    cleanLocalState();
                    return;
                }

                if (!confirm(`Удалить переменную "${variable.name}"?`)) return;

                try {
                    await deleteData(`/workflow/${workflowId}/variable/${variable.id}`);
                    cleanLocalState();
                    showNotification('Переменная успешно удалена', 'success');
                } catch (e) {
                    console.error("Ошибка при удалении переменной:", e);
                    showNotification(`Ошибка удаления: ${e.message}`, 'error');
                }
            };

            div.appendChild(deleteBtn);
        }

        return div;
    }

    // 3. Функция создания секции аккордеона (классическое поведение)
    function createAccordionSection(title, groupItems, storageKey) {
        const section = document.createElement('div');
        section.className = 'variables-accordion-section';
        section.dataset.key = storageKey;

        // По умолчанию открыта только группа "Переменные workflow"
        if (storageKey === 'workflow') {
            section.classList.add('active');
        }

        const header = document.createElement('div');
        header.className = 'variables-accordion-header';
        header.innerHTML = `<span>${title} (${groupItems.length})</span><span class="arrow">▶</span>`;

        const content = document.createElement('div');
        content.className = 'variables-accordion-content';

        if (groupItems.length === 0) {
            content.innerHTML = '<div class="empty-text" style="font-size: 11px; padding: 4px; color: #888;">Нет переменных</div>';
        } else {
            groupItems.forEach(item => {
                content.appendChild(createVariableElement(item));
            });
        }

        header.onclick = () => {
            const isActive = section.classList.contains('active');

            // Схлопываем все группы
            const allSections = container.querySelectorAll('.variables-accordion-section');
            allSections.forEach(s => s.classList.remove('active'));

            // Раскрываем текущую, только если она была закрыта
            if (!isActive) {
                section.classList.add('active');
            }
        };

        section.append(header, content);
        return section;
    }

    // 4. Добавляем секции аккордеона в контейнер
    workflowVariableSections({commonGroup, nodeGroup, workflowGroup, toolGroup, inputGroup}).forEach(([title, groupItems, storageKey]) => {
        container.appendChild(createAccordionSection(title, groupItems, storageKey));
    });

    // 5. Помечаем неиспользуемые переменные workflow (если шаги уже загружены)
    markUnusedWorkflowVariables();

    // 6. Восстанавливаем подсветку переменных активного шага после перерисовки
    const activeStepBlock = document.querySelector('.step-item-block.active');
    if (activeStepBlock && Array.isArray(state.allCurrentStepsData)) {
        const activeStep = state.allCurrentStepsData.find(s => String(s.id) === String(activeStepBlock.dataset.id));
        if (activeStep) {
            highlightStepToolVariables(activeStep);
            highlightStepWorkflowVariables(activeStep);
        }
    }
}

async function addWorkflowVariable() {
    const workflowId = document.getElementById('workflowId').value;
    const newVariableNameInput = document.getElementById('newVariableName');
    const newVariableValueInput = document.getElementById('newVariableValue');

    if (!newVariableNameInput) return;

    const varName = newVariableNameInput.value.trim();
    const varValue = newVariableValueInput.value.trim();

    // 1. Клиентская валидация перед отправкой
    if (!varName) {
        showNotification('Имя переменной не может быть пустым', 'error');
        return;
    }

    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(varName)) {
        showNotification('Недопустимый формат (разрешены буквы, цифры и _ начиная с буквы)', 'error');
        return;
    }

    // Если workflow еще не сохранен (нет ID), мы не можем отправить запрос на бэкенд
    if (!workflowId) {
        showNotification('Сначала сохраните workflow, чтобы добавлять переменные', 'warning');
        return;
    }

    // Проверяем дубликаты локально по свойству .name внутри объектов стейта
    const isDuplicate = state.allCurrentVariables.some(v => v.name === varName);
    if (isDuplicate) {
        showNotification('Такая переменная уже существует в этом workflow', 'error');
        return;
    }

    try {
        // 2. Отправка POST-запроса на бэкенд
        // Передаем payload (название поля 'name' подстройте под требования вашего API, если оно отличается)
        await postData(`/workflow/${workflowId}/variable`, {
            name: varName,
            "default": varValue === '' ? null : varValue
        });

        showNotification('Переменная успешно добавлена', 'success');

        // 3. Очищаем инпут ввода
        newVariableNameInput.value = '';
        newVariableValueInput.value = '';
        newVariableNameInput.focus();

        // 4. Перезагружаем список переменных с бэкенда для синхронизации UI
        await loadWorkflowVariables(workflowId);

    } catch (e) {
        console.error("Ошибка при добавлении переменной:", e);
        showNotification(`Ошибка добавления: ${e.message}`, 'error');
    }
}


/**
 * При выборе шага tool_invoke раскрывает аккордеон "Tool переменные" и подсвечивает
 * переменные результата этого шага ({tool_name}_{step_id}_result_*).
 * Для остальных шагов просто снимает подсветку.
 */
export function highlightStepToolVariables(step) {
    const container = document.getElementById('variablesContainer');
    if (!container) return;

    // Снимаем прошлую подсветку
    container.querySelectorAll('.variable-item.tool-var-highlight')
        .forEach(el => el.classList.remove('tool-var-highlight'));

    const metadata = parseMetadata(step.metadata);
    const typeName = state.allWorkflowStepsType[step.type_id]?.name;

    // Префикс переменных результата: tool_invoke — по имени инструмента,
    // workflow_invoke — по имени вызываемого sub-workflow
    let prefix = null;
    if (typeName === 'tool_invoke' && metadata?.tool_invoke?.tool_name) {
        prefix = `${metadata.tool_invoke.tool_name}_${step.id}_result_`;
    } else if (typeName === 'workflow_invoke' && metadata?.workflow_invoke?.workflow_id) {
        const wf = (state.allWorkflows || []).find(w => String(w.id) === String(metadata.workflow_invoke.workflow_id));
        const childName = wf ? wf.name : ('workflow_' + metadata.workflow_invoke.workflow_id);
        prefix = `${childName}_${step.id}_result_`;
    }
    if (!prefix) return;

    const toolSection = container.querySelector('.variables-accordion-section[data-key="tool"]');
    if (!toolSection) return;
    const matched = [...toolSection.querySelectorAll('.variable-item')]
        .filter(el => (el.dataset.name || '').startsWith(prefix));
    if (matched.length === 0) return;

    // Раскрываем группу tool (сворачиваем остальные — стандартное поведение аккордеона)
    container.querySelectorAll('.variables-accordion-section').forEach(s => s.classList.remove('active'));
    toolSection.classList.add('active');

    matched.forEach(el => el.classList.add('tool-var-highlight'));
}

/**
 * При выборе шага "Переменные" (variable_conversion) раскрывает группу "Переменные workflow"
 * и подсвечивает переменные, в которые пишет этот шаг. Имена берутся из значений селектов
 * формы шага справа (#dynamicStepFieldsContainer).
 * Для остальных шагов просто снимает подсветку.
 */
export function highlightStepWorkflowVariables(step) {
    const container = document.getElementById('variablesContainer');
    if (!container) return;

    // Снимаем прошлую подсветку
    container.querySelectorAll('.variable-item.workflow-var-highlight')
        .forEach(el => el.classList.remove('workflow-var-highlight'));

    if (state.allWorkflowStepsType[step.type_id]?.name !== 'variable_conversion') return;

    // Значения селектов в форме шага — имена переменных, в которые идет запись
    const fieldsContainer = document.getElementById('dynamicStepFieldsContainer');
    if (!fieldsContainer) return;

    const variableNames = new Set(
        [...fieldsContainer.querySelectorAll('select')]
            .map(sel => (sel.value || '').trim())
            .filter(Boolean)
    );
    if (variableNames.size === 0) return;

    const workflowSection = container.querySelector('.variables-accordion-section[data-key="workflow"]');
    if (!workflowSection) return;

    const matched = [...workflowSection.querySelectorAll('.variable-item')]
        .filter(el => variableNames.has(el.dataset.name || ''));
    if (matched.length === 0) return;

    // Раскрываем группу workflow (сворачиваем остальные — стандартное поведение аккордеона)
    container.querySelectorAll('.variables-accordion-section').forEach(s => s.classList.remove('active'));
    workflowSection.classList.add('active');

    matched.forEach(el => el.classList.add('workflow-var-highlight'));
}

// Живое обновление подсветки при смене переменной в селектах формы шага
document.getElementById('dynamicStepFieldsContainer')?.addEventListener('change', (e) => {
    if (e.target.tagName !== 'SELECT') return;
    const activeStepBlock = document.querySelector('.step-item-block.active');
    if (!activeStepBlock || !Array.isArray(state.allCurrentStepsData)) return;
    const activeStep = state.allCurrentStepsData.find(s => String(s.id) === String(activeStepBlock.dataset.id));
    if (activeStep) highlightStepWorkflowVariables(activeStep);
});


export function initVariablesHandlers() {
    const addVariableBtn = document.getElementById('addVariableBtn');
    const newVariableNameInput = document.getElementById('newVariableName');

    if (!addVariableBtn || !newVariableNameInput) return;

    // Клик по кнопке "+ Добавить"
    addVariableBtn.onclick = async () => {
        await addWorkflowVariable();
    };

    // Нажатие Enter внутри инпута ввода
    newVariableNameInput.onkeydown = async (e) => {
        if (e.key === 'Enter') {
            e.preventDefault(); // Запрещаем сабмит основной формы workflowForm
            await addWorkflowVariable();
        }
    };

    // Кнопка "+ Добавить переменную" в блоке входящих переменных (настройки workflow)
    const addInputVariableBtn = document.getElementById('addInputVariableBtn');
    if (addInputVariableBtn) {
        addInputVariableBtn.onclick = () => createInputVariableRow();
    }
}

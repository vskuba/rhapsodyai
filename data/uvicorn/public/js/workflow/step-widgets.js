// Динамические поля формы шага по его типу: textarea/checkbox и виджеты
// widget_json_variable, widget_tool_invoke, widget_variable_conversion

import {getData} from '../api.js';
import {showNotification} from '../notification.js';
import {state, WORKFLOW_STEP_CONFIG} from './state.js';
import {parseMetadata, getToolOutputKeys} from './utils.js';
import {fillVariablesSelectOptions} from './variables.js';

export function renderCustomStepFields(step, metadata) {
    const container = document.getElementById('dynamicStepFieldsContainer');
    if (!container) return;
    container.innerHTML = '';

    let stepType = state.allWorkflowStepsType[step.type_id];

    // Получаем схему полей для данного типа шага
    const fieldsSchema = WORKFLOW_STEP_CONFIG[stepType.name] || WORKFLOW_STEP_CONFIG['default'];

    fieldsSchema.forEach(field => {
        const fieldWrapper = document.createElement('div');
        fieldWrapper.className = 'form-group';
        fieldWrapper.style = "display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px;";

        if (field.type === 'checkbox') {
            fieldWrapper.style = "display: flex; flex-direction: row;";
        }

        const label = document.createElement('label');
        label.style = "font-size: 12px; font-weight: 600; color: #4a5568;";
        label.textContent = field.label;
        fieldWrapper.appendChild(label);

        // Извлекаем текущее сохраненное значение или берем дефолтное
        const currentValue = metadata[field.key] !== undefined ? metadata[field.key] : (field.default || '');

        let inputElement;

        const saveChanges = (customValue) => {
            let latestMeta = parseMetadata(step.metadata)

            // Записываем значение (для обычных полей берем из инпута, для виджета передаем кастомный JSON)
            const metaKey = field.key;
            if (!metaKey) {
                return;
            }

            if (customValue !== undefined) {
                latestMeta[metaKey] = customValue;
            } else if (inputElement) {
                let value = inputElement.value;
                if (field.type === 'number') {
                    value = parseFloat(value) || 0;
                }
                if (field.type === 'checkbox') {
                    value = inputElement.checked;
                }
                if (typeof value === 'string') {
                    value = value.replace(/"/g, '\"');
                }

                latestMeta[metaKey] = value;
            }

            // Сохраняем обратно в state шага в виде строки JSON
            step.metadata = JSON.stringify(latestMeta);

            // Дублируем в скрытую текстареа
            const stepTextarea = document.getElementById('stepTextarea');
            if (stepTextarea) {
                stepTextarea.value = step.metadata;
            }
        };

        // --- НОВЫЙ ТИП: widget_json_variable ---
        if (field.type === 'widget_json_variable' || field.type === 'widget_variable_conversion') {
            const widgetContainer = document.createElement('div');
            widgetContainer.id = `field_${field.key}`;
            widgetContainer.style = "display: flex; flex-direction: column; gap: 8px; background: #f8fafc; padding: 10px; border: 1px solid #e2e8f0; border-radius: 6px;";

            const rowsContainer = document.createElement('div');
            rowsContainer.className = 'widget-rows-list';
            widgetContainer.appendChild(rowsContainer);

            // Собираем актуальный массив данных из сохраненного JSON (ожидаем массив объектов)
            let savedRows = [];
            if (currentValue) {
                try {
                    savedRows = typeof currentValue === 'string' ? JSON.parse(currentValue) : currentValue;
                } catch (e) {
                    savedRows = [];
                }
            }
            if (!Array.isArray(savedRows)) savedRows = [];

            // Функция сбора данных со всех строк виджета и записи их в metadata
            const collectWidgetData = () => {
                const rows = rowsContainer.querySelectorAll('.widget-row');
                const data = [];
                rows.forEach(row => {
                    const selectEl = row.querySelector('.widget-select');
                    const txtEl = row.querySelector('.widget-textarea');

                    // Безопасное извлечение значения селекта
                    const variableName = selectEl ? selectEl.value : '';
                    const textValue = txtEl ? txtEl.value : '';

                    // Добавляем в массив только если выбрана переменная
                    data.push({
                        variable: variableName,
                        text: textValue
                    });
                });
                saveChanges(data); // Сохраняем массив в metadata
            };

            // Функция создания ОДНОЙ интерактивной строки виджета
            const createWidgetRow = (initialVariable = '', initialText = '') => {
                const row = document.createElement('div');
                row.className = 'widget-row';

                // 1. Создаем селект с переменными, сгруппированными как в #variablesContainer
                const select = document.createElement('select');
                select.className = 'form-control widget-select';
                select.style = "flex: 1; padding: 5px; font-size: 12px;";
                fillVariablesSelectOptions(select, initialVariable, 'Выбрать...');

                // 2. Создаем текстовое поле textarea
                const txt = document.createElement('textarea');
                txt.className = 'form-control widget-textarea';
                txt.placeholder = 'Введите текст...';
                txt.style = "flex: 2; resize: vertical; padding: 5px; font-size: 12px;";
                txt.value = initialText;

                // 3. Кнопка удаления конкретной строки
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'btn-delete-widget-row';
                deleteBtn.type = 'button';
                deleteBtn.innerHTML = '&times;';

                deleteBtn.onclick = () => {
                    row.remove();
                    collectWidgetData();
                };

                // Навешиваем живое автосохранение на изменение полей
                select.onchange = collectWidgetData;
                txt.oninput = collectWidgetData;

                row.appendChild(select);
                row.appendChild(deleteBtn);
                row.appendChild(txt);

                rowsContainer.appendChild(row);
            };

            // Отрисовываем ранее сохраненные строки (если они есть)
            if (savedRows.length > 0) {
                savedRows.forEach(rowData => {
                    createWidgetRow(rowData.variable, rowData.text);
                });
            } else {
                createWidgetRow(); // Если данных нет, создаем одну пустую строку для удобства
            }

            const actionsContainer = document.createElement('div');
            actionsContainer.className = 'widget-actions-row';
            actionsContainer.style = "display: flex; gap: 8px; align-items: center; margin-top: 8px;";

            // 4. Кнопка "+ Add" для добавления новой чистой строки внизу виджета
            const addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'btn-add-widget-row';
            addBtn.textContent = '+ Add';

            addBtn.onclick = () => {
                createWidgetRow(); // Создает пустую строку
                collectWidgetData(); // Обновляет JSON-структуру в метаданных
            };

            actionsContainer.appendChild(addBtn);

            if (field.type === 'widget_json_variable') {
                const refreshPromptBtn = document.createElement('button');
                refreshPromptBtn.type = 'button';
                refreshPromptBtn.className = 'btn-refresh-prompt';
                refreshPromptBtn.textContent = '+ Обновить Prompt';
                refreshPromptBtn.style = "align-self: flex-start; margin-top: 4px; margin-left: 8px; padding: 4px 12px; font-size: 12px; font-weight: 500; background: #3182ce; color: white; border: none; border-radius: 4px; cursor: pointer;";

                refreshPromptBtn.onclick = () => {
                    const targetTextarea = document.getElementById('field_prompt_user') || document.querySelector('[id$="prompt"]');
                    if (!targetTextarea) {
                        showNotification('Целевое поле промпта не найдено на форме', 'error');
                        return;
                    }

                    const rows = rowsContainer.querySelectorAll('.widget-row');
                    let descriptionJsonSchema = "";
                    let exampleJsonSchema = {};

                    rows.forEach(row => {
                        const selectEl = row.querySelector('.widget-select');
                        const txtEl = row.querySelector('.widget-textarea');

                        if (selectEl && selectEl.value) {
                            // Читаем значение напрямую, убирая возможные случайные пробелы
                            let variableName = selectEl.value.trim();
                            let textValue = txtEl ? txtEl.value.trim() : '';

                            if (variableName) {
                                descriptionJsonSchema += `- "${variableName}": ${textValue || 'Without description'}\n`;
                                exampleJsonSchema[variableName] = textValue || "value";
                            }
                        }
                    });

                    if (!descriptionJsonSchema) {
                        showNotification('Нет заполненных переменных для генерации промпта', 'warning');
                        return;
                    }

                    // 3. Формируем новый текст инструкции
                    const systemInstructions = "Please return your response in JSON format. " +
                        "The JSON response must contain follow keys: \n" + descriptionJsonSchema + "\n" +
                        "Example of JSON response:\n" + JSON.stringify(exampleJsonSchema, null, 2);

                    // Маркер-разделитель для безопасного удаления старой схемы
                    const delimiter = "\n\n=== Important information about final response ===";
                    let currentPrompt = targetTextarea.value;

                    // 4. ПРОВЕРКА И ОЧИСТКА:
                    // Если в поле уже есть маркер ИЛИ старый текст инструкции — отсекаем его
                    if (currentPrompt.includes(delimiter)) {
                        // Разделяем строку по маркеру и берем только первую часть (текст пользователя)
                        currentPrompt = currentPrompt.split(delimiter)[0].trim();
                    } else if (currentPrompt.includes("Please return your response in JSON format.")) {
                        // Альтернативный фоллбек: если маркера еще нет, но есть старый текст, отрезаем всё, что идет до него
                        currentPrompt = currentPrompt.split("Please return your response in JSON format.")[0].trim();
                    }

                    // 5. ВСТАВКА ОБНОВЛЕННОГО ТЕКСТА
                    // Если у пользователя был свой текст, добавляем отступ, если поле было пустым — вставляем сразу
                    const separator = currentPrompt ? "\n\n" : "";
                    targetTextarea.value = currentPrompt + separator + "=== Important information about final response ===\n" + systemInstructions;

                    // 6. Триггерим событие сохранения для обновления metadata в стейте шага
                    targetTextarea.dispatchEvent(new Event('input'));

                    showNotification('Промпт успешно обновлен', 'success');
                };

                actionsContainer.appendChild(refreshPromptBtn);
            }

            widgetContainer.appendChild(actionsContainer);

            fieldWrapper.appendChild(widgetContainer);

        } else if (field.type === 'widget_tool_invoke') {
            const toolContainer = document.createElement('div');
            toolContainer.id = `field_${field.key}`;
            toolContainer.style = "display: flex; flex-direction: column; gap: 12px; background: #f8fafc; padding: 12px; border: 1px solid #e2e8f0; border-radius: 6px;";

            // 1. Селект выбора самого инструмента
            const selectElement = document.createElement('select');
            selectElement.className = 'form-control tool-select';
            selectElement.style = "width: 100%; padding: 6px; font-size: 13px; height: 36px; font-weight: 500;";
            selectElement.innerHTML = '<option value="">-- Выберите инструмент --</option>';

            // 2. Блок описания
            const descContainer = document.createElement('div');
            descContainer.className = 'tool-desc-text';
            descContainer.style = "font-size: 11px; color: #64748b; font-style: italic; display: none; background: #fff; padding: 6px 10px; border: 1px dashed #cbd5e0; border-radius: 4px;";

            // 3. Блок интерактивного маппинга аргументов
            const mappingContainer = document.createElement('div');
            mappingContainer.className = 'tool-mapping-block';
            mappingContainer.style = "display: flex; flex-direction: column; gap: 10px; margin-top: 5px;";

            // Группировка инструментов по optgroup
            const groups = {};
            state.allAvailableTools.forEach(t => {
                const groupName = t.group_name || t.group_id || 'Без группы';
                if (!groups[groupName]) groups[groupName] = [];
                groups[groupName].push(t);
            });

            Object.keys(groups).forEach(groupName => {
                const optgroup = document.createElement('optgroup');
                optgroup.label = groupName;
                groups[groupName].forEach(t => {
                    const option = document.createElement('option');

                    // ВАЖНО: Записываем имя инструмента в качестве value
                    option.value = t.name;
                    option.textContent = t.name;

                    if (currentValue && currentValue.tool_name === t.name) {
                        option.selected = true;
                    }
                    optgroup.appendChild(option);
                });
                selectElement.appendChild(optgroup);
            });

            // Функция сборки и сохранения всего стейта виджета
            const collectToolWidgetData = () => {
                const selectedName = selectElement.value; // Теперь тут лежит имя инструмента
                const inputsMap = {};

                // Собираем Inputs
                mappingContainer.querySelectorAll('.input-map-row').forEach(row => {
                    const varSel = row.querySelector('.map-var-select');
                    const argSel = row.querySelector('.map-arg-select');
                    if (argSel && argSel.value && varSel && varSel.value) {
                        inputsMap[argSel.value] = varSel.value;
                    }
                });

                // Сохраняем структуру с tool_name
                saveChanges({
                    tool_name: selectedName || null,
                    inputs_map: inputsMap,
                    outputs_map: {}
                });
            };

            // Вспомогательный хелпер генерации селекта со списком глобальных переменных {{var}}
            // Переменные сгруппированы через optgroup так же, как в списке #variablesContainer
            const createVariablesSelect = (selectedVal = '') => {
                const sel = document.createElement('select');
                sel.className = 'form-control map-var-select';
                sel.style = "flex: 1; padding: 4px; font-size: 12px; height: 32px;";
                fillVariablesSelectOptions(sel, selectedVal);
                sel.onchange = collectToolWidgetData;
                return sel;
            };

            // Функция рендеринга интерактивных связей аргументов
            const renderToolDetails = (toolName) => {
                mappingContainer.innerHTML = '';
                descContainer.innerHTML = '';
                descContainer.style.display = 'none';
                if (!toolName) return;

                // ВАЖНО: Ищем инструмент в массиве по его названию (name)
                const selectedTool = state.allAvailableTools.find(t => String(t.name) === String(toolName));
                if (!selectedTool) return;

                // Отрисовка описания
                if (selectedTool.description) {
                    descContainer.textContent = 'Описание: ' + selectedTool.description;
                    descContainer.style.display = 'block';
                }

                // Парсинг аргументов из базы
                let argsObj = parseMetadata(selectedTool.args);

                if (!argsObj) return;

                // 1. Извлекаем входящие параметры строго по вашей структуре: args.input
                const inputs = argsObj.input || {};
                const inputKeys = Object.keys(inputs);

                // 2. Извлекаем выходящие параметры инструмента
                const outputKeys = getToolOutputKeys(toolName);

                // --- РЕНДЕРИНГ ВХОДЯЩИХ (Input) ---
                if (inputKeys.length > 0) {
                    const title = document.createElement('div');
                    title.style = "font-size: 11px; font-weight: bold; color: #4a5568; margin-top: 5px;";
                    title.textContent = "Входящие параметры (Input Mapping):";
                    mappingContainer.appendChild(title);

                    inputKeys.forEach(argName => {
                        const row = document.createElement('div');
                        row.className = 'input-map-row';
                        row.style = "display: flex; align-items: center; gap: 8px; background: #fff; padding: 6px; border: 1px solid #e2e8f0; border-radius: 4px;";

                        // Левый селект: переменные
                        const savedVar = (currentValue && currentValue.inputs_map) ? currentValue.inputs_map[argName] : '';
                        const varSelect = createVariablesSelect(savedVar);

                        // Стрелочка разделитель
                        const arrow = document.createElement('span');
                        arrow.innerHTML = '➔';
                        arrow.style = "color: #a0aec0; font-size: 12px;";

                        // Правый селект: фиксированный аргумент (чистая конкатенация строк во избежание конфликта с Jinja2)
                        const argSelect = document.createElement('select');
                        argSelect.className = 'form-control map-arg-select';
                        argSelect.style = "flex: 1; padding: 4px; font-size: 12px; height: 32px; background: #edf2f7; pointer-events: none;";
                        argSelect.innerHTML = '<option value="' + argName + '" selected>' + argName + '</option>';

                        row.appendChild(varSelect);
                        row.appendChild(arrow);
                        row.appendChild(argSelect);
                        mappingContainer.appendChild(row);
                    });
                }

                // --- ДЕЛИМИТЕР (Разделительная линия) ---
                if (inputKeys.length > 0 && outputKeys.length > 0) {
                    const hr = document.createElement('div');
                    hr.style = "border-top: 1px solid #e2e8f0; margin: 8px 0;";
                    mappingContainer.appendChild(hr);
                }

                // --- РЕНДЕРИНГ ВЫХОДЯЩИХ (Output) ---
                if (outputKeys.length > 0) {
                    const title = document.createElement('div');
                    title.style = "font-size: 11px; font-weight: bold; color: #4a5568;";
                    title.textContent = "Выходящие параметры (Output Mapping):";
                    mappingContainer.appendChild(title);

                    outputKeys.forEach(argName => {
                        const row = document.createElement('div');
                        row.className = 'output-map-row';
                        row.style = "display: flex; align-items: center; gap: 8px; background: #fff; padding: 6px; border: 1px solid #e2e8f0; border-radius: 4px;";

                        // Левая часть: текстовое название выходного ключа инструмента
                        const argText = document.createElement('span');
                        argText.style = "flex: 1; padding: 4px; font-size: 12px; color: #ea3d3d; font-weight: bold;";
                        argText.textContent = argName;

                        // Скрытый инпут для сбора ключа (argSel.value)
                        const argHidden = document.createElement('input');
                        argHidden.type = 'hidden';
                        argHidden.className = 'map-arg-select';
                        argHidden.value = argName;

                        // Стрелочка разделитель
                        const arrow = document.createElement('span');
                        arrow.innerHTML = '➔';
                        arrow.style = "color: #a0aec0; font-size: 12px;";

                        // Правая часть: переменная, куда записывается результат (в стиле variable-name с копированием)
                        const varSpanContainer = document.createElement('div');
                        varSpanContainer.style = "flex: 1; display: flex; align-items: center; padding: 4px;font-size: 11px;";

                        const varSpan = document.createElement('span');
                        varSpan.className = 'variable-name';
                        varSpan.style.marginRight = '0';
                        varSpan.title = 'Нажмите, чтобы скопировать';
                        const varText = `%${toolName}_${step.id}_result_${argName}%`;
                        varSpan.textContent = varText;

                        varSpan.onclick = async () => {
                            try {
                                await navigator.clipboard.writeText(varText);
                                showNotification(`Переменная ${varText} скопирована в буфер`, 'success');
                            } catch (err) {
                                showNotification('Не удалось скопировать переменную', 'error');
                            }
                        };

                        varSpanContainer.appendChild(varSpan);

                        // Скрытый инпут для сбора значения (varSel.value)
                        const varHidden = document.createElement('input');
                        varHidden.type = 'hidden';
                        varHidden.className = 'map-var-select';
                        varHidden.value = `${toolName}_${step.id}_result_${argName}`;

                        row.appendChild(argHidden);
                        row.appendChild(argText);
                        row.appendChild(arrow);
                        row.appendChild(varSpanContainer);
                        row.appendChild(varHidden);
                        mappingContainer.appendChild(row);
                    });
                }
            };

            // Навешивание события смены инструмента
            selectElement.onchange = () => {
                renderToolDetails(selectElement.value);
                collectToolWidgetData();

                const inputStepTitle = document.getElementById('stepTitle');
                inputStepTitle.value = selectElement.value;
                const stepTitleEl = document.querySelectorAll('.step-item-block.active .step-title-text')
                stepTitleEl.forEach(el => el.textContent = selectElement.value);
            };

            // Первичный запуск при открытии ноды
            if (currentValue && currentValue.tool_name) {
                renderToolDetails(currentValue.tool_name);
            }

            toolContainer.appendChild(selectElement);
            toolContainer.appendChild(descContainer);
            toolContainer.appendChild(mappingContainer);
            fieldWrapper.appendChild(toolContainer);

        } else {
            // --- СТАНДАРТНАЯ ОТРИСОВКА ОСТАЛЬНЫХ ТИПОВ ПОЛЕЙ ---
            if (field.type === 'textarea') {
                inputElement = document.createElement('textarea');
                inputElement.id = `field_${field.key}`;
                inputElement.className = 'form-control';
                inputElement.style = "height: 170px; resize: vertical; font-size: 13px; padding: 8px;";
                inputElement.placeholder = field.placeholder || '';
                inputElement.value = currentValue;
            } else if (field.type === 'select') {
                inputElement = document.createElement('select');
                inputElement.id = `field_${field.key}`;
                inputElement.className = 'form-control';
                inputElement.style = "padding: 6px; font-size: 13px;";

                if (field.options && Array.isArray(field.options)) {
                    field.options.forEach(opt => {
                        const option = document.createElement('option');
                        option.value = opt;
                        option.textContent = opt;
                        if (String(opt) === String(currentValue)) option.selected = true;
                        inputElement.appendChild(option);
                    });
                }
            } else if (field.type === 'checkbox') {
                inputElement = document.createElement('input');
                inputElement.type = 'checkbox';
                inputElement.id = `field_${field.key}`;
                inputElement.className = 'form-check-input';
                inputElement.style = "cursor: pointer; width: 16px; height: 16px; margin: 0;";
                inputElement.checked = currentValue === true || String(currentValue).toLowerCase() === 'true';
            } else {
                inputElement = document.createElement('input');
                inputElement.id = `field_${field.key}`;
                inputElement.type = field.type;
                inputElement.className = 'form-control';
                inputElement.style = "padding: 6px; font-size: 13px;";
                if (field.min !== undefined) inputElement.min = field.min;
                if (field.max !== undefined) inputElement.max = field.max;
                if (field.step !== undefined) inputElement.step = field.step;
                inputElement.value = currentValue;
            }

            inputElement.oninput = () => saveChanges();
            inputElement.onchange = () => saveChanges();

            fieldWrapper.appendChild(inputElement);

            const latestMeta = parseMetadata(step.metadata);
            if (latestMeta[field.key] === undefined && currentValue !== '') {
                saveChanges();
            }
        }

        container.appendChild(fieldWrapper);
    });
}

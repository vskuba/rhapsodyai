// Панель переменных редактора workflow: группы/аккордеон, подсветки использования,
// tool/workflow-подсветки выбранного шага, входящие переменные формы настроек

import {getData, putData, postData, deleteData} from '../api.js';
import {showNotification} from '../notification.js';
import {state} from './state.js';
import {parseMetadata} from './utils.js';
import {stepVariables, groupWorkflowVariables, variableGroupIndex,
    workflowVariableSections} from './variable-group.js';

/**
 * Разбивка переменных по группам для **открытого в редакторе** workflow.
 *
 * ⚠⚠ Единственное место, где правило из `variable-group.js` связывается со стейтом
 * страницы. Само правило стейта не знает намеренно (им пользуется и трасса
 * прогона, где никакого редактора нет), но привязку надо где-то держать — и
 * держать в одном месте: три вызова с четвёркой `state.*` разошлись бы молча,
 * стоит одному из них забыть справочник.
 */
export function editorVariableGroups(variables) {
    return groupWorkflowVariables(variables, state.allCurrentStepsData,
                                  state.allWorkflows, state.allAvailableTools);
}

/**
 * Карта «имя → группа» для открытого в редакторе workflow.
 *
 * ⚠ Карта на весь список, а не вопрос про одно имя: разбивка стоит разбора
 * метаданных всех шагов, и спрашивать её в цикле по именам — ровно та работа,
 * которая тормозила фильтр в графе (`graph.js`).
 */
export function editorVariableGroupIndex() {
    return variableGroupIndex(state.allCurrentVariables || [], state.allCurrentStepsData,
                              state.allWorkflows, state.allAvailableTools);
}

/**
 * Собирает имена всех переменных, используемых в шагах workflow,
 * и сохраняет их в state.allUsedVariables.
 */
export function extractVariablesFromSteps(steps) {
    const usedVariables = new Set();

    (Array.isArray(steps) ? steps : [])
        .forEach(step => stepVariables(step).forEach(name => usedVariables.add(name)));

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
    const list = document.getElementById('inputVariablesList');
    const hidden = document.getElementById('inputVariablesContainer');
    if (!list || !hidden) return;

    list.innerHTML = '';
    hidden.innerHTML = '';

    const all = Array.isArray(state.allCurrentVariables) ? state.allCurrentVariables : [];
    const inputs = all.filter(v => v.type === 'input');

    // ⚠ Скрытые строки остаются: на них держится сохранение вместе с workflow
    // (`saveInputVariables` читает `#inputVariablesContainer`). Вид сменился,
    // сохранение — нет.
    inputs.forEach(variable => createInputVariableRow(variable));

    inputs.forEach(variable => list.append(nameButton(variable)));

    if (!inputs.length) {
        list.innerHTML = '<div class="input-vars-empty">переменных нет</div>';
    }

    // Выбранную держим между перерисовками: список перечитывается после каждого
    // сохранения, и сброс выбора выбрасывал бы человека из формы, которую он
    // правит.
    const want = inputs.find(v => String(v.id) === String(state.inputVarPicked))
        || inputs[0];

    if (want) pickInputVariable(want);
    else showInputForm(null);
}

/**
 * Строка списка: имя слева, кружок удаления справа.
 *
 * ⚠ `div`, а не `button`: внутри кнопки другая кнопка недопустима по разметке, а
 * удаление обязано быть отдельной кнопкой — иначе щелчок по нему выбирал бы
 * переменную вместо удаления.
 *
 * ⚠⚠ Кружок появляется **по наведению**. Всегда видимый ряд крестиков в списке
 * читается как «это всё можно снести» и провоцирует промах: строки узкие, а
 * выбор и удаление стояли бы в паре пикселей друг от друга.
 */
function nameButton(variable) {
    const row = document.createElement('div');
    row.className = 'input-var-name';
    row.dataset.id = variable.id ?? '';
    row.tabIndex = 0;
    if (!variable.id) row.classList.add('fresh');

    const label = document.createElement('span');
    label.className = 'input-var-label';
    label.textContent = variable.name || '(без имени)';
    // ⚠ Ширина списка рассчитана на самое длинное здешнее имя, но имена
    // заводит человек: что не влезло, показывается подсказкой.
    label.title = variable.name || '';

    const kill = document.createElement('button');
    kill.type = 'button';
    kill.className = 'input-var-kill';
    kill.title = `Удалить «${variable.name || 'переменную'}»`;
    kill.textContent = '×';
    kill.onclick = (e) => {
        // ⚠ Щелчок по кружку не должен всплывать до строки: иначе переменная
        // сперва выберется, а следом откроется вопрос об удалении — и человек
        // подтвердит его, глядя на только что открывшуюся форму.
        e.stopPropagation();
        removeInputVariable(variable);
    };

    row.onclick = () => pickInputVariable(variable);
    row.append(label, kill);

    return row;
}

function pickInputVariable(variable) {
    state.inputVarPicked = variable.id ?? null;

    document.querySelectorAll('.input-var-name').forEach(one => {
        one.classList.toggle('active',
            String(one.dataset.id) === String(variable.id ?? ''));
    });

    showInputForm(variable);
}

/**
 * Форма выбранной переменной: имя, значение по умолчанию, описание.
 *
 * ⚠⚠ **Все три поля сохраняются сами**, по уходу из поля. Кнопки «сохранить»
 * тут нет: правка идёт по одному полю за раз, и лишний щелчок после каждой
 * означал бы, что описания просто не станут править.
 *
 * ⚠ Новая переменная (без номера) сохраняется вместе с workflow — ей ещё некуда
 * слать PUT. Оттого поля у неё живут в скрытой строке, а форма только
 * показывает, что она есть.
 */
function showInputForm(variable) {
    const box = document.getElementById('inputVariablesForm');
    if (!box) return;

    box.innerHTML = '';

    if (!variable) {
        box.innerHTML = '<div class="input-vars-empty">выберите переменную слева</div>';
        return;
    }

    box.append(
        formField('Имя переменной', inputField(variable, 'name')),
        formField('Значение по умолчанию', textField(variable, 'default', 2)),
        formField('Описание — зачем она и что в неё кладут',
                  noteView(variable)),
    );

    // ⚠ Кнопки удаления здесь нет: она живёт в списке слева, у каждой строки.
    // Два места для одного действия означали бы вопрос, чем они отличаются.
}

function formField(label, control) {
    const wrap = document.createElement('div');
    const cap = document.createElement('div');
    cap.className = 'field-label';
    cap.textContent = label;
    wrap.append(cap, control);

    return wrap;
}

/**
 * Описание: текст и карандаш; поле ввода открывается щелчком.
 *
 * ⚠ Читают описание в разы чаще, чем правят, — постоянное текстовое поле
 * выглядит как «здесь надо что-то заполнить», а рядом с ним ещё два таких же.
 * Текст отвечает на «что это», не требуя ничего.
 *
 * ⚠⚠ Сохраняется само, по уходу из поля. Кнопки «сохранить» нет: правка одна на
 * заход, и лишний щелчок после каждой означал бы, что описания не станут править.
 */
function noteView(variable) {
    const box = document.createElement('div');
    box.className = 'note-view';

    const text = document.createElement('div');
    text.className = 'note-text';

    const show = () => {
        const note = variable.description ?? '';
        text.textContent = note || 'без описания';
        text.classList.toggle('empty', !note);
        text.title = note ? 'Нажмите, чтобы изменить' : 'Нажмите, чтобы описать';
    };

    const pen = document.createElement('button');
    pen.type = 'button';
    pen.className = 'btn-note-edit';
    pen.title = 'Описать переменную';
    pen.textContent = '✎';

    const edit = () => {
        if (box.querySelector('textarea')) return;

        const field = textField(variable, 'description', 4, 'field-note');
        field.placeholder = 'Зачем эта переменная и что в неё кладут';

        // ⚠ Возврат к тексту — **после** сохранения: `bindSave` висит на `blur`
        // и к этому мигу уже записал значение в `variable`.
        field.addEventListener('blur', () => {
            setTimeout(() => {
                field.replaceWith(text);
                pen.style.display = '';
                show();
            }, 0);
        });

        pen.style.display = 'none';
        text.replaceWith(field);
        field.focus();
    };

    text.onclick = edit;
    pen.onclick = edit;

    show();
    box.append(text, pen);

    return box;
}

function inputField(variable, field) {
    const el = document.createElement('input');
    el.type = 'text';
    el.className = 'form-control';
    el.value = variable[field] ?? '';
    bindSave(el, variable, field);

    return el;
}

function textField(variable, field, rows, extra = '') {
    const el = document.createElement('textarea');
    el.className = `form-control ${extra}`.trim();
    el.rows = rows;
    el.value = variable[field] ?? '';
    bindSave(el, variable, field);

    return el;
}

/** Автосохранение поля: по уходу и по Ctrl+Enter, один раз на правку. */
function bindSave(el, variable, field) {
    const save = async () => {
        const value = el.value.trim();
        if (value === (variable[field] ?? '')) return;

        // ⚠ Новая переменная уедет вместе с workflow: PUT слать некуда, но
        // скрытую строку обновить надо — из неё читает `saveInputVariables`.
        if (!variable.id) {
            variable[field] = value;
            syncHiddenRow(variable);
            return;
        }

        if (field === 'name'
                && !/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(value)) {
            showNotification(`Недопустимое имя переменной: "${value}"`, 'error');
            el.value = variable.name;
            return;
        }

        const workflowId = document.getElementById('workflowId')?.value;

        try {
            await putData(`/workflow/${workflowId}/variable/${variable.id}`,
                {[field]: value || null});
            variable[field] = value;
            syncHiddenRow(variable);
            if (field === 'name') renderInputVariables();
            savedMark(el);
        } catch (err) {
            console.error('Переменная не сохранилась:', err);
            showNotification(`Не сохранилось: ${err.message}`, 'error');
            el.value = variable[field] ?? '';
        }
    };

    el.addEventListener('blur', save);
    el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey || el.tagName === 'INPUT')) {
            e.preventDefault();
            el.blur();
        }
    });
}

/** Скрытая строка — источник для сохранения вместе с workflow. */
function syncHiddenRow(variable) {
    const row = document.querySelector(
        `#inputVariablesContainer .input-variable-row[data-id="${variable.id}"]`);
    if (!row) return;

    row.querySelector('.var-key').value = variable.name ?? '';
    row.querySelector('.var-value').value = variable.default ?? '';
    row.dataset.originalName = variable.name ?? '';
    row.dataset.originalDefault = variable.default ?? '';
}

/** Короткая отметка «сохранено»: всплывающее сообщение на каждое поле — шум. */
function savedMark(el) {
    const was = el.style.borderColor;
    el.style.borderColor = '#16a34a';
    setTimeout(() => { el.style.borderColor = was; }, 900);
}

async function removeInputVariable(variable) {
    if (!variable.id) {
        state.inputVarPicked = null;
        renderInputVariables();
        return;
    }

    if (!confirm(`Удалить переменную "${variable.name}"?`)) return;

    const workflowId = document.getElementById('workflowId')?.value;

    try {
        await deleteData(`/workflow/${workflowId}/variable/${variable.id}`);
        showNotification('Переменная успешно удалена', 'success');
        state.inputVarPicked = null;
        await loadWorkflowVariables(workflowId);
    } catch (err) {
        console.error('Ошибка удаления переменной:', err);
        showNotification(`Ошибка удаления: ${err.message}`, 'error');
    }
}

function createInputVariableRow(variable = null) {
    const container = document.getElementById('inputVariablesContainer');
    if (!container) return;

    const row = document.createElement('div');
    row.className = 'variable-row input-variable-row';
    if (variable) {
        row.dataset.id = variable.id;
        row.dataset.originalName = variable.name;
        row.dataset.originalDefault = variable.default ?? '';
    }

    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'form-control var-key';
    nameInput.value = variable ? variable.name : '';

    const valInput = document.createElement('input');
    valInput.type = 'text';
    valInput.className = 'form-control var-value';
    valInput.value = variable ? (variable.default ?? '') : '';

    row.append(nameInput, valInput);
    container.appendChild(row);

    // Новая строка: показываем её в списке и открываем форму.
    if (!variable) {
        state.inputVarPicked = null;
        const list = document.getElementById('inputVariablesList');
        const fresh = {name: '', default: '', description: '', id: null};
        if (list) list.append(nameButton(fresh));
        showInputForm(fresh);
    }
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
                await putData(`/workflow/${workflowId}/variable/${variableId}`, {
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


// Заполняет селект опциями переменных из window.allCurrentVariables,
// сгруппированными через optgroup так же, как в списке #variablesContainer
export function fillVariablesSelectOptions(sel, selectedVal = '', placeholder = '-- Переменная --') {
    sel.innerHTML = '<option value="">' + placeholder + '</option>';

    let selectedMatched = false;
    const groups = editorVariableGroups(window.allCurrentVariables);
    workflowVariableSections(groups).forEach(([label, items]) => {
        if (items.length === 0) return;
        const optgroup = document.createElement('optgroup');
        optgroup.label = label;
        items.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.name;
            opt.textContent = '%' + v.name + '%';
            if (v.name === selectedVal) {
                opt.selected = true;
                selectedMatched = true;
            }
            optgroup.appendChild(opt);
        });
        sel.appendChild(optgroup);
    });

    // Сохраненное в metadata значение не объявлено среди переменных workflow:
    // показываем его отдельной группой, иначе селект выглядит пустым, а
    // автосохранение формы молча затирает значение в metadata
    if (selectedVal && !selectedMatched) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = '⚠️ Не в списке переменных';
        const opt = document.createElement('option');
        opt.value = selectedVal;
        opt.textContent = '%' + selectedVal + '%';
        opt.selected = true;
        optgroup.appendChild(opt);
        sel.appendChild(optgroup);
    }
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
    const {commonGroup, nodeGroup, workflowGroup, toolGroup, inputGroup,
           dynamicGroup} = editorVariableGroups(variablesArray);

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
        if (variable.id === -3) {
            div.className += ' variable-item-dynamic';
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
        // Переменные ноды и глобальные живут в других таблицах —
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
    workflowVariableSections({commonGroup, nodeGroup, workflowGroup, toolGroup,
                              inputGroup, dynamicGroup}).forEach(([title, groupItems, storageKey]) => {
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
 * Раскрывает группу "Переменные workflow" и подсвечивает **все** переменные,
 * участвующие в выбранном шаге: и читаемые, и записываемые.
 *
 * ## ⚠⚠ Для любого типа шага, а не для трёх из семи
 *
 * Прежде подсветка была написана под `variable_conversion` и выходила на первой
 * строке для всего остального:
 *
 *     if (typeName !== 'variable_conversion') return;
 *
 * Тёмными оставались **67 шагов**, и все они с переменными работают: «Ответ в
 * чат» читает историю разговора и анкеты, «Валидация ответа» — черновик. Со
 * стороны это выглядело как случайная поломка («подсвечивает не всегда»), хотя
 * было незаконченной работой.
 *
 * ⚠ Имена берёт `stepVariables` — тот же сбор, что помечает неиспользуемые. Один
 * источник на оба применения: разойдись они, переменная числилась бы
 * использованной в одном месте и неиспользуемой в другом.
 *
 * ## ⚠ Что подсветить нельзя
 *
 * То, чего нет **в реестре**: панель рисует его, а не метаданные шага. Шаг вправе
 * положить переменную, не заведённую в реестре (`talk_topic`,
 * `girl_response_fixed` у `dating_talk`), — такая останется тёмной, и это уже про
 * реестр, а не про подсветку.
 */
export function highlightStepWorkflowVariables(step) {
    const container = document.getElementById('variablesContainer');
    if (!container) return;

    // Снимаем прошлую подсветку
    container.querySelectorAll('.variable-item.workflow-var-highlight')
        .forEach(el => el.classList.remove('workflow-var-highlight'));

    const variableNames = stepVariables(step);

    // ⚠ Значения селектов формы — **поверх** метаданных: у шага «Переменные»
    // человек правит цель на месте, и до сохранения метаданные ещё старые.
    if (state.allWorkflowStepsType[step.type_id]?.name === 'variable_conversion') {
        document.querySelectorAll('#dynamicStepFieldsContainer select')
            .forEach(sel => {
                const name = (sel.value || '').trim();
                if (name) variableNames.add(name);
            });
    }

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

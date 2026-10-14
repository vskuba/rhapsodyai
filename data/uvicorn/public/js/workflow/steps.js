// Режим «Шаги»: список шагов, выбор и детали шага, переходы (before/after),
// drag-and-drop сортировка, добавление/удаление шагов

import {getData, putData, postData, deleteData} from '../api.js';
import {showNotification} from '/static/js/notification.js';
import {state} from './state.js';
import {parseMetadata, getDragAfterElement, editorWorkflowId} from './utils.js';
import {renderWorkflowVariables, extractVariablesFromSteps, fillVariablesSelectOptions,
    highlightStepToolVariables, highlightStepWorkflowVariables} from './variables.js';
import {renderCustomStepFields} from './step-widgets.js';
import {invalidateUndefinedIndex} from './variable-undefined.js';

function renderWorkflowSteps(steps) {
    const container = document.getElementById('workflowStepsSortable');
    if (!container) return;
    container.innerHTML = '';

    const stepsArray = Array.isArray(steps) ? steps : (steps?.result || []);

    stepsArray.sort((a, b) => (a.position || 0) - (b.position || 0)).forEach((step, index) => {
        const div = document.createElement('div');
        div.className = 'step-item-block';
        if (
            state.allWorkflowStepsType[step.type_id].name === 'return_response_text'
            || state.allWorkflowStepsType[step.type_id].name === 'return_response_llm'
        ) {
            div.className += ' step-return-response';
        }
        if (state.allTargetSteps.includes(String(step.id))) {
            div.className += ' step-transition-target';
        }
        div.draggable = true;
        div.dataset.id = step.id;

        // Получаем строку с условиями переходов
        const transitionHtmlBefore = getWorkflowStepConditionsHtml(stepsArray, step, 'Before');
        const transitionHtmlAfter = getWorkflowStepConditionsHtml(stepsArray, step, 'After');

        // Формируем финальный HTML одним блоком
        div.innerHTML = `
        <div class="step-content" style="flex-wrap: wrap;">
            <div style="display: flex; align-items: center; width: 100%;">
                <span style="color: #ccc; margin-right: 12px; cursor: grab;">☰</span>
                <span class="step-number-badge">${index + 1}</span>
                <span class="step-type-icon" style="font-size: 16px; margin-right: 10px;">${step.icon || ''}</span>
                <span class="step-title-text" style="flex:1;">${step.title}</span>
                <span class="step-id-badge" style="font-size:10px;color:#94a3b8;margin-right:6px;white-space:nowrap;">#${step.id}</span>
                <button type="button" class="btn-delete-step" title="Удалить">&times;</button>
            </div>
            <div class="step-flow-info" style="margin-left: 62px; width: 100%;">
                ${transitionHtmlBefore}
                ${transitionHtmlAfter}
            </div>
        </div>
    `;

        const deleteBtn = div.querySelector('.btn-delete-step');
        deleteBtn.onclick = (e) => {
            e.stopPropagation();
            deleteStep(step.id, step.title);
        };

        div.addEventListener('dragstart', () => div.classList.add('dragging'));
        div.addEventListener('dragend', () => {
            div.classList.remove('dragging');
            updateStepsPosition();
        });
        div.onclick = () => selectStep(step, div);

        container.appendChild(div);
    });
}

function getWorkflowStepConditionsHtml(allSteps, currentStep, type) {
    let transitionInfo = '';
    try {

        let metadata = parseMetadata(currentStep.metadata);

        const transitionKey = 'transitions_' + type.toLowerCase();
        if (metadata[transitionKey] && metadata[transitionKey].length > 0) {
            transitionInfo = metadata[transitionKey].map(tr => {
                // Ищем целевой шаг по новому ключу step_id
                const target = allSteps.find(s => String(s.id) === String(tr.step_id));

                // Формируем красивое название цели
                const targetName = target ? target.title : '???';

                // Собираем читаемое условие: если есть переменная, пишем "%var% == value"
                let conditionText = '';
                if (tr.variable) {
                    conditionText = '%' + tr.variable + '% ' + (tr.operator || '==') + ' ' + (tr.value || '');
                } else {
                    // Фолбек на случай, если поле переменной не выбрано
                    conditionText = tr.value || 'Условие';
                }

                return '<div style="font-size: 10px; color: #3498db; margin-top: 2px;">' +
                    'if <b>"' + conditionText + '"</b> → ' + targetName +
                    '</div>';
            }).join('');
        }
    } catch (e) {
        console.error("Ошибка парсинга метаданных для превью условий:", e);
    }
    return transitionInfo;
}


/**
 * Загрузка списка шагов (Step) для выбранной задачи
 */
export async function loadWorkflowSteps(workflowId) {
    const container = document.getElementById('workflowStepsSortable');
    if (!container) return;

    try {
        const data = await getData(`/workflow/${workflowId}/steps`);

        // 2. Сохраняем полученные шаги в глобальную переменную
        // Это позволит функции добавления условий видеть актуальный список шагов
        state.allCurrentStepsData = data.result || [];

        // ⚠ Свежие шаги — повод выбросить кэш «Undefined переменных»: этот workflow
        // теперь считают по свежему составу, а значки в левом списке берут его из
        // кэша. Вызов и на открытии, и после правки шага — кэш всегда за state.
        invalidateUndefinedIndex(workflowId);

        let activeStepId = null;
        let currentStepData = null;
        let currentStepBlock = null;

        const activeStepBlock = document.querySelector('.step-item-block.active');
        if (activeStepBlock) {
            activeStepId = activeStepBlock.dataset.id;
        }

        collectWorkflowTargetSteps()
        extractVariablesFromSteps(state.allCurrentStepsData);
        renderWorkflowVariables(state.allCurrentVariables);
        renderWorkflowSteps(state.allCurrentStepsData);

        if (activeStepId) {
            currentStepData = state.allCurrentStepsData.find(s => String(s.id) === String(activeStepId));
            currentStepBlock = container.querySelector(`.step-item-block[data-id="${activeStepId}"]`);
        }

        const firstStepBlock = container.querySelector('.step-item-block');

        if (currentStepData) {
            selectStep(currentStepData, currentStepBlock);
        } else if (firstStepBlock) {
            const firstStepData = state.allCurrentStepsData[0];
            selectStep(firstStepData, firstStepBlock);
        } else {
            document.getElementById('stepDetailsContent').style.display = 'none';
            document.getElementById('noStepSelected').style.display = 'block';
        }

        // --- Drag-and-drop блок ---
        container.addEventListener('dragover', e => {
            e.preventDefault();
            const dragging = document.querySelector('.dragging');
            if (!dragging) return;

            const afterElement = getDragAfterElement(container, e.clientY);
            if (afterElement == null) {
                container.appendChild(dragging);
            } else {
                container.insertBefore(dragging, afterElement);
            }
        });
    } catch (e) {
        console.error("Ошибка загрузки шагов:", e);
        state.allCurrentStepsData = [];
    }
}

function collectWorkflowTargetSteps() {
    const targetStepsSet = new Set();
    state.allCurrentStepsData.forEach(step => {
        let metadata = parseMetadata(step.metadata);
        ['transitions_before', 'transitions_after'].forEach(key => {
            if (metadata[key] && Array.isArray(metadata[key])) {
                metadata[key].forEach(transition => {

                    if (transition.step_id) {
                        targetStepsSet.add(String(transition.step_id));
                    }
                });
            }
        });
    });

    state.allTargetSteps = Array.from(targetStepsSet);
}

export async function loadAvailableStepTypes() {
    const select = document.getElementById('availableStepsSelect');
    try {
        const data = await getData('/workflow_step/list');
        select.innerHTML = '';
        data.result.forEach(stepType => {
            const opt = document.createElement('option');
            opt.value = stepType.id;
            opt.textContent = stepType.icon + ' ' + stepType.description;
            select.appendChild(opt);

            state.allWorkflowStepsType[stepType.id] = stepType
        });
    } catch (e) {
        select.innerHTML = '<option>Ошибка загрузки</option>';
    }
}

async function updateStepsPosition() {
    const workflowId = editorWorkflowId();
    if (!workflowId) return;

    const items = [...document.querySelectorAll('.step-item-block')];

    const newPositions = items.map((el, index) => ({
        id: el.dataset.id,
        position: index
    }));

    try {
        await putData(`/workflow/${workflowId}/steps/reorder`, {positions: newPositions});
        // Порядок шагов — это и нумерация в значках «Undefined переменных»:
        // сбрасываем кэш, списки пересчитают состав и номера по свежему порядку.
        invalidateUndefinedIndex(workflowId);

        // Обновляем визуальные номера шагов
        items.forEach((el, idx) => {
            const titleSpan = el.querySelector('span:nth-child(2)');

            // Очищаем старый номер и ставим новый
            const currentText = titleSpan.textContent.includes('. ')
                ? titleSpan.textContent.split('. ').slice(1).join('. ')
                : titleSpan.textContent;
            titleSpan.textContent = `${idx}. ${currentText}`;

            const badge = el.querySelector('.step-number-badge');
            if (badge) badge.textContent = idx;
        });
        showNotification('Порядок сохранен', 'success');

    } catch (e) {
        showNotification('Ошибка сохранения порядка', 'error');
    }
}

export function selectStep(step, element) {
    // 1. Подсветка и активация класса
    document.querySelectorAll('.step-item-block').forEach(el => {
        el.classList.remove('active');
        el.style.background = '#f8f9fa';
        el.style.borderColor = '#ddd';
    });
    element.classList.add('active');
    element.style.background = '#eef6fc';
    element.style.borderColor = '#3498db';

    const detailsContent = document.getElementById('stepDetailsContent');
    const noStepSelected = document.getElementById('noStepSelected');
    if (detailsContent && noStepSelected) {
        noStepSelected.style.display = 'none';
        detailsContent.style.display = 'block';
    }

    let metadata = parseMetadata(step.metadata);

    const stepTitle = document.getElementById('stepTitle');
    if (stepTitle) {
        stepTitle.value = step.title || state.allWorkflowStepsType[step.type_id].description || '';
    }

    const stepDescriptionFull = document.getElementById('stepDescriptionFull');
    if (stepDescriptionFull) {
        stepDescriptionFull.innerHTML = state.allWorkflowStepsType[step.type_id].description_full || '';
    }

    // 4. Заполнение Метаданных (сырой текст в textarea)
    const metadataField = document.getElementById('stepTextarea');
    if (metadataField) {
        // Записываем весь объект metadata в виде строки, чтобы не терять кастомные поля
        metadataField.value = typeof step.metadata === 'string' ? step.metadata : JSON.stringify(metadata);
    }

    renderCustomStepFields(step, metadata);

    // 5. Отрисовка переходов
    ['Before', 'After'].forEach(type => {
        renderTransitions(step, state.allCurrentStepsData, type);
    });

    toNextStepShow(metadata);

    const stepTransitionsViews = document.querySelectorAll('.transitions-editor');
    if (state.allWorkflowStepsType[step.type_id].name === 'return_response_llm') {
        stepTransitionsViews.forEach(view => {
            view.style.display = 'none';
        });
    } else {
        stepTransitionsViews.forEach(view => {
            view.style.display = '';
        });
    }

    // 6. Для шага-инструмента раскрываем группу tool-переменных и подсвечиваем его результаты,
    // для шага "Переменные" — группу workflow-переменных, в которые он пишет
    highlightStepToolVariables(step);
    highlightStepWorkflowVariables(step);
}

// Прячем поле "Значение", когда оператор его не использует (exists/empty).
// visibility (а не display), чтобы строка перехода не «прыгала» по ширине
function toggleTransitionValueVisibility(opSelect, valInput) {
    const hidden = opSelect.value === 'exists' || opSelect.value === 'empty';
    valInput.style.visibility = hidden ? 'hidden' : 'visible';
}

function renderTransitions(step, allSteps, type) {
    const container = document.getElementById('stepTransitionsList' + type);
    if (!container) return;
    container.innerHTML = '';

    let metadata = parseMetadata(step.metadata);

    const transitionKey = 'transitions_' + type.toLowerCase();
    const transitions = metadata[transitionKey] || [];
    const stepsArray = Array.isArray(allSteps) ? allSteps : [];

    // Вспомогательный хелпер для генерации селекта операторов
    const createOperatorSelect = (selectedOp = '==') => {
        const sel = document.createElement('select');
        sel.className = 'form-control tr-operator';
        sel.style = "width: 110px; padding: 4px; font-size: 12px; height: 32px; text-align: center;";

        const ops = ['==', '!=', '>', '<', '>=', '<=', 'contains', 'not_contains', 'regex', 'exists', 'empty'];
        ops.forEach(op => {
            const opt = document.createElement('option');
            opt.value = op;
            opt.textContent = op;
            if (op === selectedOp) opt.selected = true;
            sel.appendChild(opt);
        });
        return sel;
    };

    // Вспомогательный хелпер для генерации селекта переменных воркфлоу с процентами %
    // (сгруппированы через optgroup как в #variablesContainer)
    const createTrVariablesSelect = (selectedVar = '') => {
        const sel = document.createElement('select');
        sel.className = 'form-control tr-variable';
        sel.style = "flex: 1.5; padding: 4px; font-size: 12px; height: 32px;";
        fillVariablesSelectOptions(sel, selectedVar);
        return sel;
    };

    transitions.forEach((tr) => {
        const row = document.createElement('div');
        row.className = 'transition-row transition-row-' + type.toLowerCase();
        row.style = "display: flex; gap: 6px; align-items: center; background: #f9fafb; padding: 8px; border-radius: 6px; border: 1px solid #edf2f7; margin-bottom: 5px;";

        // 1. Селект переменной
        const varSelect = createTrVariablesSelect(tr.variable || '');

        // 2. Селект оператора сравнения
        const opSelect = createOperatorSelect(tr.operator || '==');

        // 3. Инпут текстового значения для сравнения (ВОЗВРАЩАЕМ ПОЛЕ)
        const valInput = document.createElement('input');
        valInput.type = 'text';
        valInput.className = 'form-control tr-value';
        valInput.placeholder = 'Значение';
        valInput.value = tr.value || '';
        valInput.style = "flex: 1.5; padding: 4px; font-size: 12px; height: 32px;";

        // Стрелочка к цели
        const arrow = document.createElement('span');
        arrow.innerHTML = '➔';
        arrow.style = "color: #a0aec0; font-size: 12px; margin: 0 2px;";

        // 4. Селект целевого шага
        const targetSelect = document.createElement('select');
        targetSelect.className = 'form-control tr-target';
        targetSelect.style = "flex: 2; padding: 4px; font-size: 12px; height: 32px;";
        targetSelect.innerHTML = stepsArray.map(s =>
            '<option value="' + s.id + '" ' + (s.id == tr.step_id ? 'selected' : '') + '>' + s.title + '</option>'
        ).join('');

        // 5. Кнопка удаления строки перехода
        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn-delete-transition';
        delBtn.style = "background:none; border:none; color:#dc3545; font-size:16px; cursor:pointer; padding:0 4px;";
        delBtn.innerHTML = '&times;';

        // Начальное состояние поля "Значение" для сохраненного оператора
        toggleTransitionValueVisibility(opSelect, valInput);

        // Навешиваем живую синхронизацию изменений на все четыре элемента
        varSelect.onchange = () => syncTransitionsToStepState(step, type);
        opSelect.onchange = () => {
            toggleTransitionValueVisibility(opSelect, valInput);
            syncTransitionsToStepState(step, type);
        };
        valInput.oninput = () => syncTransitionsToStepState(step, type);
        targetSelect.onchange = () => syncTransitionsToStepState(step, type);
        delBtn.onclick = () => {
            row.remove();
            syncTransitionsToStepState(step, type);
        };

        row.appendChild(varSelect);
        row.appendChild(opSelect);
        row.appendChild(valInput); // Вставляем инпут на UI
        row.appendChild(arrow);
        row.appendChild(targetSelect);
        row.appendChild(delBtn);
        container.appendChild(row);
    });
}

async function deleteStep(stepId, stepTitle) {
    const workflowId = editorWorkflowId();
    if (!workflowId) return;

    if (!confirm(`Удалить шаг "${stepTitle}" из задачи?`)) return;

    try {
        await deleteData(`/workflow/${workflowId}/step/${stepId}`);
        showNotification('Шаг удален', 'success');

        // Скрываем детали шага, если удалили тот, что редактировали
        document.getElementById('stepDetailsContent').style.display = 'none';
        document.getElementById('noStepSelected').style.display = 'block';

        // Перезагружаем список шагов
        await loadWorkflowSteps(workflowId);
    } catch (e) {
        console.error("Ошибка при удалении шага:", e);
        // ⚠ 409 — не поломка, а отказ по существу: на шаг ведут переходы других
        // шагов, и сервер прислал их список. Показываем его словами сервера и
        // без «Ошибка:» — читать это человеку, и чинить ему же.
        if (e.status === 409) showNotification(e.message, 'warning');
        else showNotification(`Ошибка: ${e.message}`, 'error');
    }
}

export function collectTransitions(type) {
    const rows = document.querySelectorAll('.transition-row-' + type.toLowerCase());
    const transitions = [];

    rows.forEach(row => {
        const varEl = row.querySelector('.tr-variable');
        const opEl = row.querySelector('.tr-operator');
        const valEl = row.querySelector('.tr-value'); // Селектор инпута
        const targetEl = row.querySelector('.tr-target');

        if (targetEl && targetEl.value) {
            const varName = varEl ? varEl.value : '';
            const opName = opEl ? opEl.value : '==';
            const valueText = valEl ? valEl.value.trim() : ''; // Забираем текст

            transitions.push({
                variable: varName,
                operator: opName,
                value: valueText, // Сохраняем значение
                step_id: targetEl.value
            });
        }
    });

    return transitions;
}


function syncTransitionsToStepState(step, type) {
    let latestMeta = parseMetadata(step.metadata);

    const transitionKey = 'transitions_' + type.toLowerCase();
    // Вызываем обновленный collectTransitions(), который собирает только переменные, операторы и step_id
    latestMeta[transitionKey] = collectTransitions(type);
    // ⚠ Галочка едет вместе с условиями: она часть одного ответа на вопрос
    // «куда пойдёт поток», и сохранить половину значило бы потерять вторую.
    latestMeta[TO_NEXT_STEP] = toNextStepValue();

    // Записываем обновленный объект обратно в state текущего шага в виде строки JSON
    step.metadata = JSON.stringify(latestMeta);

    // Синхронизируем со скрытой текстовой областью для сабмита формы
    const stepTextarea = document.getElementById('stepTextarea');
    if (stepTextarea) {
        stepTextarea.value = step.metadata;
    }
}

// Ключ галочки «to next step» в метаданных шага. ⚠ То же имя, что читает
// движок (`AI_FRAMEWORK_TO_NEXT_STEP`): разойдутся — страница будет показывать
// одно, а поток пойдёт по другому.
const TO_NEXT_STEP = 'to_next_step';

// Что показать в галочке у открытого шага.
//
// ⚠ **Ключа нет — значит включена.** Так работали все шаги до её появления, и
// снятая галочка у старого шага оборвала бы его молча.
function toNextStepShow(metadata) {
    const box = document.getElementById('stepToNextStep');
    if (!box) return;

    box.checked = (metadata || {})[TO_NEXT_STEP] !== false;
    toNextStepPaint();
}

// Снятая галочка заметна серым полем: тупик в потоке не должен выглядеть как
// обычный шаг. ⚠ Красит та же пара, что читает и пишет значение — иначе вид и
// смысл разошлись бы.
function toNextStepPaint() {
    const box = document.getElementById('stepToNextStep');
    const frame = document.getElementById('stepToNextStepBox');
    if (box && frame) frame.classList.toggle('off', !box.checked);
}

// Что стоит в галочке сейчас. Нет её на странице — считаем включённой: иначе
// правка шага со скрытым блоком переходов снимала бы её сама собой.
function toNextStepValue() {
    const box = document.getElementById('stepToNextStep');

    return box ? !!box.checked : true;
}

// ⚠ Правка галочки сохраняется тем же путём, что правка условия: снятая и
// незаписанная, она обещала бы тупик, которого в базе нет.
document.getElementById('stepToNextStep').onchange = () => {
    toNextStepPaint();

    const activeStepBlock = document.querySelector('.step-item-block.active');
    if (!activeStepBlock) return;

    const step = state.allCurrentStepsData.find(
        s => String(s.id) === String(activeStepBlock.dataset.id));
    if (step) syncTransitionsToStepState(step, 'After');
};

['Before', 'After'].forEach(type => {
    document.getElementById('addConditionBtn' + type).onclick = () => {
        const container = document.getElementById('stepTransitionsList' + type);
        if (!container) return;

        const activeStepBlock = document.querySelector('.step-item-block.active');
        if (!activeStepBlock) return;
        const currentStepData = state.allCurrentStepsData.find(s => String(s.id) === String(activeStepBlock.dataset.id));

        const optionsHtml = state.allCurrentStepsData.map(s =>
            '<option value="' + s.id + '">' + s.title + '</option>'
        ).join('');

        const row = document.createElement('div');
        row.className = 'transition-row transition-row-' + type.toLowerCase();
        row.style = "display: flex; gap: 6px; align-items: center; background: #f9fafb; padding: 8px; border-radius: 6px; border: 1px solid #edf2f7; margin-bottom: 5px;";

        // Рендерим 4 элемента в ряд без бэктиков во избежание конфликтов со знаком доллара
        row.innerHTML =
            '<select class="form-control tr-variable" style="flex: 1.5; padding: 4px; font-size: 12px; height: 32px;"></select>' +
            '<select class="form-control tr-operator" style="width: 110px; padding: 4px; font-size: 12px; height: 32px; text-align: center;">' +
            '<option value="==">==</option>' +
            '<option value="!=">!=</option>' +
            '<option value=">">&gt;</option>' +
            '<option value="<">&lt;</option>' +
            '<option value=">=">&gt;=</option>' +
            '<option value="<=">&lt;=</option>' +
            '<option value="contains">contains</option>' +
            '<option value="not_contains">not_contains</option>' +
            '<option value="regex">regex</option>' +
            '<option value="exists">exists</option>' +
            '<option value="empty">empty</option>' +
            '</select>' +
            '<input type="text" class="form-control tr-value" placeholder="Значение" style="flex: 1.5; padding: 4px; font-size: 12px; height: 32px;">' +
            '<span style="color: #a0aec0; font-size: 12px; margin: 0 2px;">➔</span>' +
            '<select class="form-control tr-target" style="flex: 2; padding: 4px; font-size: 12px; height: 32px;">' + optionsHtml + '</select>' +
            '<button type="button" class="btn-delete-transition" style="background:none; border:none; color:#dc3545; font-size:16px; cursor:pointer; padding:0 4px;">&times;</button>';

        const varSelect = row.querySelector('.tr-variable');
        fillVariablesSelectOptions(varSelect);
        const opSelect = row.querySelector('.tr-operator');
        const valInput = row.querySelector('.tr-value'); // Находим новый инпут
        const targetSelect = row.querySelector('.tr-target');
        const delBtn = row.querySelector('.btn-delete-transition');

        toggleTransitionValueVisibility(opSelect, valInput);

        if (currentStepData) {
            varSelect.onchange = () => syncTransitionsToStepState(currentStepData, type);
            opSelect.onchange = () => {
                toggleTransitionValueVisibility(opSelect, valInput);
                syncTransitionsToStepState(currentStepData, type);
            };
            valInput.oninput = () => syncTransitionsToStepState(currentStepData, type);
            targetSelect.onchange = () => syncTransitionsToStepState(currentStepData, type);
            delBtn.onclick = () => {
                row.remove();
                syncTransitionsToStepState(currentStepData, type);
            };
        }

        container.appendChild(row);
        if (currentStepData) syncTransitionsToStepState(currentStepData, type);
    };
});



const addStepToWorkflowBtn = document.getElementById('addStepToWorkflowBtn');
if (addStepToWorkflowBtn) {
    addStepToWorkflowBtn.onclick = async () => {
        const stepSelectEl = document.getElementById('availableStepsSelect');
        if (!stepSelectEl) return;

        const workflowId = editorWorkflowId();
        const typeId = stepSelectEl.value;

        if (!workflowId || !typeId) {
            showNotification('Не выбран workflow или тип шага', 'warning');
            return;
        }

        try {
            // Отправляем запрос на создание шага
            const response = await postData(`/workflow/${workflowId}/step`, {type_id: typeId});
            showNotification('Шаг успешно добавлен', 'success');

            // Перезагружаем список шагов
            await loadWorkflowSteps(workflowId);

            // UX-ФИКС: Автоматически прокручиваем контейнер вниз и активируем добавленный шаг
            setTimeout(() => {
                const container = document.getElementById('workflowStepsSortable');
                if (container) {
                    const steps = container.querySelectorAll('.step-item-block');
                    if (steps.length > 0) {
                        const lastStep = steps[steps.length - 1];
                        lastStep.scrollIntoView({behavior: 'smooth', block: 'nearest'});

                        // Если бэкенд возвращает созданный объект с ID, можно сразу сэмулировать клик
                        if (response && (response.id || response.result?.id)) {
                            const targetId = response.id || response.result.id;
                            const addedStepBlock = container.querySelector(`.step-item-block[data-id="${targetId}"]`);
                            if (addedStepBlock) addedStepBlock.click();
                        } else {
                            lastStep.click(); // Фолбек на последний элемент списка
                        }
                    }
                }
            }, 100);

        } catch (e) {
            console.error("Ошибка добавления шага:", e);
            showNotification('Ошибка добавления шага', 'error');
        }
    };
}

// --- Автосохранение деталей шага ---
// Селекты и чекбоксы сохраняются при изменении, textarea и текстовые поля —
// при уходе фокуса. Снимок состояния делается синхронно в момент события
// (пока таймер ждет, пользователь может переключиться на другой шаг —
// сохранится именно измененный), отправка — с коротким дебаунсом.
let stepAutoSavePending = null;
let stepAutoSaveTimer = null;

function stepAutoSaveSchedule() {
    const workflowId = editorWorkflowId();
    const activeStepBlock = document.querySelector('.step-item-block.active');
    if (!workflowId || !activeStepBlock) return;

    const stepId = activeStepBlock.dataset.id;
    const currentStepData = (state.allCurrentStepsData || []).find(s => String(s.id) === String(stepId));
    if (!currentStepData) return;

    // Собираем актуальное состояние: metadata обновляется виджетами живьем,
    // переходы интегрируем из UI (как делает кнопка Save)
    const metadata = parseMetadata(currentStepData.metadata);
    metadata.transitions_before = collectTransitions('Before');
    metadata.transitions_after = collectTransitions('After');
    metadata[TO_NEXT_STEP] = toNextStepValue();

    const stepTitleEl = document.getElementById('stepTitle');
    const title = (stepTitleEl && stepTitleEl.value.trim()) || currentStepData.title;

    currentStepData.metadata = JSON.stringify(metadata);
    currentStepData.title = title;

    stepAutoSavePending = {
        workflowId,
        stepId,
        payload: {metadata: currentStepData.metadata, title: title},
        titleEl: activeStepBlock.querySelector('.step-title-text'),
    };

    clearTimeout(stepAutoSaveTimer);
    stepAutoSaveTimer = setTimeout(stepAutoSaveFlush, 400);
}

async function stepAutoSaveFlush() {
    if (!stepAutoSavePending) return;
    const {workflowId, stepId, payload, titleEl} = stepAutoSavePending;
    stepAutoSavePending = null;

    try {
        await putData(`/workflow/${workflowId}/step/${stepId}`, payload);
        // Метка шага правилась на странице — перечитаем кэш «Undefined переменных»
        // для workflow слева и для панели графа: они считают по метаданным из стейта.
        invalidateUndefinedIndex(workflowId);
        if (titleEl) titleEl.textContent = payload.title;
        showNotification(`Шаг «${payload.title}» сохранен`, 'success');
    } catch (e) {
        console.error('Ошибка автосохранения шага:', e);
        showNotification(`Ошибка автосохранения шага: ${e.message}`, 'error');
    }
}

// Делегирование на всю колонку деталей: работает и для динамических
// виджетов, которые перерисовываются при каждом выборе шага
const stepDetailsViewEl = document.getElementById('stepDetailsView');
if (stepDetailsViewEl) {
    stepDetailsViewEl.addEventListener('change', (e) => {
        if (e.target.matches('select, input[type="checkbox"]')) stepAutoSaveSchedule();
    });
    stepDetailsViewEl.addEventListener('focusout', (e) => {
        if (e.target.matches('textarea, input[type="text"], input[type="number"]')) stepAutoSaveSchedule();
    });
}

// ⚠⚠ Правка, пришедшая **кнопкой**, своего события формы не имеет: клик не даёт
// ни `change`, ни `focusout`, и делегаты выше его не видят. Такой виджет
// сообщает о себе сам (`subflow-maps.js` — снос пары карты и добавление
// строки). Поймано живым прогоном: снос не доезжал до базы вовсе.
//
// ⚠ Через событие документа, а не прямым вызовом: виджеты лежат в
// `step-widgets.js`, который этот файл импортирует, — обратный импорт замкнул бы
// круг. Тем же приёмом ходит ссылка «Перейти в…» у шага подпотока.
document.addEventListener('workflow:step-dirty', stepAutoSaveSchedule);

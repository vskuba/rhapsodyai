// Точка входа редактора workflow (/admin/workflow): инициализация страницы,
// список workflow, переключение режимов, сохранение/удаление workflow

import {getData, putData, postData, deleteData} from '../api.js';
import {showNotification} from '../notification.js';
import {state} from './state.js';
import {parseMetadata} from './utils.js';
import {initGraphMode} from './graph.js';
import {loadWorkflowVariables, saveInputVariables, initVariablesHandlers} from './variables.js';
import {loadWorkflowSteps, loadAvailableStepTypes, collectTransitions} from './steps.js';

// Инициализация режима Graph (mermaid + кнопка)
initGraphMode();

const workflowListContainer = document.getElementById('workflowList');
const workflowForm = document.getElementById('workflowForm');
const deleteBtn = document.getElementById('deleteBtn');
const addStepBtn = document.getElementById('addStepToWorkflowBtn');

/**
 * Инициализация страницы: загрузка задач и нод для селекта
 */
async function initWorkflowManager() {
    try {
        const [workflowsRes, nodesRes, toolsRes] = await Promise.all([
            getData('/workflow/list'),
            getData('/node/list'),
            getData('/tool/list')
        ]);

        state.allAvailableTools = toolsRes.result || toolsRes || [];

        // Также загружаем типы шагов для селекта
        await loadAvailableStepTypes();

        const workflows = workflowsRes.result;
        state.allWorkflows = workflows || [];
        const nodes = nodesRes.result.sort((a, b) => a.position - b.position);

        const nodeSelect = document.getElementById('node_id');
        if (nodeSelect) {
            nodeSelect.innerHTML = '<option value="">Без ноды</option>';
            nodes.forEach(n => {
                nodeSelect.innerHTML += `<option value="${n.id}">${n.name}</option>`;
            });
        }

        const activeWorkflowLink = workflowListContainer.querySelector('.agent-item.active .workflow-name-link');
        const activeWorkflowLinkId = activeWorkflowLink ? activeWorkflowLink.id : null;

        // Запоминаем текущий режим: если открыта форма настроек workflow,
        // после перерисовки списка нужно остаться на ней, а не переключаться на шаги
        const settingsViewEl = document.getElementById('workflowSettingsView');
        const isSettingsViewOpen = !!activeWorkflowLinkId && settingsViewEl && settingsViewEl.style.display !== 'none';

        renderWorkflowList(workflows, nodes);
        initVariablesHandlers();

        if (activeWorkflowLinkId && workflowListContainer.querySelector('#' + activeWorkflowLinkId)) {
            const activeWorkflowLink = workflowListContainer.querySelector('#' + activeWorkflowLinkId);
            if (isSettingsViewOpen) {
                // Остаемся в форме редактирования: кликаем по иконке параметров
                const editIcon = activeWorkflowLink.closest('.agent-item')?.querySelector('.edit-icon');
                if (editIcon) {
                    editIcon.click();
                } else {
                    activeWorkflowLink.click();
                }
            } else {
                activeWorkflowLink.click();
            }
        } else {
            const firstWorkflowLink = workflowListContainer.querySelector('.agent-item .workflow-name-link');
            if (firstWorkflowLink) firstWorkflowLink.click();
        }

        if (deleteBtn) {
            deleteBtn.onclick = deleteWorkflow;
        }

    } catch (e) {
        console.error("Ошибка инициализации:", e);
    }
}

// Карусель нод: ноды в порядке position (+ «Вне нод» в конце), листается по кругу
let carouselNodes = [];
let carouselIndex = 0;
let sidebarWorkflows = [];

function renderWorkflowList(workflows, nodes) {
    sidebarWorkflows = workflows || [];

    carouselNodes = nodes.map(n => ({id: n.id, name: n.name}));
    if (sidebarWorkflows.some(w => !w.node_id) || carouselNodes.length === 0) {
        carouselNodes.push({id: 'none', name: 'Вне нод'});
    }

    // Показываем ноду активного workflow, чтобы выбор пережил перерисовку списка
    const activeLink = workflowListContainer.querySelector('.agent-item.active .workflow-name-link');
    if (activeLink) {
        const wfId = activeLink.id.replace('workflow_link_', '');
        const wf = sidebarWorkflows.find(w => String(w.id) === String(wfId));
        if (wf) {
            const idx = carouselNodes.findIndex(n => String(n.id) === String(wf.node_id || 'none'));
            if (idx >= 0) carouselIndex = idx;
        }
    }
    if (carouselIndex >= carouselNodes.length) carouselIndex = 0;

    renderCarouselNode();
}

function renderCarouselNode() {
    const node = carouselNodes[carouselIndex];
    const nameEl = document.getElementById('nodeCarouselName');
    if (nameEl) {
        nameEl.textContent = node.name;
        nameEl.title = node.name;
    }

    workflowListContainer.innerHTML = '';

    const nodeWorkflows = sidebarWorkflows.filter(w => String(w.node_id || 'none') === String(node.id));

    if (nodeWorkflows.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'workflow-list-empty';
        empty.textContent = 'В ноде нет workflow';
        workflowListContainer.appendChild(empty);
        return;
    }

    // Алфавитная сортировка; сверху — workflow агентов, под разделителем — subflow
    const byTitle = (a, b) => (a.title || a.name || '').localeCompare(b.title || b.name || '');
    const agentWorkflows = nodeWorkflows.filter(w => !w.subflow).sort(byTitle);
    const subflows = nodeWorkflows.filter(w => w.subflow).sort(byTitle);

    const renderItem = (workflow) => {
        const div = document.createElement('div');
        div.className = 'agent-item';

        div.innerHTML = `
    <span class="workflow-name-link" id="workflow_link_${workflow.id}" style="flex:1;">${workflow.title}</span>
    <div class="workflow-actions">
        <span class="edit-icon" title="Параметры задачи">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
            </svg>
        </span>
    </div>
`;

        // Клик по названию — ШАГИ
        div.querySelector('.workflow-name-link').onclick = () => openWorkflowSteps(workflow, div);

        // Клик по иконке — ПАРАМЕТРЫ
        div.querySelector('.edit-icon').onclick = () => openWorkflowSettings(workflow, div);

        workflowListContainer.appendChild(div);
    };

    agentWorkflows.forEach(renderItem);

    if (subflows.length > 0) {
        const divider = document.createElement('div');
        divider.className = 'workflow-divider';
        workflowListContainer.appendChild(divider);
        subflows.forEach(renderItem);
    }

    // Восстанавливаем выделение открытого workflow, если он в этой ноде
    const currentId = document.getElementById('workflowId')?.value;
    if (currentId) {
        const link = workflowListContainer.querySelector(`#workflow_link_${currentId}`);
        if (link) link.closest('.agent-item').classList.add('active');
    }
}

// Стрелки карусели: следующая/предыдущая нода по кругу
document.getElementById('nodeCarouselPrev')?.addEventListener('click', () => {
    if (!carouselNodes.length) return;
    carouselIndex = (carouselIndex - 1 + carouselNodes.length) % carouselNodes.length;
    renderCarouselNode();
});

document.getElementById('nodeCarouselNext')?.addEventListener('click', () => {
    if (!carouselNodes.length) return;
    carouselIndex = (carouselIndex + 1) % carouselNodes.length;
    renderCarouselNode();
});

async function openWorkflowSteps(workflow, element) {
    setActiveItem(element);

    // 1. ПЕРЕКЛЮЧАЕМ ВИДИМОСТЬ (Явно скрываем настройки и показываем шаги)
    document.getElementById('workflowSettingsView').style.display = 'none';
    document.getElementById('stepsEditorView').style.display = 'flex';
    document.getElementById('stepsGraph').style.display = 'none';
    document.getElementById('addStepToWorkflowBtn').style.display = 'block';

    // 2. ЗАПОЛНЯЕМ ДАННЫЕ
    await fillWorkflowForm(workflow);
    await loadWorkflowSteps(workflow.id);

    // 3. ОБНОВЛЯЕМ ЗАГОЛОВОК
    document.getElementById('formTitle').textContent = `Шаги workflow: ${workflow.title}`;
}

/**
 * Режим 2: Редактирование параметров задачи (без шагов)
 */
function openWorkflowSettings(workflow, element) {
    setActiveItem(element);

    // Переключаем видимость блоков
    document.getElementById('workflowSettingsView').style.display = 'flex';
    document.getElementById('stepsEditorView').style.display = 'none';
    document.getElementById('stepsGraph').style.display = 'none';
    document.getElementById('formTitle').textContent = `Редактирование задачи: ${workflow.title}`;

    fillWorkflowForm(workflow);
}

// Вспомогательные функции
function setActiveItem(el) {
    document.querySelectorAll('.agent-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
}

async function fillWorkflowForm(workflow) {
    document.getElementById('workflowId').value = workflow.id;
    document.getElementById('name').value = workflow.name || '';
    document.getElementById('title').value = workflow.title || '';
    document.getElementById('node_id').value = workflow.node_id || '';
    document.getElementById('position').value = workflow.position || 0;
    document.getElementById('description').value = workflow.description || '';
    document.getElementById('subflow').checked = !!workflow.subflow;

    if (workflow.id) {
        await loadWorkflowVariables(workflow.id);
    }

    deleteBtn.style.display = 'block';
}

async function deleteWorkflow() {
    const id = document.getElementById('workflowId')?.value;
    const title = document.getElementById('title')?.value;

    if (!id || !confirm(`Удалить задачу "${title}" со всеми её шагами?`)) {
        return;
    }

    try {
        await deleteData(`/workflow/${id}`);
        showNotification('Задача удалена', 'success');

        // После удаления перезагружаем всё, чтобы интерфейс обнулился
        await initWorkflowManager();
    } catch (e) {
        showNotification(`Ошибка удаления: ${e.message}`, 'error');
    }
}

/**
 * Сохранение изменений задачи
 */
workflowForm.onsubmit = async (e) => {
    e.preventDefault();

    const idEl = document.getElementById('workflowId');
    const id = idEl ? idEl.value : '';

    // 1. Безопасный сбор основного payload задачи
    const payload = {
        name: document.getElementById('name')?.value.trim() || '',
        title: document.getElementById('title')?.value || '',
        node_id: document.getElementById('node_id')?.value || null,
        description: document.getElementById('description')?.value || '',
        position: parseInt(document.getElementById('position')?.value) || 0,
        subflow: document.getElementById('subflow')?.checked ? 1 : 0,
    };

    try {
        if (id) {
            const activeStepBlock = document.querySelector('.step-item-block.active');

            if (activeStepBlock && state.allCurrentStepsData.length > 0) {
                const stepId = activeStepBlock.dataset.id;
                const currentStepData = state.allCurrentStepsData.find(s => String(s.id) === String(stepId));

                if (currentStepData) {
                    // Извлекаем текущие живые метаданные (они уже обновлены функциями ввода/oninput)
                    let metadata = parseMetadata(currentStepData.metadata);

                    // Интегрируем свежие переходы из UI в метаданные шага
                    metadata.transitions_before = collectTransitions("Before");
                    metadata.transitions_after = collectTransitions("After");

                    try {
                        // Сохраняем данные конкретного шага
                        const stepTitleEl = document.getElementById('stepTitle');
                        await putData(`/workflow/${id}/step/${stepId}`, {
                            metadata: JSON.stringify(metadata),
                            title: stepTitleEl ? stepTitleEl.value : currentStepData.title
                        });
                    } catch (stepErr) {
                        console.error("Ошибка сохранения шага:", stepErr);
                        showNotification(`Ошибка сохранения шага: ${stepErr.message}`, 'error');
                        return; // Прерываем операцию, если шаг не сохранился
                    }
                }
            }

            await putData(`/workflow/${id}`, payload);
            await saveInputVariables(id); // Создаем новые и обновляем измененные входящие переменные
            showNotification('Изменения успешно сохранены', 'success');
            await initWorkflowManager(); // Полностью обновляем списки в UI
        } else {
            const createRes = await postData('/workflow', payload);
            if (createRes && createRes.result && createRes.result.id) {
                await saveInputVariables(createRes.result.id);
            }
            showNotification('Новый workflow успешно создан!', 'success');

            await initWorkflowManager();

            if (createRes && createRes.result && createRes.result.id) {
                const newId = createRes.result.id;
                setTimeout(() => {
                    const allLinks = document.querySelectorAll('.workflow-name-link');
                    // Ищем ссылку, текст которой совпадает с названием нашего нового воркфлоу, и кликаем
                    allLinks.forEach(link => {
                        if (link.textContent.trim() === payload.title.trim()) {
                            link.click();
                        }
                    });
                }, 300);
            }
        }
    } catch (e) {
        console.error("Ошибка сохранения воркфлоу:", e);
        showNotification(e.message, 'error');
    }
};

/**
 * Логика кнопки "Создать задачу"
 */
const createNewWorkflowBtn = document.getElementById('createNewWorkflow');
if (createNewWorkflowBtn) {
    createNewWorkflowBtn.onclick = () => {
        document.querySelectorAll('.agent-item').forEach(el => el.classList.remove('active'));

        if (workflowForm) workflowForm.reset();

        const workflowIdEl = document.getElementById('workflowId');
        const nameEl = document.getElementById('name');
        const formTitleEl = document.getElementById('formTitle');

        if (workflowIdEl) workflowIdEl.value = '';
        if (nameEl) nameEl.value = '';
        if (formTitleEl) formTitleEl.textContent = 'Новый workflow';

        // Очищаем список входящих переменных предыдущего workflow
        const inputVarsContainer = document.getElementById('inputVariablesContainer');
        if (inputVarsContainer) inputVarsContainer.innerHTML = '';

        // Безопасно скрываем кнопки управления шагами для нового воркфлоу
        if (deleteBtn) deleteBtn.style.display = 'none';

        const addStepContainer = document.getElementById('addStepToWorkflowBtn') || addStepBtn;
        if (addStepContainer) addStepContainer.style.display = 'none';

        // Скрываем редактор шагов и показываем базовую форму
        const settingsView = document.getElementById('workflowSettingsView');
        const stepsView = document.getElementById('stepsEditorView');
        const graphView = document.getElementById('stepsGraph');
        if (settingsView) settingsView.style.display = 'flex';
        if (stepsView) stepsView.style.display = 'none';
        if (graphView) graphView.style.display = 'none';
    };
}

initWorkflowManager().catch(err => console.error("Критический сбой инициализации модуля:", err));

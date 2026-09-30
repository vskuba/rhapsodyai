// Точка входа редактора workflow (/admin/workflow): инициализация страницы,
// список workflow, переключение режимов, сохранение/удаление workflow

import {getData, putData, postData, deleteData} from '../api.js';
import {showNotification} from '../notification.js';
import {state} from './state.js';
import {parseMetadata, activateTab, savedTab} from './utils.js';
import {initGraphMode, openWorkflowGraph} from './graph.js';
import {loadWorkflowVariables, saveInputVariables, initVariablesHandlers} from './variables.js';
import {loadWorkflowSteps, loadAvailableStepTypes, collectTransitions} from './steps.js';
import {buildGroupTree, renderGroupTree} from '../agent_group_tree.js';
import {ensureUndefinedIndex, workflowUndefinedEntriesSync,
    onUndefinedIndexChange, invalidateUndefinedIndex} from './undefined-index.js';

// Инициализация режима Graph (mermaid)
initGraphMode();

// ⚠ Вкладка, на которой страницу оставили: снимаем её **до** первой загрузки
// списка. Открытие workflow показывает «Шаги» и тем самым перезапишет память —
// прочитай мы её позже, восстанавливать было бы нечего.
const tabToRestore = savedTab();

document.getElementById('tabSteps')?.addEventListener('click', async () => {
    const workflowId = document.getElementById('workflowId')?.value;
    if (!workflowId) return;
    activateTab('tabSteps');
    document.getElementById('workflowSettingsView').style.display = 'none';
    document.getElementById('stepsEditorView').style.display = 'flex';
    document.getElementById('stepsGraph').style.display = 'none';
    document.getElementById('addStepToWorkflowBtn').style.display = 'block';
    // Если шаги не загружены для этого workflow — загружаем
    if (!state.allCurrentStepsData?.length
        || String(state.allCurrentStepsData[0]?.workflow_id) !== String(workflowId)) {
        await loadWorkflowSteps(workflowId);
    }
});

document.getElementById('tabSettings')?.addEventListener('click', () => {
    if (!document.getElementById('workflowId')?.value) return;
    activateTab('tabSettings');
    document.getElementById('workflowSettingsView').style.display = 'flex';
    document.getElementById('stepsEditorView').style.display = 'none';
    document.getElementById('stepsGraph').style.display = 'none';
});

document.getElementById('tabGraph')?.addEventListener('click', () => {
    activateTab('tabGraph');
    openWorkflowGraph();
});

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
            getData('/tool/list'),
            // ⚠⚠ Сырьё индекса «Undefined переменных» — одним запросом на всю
            // страницу (указание хозяина: держать список переменных на фронте и
            // брать его быстрым чтением). Строки списка читают кэш синхронно,
            // потому загрузка — до отрисовки списка.
            ensureUndefinedIndex(),
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
        let activeWorkflowLinkId = activeWorkflowLink ? activeWorkflowLink.id : null;

        // Холодная перезагрузка страницы: DOM еще пуст (нет .agent-item.active) —
        // восстанавливаем выбор из sessionStorage, чтобы не улетать на первый пункт списка
        if (!activeWorkflowLinkId) {
            const savedWorkflowId = sessionStorage.getItem('workflow_selected_id');
            if (savedWorkflowId) {
                activeWorkflowLinkId = 'workflow_link_' + savedWorkflowId;
            }
        }

        renderWorkflowList(workflows, nodes);
        initVariablesHandlers();

        // Deep-link: /admin/workflow?workflow_id=N — открываем конкретный workflow
        // (только при первой загрузке, чтобы не сбивать навигацию после сохранений)
        const deepLinkId = new URLSearchParams(window.location.search).get('workflow_id');
        if (!deepLinkApplied && deepLinkId && openWorkflowById(deepLinkId)) {
            deepLinkApplied = true;
        } else if (activeWorkflowLinkId && workflowListContainer.querySelector('#' + activeWorkflowLinkId)) {
            workflowListContainer.querySelector('#' + activeWorkflowLinkId).click();
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
let deepLinkApplied = false;
// ⚠ Вкладку возвращаем **один раз за жизнь страницы**, как и deep-link рядом:
// список перечитывается после каждого сохранения, и без этой отметки правка в
// «Настройках» дёргала бы человека обратно на вкладку, где он уже стоит.
let tabRestored = false;

// Клик по ссылке sub-workflow в виджете шага (step-widgets.js шлет событие,
// прямой импорт оттуда невозможен — циклическая зависимость модулей)
document.addEventListener('workflow:open', (e) => {
    const workflowId = e.detail && e.detail.workflowId;
    if (workflowId) openWorkflowById(workflowId);
});

// Открывает workflow по id: переключает карусель на его ноду и кликает по ссылке
function openWorkflowById(workflowId) {
    const workflow = sidebarWorkflows.find(w => String(w.id) === String(workflowId));
    if (!workflow) return false;

    const nodeIndex = carouselNodes.findIndex(n => String(n.id) === String(workflow.node_id || 'none'));
    if (nodeIndex >= 0 && nodeIndex !== carouselIndex) {
        carouselIndex = nodeIndex;
        renderCarouselNode();
    }

    const link = workflowListContainer.querySelector(`#workflow_link_${workflow.id}`);
    if (!link) return false;
    link.click();
    return true;
}

function renderWorkflowList(workflows, nodes) {
    sidebarWorkflows = workflows || [];

    carouselNodes = nodes.map(n => ({id: n.id, name: n.name}));
    if (sidebarWorkflows.some(w => !w.node_id) || carouselNodes.length === 0) {
        carouselNodes.push({id: 'none', name: 'Вне нод'});
    }

    // Показываем ноду активного workflow, чтобы выбор пережил перерисовку списка
    const activeLink = workflowListContainer.querySelector('.agent-item.active .workflow-name-link');
    let activeNodeId = null;
    if (activeLink) {
        const wfId = activeLink.id.replace('workflow_link_', '');
        const wf = sidebarWorkflows.find(w => String(w.id) === String(wfId));
        if (wf) activeNodeId = wf.node_id || 'none';
    } else {
        // Холодная перезагрузка: DOM еще пуст — берем ноду из sessionStorage
        activeNodeId = sessionStorage.getItem('workflow_selected_node_id');
    }
    if (activeNodeId !== null) {
        const idx = carouselNodes.findIndex(n => String(n.id) === String(activeNodeId));
        if (idx >= 0) carouselIndex = idx;
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

    const byTitle = (a, b) => (a.title || a.name || '').localeCompare(b.title || b.name || '');
    const agentWorkflows = nodeWorkflows.filter(w => !w.subflow).sort(byTitle);
    const subflows = nodeWorkflows.filter(w => w.subflow).sort(byTitle);

    const makeItem = (workflow, depth = 0, indent = 10) => {
        const div = document.createElement('div');
        div.className = 'agent-item';
        if (depth > 0) div.style.paddingLeft = `${indent}px`;

        const label = (depth > 0 ? '· ' : '') + workflow.title;

        // ⚠⚠ Мигающая «!» в квадратике: в этом workflow шаги читают переменные,
        // которых не заведёт ни один его шаг. Список слева ничего не считает сам:
        // он показывает то, что посчитало правило из `variable-group.js`, по кэшу
        // `undefined-index.js`. Нет данных — нет значка: лучше молчание, чем вранье.
        const undefinedEntries = workflowUndefinedEntriesSync(workflow.id);
        const warnMark = (undefinedEntries && undefinedEntries.size > 0)
            ? `<span class="workflow-warn-mark" title="Неопределённые переменные читают ${undefinedEntries.size} шаг(ов): `
              + `${[...undefinedEntries.keys()].slice(0, 3).join(', ')}${undefinedEntries.size > 3 ? ' …' : ''}">!</span>`
            : '';

        div.innerHTML = `
    <div class="workflow-title-row">
        ${warnMark}<span class="workflow-name-link" id="workflow_link_${workflow.id}">${label}</span>
    </div>
`;

        div.querySelector('.workflow-name-link').onclick = () => openWorkflowSteps(workflow, div);

        return div;
    };

    renderGroupTree(
        buildGroupTree(agentWorkflows),
        workflowListContainer,
        0,
        `workflow_group_${node.id}`,
        (workflow, depth, indent) => makeItem(workflow, depth, indent)
    );

    if (subflows.length > 0) {
        const divider = document.createElement('div');
        divider.className = 'workflow-divider';
        workflowListContainer.appendChild(divider);
        subflows.forEach(w => workflowListContainer.appendChild(makeItem(w)));
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

/**
 * Дубликат workflow: сервер копирует строку agent_workflow (title + ' copy'),
 * шаги (с ремапом id в transitions и переменных результатов) и связи переменных
 */
async function duplicateWorkflow(workflow) {
    try {
        const res = await postData(`/workflow/${workflow.id}/duplicate`, {});
        const newId = res.result?.id;
        showNotification(`Создан дубликат: ${res.result?.title || workflow.title + ' copy'}`, 'success');
        await initWorkflowManager();
        if (newId) openWorkflowById(newId);
    } catch (e) {
        showNotification(`Ошибка дублирования: ${e.message}`, 'error');
    }
}

async function openWorkflowSteps(workflow, element) {
    setActiveItem(element);
    workflowSelectionSave(workflow);
    activateTab('tabSteps');

    document.getElementById('workflowSettingsView').style.display = 'none';
    document.getElementById('stepsEditorView').style.display = 'flex';
    document.getElementById('stepsGraph').style.display = 'none';
    document.getElementById('addStepToWorkflowBtn').style.display = 'block';

    await fillWorkflowForm(workflow);
    await loadWorkflowSteps(workflow.id);

    tabRestore();
}

/**
 * Вернуть вкладку, на которой страницу оставили. Один раз за жизнь страницы.
 *
 * ⚠⚠ **Отсюда, а не из загрузки списка.** Список открывает workflow щелчком по
 * ссылке, но `openWorkflowSteps` асинхронна: к возврату из `.click()` форма ещё
 * пуста. А обработчик «Настроек» первым делом смотрит на `workflowId` и при
 * пустом **молча выходит** — вкладка не вернулась бы, и выглядело бы это как
 * «иногда работает»: успеет форма заполниться или нет, зависит от скорости сети.
 *
 * ⚠ Один раз: список перечитывается после каждого сохранения, и без отметки
 * правка в «Настройках» возвращала бы человека на вкладку, где он уже стоит.
 */
function tabRestore() {
    if (tabRestored) return;

    tabRestored = true;

    // «Шаги» уже показаны открытием — щёлкать по ним значит грузить их заново.
    if (tabToRestore !== 'tabSteps') document.getElementById(tabToRestore)?.click();
}

// Запоминаем ноду и выбранный workflow, чтобы пережить перезагрузку страницы.
//
// ⚠ Вкладку здесь **не пишем**: её ведёт `activateTab` в `utils.js`, и каждый
// переход через неё проходит. Прежде эта функция писала ещё и режим
// («шаги»/«настройки») — но ту запись никто не читал, а вторая половина пары,
// `openWorkflowSettings`, не вызывалась ни разу: вкладку «Настройки» открывает
// её собственная кнопка. Половина механизма, которая молча ничего не делает,
// хуже отсутствующей — на неё смотрят и считают, что запоминание уже есть.
function workflowSelectionSave(workflow) {
    sessionStorage.setItem('workflow_selected_node_id', workflow.node_id || 'none');
    sessionStorage.setItem('workflow_selected_id', workflow.id);
}

// Вспомогательные функции
function setActiveItem(el) {
    document.querySelectorAll('.agent-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
}

async function fillWorkflowForm(workflow) {
    document.getElementById('workflowId').value = workflow.id;
    const wfIdEl = document.querySelector('.workflow-id');
    if (wfIdEl) wfIdEl.textContent = workflow.id ? `Workflow: #${workflow.id} ${workflow.name || ''}` : 'Workflow: #';
    document.getElementById('name').value = workflow.name || '';
    document.getElementById('title').value = workflow.title || '';
    document.getElementById('node_id').value = workflow.node_id || '';
    document.getElementById('group_name').value = workflow.group_name || '';
    document.getElementById('description').value = workflow.description || '';
    document.getElementById('subflow').checked = !!workflow.subflow;

    if (workflow.id) {
        await loadWorkflowVariables(workflow.id);
    }

    await renderParentWorkflows(workflow);
    await renderParentAgents(workflow);

    deleteBtn.style.display = 'block';
}

async function renderParentWorkflows(workflow) {
    const el = document.querySelector('.parent-workflow');
    if (!el) return;

    if (!workflow.subflow || !workflow.id) {
        el.style.display = 'none';
        return;
    }

    el.style.display = 'flex';
    el.innerHTML = '<div class="parent-workflow-label">↑ Вызывается из:</div><div class="parent-workflow-list">Загрузка...</div>';

    try {
        const data = await getData(`/workflow/${workflow.id}/parents`);
        const parents = data.result || [];
        const list = el.querySelector('.parent-workflow-list');
        if (!parents.length) {
            list.textContent = 'Не используется ни одним workflow';
            return;
        }
        list.innerHTML = parents.map(p =>
            `<a class="parent-workflow-chip" href="/admin/workflow?workflow_id=${p.id}" title="${p.name}">
                <svg width="10" height="10" viewBox="0 0 16 16" fill="none"><path d="M8 2L14 8L8 14M14 8H2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                ${p.title || p.name}
            </a>`
        ).join('');
    } catch (e) {
        el.querySelector('.parent-workflow-list').textContent = 'Ошибка загрузки';
    }
}

async function renderParentAgents(workflow) {
    const el = document.querySelector('.parent-agent');
    if (!el) return;

    if (!workflow.id) {
        el.style.display = 'none';
        return;
    }

    el.style.display = 'flex';
    el.innerHTML = '<div class="parent-agent-label">Агент:</div><div class="parent-agent-list">Загрузка...</div>';

    try {
        const data = await getData(`/workflow/${workflow.id}/agents`);
        const agents = data.result || [];
        const list = el.querySelector('.parent-agent-list');
        if (!agents.length) {
            el.style.display = 'none';
            return;
        }
        list.innerHTML = agents.map(a =>
            `<a class="parent-agent-chip" href="/admin/agent?agent_id=${a.id}" title="${a.name}">
                <svg width="10" height="10" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="5" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M2 14c0-3.3 2.7-5 6-5s6 1.7 6 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
                ${a.title || a.name}
            </a>`
        ).join('');
    } catch (e) {
        el.querySelector('.parent-agent-list').textContent = 'Ошибка загрузки';
    }
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
        group_name: document.getElementById('group_name')?.value.trim() || null,
        description: document.getElementById('description')?.value || '',
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
            // Кэш «Undefined переменных» по этому workflow протух: сохранение могло
            // завести/править переменные — значки в списке слева считают по свежему.
            invalidateUndefinedIndex(id);
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
        activateTab('tabSettings');

        const workflowIdEl = document.getElementById('workflowId');
        const nameEl = document.getElementById('name');

        if (workflowIdEl) workflowIdEl.value = '';
        if (nameEl) nameEl.value = '';

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

/**
 * Экспорт и импорт workflow узла карусели.
 *
 * Экспорт — скачивание .json со всеми workflow текущей ноды; импорт — выбор
 * такого файла, подтверждение и замена workflow ноды на его содержимое.
 * Сервер сохраняет исходные id (они зашиты внутри metadata), детали — в
 * `src/uvicorn/routers/workflow/workflow_export.py` и `workflow_import.py`.
 */
const exportWorkflowsBtn = document.getElementById('exportWorkflowsBtn');
const importWorkflowsBtn = document.getElementById('importWorkflowsBtn');
const importWorkflowsFile = document.getElementById('importWorkflowsFile');

// Нода карусели — вот её узел и экспортируем, и заменяем; «Вне нод» — 'none'.
function currentCarouselNode() {
    return carouselNodes[carouselIndex] || null;
}

function currentNodeParam(node) {
    return node.id === 'none' ? 'none' : String(node.id);
}

function fileStamp() {
    // Метка в UTC: имя файла пересылают между машинами, местный пояс в нём только путает.
    return new Date().toISOString().replace('T', '_').slice(0, 19);
}

if (exportWorkflowsBtn) {
    exportWorkflowsBtn.onclick = async () => {
        const node = currentCarouselNode();
        if (!node) {
            showNotification('Нода не выбрана — нечего экспортировать', 'error');
            return;
        }
        exportWorkflowsBtn.disabled = true;
        try {
            const res = await getData(`/workflow/export?node_id=${encodeURIComponent(currentNodeParam(node))}`);
            const payload = res.result;
            const blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'});
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = `workflow_export_${(payload.node ? payload.node.name : 'vne_nod').replace(/\s+/g, '_')}_${fileStamp()}.json`;
            link.click();
            URL.revokeObjectURL(link.href);
            let message = `Экспортировано workflow: ${payload.workflows.length}, шагов: ${payload.steps.length}`;
            if (payload.warnings.length) message += ` — предупреждений: ${payload.warnings.length}`;
            showNotification(message, payload.warnings.length ? 'warning' : 'success');
        } catch (e) {
            showNotification(e.message, 'error');
        } finally {
            exportWorkflowsBtn.disabled = false;
        }
    };
}

if (importWorkflowsBtn && importWorkflowsFile) {
    importWorkflowsBtn.onclick = () => {
        if (!currentCarouselNode()) {
            showNotification('Нода не выбрана', 'error');
            return;
        }
        importWorkflowsFile.click();
    };

    importWorkflowsFile.onchange = async () => {
        const file = importWorkflowsFile.files[0];
        // Снимаем выбор сразу: повторный выбор того же файла должен снова дать onchange.
        importWorkflowsFile.value = '';
        if (!file) return;

        let payload;
        try {
            payload = JSON.parse(await file.text());
        } catch (e) {
            showNotification(`Файл не читается как JSON: ${e.message}`, 'error');
            return;
        }
        // Метку формата и версию проверяет сервер (авторитет) — и отвечает внятным
        // 400 на чужой файл; третья копия метки здесь была бы не нужна.

        const fileNodeName = payload.node ? payload.node.name : 'Вне нод';
        const currentNode = currentCarouselNode();
        const currentName = currentNode ? currentNode.name : '—';
        const fileCount = (payload.workflows || []).length;
        const doomedCount = sidebarWorkflows.filter(
            w => String(w.node_id || 'none') === currentNodeParam(currentNode)).length;

        // Файл всегда заменяет СВОЮ ноду — если пользователь стоит на другой,
        // об этом надо спросить, а не подменять цель молча.
        const foreign = fileNodeName !== currentName;
        const question = foreign
            ? `Файл для ноды «${fileNodeName}», а в карусели выбрана «${currentName}».\n\n` +
              `Заменить workflow ноды «${fileNodeName}»? Все её текущие будут удалены, в файле: ${fileCount}.\n` +
              `Нода «${currentName}» останется без изменений.`
            : `Заменить workflow ноды «${currentName}»?\n\n` +
              `Сейчас в ноде: ${doomedCount}. В файле: ${fileCount}. Остальные ноды не изменятся.`;
        if (!confirm(question)) return;

        importWorkflowsBtn.disabled = true;
        try {
            const res = await postData('/workflow/import', payload);
            const result = res.result;
            let message = `Импорт: workflow ${result.workflows_imported}, шагов ${result.steps_imported}`;
            if (result.agents_rebound) message += `, агентов возвращено ${result.agents_rebound}`;
            showNotification(message, 'success');
            (result.notes || []).forEach(note => showNotification(note, 'warning'));

            // Открытый workflow мог быть удалён заменой — сбрасываем выбор и
            // перетаскиваем карусель на ноду файла: импорт меняет именно её.
            sessionStorage.removeItem('workflow_selected_id');
            await initWorkflowManager();
            const fileNodeIndex = carouselNodes.findIndex(
                n => n.name === (payload.node ? payload.node.name : 'Вне нод'));
            if (fileNodeIndex >= 0 && fileNodeIndex !== carouselIndex) {
                carouselIndex = fileNodeIndex;
                renderCarouselNode();
            }
            if (!workflowListContainer.querySelector('.agent-item.active') && createNewWorkflowBtn) {
                // Нода осталась пустой (или активной строки нет) — чистый редактор,
                // а не старый workflow, которого в базе уже нет.
                createNewWorkflowBtn.click();
            }
        } catch (e) {
            // Сервер при любой ошибке откатывает транзакцию — база остаётся как была.
            showNotification(e.message, 'error');
        } finally {
            importWorkflowsBtn.disabled = false;
        }
    };
}

// Индекс «Undefined переменных»: сырьё догрузилось или кэш сброшен — значки в
// левом списке расставляют заново, не дожидаясь, пока человек полистает карусель.
onUndefinedIndexChange(() => {
    try {
        renderCarouselNode();
    } catch (e) {
        console.error('Не удалось перерисовать список после обновления индекса:', e);
    }
});

initWorkflowManager().catch(err => console.error("Критический сбой инициализации модуля:", err));

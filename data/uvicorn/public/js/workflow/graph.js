// Режим 3: Граф переходов workflow (mermaid)

import {state} from './state.js';
import {parseMetadata, graphLabelEscape} from './utils.js';
import {showNotification} from '../notification.js';

// Функции из других модулей (steps), передаются через initGraphMode —
// пока steps-код живет в шаблоне, прямой import невозможен
let deps = {
    loadWorkflowSteps: null,
    selectStep: null,
};

/**
 * Инициализация режима графа: настройка mermaid и кнопка Graph.
 * dependencies: {loadWorkflowSteps, selectStep}
 */
export function initGraphMode(dependencies) {
    deps = dependencies;

    if (window.mermaid) {
        window.mermaid.initialize({startOnLoad: false, securityLevel: 'strict', flowchart: {curve: 'basis'}});
    }

    const graphBtn = document.getElementById('graphBtn');
    if (graphBtn) {
        graphBtn.onclick = () => openWorkflowGraph();
    }
}

/**
 * Строит mermaid-описание графа шагов workflow.
 * Ребра: сплошные — последовательное выполнение, пунктирные — условные переходы
 * (before/after) и continue_workflow. Возвращает {definition, warnings}.
 */
export function buildWorkflowGraphDefinition(steps) {
    const warnings = [];
    const stepsSorted = [...steps].sort((a, b) => (a.position || 0) - (b.position || 0));
    const stepIds = new Set(stepsSorted.map(s => String(s.id)));
    const hasIncoming = new Set();

    const lines = ['flowchart TD'];

    // Узлы: форма по типу (терминальные — "стадион"), класс по типу шага
    stepsSorted.forEach((step, index) => {
        const type = state.allWorkflowStepsType[step.type_id] || {};
        const typeName = type.name || 'unknown';
        const label = graphLabelEscape(`${type.icon || ''} ${index + 1}. ${step.title || type.description || ''}`);
        const isTerminal = typeName === 'return_response_llm' || typeName === 'return_response_text';
        const shape = isTerminal ? `(["${label}"])` : `["${label}"]`;
        lines.push(`S${step.id}${shape}:::type_${typeName}`);
    });

    if (stepsSorted.length > 0) {
        lines.push('START((▶)):::start_node');
        lines.push(`START --> S${stepsSorted[0].id}`);
        hasIncoming.add(String(stepsSorted[0].id));
    }

    // Ребра
    stepsSorted.forEach((step, index) => {
        const typeName = (state.allWorkflowStepsType[step.type_id] || {}).name || '';
        const metadata = parseMetadata(step.metadata);
        const next = stepsSorted[index + 1];

        // Последовательный переход к следующему шагу по position
        if (next) {
            if (typeName === 'return_response_llm') {
                // Терминальный шаг: workflow завершается, продолжения нет
            } else if (typeName === 'return_response_text') {
                if (metadata.continue_workflow) {
                    lines.push(`S${step.id} -. "следующий запрос" .-> S${next.id}`);
                    hasIncoming.add(String(next.id));
                }
            } else {
                lines.push(`S${step.id} --> S${next.id}`);
                hasIncoming.add(String(next.id));
            }
        }

        // Условные переходы before/after
        ['transitions_before', 'transitions_after'].forEach(key => {
            const suffix = key === 'transitions_before' ? 'before' : 'after';
            const transitions = Array.isArray(metadata[key]) ? metadata[key] : [];
            transitions.forEach(tr => {
                if (!tr || !tr.step_id) return;
                const target = String(tr.step_id);
                const cond = graphLabelEscape(`${tr.variable} ${tr.operator || '=='} ${tr.value ?? ''} (${suffix})`);

                if (!stepIds.has(target)) {
                    warnings.push(`Шаг "${step.title}" (id ${step.id}): переход (${suffix}) на несуществующий шаг id ${target}`);
                    return;
                }
                lines.push(`S${step.id} -. "${cond}" .-> S${target}`);
                hasIncoming.add(target);
            });
        });
    });

    // Недостижимые шаги: нет ни одного входящего ребра
    stepsSorted.forEach(step => {
        if (!hasIncoming.has(String(step.id))) {
            warnings.push(`Шаг "${step.title}" (id ${step.id}) недостижим: нет входящих переходов`);
            lines.push(`class S${step.id} unreachable`);
        }
    });

    // Стили по типам шагов (в цветах редактора)
    lines.push('classDef start_node fill:#2c3e50,stroke:#2c3e50,color:#fff;');
    lines.push('classDef type_return_response_llm fill:#d4efdf,stroke:#27ae60,color:#1e6b3a;');
    lines.push('classDef type_return_response_text fill:#d4efdf,stroke:#27ae60,color:#1e6b3a;');
    lines.push('classDef type_llm_to_json fill:#e8daef,stroke:#8e44ad,color:#5b2c6f;');
    lines.push('classDef type_tool_invoke fill:#fdebf3,stroke:#f488d5,color:#943b6d;');
    lines.push('classDef type_variable_conversion fill:#e3f0ff,stroke:#2974df,color:#1a4d8f;');
    lines.push('classDef unreachable fill:#fdecea,stroke:#e74c3c,color:#922b21,stroke-width:2px;');

    return {definition: lines.join('\n'), warnings};
}

/**
 * Открывает режим графа: скрывает настройки/шаги, строит и рендерит диаграмму.
 */
export async function openWorkflowGraph() {
    const workflowId = document.getElementById('workflowId').value;
    if (!workflowId) {
        showNotification('Сначала выберите workflow', 'warning');
        return;
    }

    document.getElementById('workflowSettingsView').style.display = 'none';
    document.getElementById('stepsEditorView').style.display = 'none';
    document.getElementById('stepsGraph').style.display = 'block';

    const container = document.getElementById('stepsGraphContainer');
    const warningsBox = document.getElementById('stepsGraphWarnings');
    container.innerHTML = '<div style="color:#999; padding:20px;">Построение графа...</div>';
    warningsBox.innerHTML = '';

    // Из режима настроек шаги могли не загружаться (или лежат от другого workflow)
    if (!Array.isArray(state.allCurrentStepsData) || state.allCurrentStepsData.length === 0
        || String(state.allCurrentStepsData[0].workflow_id) !== String(workflowId)) {
        await deps.loadWorkflowSteps(workflowId);
        // loadWorkflowSteps показывает редактор шагов через selectStep — возвращаем граф
        document.getElementById('stepsEditorView').style.display = 'none';
        document.getElementById('stepsGraph').style.display = 'block';
    }

    if (!Array.isArray(state.allCurrentStepsData) || state.allCurrentStepsData.length === 0) {
        container.innerHTML = '<div style="color:#999; text-align:center; padding:40px;">У этого workflow пока нет шагов</div>';
        return;
    }

    const {definition, warnings} = buildWorkflowGraphDefinition(state.allCurrentStepsData);

    warnings.forEach(w => {
        const div = document.createElement('div');
        div.textContent = '⚠️ ' + w;
        warningsBox.appendChild(div);
    });

    if (!window.mermaid) {
        container.innerHTML = '<div style="color:#c0392b;">Библиотека mermaid не загружена (/static/js/vendor/mermaid.min.js)</div>';
        return;
    }

    try {
        const renderId = 'wfGraphSvg' + Date.now();
        const {svg} = await window.mermaid.render(renderId, definition);
        container.innerHTML = svg;
        attachGraphNodeHandlers(container);
    } catch (e) {
        console.error('Ошибка построения графа:', e, definition);
        container.innerHTML = `<div style="color:#c0392b;">Не удалось построить граф: ${e.message}</div>`;
    }
}

/**
 * Навешивает интерактив на узлы графа: клик — переход в редактор шагов
 * с выбором шага; активный в редакторе шаг подсвечивается рамкой.
 */
function attachGraphNodeHandlers(container) {
    const activeStepBlock = document.querySelector('.step-item-block.active');
    const activeId = activeStepBlock ? String(activeStepBlock.dataset.id) : null;

    container.querySelectorAll('.node').forEach(nodeEl => {
        // id узла в DOM имеет вид "flowchart-S25-12"
        const m = (nodeEl.id || '').match(/-S(\d+)-/);
        if (!m) return;
        const stepId = m[1];

        if (activeId === stepId) {
            nodeEl.querySelectorAll('rect, polygon, path').forEach(shape => {
                shape.style.stroke = '#e67e22';
                shape.style.strokeWidth = '3px';
            });
        }

        nodeEl.addEventListener('click', () => {
            const step = state.allCurrentStepsData.find(s => String(s.id) === stepId);
            if (!step) return;

            // Возвращаемся в редактор шагов и выбираем кликнутый шаг
            document.getElementById('stepsGraph').style.display = 'none';
            document.getElementById('stepsEditorView').style.display = 'flex';
            const stepBlock = document.querySelector(`.step-item-block[data-id="${stepId}"]`);
            if (stepBlock) deps.selectStep(step, stepBlock);
        });
    });
}

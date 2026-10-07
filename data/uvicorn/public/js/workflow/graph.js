// Режим 3: Граф переходов workflow (mermaid)

// Ключ галочки «to next step». ⚠ То же имя, что у движка и редактора:
// разойдутся — граф покажет путь, которого нет, или скроет живой.
const TO_NEXT_STEP = 'to_next_step';

import {state} from './state.js';
import {branchRoadOf, branchRoadsLoad} from './branch-roads.js';
import {parseMetadata, graphLabelEscape, activateTab, editorWorkflowId} from './utils.js';
import {showNotification} from '/static/js/notification.js';
import {loadWorkflowSteps, selectStep} from './steps.js';
import {getData} from '../api.js';
import {variablesTrace, VAR_GROUP_UNKNOWN} from './variable-group.js';
import {editorVariableGroupIndex} from './variables.js';
import {workflowUndefinedEntries,
    workflowUndefinedEntriesSync} from './variable-undefined.js';

export function initGraphMode() {
    if (window.mermaid) {
        window.mermaid.initialize({startOnLoad: false, securityLevel: 'strict', flowchart: {curve: 'basis'}});
    }
}

// Fetch steps for a sub-workflow by ID
async function _fetchSubflowSteps(workflowId) {
    try {
        const data = await getData(`/workflow/${workflowId}/steps`);
        return data.result || [];
    } catch (e) {
        console.warn(`Не удалось загрузить шаги workflow ${workflowId}:`, e);
        return [];
    }
}

// Подпоток, который стоит за шагом: у `workflow_invoke` он в метаданных, у
// `branch` — в реестре веток по номеру ветки.
//
// ⚠ Реестр спрашивается общей `branchRoadOf` (`branch-roads.js`): своей копии
// карты здесь быть не должно, её читают трое.
function _stepSubflowId(step) {
    const type = state.allWorkflowStepsType[step.type_id] || {};
    const meta = parseMetadata(step.metadata);

    if (type.name === 'workflow_invoke') {
        const wfId = meta?.workflow_invoke?.workflow_id;
        return wfId ? String(wfId) : null;
    }
    if (type.name === 'branch') {
        const branchId = meta?.branch?.branch_id;
        return branchId ? branchRoadOf(branchId) : null;
    }
    return null;
}

// Collect workflow_invoke / branch sub-workflow IDs referenced in steps
function _collectSubflowIds(steps) {
    const ids = new Set();
    steps.forEach(step => {
        const wfId = _stepSubflowId(step);
        if (wfId) ids.add(wfId);
    });
    return ids;
}

// Recursively fetch all subflow steps (up to depth 4)
async function _fetchAllSubflowSteps(steps, acc = {}, depth = 0) {
    if (depth > 4) return acc;
    const ids = _collectSubflowIds(steps);
    const pending = [...ids].filter(id => !acc[id]);
    if (!pending.length) return acc;
    await Promise.all(pending.map(async id => {
        const subSteps = await _fetchSubflowSteps(id);
        acc[id] = subSteps;
        await _fetchAllSubflowSteps(subSteps, acc, depth + 1);
    }));
    return acc;
}

// Build mermaid lines for a set of steps (recursive).
// prefix     — string prefix for all node IDs to avoid conflicts across workflows
// includeStart — emit START((▶)) node for top-level only
// Returns lines array (no flowchart header, no classDef).
function _buildInnerLines(steps, prefix, subflowStepsMap, warnings, includeStart) {
    const lines = [];
    const stepsSorted = [...steps].sort((a, b) => (a.position || 0) - (b.position || 0));
    const stepIds = new Set(stepsSorted.map(s => String(s.id)));

    // ── 1. Node definitions ──────────────────────────────────────────────────
    stepsSorted.forEach((step, index) => {
        const type = state.allWorkflowStepsType[step.type_id] || {};
        const typeName = type.name || 'unknown';
        const label = graphLabelEscape(`${type.icon || ''} ${index + 1}. ${step.title || type.description || ''}`);
        const isTerminal = typeName === 'return_response_llm' || typeName === 'return_response_text';
        const shape = isTerminal ? `(["${label}"])` : `["${label}"]`;
        const nodeId = `${prefix}S${step.id}`;
        lines.push(`  ${nodeId}${shape}:::type_${typeName}`);

        // Inline subgraph for workflow_invoke / branch with known sub-workflow steps
        if (typeName === 'workflow_invoke' || typeName === 'branch') {
            const subWfId = _stepSubflowId(step);
            const subSteps = subWfId ? subflowStepsMap[subWfId] : null;
            if (subSteps && subSteps.length > 0) {
                const subWf = (state.allWorkflows || []).find(w => String(w.id) === subWfId);
                const subTitle = graphLabelEscape(subWf ? (subWf.title || subWf.name) : `Workflow ${subWfId}`);
                const sgId = `${prefix}SG${step.id}`;
                const subPrefix = `${prefix}W${subWfId}_`;
                lines.push(`  subgraph ${sgId}["${subTitle}"]`);
                lines.push(..._buildInnerLines(subSteps, subPrefix, subflowStepsMap, warnings, false));
                lines.push(`  end`);
                lines.push(`  class ${sgId} subflow_group`);
            }
        }
    });

    // ── 2. START node (top-level only) ───────────────────────────────────────
    if (includeStart && stepsSorted.length > 0) {
        lines.push(`  ${prefix}START((▶)):::start_node`);
        lines.push(`  ${prefix}START --> ${prefix}S${stepsSorted[0].id}`);
    }

    // ── 3. Edges ─────────────────────────────────────────────────────────────
    stepsSorted.forEach((step, index) => {
        const type = state.allWorkflowStepsType[step.type_id] || {};
        const typeName = type.name || 'unknown';
        const meta = parseMetadata(step.metadata);
        const next = stepsSorted[index + 1];
        const nodeId = `${prefix}S${step.id}`;
        const isTerminal = typeName === 'return_response_llm' || typeName === 'return_response_text';

        // Sequential → next step
        //
        // ⚠⚠ **Снятая галочка «to next step» убирает эту стрелку.** Она рисуется
        // всем подряд и оттого показывает путь, которого может не быть: у шага
        // развилки следующий по номеру — чужая ветка, и поток туда не идёт.
        // Человек же читал стрелку как «идёт», и разобраться, куда поток попадёт
        // на самом деле, можно было только по условиям переходов.
        //
        // ⚠ Ключа нет — стрелка рисуется: так вёл себя граф до появления
        // галочки, и все прежние шаги должны выглядеть как выглядели.
        if (next && meta[TO_NEXT_STEP] !== false) {
            if (isTerminal) {
                if (typeName === 'return_response_text' && meta.continue_workflow) {
                    lines.push(`  ${nodeId} -. "следующий запрос" .-> ${prefix}S${next.id}`);
                }
            } else {
                lines.push(`  ${nodeId} --> ${prefix}S${next.id}`);
            }
        }

        // workflow_invoke: entry edge → first sub-step; repeat loop inside subgraph
        if (typeName === 'workflow_invoke') {
            const invoke = meta?.workflow_invoke || {};
            const subWfId = invoke.workflow_id ? String(invoke.workflow_id) : null;
            const subSteps = subWfId ? subflowStepsMap[subWfId] : null;
            if (subSteps && subSteps.length > 0) {
                const subSorted = [...subSteps].sort((a, b) => (a.position || 0) - (b.position || 0));
                const subPrefix = `${prefix}W${subWfId}_`;
                // Entry: invoke node → first sub-workflow step
                lines.push(`  ${nodeId} --> ${subPrefix}S${subSorted[0].id}`);

                // ⚠⚠ **И возврат обратно.** Подпрогон всегда отдаёт результат
                // вызвавшему шагу: движок кладёт его переменные в `variables`
                // родителя по `outputs_map`, а прогон продолжается с того же
                // места (`ai_framework_manager`, ветка `workflow_invoke`).
                //
                // Рисовалась только стрелка входа, и граф читался так, будто
                // поток уходит в подпрогон и там кончается. По нему нельзя было
                // понять, откуда родитель берёт то, что кладёт следующий шаг.
                //
                // ⚠ Сплошной, как и вход: возврат случается **всегда**, а не
                // при условии. Пунктир на этом графе означает «может не
                // произойти» — им нарисованы повтор подпрогона (`↩ until …`) и
                // условные переходы. Отдай мы возврату тот же вид, читающий
                // искал бы условие, которого нет.
                const backFrom = `${subPrefix}S${subSorted[subSorted.length - 1].id}`;
                const backLabel = _invokeReturnLabel(invoke);
                lines.push(`  ${backFrom} -- "${backLabel}" --> ${nodeId}`);
                // Repeat loop: last sub-step ↩ first sub-step (condition from invoke metadata)
                if (invoke.repeat?.until) {
                    const {variable, operator = '==', value = ''} = invoke.repeat.until;
                    const label = graphLabelEscape(`↩ until ${variable} ${operator} ${value}`);
                    const lastId = `${subPrefix}S${subSorted[subSorted.length - 1].id}`;
                    const firstId = `${subPrefix}S${subSorted[0].id}`;
                    lines.push(`  ${lastId} -. "${label}" .-> ${firstId}`);
                }
            }
        }

        // transitions_before / transitions_after (conditional jumps)
        ['transitions_before', 'transitions_after'].forEach(key => {
            const suffix = key === 'transitions_before' ? 'before' : 'after';
            const transitions = Array.isArray(meta[key]) ? meta[key] : [];
            const deadAfter = suffix === 'after' && isTerminal && transitions.length > 0;
            if (deadAfter) {
                warnings.push(`Шаг "${step.title}" (id ${step.id}): transitions_after у финального шага не сработают`);
            }
            transitions.forEach(tr => {
                if (!tr || !tr.step_id) return;
                if (!stepIds.has(String(tr.step_id))) {
                    warnings.push(`Шаг "${step.title}" (id ${step.id}): переход (${suffix}) на несуществующий шаг id ${tr.step_id}`);
                    return;
                }
                const cond = graphLabelEscape(`${deadAfter ? '⚠ ' : ''}${tr.variable} ${tr.operator || '=='} ${tr.value ?? ''} (${suffix})`);
                lines.push(`  ${nodeId} -. "${cond}" .-> ${prefix}S${tr.step_id}`);
            });
        });
    });

    // Unreachable steps: no incoming edges
    const hasIncoming = new Set();
    if (stepsSorted.length > 0) hasIncoming.add(String(stepsSorted[0].id));
    stepsSorted.forEach((step, index) => {
        const typeName = (state.allWorkflowStepsType[step.type_id] || {}).name || '';
        const meta = parseMetadata(step.metadata);
        const next = stepsSorted[index + 1];
        // ⚠ Тот же довод: шаг, в который стрелки не будет, не считается
        // «имеющим входящие» — иначе граф счёл бы ветку достижимой по номеру.
        if (next && typeName !== 'return_response_llm'
                && meta[TO_NEXT_STEP] !== false) hasIncoming.add(String(next.id));
        ['transitions_before', 'transitions_after'].forEach(key => {
            (Array.isArray(meta[key]) ? meta[key] : []).forEach(tr => {
                if (tr?.step_id) hasIncoming.add(String(tr.step_id));
            });
        });
    });
    stepsSorted.forEach(step => {
        if (!hasIncoming.has(String(step.id)) && !includeStart) return; // only warn at top level
        if (!hasIncoming.has(String(step.id)) && includeStart) {
            warnings.push(`Шаг "${step.title}" (id ${step.id}) недостижим`);
            lines.push(`  class ${prefix}S${step.id} unreachable`);
        }
    });

    return lines;
}

/**
 * Builds mermaid definition for the given steps + all referenced sub-workflows.
 * subflowStepsMap: { workflowId: steps[] }
 */
/**
 * Подпись стрелки возврата из подпрогона: что именно он отдаёт родителю.
 *
 * ⚠ Имена переменных, а не «результат вообще»: по ним видно, ради чего вызов и
 * сделан. Их до трёх — дальше многоточие, иначе подпись растянет узел вдвое.
 */
function _invokeReturnLabel(invoke) {
    const outputs = Object.values((invoke && invoke.outputs_map) || {})
        .filter(one => typeof one === 'string' && one);

    if (outputs.length === 0) return '↩';

    const shown = outputs.slice(0, 3).join(', ');

    return graphLabelEscape(`↩ ${shown}${outputs.length > 3 ? '…' : ''}`);
}

export function buildWorkflowGraphDefinition(steps, subflowStepsMap = {}) {
    const warnings = [];
    const lines = ['flowchart TD'];
    lines.push(..._buildInnerLines(steps, '', subflowStepsMap, warnings, true));
    lines.push('classDef start_node fill:#2c3e50,stroke:#2c3e50,color:#fff;');
    lines.push('classDef type_return_response_llm fill:#d4efdf,stroke:#27ae60,color:#1e6b3a;');
    lines.push('classDef type_return_response_text fill:#d4efdf,stroke:#27ae60,color:#1e6b3a;');
    lines.push('classDef type_llm_to_json fill:#e8daef,stroke:#8e44ad,color:#5b2c6f;');
    lines.push('classDef type_llm_to_json_variable fill:#e8daef,stroke:#8e44ad,color:#5b2c6f;');
    lines.push('classDef type_tool_invoke fill:#fdebf3,stroke:#f488d5,color:#943b6d;');
    lines.push('classDef type_variable_conversion fill:#e3f0ff,stroke:#2974df,color:#1a4d8f;');
    lines.push('classDef type_workflow_invoke fill:#fff3e0,stroke:#f39c12,color:#9c640c;');
    lines.push('classDef type_llm_to_image fill:#fef9c3,stroke:#d97706,color:#78350f;');
    lines.push('classDef type_branch fill:#e8f6ec,stroke:#3fa45b,color:#1e6b3a;');
    lines.push('classDef unreachable fill:#fdecea,stroke:#e74c3c,color:#922b21,stroke-width:2px;');
    lines.push('classDef subflow_group fill:#f0f9ff,stroke:#3b82f6,color:#1e40af,stroke-width:2px;');
    return {definition: lines.join('\n'), warnings};
}

/**
 * Opens graph mode: loads steps, fetches all sub-workflow steps recursively, renders diagram.
 */
export async function openWorkflowGraph() {
    const workflowId = editorWorkflowId();
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

    if (!Array.isArray(state.allCurrentStepsData) || state.allCurrentStepsData.length === 0
        || String(state.allCurrentStepsData[0]?.workflow_id) !== String(workflowId)) {
        await loadWorkflowSteps(workflowId);
        document.getElementById('stepsEditorView').style.display = 'none';
        document.getElementById('stepsGraph').style.display = 'block';
    }

    if (!Array.isArray(state.allCurrentStepsData) || state.allCurrentStepsData.length === 0) {
        container.innerHTML = '<div style="color:#999; text-align:center; padding:40px;">У этого workflow пока нет шагов</div>';
        return;
    }

    // ⚠ Реестр веток читается ДО обхода подпотоков: без него шаг `branch` не
    // знает, какой подпоток за ним стоит, и граф нарисовал бы его пустым.
    const graphWorkflow = (state.allWorkflows || [])
        .find(w => String(w.id) === String(workflowId));
    await branchRoadsLoad(graphWorkflow && graphWorkflow.node_id);

    // Fetch all sub-workflow steps recursively
    const subflowStepsMap = await _fetchAllSubflowSteps(state.allCurrentStepsData);

    const {definition, warnings} = buildWorkflowGraphDefinition(state.allCurrentStepsData, subflowStepsMap);

    warnings.forEach(w => {
        const div = document.createElement('div');
        div.textContent = '⚠️ ' + w;
        warningsBox.appendChild(div);
    });

    if (!window.mermaid) {
        container.innerHTML = '<div style="color:#c0392b;">Библиотека mermaid не загружена</div>';
        return;
    }

    try {
        const renderId = 'wfGraphSvg' + Date.now();
        const {svg} = await window.mermaid.render(renderId, definition);
        container.innerHTML = svg;
        // hint stays as last child — re-append after innerHTML reset
        const hint = document.createElement('div');
        hint.className = 'graph-hint';
        hint.textContent = 'колёсико — масштаб · стик — перемещение';
        container.appendChild(hint);
        attachGraphPanZoom(container);
        attachGraphNodeHandlers(container);
        // ⚠ После узлов: подсветка ищет их в готовом SVG, а выбор переменной
        // переживает перерисовку — панель восстановит его сама.
        renderGraphVariables(container);
        // Сеть внутри: список читает синхронный кэш, узлы ждут индекс сами —
        // иначе первая отрисовка молча обошлась бы без значков.
        markUndefinedWarnings(container);
    } catch (e) {
        console.error('Ошибка построения графа:', e, definition);
        container.innerHTML = `<div style="color:#c0392b; margin-bottom:8px;">Не удалось построить граф: ${e.message}</div>`
            + `<pre style="font-size:11px;color:#666;white-space:pre-wrap;">${definition}</pre>`;
    }
}

// Module-level cleanup for document-level pan listeners (prevents accumulation on re-render)
let _panCleanup = null;

/**
 * Pan & zoom for the graph container.
 * Wheel → zoom toward cursor. Middle mouse button drag → pan (document-level listeners).
 */
function attachGraphPanZoom(container) {
    const svg = container.querySelector('svg');
    if (!svg) return;

    // Remove previous document-level pan listeners if graph was re-rendered
    if (_panCleanup) { _panCleanup(); _panCleanup = null; }

    // Viewport wrapper — transform applied here
    const vp = document.createElement('div');
    vp.style.cssText = 'position: absolute; top: 0; left: 0; transform-origin: 0 0;';
    svg.parentNode.insertBefore(vp, svg);
    vp.appendChild(svg);

    let zoom = 1, tx = 0, ty = 0;

    const apply = () => {
        vp.style.transform = `translate(${tx}px, ${ty}px) scale(${zoom})`;
    };
    apply(); // identity — SVG visible at natural size while waiting for layout

    // Fit after two animation frames so browser has fully laid out container and SVG
    requestAnimationFrame(() => requestAnimationFrame(() => {
        const cW = container.offsetWidth;
        const cH = container.offsetHeight;
        // getBoundingClientRect at scale(1) gives the SVG's natural pixel size
        const svgRect = svg.getBoundingClientRect();
        const svgW = svgRect.width  || 800;
        const svgH = svgRect.height || 600;
        if (!cW || !cH || !svgW || !svgH) return;
        zoom = Math.min(cW / svgW, cH / svgH) * 0.95;
        tx = (cW - svgW * zoom) / 2;
        ty = (cH - svgH * zoom) / 2;
        apply();
    }));

    // Wheel → zoom toward cursor
    container.addEventListener('wheel', e => {
        e.preventDefault();
        const rect = container.getBoundingClientRect();
        const cx = e.clientX - rect.left;
        const cy = e.clientY - rect.top;
        const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        const newZoom = Math.min(Math.max(zoom * factor, 0.05), 10);
        const wx = (cx - tx) / zoom;
        const wy = (cy - ty) / zoom;
        zoom = newZoom;
        tx = cx - wx * zoom;
        ty = cy - wy * zoom;
        apply();
    }, {passive: false});

    // Middle mouse button → pan via document-level listeners
    let panning = false, panX0, panY0, tx0, ty0;

    const onMouseDown = e => {
        if (e.button !== 1) return;
        e.preventDefault(); // block browser autoscroll
        panning = true;
        panX0 = e.clientX;
        panY0 = e.clientY;
        tx0 = tx;
        ty0 = ty;
        container.style.cursor = 'grabbing';
    };

    const onMouseMove = e => {
        if (!panning) return;
        tx = tx0 + (e.clientX - panX0);
        ty = ty0 + (e.clientY - panY0);
        apply();
    };

    const onMouseUp = e => {
        if (!panning || e.button !== 1) return;
        panning = false;
        container.style.cursor = '';
    };

    container.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);

    _panCleanup = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    };
}

/**
 * Attaches click handlers to graph nodes — click navigates to step editor.
 * Only parent-workflow steps (matching S{id} pattern) are interactive.
 */
function attachGraphNodeHandlers(container) {
    const activeStepBlock = document.querySelector('.step-item-block.active');
    const activeId = activeStepBlock ? String(activeStepBlock.dataset.id) : null;

    container.querySelectorAll('.node').forEach(nodeEl => {
        // Top-level steps have DOM id: flowchart-S{id}-{n}  (not flowchart-W*_S{id}-{n})
        const m = (nodeEl.id || '').match(/^flowchart-S(\d+)-/);
        if (!m) return;
        const stepId = m[1];

        if (activeId === stepId) {
            nodeEl.querySelectorAll('rect, polygon, path').forEach(shape => {
                shape.style.stroke = '#e67e22';
                shape.style.strokeWidth = '3px';
            });
        }

        nodeEl.style.cursor = 'pointer';
        nodeEl.addEventListener('click', () => {
            const step = state.allCurrentStepsData.find(s => String(s.id) === stepId);
            if (!step) return;
            // ⚠ Одна дорога на щелчок по узлу и на строку трассы: разойдись они,
            // один путь забыл бы запомнить вкладку, и страница после перезагрузки
            // возвращала бы на граф — туда, откуда человек как раз ушёл.
            openStepFromGraph(step);
        });
    });
}


// ── Панель переменных рядом с графом ────────────────────────────────────────
//
// ⚠⚠ **Своя, а не та, что в редакторе шагов.** Редактор при показе графа
// скрывается целиком (`stepsEditorView.style.display = 'none'`), и вместе с ним
// уходит `#variablesContainer`. Одну панель на два вида не сделать, не перестроив
// раскладку страницы.

// Цвета подсветки узлов. ⚠ Два, и они про разное: кто **кладёт** переменную и кто
// её **читает**. Один цвет на оба смысла отвечал бы на половину вопроса.
const VAR_MADE_COLOR = '#16a34a';
const VAR_USED_COLOR = '#2563eb';

// Что помним между перерисовками графа: трасса, выбранное имя, нумерация шагов и
// группы переменных.
//
// ⚠ Группы держим картой, а не спрашиваем про каждое имя: разбивка стоит разбора
// метаданных всех шагов, а список перерисовывается на **каждое нажатие** в поле
// фильтра. Пересборка на имя давала V разборов на один символ.
let _varTrace = new Map();
let _varPicked = null;
let _stepNumbers = new Map();
let _varGroups = new Map();

// Кэш панели: неопределённые переменные открытого workflow, Map<имя, [шаги-читатели]>
// (сырьё — `variable-undefined.js`). Нужен и списку (счётчик «читают N шаг(ов)» и
// подсказка в строке), и графу (треугольник в узле) — потому он общий, а не два
// дрожащих кэша.
let _undefinedNames = new Map();

/**
 * Номер шага так, как его видит человек: порядковый, с единицы.
 *
 * ⚠⚠ **Не `position`.** Тот хранится в базе с нуля и **с пропусками**: у
 * `dating_talk` позиции идут 0–33 на 33 шага, потому что миграции раздвигали их
 * и одна дырка осталась. И граф (`index + 1` в `_buildInnerLines`), и список
 * шагов (`step-number-badge`) нумеруют порядком в отсортированном массиве.
 *
 * Пока трасса печатала `position`, её номера расходились с теми, что на экране:
 * «5. Ленты разговора» в трассе против «6. Ленты разговора» на графе. Человек
 * искал шаг по номеру и не находил.
 */
function stepNumbersOf(steps) {
    const numbers = new Map();

    [...(steps || [])]
        .sort((a, b) => (a.position || 0) - (b.position || 0))
        .forEach((step, index) => numbers.set(String(step.id), index + 1));

    return numbers;
}

/**
 * Рисует список переменных workflow и вешает выбор.
 *
 * Список показывает **все** переменные workflow — реестр, tool и динамические — а не
 * только замеченные трассой: карта групп (`editorVariableGroupIndex`) и трасса
 * (`variablesTrace`) сливаются в один обход по алфавиту, имя без следа показывается
 * как `0→0`. Перед именем — значок группы из того же модуля, полная подпись группы
 * живёт подсказкой строки.
 *
 * ⚠ Зовётся **после** отрисовки диаграммы: подсветка ищет узлы в готовом SVG.
 */
function renderGraphVariables(container) {
    const listBox = document.getElementById('graphVarList');
    const traceBox = document.getElementById('graphVarTrace');
    const filterInput = document.getElementById('graphVarFilter');
    if (!listBox || !traceBox) return;

    _varTrace = variablesTrace(state.allCurrentStepsData);
    _stepNumbers = stepNumbersOf(state.allCurrentStepsData);
    _varGroups = editorVariableGroupIndex();
    // Кэш панели: индекса нет — значков нет, пустая карта — «неопределённых нет».
    _undefinedNames = workflowUndefinedEntriesSync(editorWorkflowId()) || new Map();

    const draw = (filter = '') => {
        const needle = filter.trim().toLowerCase();
        listBox.innerHTML = '';

        // ⚠⚠ Список — **все** переменные workflow: реестр (входящие, глобальные,
        // node, workflow), результаты инструментов, динамические — как их видит
        // трасса прогона. Прежний обход одной трассы молчал про имена, которых
        // шаги не касаются вовсе, и до половины списка дело не доходило.
        const names = [...new Set([..._varGroups.keys(), ..._varTrace.keys()])]
            .sort((a, b) => a.localeCompare(b));

        let shown = 0;
        names.forEach(name => {
            if (needle && !name.toLowerCase().includes(needle)) return;
            shown++;

            // ⚠ Имя без группы — не редкость: результат инструмента, чьих ключей
            // нет в `args.output`, или алиас `workflow_invoke_<шаг>_result_str` от
            // движка. Таких 117 из 2075 по всем workflow установки, и отвечать им
            // пустым местом значит оставлять вопрос без ответа — тем же `∅`, что и
            // на трассе прогона.
            const group = _varGroups.get(name) || VAR_GROUP_UNKNOWN;
            const cell = _varTrace.get(name) || {made: [], used: []};
            // Счётчик читающих — из кэша неопределённых: строка без группы и без
            // следа в трассе иначе врала бы «0→0» про имя, которое шаги читают.
            const undef = _undefinedNames.get(name);
            const row = document.createElement('div');
            // ⚠ Цвет полосы — по группе, тот же, что на панели шагов. Ключ группы
            // становится классом (`graph-var-input`), а цвета живут в CSS: два
            // списка цветов разошлись бы на первой правке.
            row.className = `graph-var graph-var-${group.key}`;
            if (name === _varPicked) row.className += ' active';
            row.dataset.name = name;
            row.title = undef
                ? `${group.label}: читают ${undef.length} шаг(ов) — ` +
                  undef.map(s => `#${_stepNumbers.get(String(s.id)) || s.id}`).join(', ')
                : group.label;

            // ⚠ Значок группы перед именем — тот же, что чип на трассе прогона:
            // группу узнают глазами, подпись читать не нужно.
            const icon = document.createElement('span');
            icon.className = 'graph-var-icon';
            icon.textContent = group.icon;

            const label = document.createElement('span');
            label.className = 'graph-var-name';
            label.textContent = name;
            // ⚠ Длинное имя обрезаем видом, а не текстом: полное нужно в подсказке.
            label.title = name;

            const count = document.createElement('span');
            count.className = 'graph-var-count';
            count.textContent = `${cell.made.length}→${cell.used.length}`;
            count.title = `кладёт шагов: ${cell.made.length}, читает: ${cell.used.length}`;

            // ⚠⚠ Значок и имя — одним блоком, счётчик отдельно. Строка это flex, и
            // пока детей было двое, `space-between` разводил их по краям как надо.
            // Третий ребёнок встал между ними, и у короткого имени значок отъехал
            // от него на 67 пикселей — читался уже не приставкой к имени, а сам по
            // себе. Обёртка возвращает значку его место, а счётчику — правый край.
            const head = document.createElement('span');
            head.className = 'graph-var-head';
            head.append(icon, label);
            row.append(head, count);
            row.onclick = () => pickVariable(name, container);
            listBox.appendChild(row);
        });

        if (shown === 0) {
            listBox.innerHTML = '<div class="empty-text" style="font-size:11px;padding:4px;color:#888;">Ничего не нашлось</div>';
        }
    };

    if (filterInput) {
        filterInput.oninput = () => draw(filterInput.value);
        draw(filterInput.value);
    } else {
        draw();
    }

    // ⚠ Выбор переживает перерисовку: граф перестраивается при каждом заходе, и
    // терять выбранное имя значило бы заставлять человека искать его заново.
    // Имя живёт и в трассе, и в одной только карте групп — проверка по обоим.
    if (_varPicked && (_varTrace.has(_varPicked) || _varGroups.has(_varPicked))) pickVariable(_varPicked, container);
    else traceBox.innerHTML = '<div style="color:#94a3b8;">Выберите переменную — покажу, кто её кладёт и кто читает</div>';
}

/**
 * Выбрать переменную: показать трассу и подсветить узлы на графе.
 */
function pickVariable(name, container) {
    _varPicked = name;
    const cell = _varTrace.get(name) || {made: [], used: []};

    document.querySelectorAll('#graphVarList .graph-var').forEach(row => {
        row.classList.toggle('active', row.dataset.name === name);
    });

    renderVariableTrace(name, cell, container);
    highlightGraphForVariable(cell, container);
}

/**
 * Трасса словами: кто кладёт, кто читает. Щелчок по шагу открывает его в редакторе.
 */
function renderVariableTrace(name, cell, container) {
    const box = document.getElementById('graphVarTrace');
    if (!box) return;
    box.innerHTML = '';

    // ⚠ Название группы над именем: по нему видно, откуда переменная берётся
    // вообще — входящая приходит снаружи, динамическую кладёт шаг.
    //
    // ⚠⚠ Строка стоит **всегда**, в том числе у имени без группы. Прочерк ниже
    // объясняется именно ею («у входящей класть и некому»), и без неё оставался
    // без объяснения — а таких имён по всем workflow установки 117 из 2075.
    const group = _varGroups.get(name) || VAR_GROUP_UNKNOWN;
    const kind = document.createElement('div');
    kind.className = `trace-group trace-group-${group.key}`;
    kind.textContent = `${group.title}:`;
    box.appendChild(kind);

    const head = document.createElement('div');
    head.className = 'trace-head';
    head.textContent = `%${name}%`;
    box.appendChild(head);

    const part = (title, steps) => {
        const label = document.createElement('div');
        label.className = 'trace-role';
        label.textContent = title;
        box.appendChild(label);

        if (steps.length === 0) {
            // ⚠ Прочерк, а не фраза: список читается глазами сверху вниз, и
            // объяснение в две строки сбивает ритм. Почему пусто, видно по группе
            // над именем — у входящей класть и некому.
            const none = document.createElement('div');
            none.className = 'trace-none';
            none.textContent = '—';
            box.appendChild(none);

            return;
        }

        steps.forEach(step => {
            const row = document.createElement('div');
            row.className = 'trace-step';
            const type = state.allWorkflowStepsType[step.type_id]?.name || '';
            row.textContent = `${_stepNumbers.get(String(step.id)) ?? '?'}. ${step.title}`;
            row.title = type;
            // ⚠ Щелчок ведёт **к шагу**: трасса отвечает «где», а поправить можно
            // только в редакторе. Тем же путём, что и щелчок по узлу графа.
            row.onclick = () => openStepFromGraph(step);
            box.appendChild(row);
        });
    };

    part('КЛАДУТ:', cell.made);
    part('ЧИТАЮТ:', cell.used);
}

/**
 * Подсвечивает на диаграмме узлы, которые кладут и читают переменную.
 *
 * ⚠⚠ Разметку узлов не меняем вовсе — только обводку в готовом SVG. Имена
 * переменных внутри узлов граф бы не вынес: «Ответ в чат» трогает 21 переменную,
 * «Письмо первым» — 24.
 */
function highlightGraphForVariable(cell, container) {
    const svg = container.querySelector('svg');
    if (!svg) return;

    // Снимаем прошлую обводку
    svg.querySelectorAll('.node').forEach(nodeEl => {
        nodeEl.querySelectorAll('rect, polygon, path, circle').forEach(shape => {
            if (shape.dataset.varMark === undefined) return;
            shape.style.stroke = shape.dataset.varStroke || '';
            shape.style.strokeWidth = shape.dataset.varWidth || '';
            delete shape.dataset.varMark;
        });
    });

    const paint = (steps, color) => {
        steps.forEach(step => {
            const nodeEl = graphNodeOfStep(svg, step.id);
            if (!nodeEl) return;
            nodeEl.querySelectorAll('rect, polygon, path, circle').forEach(shape => {
                // ⚠ Прежние значения запоминаем, чтобы снятие возвращало как было,
                // а не стирало обводку, нарисованную mermaid-ом.
                if (shape.dataset.varMark === undefined) {
                    shape.dataset.varStroke = shape.style.stroke || '';
                    shape.dataset.varWidth = shape.style.strokeWidth || '';
                }
                shape.dataset.varMark = '1';
                shape.style.stroke = color;
                shape.style.strokeWidth = '3px';
            });
        });
    };

    // ⚠ Читающие красим первыми: шаг может и класть, и читать (переход шага
    // проверяет то, что шаг положил), и «кладёт» — ответ важнее.
    paint(cell.used, VAR_USED_COLOR);
    paint(cell.made, VAR_MADE_COLOR);
}

/**
 * Узел диаграммы по номеру шага. `null` — шага на графе нет.
 *
 * ⚠ Имена узлов у mermaid: `flowchart-S{id}-{n}` у своих шагов и
 * `flowchart-W{wf}_S{id}-{n}` у шагов подпрогона. Здесь нужны **свои**: трасса
 * строится по шагам этого workflow, а у подпрогона своя область переменных.
 */
function graphNodeOfStep(svg, stepId) {
    return [...svg.querySelectorAll('.node')]
        .find(nodeEl => new RegExp(`^flowchart-S${stepId}-`).test(nodeEl.id || '')) || null;
}

/**
 * Открыть шаг в редакторе — общая дорога для узла графа и строки трассы.
 */
function openStepFromGraph(step) {
    document.getElementById('stepsGraph').style.display = 'none';
    document.getElementById('stepsEditorView').style.display = 'flex';
    // ⚠ Через общую функцию, а не двумя строками с `classList`: она же запоминает
    // вкладку, иначе страница после перезагрузки вернёт на граф.
    activateTab('tabSteps');
    const stepBlock = document.querySelector(`.step-item-block[data-id="${step.id}"]`);
    if (stepBlock) selectStep(step, stepBlock);
}

/**
 * ⚠ Треугольники «читает неопределённую переменную» внутрь узлов.
 *
 * Список панели уже красит такие имена (`graph-var-undefined` из индекса групп),
 * но на самой диаграмме имени нет — узел молчал бы про дырку в переменной.
 * Значок кладётся в тот же `g.node`, что и фигуры шага: `g.node` у mermaid не
 * имеет `transform`, поэтому координаты маркера совпадают с `getBBox()` фигурки,
 * а pan-zoom (он правит `transform` у `g.node`) уносит маркер вместе с узлом.
 *
 * ⚠ Узлы подпрогонов (`flowchart-W…`) пропускаем: чужая область переменных, её
 * имена править этим workflow — ложная тревога (указание хозяина).
 */
async function markUndefinedWarnings(container) {
    const entries = await workflowUndefinedEntries(editorWorkflowId());
    if (!entries || entries.size === 0) return;
    const svg = container.querySelector('svg');
    if (!svg) return;

    // «шаг → имена» вместо «имя → шаги»: узел на диаграмме один, а имён в нём
    // бывает несколько — подпись соберём за один обход.
    const byStep = new Map();
    for (const [name, steps] of entries) {
        for (const step of steps || []) {
            const key = String(step?.id ?? '');
            if (!key) continue;
            if (!byStep.has(key)) byStep.set(key, []);
            if (!byStep.get(key).includes(name)) byStep.get(key).push(name);
        }
    }

    const SVG_NS = 'http://www.w3.org/2000/svg';

    for (const nodeEl of svg.querySelectorAll('g.node')) {
        const m = (nodeEl.id || '').match(/^flowchart-S(\d+)-/);
        if (!m) continue; // свой шаг или подпрогон — решает id узла, см. шапку
        const names = byStep.get(m[1]);
        if (!names) continue;
        if (nodeEl.dataset.undefMark !== undefined) continue; // правка узлов после mermaid
        nodeEl.dataset.undefMark = '1';

        const shape = nodeEl.querySelector('rect, polygon, path, circle');
        if (!shape) continue;
        let box;
        try { box = shape.getBBox(); } catch (e) { continue; } // без геометрии маркер встал бы наугад

        // ⚠ Одна группа, а не две вложенных: внешняя несла только класс, и
        // `<title>` внутри неё лежал на уровень глубже, чем смотрит мышь.
        const mark = document.createElementNS(SVG_NS, 'g');
        mark.setAttribute('class', 'wf-node-warn');
        mark.setAttribute('transform', `translate(${box.x + box.width - 14},${box.y + 1})`);

        const tri = document.createElementNS(SVG_NS, 'polygon');
        tri.setAttribute('points', '0,0 11,0 5.5,9.5');
        tri.setAttribute('class', 'wf-node-warn-tri');

        const bang = document.createElementNS(SVG_NS, 'text');
        bang.setAttribute('x', '5.5');
        bang.setAttribute('y', '8');
        bang.setAttribute('text-anchor', 'middle');
        bang.setAttribute('class', 'wf-node-warn-bang');
        bang.textContent = '!';

        const tip = document.createElementNS(SVG_NS, 'title'); // нативная подсказка браузера
        tip.textContent = 'Неопределённые переменные: ' + names.join(', ');

        mark.append(tri, bang, tip);
        nodeEl.appendChild(mark);
    }
}

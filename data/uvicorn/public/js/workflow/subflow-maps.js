// Карты переменных шага-подпотока: что уходит внутрь и что возвращается наружу.
//
// ## ⚠⚠⚠ Зачем файл, а не ещё двести строк в `step-widgets.js`
//
// `outputs_map` до этого не было в UI **вовсе**: виджет показывал под подписью
// «Output Mapping» одно автоимя `%{подпоток}_{шаг}_result_str%`, а настоящая
// карта выходов лежала в метаданных и правилась только через базу. Девять шагов
// установки её несут, и у `dating_talk` через неё уходит правка судьи
// (`photo_fixed` → `girl_response_fixed`) — потеряйся она, человеку уедет
// черновик вместо исправленного текста, и по ответу это не видно.
//
// Входящие и исходящие — две стороны одного договора шага с подпотоком, поэтому
// живут вместе и переключаются вкладками. Отдельный файл — потому что
// `step-widgets.js` и без них самый большой в папке (1030 строк), а образец
// «виджет живёт своим файлом» в папке уже есть: `dice-widget.js`.

import {getData} from '../api.js';
import {showNotification} from '../notification.js';
import {state} from './state.js';
import {stepResultVariables} from './variable-group.js';
import {fillVariablesSelectOptions} from './variables.js';

// Классы строк. ⚠ Собирает значения по ним `subflowMapsCollect`, а не по
// порядку в DOM: порядок строк человек меняет кнопками, и индекс врал бы.
const ROW_INPUT = 'subflow-input-row';
const ROW_OUTPUT = 'subflow-output-row';

// ⚠⚠ Класс вкладок **свой**, не `tab-btn` страницы: глобальный `activateTab`
// снимает `active` со всех `.tab-btn` документа, и вкладки виджета гасли бы при
// каждом переключении «Шаги/Настройки/Graph».
const TAB_CLASS = 'subflow-tab';

const STYLE_ROW = 'display: flex; align-items: center; gap: 8px; background: #fff;'
    + ' padding: 6px; border: 1px solid #e2e8f0; border-radius: 4px;';
const STYLE_NOTE = 'font-size: 11px; color: #94a3b8;';
const STYLE_SELECT = 'flex: 1; padding: 4px; font-size: 12px; height: 32px;';

/**
 * Блок «Переменные подпотока»: вкладки «Входящие» и «Исходящие».
 *
 * Args:
 *     host: куда встроить блок (элемент).
 *     stepId: номер шага — нужен для автоимени результата.
 *     onChange: зовётся на любую правку; собирать значения — `subflowMapsCollect`.
 *
 * Returns:
 *     function(wfId, saved): перерисовать блок под выбранный подпоток. `saved` —
 *     сохранённое `workflow_invoke` шага (`inputs_map`, `outputs_map`).
 *
 * ## ⚠⚠ Перерисовка — одна функция на обе вкладки
 *
 * Выбор подпотока в селекте меняет **оба** списка: входящие берутся из его
 * объявленных переменных, выходящие — из всего, что он может отдать. Рисуй их
 * врозь, и половина блока осталась бы от прошлого подпотока.
 */
export function renderSubflowMaps(host, stepId, onChange) {
    const tabs = document.createElement('div');
    tabs.style = 'display: flex; gap: 0; border-bottom: 1px solid #e2e8f0;';

    const inputsPane = document.createElement('div');
    const outputsPane = document.createElement('div');
    [inputsPane, outputsPane].forEach(pane => {
        pane.style = 'display: flex; flex-direction: column; gap: 6px; padding-top: 8px;';
    });
    outputsPane.style.display = 'none';

    const inputsTab = _tab('Входящие', true);
    const outputsTab = _tab('Исходящие', false);

    const show = (which) => {
        const inputs = which === 'inputs';
        inputsTab.classList.toggle('active', inputs);
        outputsTab.classList.toggle('active', !inputs);
        inputsTab.style.cssText = _tabStyle(inputs);
        outputsTab.style.cssText = _tabStyle(!inputs);
        inputsPane.style.display = inputs ? 'flex' : 'none';
        outputsPane.style.display = inputs ? 'none' : 'flex';
    };

    inputsTab.onclick = () => show('inputs');
    outputsTab.onclick = () => show('outputs');

    tabs.append(inputsTab, outputsTab);
    host.append(tabs, inputsPane, outputsPane);
    show('inputs');

    return async (wfId, saved) => {
        inputsPane.innerHTML = '';
        outputsPane.innerHTML = '';

        if (!wfId) return;

        const known = await _subflowScope(wfId);

        _renderInputs(inputsPane, known.inputs, (saved && saved.inputs_map) || {}, onChange);
        _renderOutputs(outputsPane, known.gives, (saved && saved.outputs_map) || {},
                       wfId, stepId, onChange);

        // Счётчики на вкладках: сколько пар настроено. ⚠ Нужны затем, что
        // настроенная карта выходов с закрытой вкладки не видна вовсе — а
        // прежде её не было видно и с открытой.
        inputsTab.textContent = `Входящие (${inputsPane.querySelectorAll('.' + ROW_INPUT).length})`;
        outputsTab.textContent = `Исходящие (${outputsPane.querySelectorAll('.' + ROW_OUTPUT).length})`;
    };
}

/**
 * Собрать обе карты из полей блока.
 *
 * Returns:
 *     `{inputs_map, outputs_map}` — только заполненные пары.
 *
 * ⚠ Пустая строка (человек нажал «добавить» и не выбрал) в карту не попадает:
 * движок на пустом имени ругается в лог, которого никто не читает.
 */
export function subflowMapsCollect(host) {
    const inputs = {};
    const outputs = {};

    host.querySelectorAll('.' + ROW_INPUT).forEach(row => {
        const name = row.querySelector('.map-arg-select');
        const value = row.querySelector('.map-var-select');

        if (name && name.value && value && value.value) inputs[name.value] = value.value;
    });

    host.querySelectorAll('.' + ROW_OUTPUT).forEach(row => {
        const child = row.querySelector('.map-child-select');
        const parent = row.querySelector('.map-parent-select');

        if (child && child.value && parent && parent.value) outputs[child.value] = parent.value;
    });

    return {inputs_map: inputs, outputs_map: outputs};
}


function _tab(text, active) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = TAB_CLASS + (active ? ' active' : '');
    btn.textContent = text;
    btn.style.cssText = _tabStyle(active);

    return btn;
}

/** ⚠ Стиль строкой, а не классом: CSS вкладок страницы лежит в шаблоне, и
 * заводить там второй набор правил ради блока внутри формы незачем. */
function _tabStyle(active) {
    return 'padding: 6px 14px; font-size: 12px; font-weight: 600; cursor: pointer;'
        + ' border: none; background: none; margin-bottom: -1px;'
        + ` color: ${active ? '#2c3e50' : '#718096'};`
        + ` border-bottom: 2px solid ${active ? '#3498db' : 'transparent'};`;
}

/**
 * Что подпоток принимает и что может отдать.
 *
 * Returns:
 *     `{inputs, gives}` — объявленные входящие и все имена, годные в левую часть
 *     `outputs_map`.
 *
 * ## ⚠⚠⚠ Выход — не «переменная типа output»: такого типа нет вовсе
 *
 * Проверено по базе: типов три — `input`, `workflow`, `global`. Движок берёт
 * левую часть карты **из области видимости подпотока целиком**
 * (`child_scope`), поэтому годится и объявленная переменная, и автоимя
 * результата шага: в живых данных есть и то (`photo_deal`), и другое
 * (`list_shift_137_result_rest`).
 *
 * ⚠ Поэтому список — подсказка, а не ограничение: правая часть выбирается из
 * переменных родителя, а левая остаётся с возможностью вписать своё.
 */
async function _subflowScope(wfId) {
    const empty = {inputs: [], gives: []};

    try {
        const vars = ((await getData(`/workflow/${wfId}/variables`)).result) || [];
        const steps = ((await getData(`/workflow/${wfId}/steps`)).result) || [];

        const gives = new Set(vars.filter(one => one.type !== 'global')
                                  .map(one => one.name));
        stepResultVariables(steps, state.allWorkflows, state.allAvailableTools)
            .forEach(name => gives.add(name));

        return {
            inputs: vars.filter(one => one.type === 'input'),
            gives: [...gives].sort(),
        };
    } catch (e) {
        console.error('Не удалось прочитать переменные sub-workflow:', e);

        return empty;
    }
}

/** Строки входящих: имя переменной подпотока ⬅ переменная родителя. */
function _renderInputs(pane, inputs, saved, onChange) {
    if (inputs.length === 0) {
        pane.appendChild(_note('У выбранного workflow нет входящих переменных'));

        return;
    }

    inputs.forEach(one => {
        const row = document.createElement('div');
        row.className = ROW_INPUT;
        row.style = STYLE_ROW;

        const name = document.createElement('input');
        name.type = 'hidden';
        name.className = 'map-arg-select';
        name.value = one.name;

        const title = document.createElement('span');
        title.style = 'flex: 1; padding: 4px; font-size: 12px; color: #2b6cb0; font-weight: bold;';
        title.textContent = one.name;

        const value = document.createElement('select');
        value.className = 'form-control map-var-select';
        value.style = STYLE_SELECT;
        fillVariablesSelectOptions(value, saved[one.name] || '');
        value.onchange = onChange;

        row.append(name, title, _arrow('⬅'), value);
        pane.appendChild(row);
    });
}

/**
 * Строки исходящих: переменная подпотока ➔ переменная родителя.
 *
 * ## ⚠⚠ Первая строка — не карта, а то, что движок кладёт сам
 *
 * `%{подпоток}_{шаг}_result_str%` появляется у каждого вызова независимо от
 * карты, и правке не подлежит. Стоит она здесь затем, что человек ищет выходы
 * шага именно на этой вкладке, — а раньше под её подписью только она и была.
 */
function _renderOutputs(pane, gives, saved, wfId, stepId, onChange) {
    pane.appendChild(_resultRow(wfId, stepId));

    const rows = document.createElement('div');
    rows.style = 'display: flex; flex-direction: column; gap: 6px;';
    pane.appendChild(rows);

    const add = (child, parent) => {
        rows.appendChild(_outputRow(gives, child, parent, onChange));
        onChange();
    };

    Object.entries(saved).forEach(([child, parent]) => add(child, parent));

    if (!Object.keys(saved).length) {
        rows.appendChild(_note('Карта выходов пуста: наружу уходит только результат выше'));
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn-add-row';
    button.textContent = '+ Переменная наружу';
    button.style = 'align-self: flex-start; font-size: 12px; font-weight: 600; color: #3e8ee3;'
        + ' background: none; border: 1px dashed #bcd8f5; border-radius: 4px;'
        + ' padding: 5px 10px; cursor: pointer;';
    button.onclick = () => {
        rows.querySelectorAll('.subflow-maps-note').forEach(one => one.remove());
        add('', '');
    };

    pane.appendChild(button);
}

/** Строка карты: выбор переменной подпотока, переменной родителя и снос. */
function _outputRow(gives, child, parent, onChange) {
    const row = document.createElement('div');
    row.className = ROW_OUTPUT;
    row.style = STYLE_ROW;

    // ⚠⚠ Левая часть — select **со свободным вводом** через `datalist`: имя
    // может быть автоименем результата шага, которого в справочниках нет, а
    // запрет вписать своё сделал бы карту невыражаемой в UI — то есть вернул бы
    // ровно ту беду, от которой этот блок и заведён.
    const childInput = document.createElement('input');
    // ⚠⚠ `type` задаётся **явно**, и это не формальность: автосохранение страницы
    // слушает `focusout` по селектору `input[type="text"]`, а тот проверяет
    // **атрибут**. У поля без `type` атрибута нет, и правка имени уезжала бы в
    // никуда — поле выглядит обычным, а шаг не сохраняется.
    childInput.type = 'text';
    childInput.className = 'form-control map-child-select';
    childInput.style = STYLE_SELECT + ' color: #ea3d3d; font-weight: bold;';
    childInput.value = child || '';
    childInput.placeholder = 'переменная подпотока';
    childInput.setAttribute('list', _datalist(gives));
    childInput.oninput = onChange;

    const parentSelect = document.createElement('select');
    parentSelect.className = 'form-control map-parent-select';
    parentSelect.style = STYLE_SELECT;
    fillVariablesSelectOptions(parentSelect, parent || '', '-- Переменная родителя --');
    parentSelect.onchange = onChange;

    const drop = document.createElement('button');
    drop.type = 'button';
    drop.textContent = '×';
    drop.title = 'Убрать из карты выходов';
    drop.style = 'border: none; background: none; color: #cbd5e0; font-size: 18px;'
        + ' line-height: 1; cursor: pointer; padding: 0 4px;';
    drop.onmouseenter = () => drop.style.color = '#e53e3e';
    drop.onmouseleave = () => drop.style.color = '#cbd5e0';
    drop.onclick = () => {
        row.remove();
        onChange();
    };

    row.append(childInput, _arrow('➔'), parentSelect, drop);

    return row;
}

/**
 * Неизменяемая строка автоимени результата — с копированием по клику.
 *
 * ⚠ Имя собирается так же, как в движке и в `stepResultVariables`:
 * `{имя подпотока}_{шаг}_result_str`. Разойдись правило — человек скопировал бы
 * метку, которой в прогоне не будет.
 */
function _resultRow(wfId, stepId) {
    const wf = (state.allWorkflows || []).find(one => String(one.id) === String(wfId));
    const name = `%${wf ? wf.name : 'workflow_' + wfId}_${stepId}_result_str%`;

    const row = document.createElement('div');
    row.style = STYLE_ROW + ' background: #f8fafc;';

    const kind = document.createElement('span');
    kind.style = 'flex: 1; padding: 4px; font-size: 12px; color: #ea3d3d; font-weight: bold;';
    kind.textContent = 'str';

    const holder = document.createElement('div');
    holder.style = 'flex: 1; display: flex; align-items: center; padding: 4px; font-size: 11px;';

    const mark = document.createElement('span');
    mark.className = 'variable-name';
    mark.style.marginRight = '0';
    mark.title = 'Кладётся всегда, правке не подлежит. Нажмите, чтобы скопировать';
    mark.textContent = name;
    mark.onclick = async () => {
        try {
            await navigator.clipboard.writeText(name);
            showNotification(`Переменная ${name} скопирована в буфер`, 'success');
        } catch (e) {
            showNotification('Не удалось скопировать переменную', 'error');
        }
    };

    holder.appendChild(mark);
    row.append(kind, _arrow('➔'), holder);

    return row;
}

/**
 * Список подсказок для свободного ввода. ⚠ Один на блок: `datalist` живёт в
 * документе и адресуется по `id`, а строк карты бывает много.
 */
function _datalist(gives) {
    const id = 'subflowGivesList';
    let list = document.getElementById(id);

    if (!list) {
        list = document.createElement('datalist');
        list.id = id;
        document.body.appendChild(list);
    }

    list.innerHTML = '';
    gives.forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        list.appendChild(option);
    });

    return id;
}

function _arrow(sign) {
    const arrow = document.createElement('span');
    // ⚠ `textContent`, а не `innerHTML`: знак — обычный символ, и разметка ему
    // не нужна. Соседний виджет пишет стрелку через `innerHTML` по привычке.
    arrow.textContent = sign;
    arrow.style = 'color: #a0aec0; font-size: 12px;';

    return arrow;
}

function _note(text) {
    const note = document.createElement('div');
    note.className = 'subflow-maps-note';
    note.style = STYLE_NOTE;
    note.textContent = text;

    return note;
}

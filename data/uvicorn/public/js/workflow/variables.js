// Панель переменных редактора workflow: группы/аккордеон, подсветки использования,
// tool/workflow-подсветки выбранного шага, входящие переменные формы настроек

import {getData, putData, postData, deleteData} from '../api.js';
import {showNotification} from '../notification.js';
import {state} from './state.js';
import {parseMetadata, getToolOutputKeys} from './utils.js';

// Приставка литерала в `inputs_map`: значение за ней — текст, а не имя переменной.
// ⚠ Метки внутри него всё равно читаются: движок подставляет их до вызова
// инструмента, поэтому `_const_%girl_name%_ключ` **использует** `girl_name`.
const CONST_PREFIX = '_const_';

// Места, где лежит **имя** переменной, а не текст с метками.
//
// ⚠⚠ Их приходится перечислять, потому что отличить имя от обычной строки нельзя:
// `"companion_title"` в `inputs_map` — переменная, а такое же слово в промпте —
// просто слово. Метки (`%…%`) собираются отовсюду и списка не требуют.
const VAR_NAME_FIELDS = ['variable'];
const VAR_NAME_MAPS = ['inputs_map', 'outputs_map'];

// Управляющие слова разметки: выглядят меткой, переменной не являются.
//
// ⚠ `%endif%` и `%else%` попадали в улов и прежним сбором — вреда не было, потому
// что переменных с такими именами нет и подсветить их нечем. Но сбор теперь
// **общий**, и мусор в нём завтра прочтут как переменную.
const MARKUP_WORDS = ['if', 'else', 'endif'];

/**
 * Все переменные, которые участвуют в шаге — и читаемые, и записываемые.
 *
 * ## ⚠⚠ Обход рекурсивный, а не по списку типов
 *
 * Прежде сбор шёл перечнем: «у `llm_to_json` смотри `prompt_user`, у
 * `tool_invoke` — `inputs_map`…». Такой перечень отстаёт от устройства молча:
 * появился `workflow_invoke` с `inputs_map` (22 шага) и приставка `_const_` с
 * метками внутри (38 шагов) — и ни одно из этих мест в сбор не попало.
 *
 * Рекурсия по метаданным этого не знает и знать не должна: метку `%имя%` она
 * найдёт в любой строке, на любой глубине, у любого типа шага.
 *
 * ⚠ Имена **без** меток (`inputs_map`, `outputs_map`, `variable` у переходов и
 * у конверсии) перечислены выше: строку «companion_title» от обычного слова
 * отличает только место, в котором она лежит.
 */
export function stepVariables(step) {
    const found = new Set();

    const fromText = (text) => {
        if (typeof text !== 'string') return;
        for (const match of text.matchAll(/%(?:if !?)?([a-zA-Z_][a-zA-Z0-9_]*)%/g)) {
            if (!MARKUP_WORDS.includes(match[1])) found.add(match[1]);
        }
    };

    const walk = (node, key) => {
        if (typeof node === 'string') {
            fromText(node);

            return;
        }
        if (Array.isArray(node)) {
            node.forEach(one => walk(one, key));

            return;
        }
        if (!node || typeof node !== 'object') return;

        Object.entries(node).forEach(([name, value]) => {
            // Имя переменной прямо в поле: `variable` у переходов и у конверсии.
            if (VAR_NAME_FIELDS.includes(name) && typeof value === 'string' && value) {
                found.add(value);

                return;
            }

            // Карты доводов и выходов: значение — имя переменной, если это не литерал.
            if (VAR_NAME_MAPS.includes(name) && value && typeof value === 'object') {
                Object.values(value).forEach(one => {
                    if (typeof one !== 'string' || !one) return;
                    if (one.startsWith(CONST_PREFIX)) fromText(one);
                    else found.add(one);
                });

                return;
            }

            walk(value, name);
        });
    };

    walk(parseMetadata(step.metadata), null);

    return found;
}

// Поля, где лежит имя переменной, **в которую шаг пишет**.
//
// ⚠ Ключ `variable` встречается и у переходов — там он про чтение. Поэтому важен
// не сам ключ, а массив, в котором он лежит: `llm_to_json_variable` — ключи ответа
// модели, `variable_conversion` — цели подстановки.
const VAR_WRITE_ARRAYS = ['llm_to_json_variable', 'variable_conversion'];

/**
 * Переменные, которые шаг **создаёт**: ключи ответа модели, цели конверсии и
 * человеческие имена из `outputs_map`.
 *
 * ⚠ Отдельно от `stepVariables`, потому что вопросы разные. Тому нужно «что
 * участвует» — для подсветки; этому «что появляется» — чтобы показать
 * динамические переменные, которых нет в реестре.
 */
export function stepMadeVariables(step) {
    const made = new Set();

    const walk = (node, key) => {
        if (Array.isArray(node)) {
            node.forEach(one => walk(one, key));

            return;
        }
        if (!node || typeof node !== 'object') return;

        Object.entries(node).forEach(([name, value]) => {
            if (name === 'variable' && typeof value === 'string' && value
                    && VAR_WRITE_ARRAYS.includes(key)) {
                made.add(value);

                return;
            }
            if (name === 'outputs_map' && value && typeof value === 'object') {
                Object.values(value).forEach(one => {
                    if (typeof one === 'string' && one) made.add(one);
                });

                return;
            }

            walk(value, name);
        });
    };

    walk(parseMetadata(step.metadata), null);

    return made;
}

// Массивы, где ключ `variable` означает **чтение**: условие перехода спрашивает
// переменную, а не создаёт её.
const VAR_READ_ARRAYS = ['transitions_before', 'transitions_after'];

/**
 * Переменные, которые шаг **читает**: метки в любом тексте, имена в `inputs_map`
 * и переменные условий переходов.
 *
 * ⚠⚠ Отдельно от `stepVariables`, и вот зачем. Тот собирает всё, что участвует —
 * для подсветки этого довольно. А трассе нужно различать: у шага «Ленты разговора»
 * `talk_history_chat` — **цель** конверсии, и показывать его в списке «читают»
 * рядом с «кладут» значит показывать один шаг дважды с разным смыслом.
 *
 * ⚠ Переход своего же шага — **настоящее** чтение: «Валидация ответа» кладёт
 * `girl_response_skip` и тут же им развилку проверяет. Вычитанием такое не
 * отделить, поэтому условия переходов собираются здесь явно.
 */
export function stepReadVariables(step) {
    const read = new Set();

    const marks = (text) => {
        if (typeof text !== 'string') return;
        for (const match of text.matchAll(/%(?:if !?)?([a-zA-Z_][a-zA-Z0-9_]*)%/g)) {
            if (!MARKUP_WORDS.includes(match[1])) read.add(match[1]);
        }
    };

    const walk = (node, key) => {
        if (typeof node === 'string') {
            marks(node);

            return;
        }
        if (Array.isArray(node)) {
            node.forEach(one => walk(one, key));

            return;
        }
        if (!node || typeof node !== 'object') return;

        Object.entries(node).forEach(([name, value]) => {
            if (name === 'variable' && typeof value === 'string' && value
                    && VAR_READ_ARRAYS.includes(key)) {
                read.add(value);

                return;
            }
            if (name === 'inputs_map' && value && typeof value === 'object') {
                Object.values(value).forEach(one => {
                    if (typeof one !== 'string' || !one) return;
                    if (one.startsWith(CONST_PREFIX)) marks(one);
                    else read.add(one);
                });

                return;
            }

            walk(value, name);
        });
    };

    walk(parseMetadata(step.metadata), null);

    return read;
}

/**
 * Трасса переменных: у какой что кладёт и кто читает.
 *
 * Args:
 *     steps: шаги **одного** workflow, в порядке `position`.
 *
 * Returns:
 *     Map: имя → `{made: [шаг…], used: [шаг…]}`, отсортированная по имени.
 *
 * ## ⚠⚠ Чтение и запись считаются врозь, а не вычитанием
 *
 * Соблазн написать «читает = всё, что трогает, минус то, что кладёт» велик — и он
 * даёт ложь. Переход шага читает **то, что шаг же и положил**: «Валидация ответа»
 * кладёт `girl_response_skip` и тут же им развилку и проверяет. Вычитание объявило
 * бы такую переменную непрочитанной, и трасса врала бы на самом обычном случае —
 * проверено, пять ложных из пяти в `dating_talk`.
 *
 * ## ⚠⚠ Чего здесь **нет**: проверки порядка
 *
 * «Читают раньше, чем кладут» по номерам шагов не работает: в круге правок это
 * норма. `dating_mail_write` кладёт `write_hint` шагом «Что не так» (позиция 5) и
 * читает шагом «Письмо» (позиция 0) — поток возвращается к сочинению. Такая
 * проверка дала 14 находок по всем workflow, и **все 14 ложные**.
 *
 * Отличить круг от ошибки может только обход по переходам, и это отдельная
 * работа. Пока её нет, трасса отвечает «где», а не «правильно ли».
 */
export function variablesTrace(steps) {
    const trace = new Map();
    const put = (name, step, key) => {
        if (!trace.has(name)) trace.set(name, {made: [], used: []});
        const cell = trace.get(name)[key];
        if (!cell.includes(step)) cell.push(step);
    };

    (Array.isArray(steps) ? steps : []).forEach(step => {
        stepMadeVariables(step).forEach(name => put(name, step, 'made'));
        stepReadVariables(step).forEach(name => put(name, step, 'used'));
    });

    return new Map([...trace.entries()].sort((a, b) => a[0].localeCompare(b[0])));
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


// Распределяет переменные по группам (общие / ноды / tool / workflow) — единая логика
// для списка #variablesContainer и селектов переменных
function groupWorkflowVariables(variables) {
    const variablesArray = Array.isArray(variables) ? variables : [];
    const commonGroup = [];
    const nodeGroup = [];
    const workflowGroup = [];
    const toolGroup = [];
    const inputGroup = [];
    const dynamicGroup = [];

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

    // Динамические переменные шагов: их **никто не заводил руками**, они
    // появляются в прогоне сами — ключи ответа модели (`talk_topic`), цели
    // конверсии, имена из `outputs_map`.
    //
    // ⚠⚠ Показываем только те, которых нет ни в одной другой группе. Иначе
    // `girl_response` оказался бы в двух вкладках разом: он и в реестре, и
    // кладётся шагом.
    //
    // ⚠ Прежде их не было видно **нигде**, хотя работают они наравне с
    // заведёнными: на `talk_topic` стоит развилка ветки письма-фото, а
    // `girl_response_fixed` — это правленый судьёй ответ, тот самый, что уходит
    // человеку. Найти их можно было только чтением метаданных шага.
    const known = new Set([
        ...variablesArray.map(one => one?.name),
        ...foundToolVariables,
    ]);

    if (Array.isArray(state.allCurrentStepsData)) {
        const made = new Set();
        state.allCurrentStepsData.forEach(step => {
            stepMadeVariables(step).forEach(name => made.add(name));
        });

        [...made].filter(name => !known.has(name)).sort().forEach(name => {
            dynamicGroup.push({
                // ⚠ Отрицательный номер — чтобы не появилась кнопка удаления:
                // удалять нечего, записи в реестре у них нет.
                id: -3,
                name,
                default: null,
            });
        });
    }

    return {commonGroup, nodeGroup, workflowGroup, toolGroup, inputGroup, dynamicGroup};
}

/**
 * К какой группе относится переменная: ключ и человеческое название.
 *
 * Args:
 *     name: имя переменной.
 *
 * Returns:
 *     `{key, title}` — ключ группы (`input`, `tool`, `dynamic`…) и её подпись.
 *     Не нашлась нигде — `null`.
 *
 * ⚠⚠ Разбивку берём у `groupWorkflowVariables`, а не повторяем правила. Своя копия
 * разошлась бы с панелью на первой правке: переменная числилась бы входящей в
 * одном месте и динамической в другом.
 */
export function variableGroupOf(name) {
    const groups = groupWorkflowVariables(state.allCurrentVariables || []);

    for (const [title, items, key] of workflowVariableSections(groups)) {
        if (items.some(one => one?.name === name)) return {key, title};
    }

    return null;
}

// Порядок и названия групп — единые для списка #variablesContainer и селектов переменных
function workflowVariableSections(groups) {
    return [
        ['📥 Входящие переменные', groups.inputGroup, 'input'],
        ['🇬 Глобальные переменные', groups.commonGroup, 'common'],
        ['🇳 Node переменные', groups.nodeGroup, 'node'],
        ['⚙️ Tool переменные', groups.toolGroup, 'tool'],
        ['🇼 Workflow переменные ', groups.workflowGroup, 'workflow'],
        // ⚠ Последней: она про то, что появляется само, и заглядывают туда реже
        // прочих. Порядок этого перечня — он же порядок вкладок и групп в селектах.
        ['🌀 Dynamic переменные', groups.dynamicGroup, 'dynamic'],
    ];
}

// Заполняет селект опциями переменных из window.allCurrentVariables,
// сгруппированными через optgroup так же, как в списке #variablesContainer
export function fillVariablesSelectOptions(sel, selectedVal = '', placeholder = '-- Переменная --') {
    sel.innerHTML = '<option value="">' + placeholder + '</option>';

    let selectedMatched = false;
    const groups = groupWorkflowVariables(window.allCurrentVariables);
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
           dynamicGroup} = groupWorkflowVariables(variablesArray);

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

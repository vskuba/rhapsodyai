// Что за переменные живут в шагах workflow и к какой группе относится имя.
//
// ## ⚠⚠ Модуль чистый: ни DOM, ни сети, ни стейта страницы
//
// Правило «эта переменная входящая, а та появилась в прогоне» — знание о предметной
// области, а не о панели редактора. Пока оно лежало внутри панели (`variables.js`),
// страница трассы (`/admin/workflow_trace`) за одной функцией тянула тысячу строк
// редактора, `api.js`, `notification.js` и обработчик `change` на форме шага,
// который вешается прямо на импорте.
//
// Поэтому всё, что нужно правилу, приходит аргументами: реестр переменных, шаги,
// справочники workflow и инструментов. Откуда их взять — дело вызывающего: редактор
// берёт из стейта страницы, трасса — из данных прогона. **Умолчаний тут нет
// намеренно** — умолчание из стейта и есть та самая скрытая привязка к редактору.

import {parseMetadata} from './utils.js';

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

// Поля, где лежит имя переменной, **в которую шаг пишет**.
//
// ⚠ Ключ `variable` встречается и у переходов — там он про чтение. Поэтому важен
// не сам ключ, а массив, в котором он лежит: `llm_to_json_variable` — ключи ответа
// модели, `variable_conversion` — цели подстановки.
const VAR_WRITE_ARRAYS = ['llm_to_json_variable', 'variable_conversion'];

// Массивы, где ключ `variable` означает **чтение**: условие перехода спрашивает
// переменную, а не создаёт её.
const VAR_READ_ARRAYS = ['transitions_before', 'transitions_after'];

// Две разные записи, и обе означают чтение переменной.
//
// ⚠⚠ Списка «слова разметки, которые выглядят меткой» здесь больше нет, и его
// отсутствие — смысл перехода на `[<…>]`. Прежде условие писалось `%if имя%`, то
// есть той же парой процентов, что и подстановка: сбор ловил `if`, `else`, `endif`
// как имена и вычитал их перечнем. Перечень знали два места — этот файл и сторож
// движка, — а два места, знающих один список, расходятся.
//
// ⚠ Имя из условия собирается **наравне с меткой**: `[<if girl_name>]` переменную
// читает, и «где используется» обязано её найти. Разметка (`[<else>]`, `[<endif>]`)
// имени не несёт вовсе, поэтому под шаблон не попадает и вычитать её не из чего.
const VAR_MARK_RE = /%([a-zA-Z_][a-zA-Z0-9_]*)%/g;
// ⚠ Со словом `if` внутри скобок, а не по одним скобкам: `[[firstName]]` в
// DatingAi — метка переменной письма, и промпты писем живут в этих же шагах.
const VAR_IF_RE = /\[<if !?([a-zA-Z_][a-zA-Z0-9_]*)>\]/g;

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

    const fromText = (text) => textVariables(text, found);

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

    const marks = (text) => textVariables(text, read);

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
 * Выходящие ключи инструмента по его названию (структура `args.output`).
 *
 * ⚠ Список инструментов — обязательный аргумент, а не умолчание из стейта: у
 * трассы прогона он свой, и молчаливое чтение стейта редактора дало бы ей пустой
 * список вместо ошибки.
 */
export function getToolOutputKeys(toolName, tools) {
    const tool = (tools || []).find(t => String(t.name) === String(toolName));
    if (!tool) return [];

    const argsObj = parseMetadata(tool.args);
    if (!argsObj || !argsObj.output) return [];

    const output = argsObj.output;
    if (typeof output === 'object') {
        if (output.keys) return Object.keys(output.keys);
        if (output.type) return [output.type];
        return Object.keys(output);
    }
    if (typeof output === 'string') return [output];
    return [];
}

/**
 * Распределяет переменные по группам (общие / ноды / tool / workflow) — единая
 * логика для списка `#variablesContainer`, селектов переменных и трассы прогона.
 *
 * Args:
 *     variables: записи реестра (`/workflow/{id}/variables`): name, type, default.
 *     stepsData: шаги, у которых смотрят следы: `{id, metadata}`. Для редактора —
 *         шаги открытого workflow, для трассы — шаги прогона.
 *     workflows / tools: справочники, из которых собираются имена результатов
 *         `workflow_invoke` и `tool_invoke`.
 */
export function groupWorkflowVariables(variables, stepsData, workflows, tools) {
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
    if (Array.isArray(stepsData)) {
        stepsData.forEach(step => {
            let metadata = parseMetadata(step.metadata);
            if (metadata && metadata.tool_invoke && metadata.tool_invoke.tool_name) {
                const tool_name = metadata.tool_invoke.tool_name;
                getToolOutputKeys(tool_name, tools).forEach(key => {
                    foundToolVariables.add(tool_name + '_' + step.id + '_result_' + key);
                });
            }
            // Результат шага workflow_invoke: {имя_sub_workflow}_{step_id}_result_str
            if (metadata && metadata.workflow_invoke && metadata.workflow_invoke.workflow_id) {
                const wf = (workflows || []).find(w => String(w.id) === String(metadata.workflow_invoke.workflow_id));
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

    if (Array.isArray(stepsData)) {
        const made = new Set();
        stepsData.forEach(step => {
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
 * Карта «имя → группа» для набора переменных и их шагов.
 *
 * Args:
 *     variables / stepsData / workflows / tools: то же, что у
 *         `groupWorkflowVariables`.
 *
 * Returns:
 *     `Map<имя, {key, title}>` — ключ группы (`input`, `tool`, `dynamic`…) и её
 *     подпись с иконкой группы. В первой найденной секции и стоит имя: список
 *     не показывает переменную дважды.
 *
 * ⚠ Карта, а не вопрос про одно имя: списки спрашивают про десятки имён подряд, а
 * разбивка стоит разбора метаданных всех шагов. Перебирать её на каждое имя — та
 * самая работа, которую видно пальцами в фильтре графа.
 */
export function variableGroupIndex(variables, stepsData, workflows, tools) {
    const groups = groupWorkflowVariables(variables, stepsData, workflows, tools);
    const index = new Map();

    for (const [title, items, key] of workflowVariableSections(groups)) {
        items.forEach(one => {
            if (one?.name && !index.has(one.name)) index.set(one.name, {key, title});
        });
    }

    return index;
}

// Порядок и названия групп — единые для списка #variablesContainer, селектов
// переменных и чипов на трассе прогона
export function workflowVariableSections(groups) {
    return [
        ['📥 Входящие переменные', groups.inputGroup, 'input'],
        ['🇬 Глобальные переменные', groups.commonGroup, 'common'],
        ['🇳 Node переменные', groups.nodeGroup, 'node'],
        ['⚙️ Tool переменные', groups.toolGroup, 'tool'],
        ['🇼 Workflow переменные', groups.workflowGroup, 'workflow'],
        // ⚠ Последней: она про то, что появляется само, и заглядывают туда реже
        // прочих. Порядок этого перечня — он же порядок вкладок и групп в селектах.
        ['🌀 Dynamic переменные', groups.dynamicGroup, 'dynamic'],
    ];
}


// ── детали реализации ──

/** Имена переменных из строки: метки подстановки и условия блоков. */
function textVariables(text, into) {
    if (typeof text !== 'string') return;

    for (const match of text.matchAll(VAR_MARK_RE)) into.add(match[1]);
    for (const match of text.matchAll(VAR_IF_RE)) into.add(match[1]);
}

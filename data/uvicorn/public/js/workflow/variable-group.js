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

/**
 * Группа имени, которого нет ни в реестре, ни в следах шагов — той же формы, что
 * секции `workflowVariableSections`, и потому подставляется вместо них без оговорок.
 *
 * ⚠⚠ Живёт здесь, а не у показывающего. Имя без группы — не редкость и не сбой: по
 * всем 65 workflow установки таких 117 из 2075 (это результаты инструментов, чьи
 * ключи не объявлены в `args.output`, и алиас `workflow_invoke_<шаг>_result_str`,
 * который кладёт сам движок). Пока ответ знал один список, второй показывал на том
 * же имени пустое место — а пустое место оставляет вопрос без ответа ровно так же,
 * как его оставляло отсутствие группы.
 *
 * ⚠ Значок — знак пустого множества: имя не попало ни в одну группу. Своего цвета у
 * него нет, полоса и рамка пунктиром — как у динамических: записи в реестре нет.
 */
export const VAR_GROUP_UNKNOWN = {key: 'unknown', icon: '∅', label: 'не объявлена',
                                  title: '∅ не объявлена'};

/**
 * Номера строк, которых **нет в реестре**: их составляет разбивка, а не база.
 *
 * ## ⚠⚠ Отрицательный номер — это признак, и читают его в другом файле
 *
 * Строка с таким номером не имеет записи в `agent_workflow_variable`: удалять
 * нечего, править нечего, и панель обязана не рисовать ей ни кнопки удаления,
 * ни формы. Признак «номер меньше нуля» проверяет `variables.js` —
 * `if (variable.id > 0 …)`, а сами числа раздаёт `groupWorkflowVariables`
 * здесь. Пока числа стояли голыми в обоих файлах, знание «-3 это динамическая»
 * жило в двух местах сразу и расходилось бы молча.
 */
export const VAR_ID_TOOL = -2;
export const VAR_ID_DYNAMIC = -3;
export const VAR_ID_UNDEFINED = -4;
export const VAR_ID_TOPIC = -5;

/**
 * Значения, которые шаг темы кладёт подпотоку сам.
 *
 * ⚠⚠ Записи в `agent_workflow_variable` у них нет и не будет: шаг протаскивает
 * их сквозь, как движок протаскивает `user_language`. Карты для них тоже нет —
 * с ней один забытый маппинг выключал бы тему молча. Но **увидеть** их в
 * подпотоке надо: без списка человек пишет `%topic_action_instructions%`
 * вслепую и не знает, ни что ещё приедет, ни как оно пишется.
 *
 * Устройство слоя — `.claude/docs/workflow_topic.md`.
 */
export function topicActionNames() {
    return new Set(VAR_TOPIC_ACTION.map(([name]) => name));
}

export const VAR_TOPIC_ACTION = [
    ['topic_action_name', 'код темы — он же виден в журнале прогона'],
    ['topic_action_title', 'название темы'],
    ['topic_action_tags', 'все метки темы через запятую'],
    ['topic_action_tags_found', 'какие метки нашлись в истории — через запятую'],
    ['topic_action_instructions', 'инструкция темы: что делать, когда она поднята'],
    ['topic_action_questions', 'вопросы темы нумерованным списком'],
    ['topic_action_questions_qty', 'сколько вопросов у темы'],
    ['topic_action_questions_qty_yes_accept', 'сколько ответов «yes» означают, что тема поднята'],
];

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
//
// ⚠⚠ Ловится **всё условие целиком**, имена из него достаёт `ifNames` — потому
// что условие больше не «одно имя»: движок понимает `and`, `or` и сравнения
// (`[<if count > 5 and kind == chat>]`). Регулярка на одно имя нашла бы в таком
// условии ноль переменных, и обе они выглядели бы неиспользуемыми.
//
// ⚠ Условие — «любой знак, кроме `>` перед `]`»: сам `>` внутри законен, это
// оператор. Правило то же, что у движка (`WORKFLOW_IF_BLOCK_RE`).
const VAR_IF_RE = /\[<if ((?:[^>\[]|>(?!\]))+)>\]/g;

// Имена переменных в условии — по обе стороны оператора.
//
// ⚠⚠ Что переменная, а что слово, решают **кавычки**: `kind == 'chat'`
// сравнивает со словом, `kind == other` — со значением переменной `other`.
// Поэтому голый идентификатор справа собирается наравне с левым, а всё в
// кавычках и числа под шаблон не попадают вовсе.
//
// ⚠ Связки отбрасываются отдельно (`VAR_IF_SKIP`): `and` и `or` — слова
// разметки, а выглядят идентификаторами. Это тот самый «список слов, которые
// выглядят именем», которого удалось избежать в метках, — здесь он неизбежен,
// зато короткий и лежит рядом со своим шаблоном.
const VAR_IF_ATOM_RE = /'[^']*'|"[^"]*"|[a-zA-Z_][a-zA-Z0-9_]*/g;
const VAR_IF_SKIP = new Set(['and', 'or']);

// Цикл `[<for k,v in items>]` и присваивание `[<set n = n + 1>]`. Правила те же,
// что у движка (`WORKFLOW_FOR_HEAD_RE`, `WORKFLOW_SET_RE` в `ai_workflow.py`).
//
// ⚠⚠ Эти два тега **заводят имена прямо в тексте**, и в этом их отличие от
// условия. Не знай о них сбор, `k` и `v` попали бы в «Undefined переменные» —
// то есть страница ругалась бы на единственное место, где имя и объявлено.
//
// ⚠ Источник цикла (`items`) — наоборот, настоящее чтение, наравне с `%меткой%`:
// без него «где используется» не нашло бы переменную, ради которой цикл и
// написан.
const VAR_FOR_RE =
    /\[<for\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*,\s*([a-zA-Z_][a-zA-Z0-9_]*))?\s+in\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*,\s*start\s*=\s*((?:[^>\[]|>(?!\]))+?))?\s*>\]/g;
const VAR_SET_RE = /\[<set\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*((?:[^>\[]|>(?!\]))+?)\s*>\]/g;

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
 * Имена, которые шаг **связывает прямо в тексте**: `[<for k,v in …>]` и
 * `[<set имя = …>]`.
 *
 * ## ⚠⚠ Третий род имени, и он намеренно не «сделанное шагом»
 *
 * Положенное шагом (`stepMadeVariables`) живёт до конца прогона и показывается
 * человеку группой «Dynamic переменные». Связанное текстом живёт **только внутри
 * своего поля** — движок считает его в копии словаря (`ai_workflow_set_render`),
 * и соседнее поле того же шага его уже не видит.
 *
 * Поэтому оно гасит «Undefined» (имя объявлено, ругаться не на что), но в списки
 * не попадает: показать его значило бы предложить человеку переменную, которой
 * нигде, кроме одной строки промпта, не существует, — и ту ещё можно случайно
 * завести в реестре, молча перекрыв собою счётчик цикла.
 */
export function stepBoundVariables(step) {
    const bound = new Set();

    const walk = (node) => {
        if (typeof node === 'string') {
            textBoundVariables(node, bound);

            return;
        }
        if (Array.isArray(node)) {
            node.forEach(walk);

            return;
        }
        if (!node || typeof node !== 'object') return;

        Object.values(node).forEach(walk);
    };

    walk(parseMetadata(step.metadata));

    return bound;
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
        // ⚠⚠ Имена, связанные текстом (`[<for k,v in …>]`, `[<set …>]`),
        // вычитаются — и вычитаются ПОШАГОВО, а не одним списком на весь
        // workflow. Счётчик `v` живёт внутри одного поля и переменной workflow
        // не является; попади он сюда, список графа показал бы строку «∅ не
        // объявлена», а человек пошёл бы заводить её в реестре — и заведённая
        // пустой, она перекрыла бы собою счётчик цикла.
        //
        // ⚠ Пошагово, потому что имя законно бывает и тем и другим: цикл
        // связывает `v` в одном шаге, а в соседнем `%v%` — настоящая
        // переменная прогона. Вычти мы одним списком — пропала бы вторая.
        const bound = stepBoundVariables(step);

        stepMadeVariables(step).forEach(name => {
            if (!bound.has(name)) put(name, step, 'made');
        });
        stepReadVariables(step).forEach(name => {
            if (!bound.has(name)) put(name, step, 'used');
        });
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

// Объявления выхода, по которым **нельзя** перечислить ключи результата: движок
// раскладывает словарь как `{tool}_{step}_result_{ключ}`, а какие в нём ключи —
// знает только сам инструмент в момент ответа.
const TOOL_OUTPUT_OPAQUE_TYPES = ['dict', 'any', 'object', 'json'];

/**
 * Можно ли перечислить ключи результата инструмента, или он «отдаёт что угодно».
 *
 * ## ⚠⚠ Зачем спрашивать это отдельно от `getToolOutputKeys`
 *
 * Тот отвечает «какие ключи объявлены», и на `{"type": "dict"}` честно отдаёт
 * `['dict']` — одно имя `{tool}_{step}_result_dict`. Для списка групп этого
 * довольно. Для правила неопределённости — нет: у `list_shift` объявлен `dict`,
 * а шаги читают `list_shift_137_result_greeting`, `…_name`, `…_sheet` и ещё два,
 * и все их движок вправду кладёт. Считать их дырками значит кричать на живое:
 * таких инструментов 37 из 121 на этой установке.
 *
 * Args:
 *     toolName: имя из `tool_invoke.tool_name`.
 *     tools: справочник `/tool/list` — обязательный аргумент, как и у соседа.
 *
 * Returns:
 *     boolean: `true` — ключи неизвестны, всё `{tool}_{step}_result_*` этого шага
 *     считается обеспеченным. `false` — ключи перечислены (`output.keys`) или
 *     результат одиночный (`{"type": "str"}`), и лишнее имя вправду лишнее.
 *
 * ⚠ Инструмент, которого в справочнике нет вовсе, тоже непрозрачен. Он либо
 * переименован, либо снят — но шаг на него ссылается, и доказать пустоту нечем.
 */
export function toolOutputIsOpaque(toolName, tools) {
    const tool = (tools || []).find(t => String(t.name) === String(toolName));
    if (!tool) return true;

    const argsObj = parseMetadata(tool.args);
    const output = argsObj && argsObj.output;
    if (!output) return true;

    if (typeof output === 'object') {
        if (output.keys) return false; // ключи перечислены — спрос по списку
        if (output.type) return TOOL_OUTPUT_OPAQUE_TYPES.includes(String(output.type).toLowerCase());

        return false;
    }

    return TOOL_OUTPUT_OPAQUE_TYPES.includes(String(output).toLowerCase());
}

/**
 * Имена, которые **шаги кладут сами**: результаты инструментов и подпрогонов.
 *
 * ## ⚠⚠ Одно знание, два потребителя
 *
 * Эти имена нужны и разбивке на группы (строки `⚙️ Tool переменные`), и правилу
 * неопределённости (`undefinedVariables`): имя `dating_talk_42_result_str` никто
 * в реестр не заводил — работает оно наравне. Пока оно строилось внутри
 * `groupWorkflowVariables` и наружу не отдавалось, второе правило вынуждено
 * были бы перестраивать его своим перебором — а два знатока одного шаблона
 * расходятся при первой правке, это уже проходили на `foundToolVariables`.
 *
 * Args:
 *     stepsData / workflows / tools: то же, что у `groupWorkflowVariables`.
 *
 * Returns:
 *     Set<имя>: `{tool_name}_{step_id}_result_{ключ}` из `args.output` инструмента
 *     и `{имя_подпрогона}_{step_id}_result_str` — строковый итог `workflow_invoke`.
 */
export function stepResultVariables(stepsData, workflows, tools) {
    const found = new Set();

    (Array.isArray(stepsData) ? stepsData : []).forEach(step => {
        const metadata = parseMetadata(step.metadata);
        if (metadata && metadata.tool_invoke && metadata.tool_invoke.tool_name) {
            const tool_name = metadata.tool_invoke.tool_name;
            getToolOutputKeys(tool_name, tools).forEach(key => {
                found.add(tool_name + '_' + step.id + '_result_' + key);
            });
        }
        // Результат шага workflow_invoke: {имя_sub_workflow}_{step_id}_result_str
        if (metadata && metadata.workflow_invoke && metadata.workflow_invoke.workflow_id) {
            const wf = (workflows || []).find(w => String(w.id) === String(metadata.workflow_invoke.workflow_id));
            const childName = wf ? wf.name : ('workflow_' + metadata.workflow_invoke.workflow_id);
            found.add(childName + '_' + step.id + '_result_str');
        }
    });

    return found;
}

/**
 * Переменные, которые шаги **читают, но никто не кладёт и в реестре их нет**.
 *
 * ## ⚠⚠ Почему это отдельное правило, а не догадка по группам
 *
 * Имя из `%...%` в промпте может значить что угодно: опечатку, след удалённой
 * переменной, легальное имя из proxy ноды или переменных агента. Первые —
 * неработающие ссылки: шаг читает то, что ему никто не даёт, и в прогоне там
 * пусто или нераскрытый `%имя%`. Вторые — рабочие, но не видны по списку
 * реестра. Отличают их друг от друга только оба списка сразу.
 *
 * Undefined = прочитанное минус всё легально доступное:
 *
 * * реестр workflow (входящие, глобальные, workflow, публичные ноды);
 * * следы шагов — результаты инструментов/подпрогонов (`stepResultVariables`)
 *   и сделанное шагами (`stepMadeVariables`: ключи модели, цели конверсии);
 * * алиас `workflow_invoke_{шаг}_result_str` — его кладёт движок сверх
 *   именованного результата, в справочниках его нет вовсе;
 * * `hiddenNames` — то, что движок подмешивает в scope молча: proxy-переменные
 *   ноды, `agent_variable` агента, словарь запускающего из `variables_start`
 *   последних прогонов и `inputs_map` родительского `workflow_invoke`, если
 *   этот workflow — подпрогон. По указанию хозяина **не показывать их
 *   в списках** — но считать обеспеченными обязаны, иначе `%girl_name%` из
 *   переменных агента кричал бы предупреждением на каждом шагу.
 *
 * ## ⚠⚠ Две поправки на то, чего знать неоткуда
 *
 * Правило молчит там, где доказать пустоту нечем, — иначе оно кричит на живое:
 *
 * * **шаг с непрозрачным инструментом** (`toolOutputIsOpaque`): объявлен
 *   `{"type": "dict"}`, а ключи движок раскладывает по ответу. Всё
 *   `{tool}_{шаг}_result_*` такого шага считается обеспеченным;
 * * **однобуквенное имя**: `%Y%m%d%H%M%S` в промпте — формат даты, а не три
 *   переменные, но метка `%…%` в нём выглядит как переменная (`Y`, `m`, `d`).
 *   Переменных в один символ на установке нет ни одной, а формат даты в
 *   промптах есть.
 *
 * Args:
 *     variables / stepsData / workflows / tools: то же, что у `groupWorkflowVariables`.
 *     hiddenNames: массив имён, легальных, но не показуемых (proxy, агентские,
 *         словарь запускающего, входящие подпрогона).
 *
 * Returns:
 *     `Map<имя, [шаг…]>`: читающие шаги в порядке `position`, по имени
 *     отсортированно. У имени, читаемого из нескольких мест, шаг не повторяется.
 *
 * ⚠ Порядок «прочитано раньше, чем положено» не проверяется намеренно — по
 * номерам он ложен в кругах правок, см. `variablesTrace`.
 */
export function undefinedVariables(variables, stepsData, workflows, tools, hiddenNames) {
    const steps = Array.isArray(stepsData) ? stepsData : [];

    const readers = new Map();
    steps.forEach(step => {
        stepReadVariables(step).forEach(name => {
            if (!readers.has(name)) readers.set(name, []);
            readers.get(name).push(step);
        });
    });

    const _names = (list) => (Array.isArray(list) ? list : [])
        .map(one => (typeof one === 'string' ? one : one?.name))
        .filter(name => !!name);

    const known = new Set([
        ..._names(variables),
        ...stepResultVariables(stepsData, workflows, tools),
        ..._names(hiddenNames),
    ]);

    // Приставки шагов, чей инструмент не объявил ключей: имя с такой приставкой
    // спрашивать не с кого — см. «две поправки» в шапке.
    const opaquePrefixes = [];

    steps.forEach(step => {
        stepMadeVariables(step).forEach(name => known.add(name));

        // ⚠ Связанные текстом — только сюда, в гашение «Undefined». В
        // `dynamicGroup` их нет намеренно: они не переживают своего поля.
        stepBoundVariables(step).forEach(name => known.add(name));

        const metadata = parseMetadata(step.metadata);
        if (!metadata) return;

        // Алиас движка: кладётся сверх `{имя_подпрогона}_{шаг}_result_str` и в
        // справочниках не значит нигде — берём его из устройства шага.
        if (metadata.workflow_invoke && metadata.workflow_invoke.workflow_id) {
            known.add('workflow_invoke_' + step.id + '_result_str');
        }
        if (metadata.tool_invoke && metadata.tool_invoke.tool_name
                && toolOutputIsOpaque(metadata.tool_invoke.tool_name, tools)) {
            opaquePrefixes.push(metadata.tool_invoke.tool_name + '_' + step.id + '_result_');
        }
    });

    const supplied = (name) => known.has(name)
        || name.length < 2
        || opaquePrefixes.some(prefix => name.startsWith(prefix));

    const result = new Map();
    [...readers.keys()].filter(name => !supplied(name)).sort()
        .forEach(name => result.set(name, readers.get(name)));

    return result;
}

/**
 * Распределяет переменные по группам (общие / ноды / tool / workflow / undefined) —
 * единая логика для списка `#variablesContainer`, селектов переменных и трассы прогона.
 *
 * Args:
 *     variables: записи реестра (`/workflow/{id}/variables`): name, type, default.
 *     stepsData: шаги, у которых смотрят следы: `{id, metadata}`. Для редактора —
 *         шаги открытого workflow, для трассы — шаги прогона.
 *     workflows / tools: справочники, из которых собираются имена результатов
 *         `workflow_invoke` и `tool_invoke`.
 *     hiddenNames: легальные, но не показуемые имена (`undefinedVariables`).
 *
 * Returns:
 *     Группы плюс `undefinedGroup`: записи `{id: VAR_ID_UNDEFINED, name, readers}` — читающие
 *     шаги нужны подписи «читают N шагов» и подсказке, своего места в строке
 *     им не отдавать.
 */
export function groupWorkflowVariables(variables, stepsData, workflows, tools, hiddenNames,
                                       isBranchRoad = false) {
    const variablesArray = Array.isArray(variables) ? variables : [];

    // ⚠ Группа только у подпотока, который **и есть дорога ветки**. У прочих
    // (`girl_fact_invent`, `companion_fact_extract`) этих значений не бывает, и
    // список из семи никому не нужных имён сбивал бы с толку.
    const branchGroup = isBranchRoad
        ? VAR_TOPIC_ACTION.map(([name, description]) => ({
            id: VAR_ID_TOPIC, name, default: null, description,
        }))
        : [];
    const branchNames = new Set(branchGroup.map(item => item.name));
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
    const foundToolVariables = stepResultVariables(stepsData, workflows, tools);

    foundToolVariables.forEach(varName => {
        toolGroup.push({
            id: VAR_ID_TOOL, // не из реестра: кнопки удаления у строки не будет
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
        ...(Array.isArray(hiddenNames) ? hiddenNames : []),
    ]);

    if (Array.isArray(stepsData)) {
        const made = new Set();
        stepsData.forEach(step => {
            stepMadeVariables(step).forEach(name => made.add(name));
        });

        [...made].filter(name => !known.has(name)).sort().forEach(name => {
            dynamicGroup.push({
                // ⚠ Не из реестра: удалять нечего, записи у них там нет.
                id: VAR_ID_DYNAMIC,
                name,
                default: null,
            });
        });
    }

    // ⚠⚠ Неопределённые — после tool и workflow групп и перед dynamic: имя может
    // быть и прочитанным, и положенным разными шагами, и тогда оно уже показано
    // выше; здесь остаются только те, коим нет места ни в одной другой группе.
    const undefinedGroup = [];
    if (Array.isArray(stepsData)) {
        undefinedVariables(variablesArray, stepsData, workflows, tools, hiddenNames)
            .forEach((readers, name) => {
                // ⚠⚠ `topic_*` в дороге ветки — не «неопределённая»: записи в
                // реестре у неё нет по устройству, а значение приедет. Без этого
                // отсева `%topic_instructions%` в промпте горел бы красным «нигде не
                // заведена», и человек заводил бы её руками — а заведённая пустой
                // она **перекрыла** бы приехавшую.
                if (branchNames.has(name)) return;

                undefinedGroup.push({
                    // ⚠ Свой номер: в реестре такой переменной нет — кнопки
                    // удаления и формы правки у её строки быть не должно.
                    id: VAR_ID_UNDEFINED,
                    name,
                    default: null,
                    readers,
                });
            });
    }

    return {commonGroup, nodeGroup, workflowGroup, toolGroup, inputGroup, dynamicGroup,
            undefinedGroup, branchGroup};
}

/**
 * Карта «имя → группа» для набора переменных и их шагов.
 *
 * Args:
 *     variables / stepsData / workflows / tools / hiddenNames: то же, что у
 *         `groupWorkflowVariables`.
 *
 * Returns:
 *     `Map<имя, секция>` — та самая запись, что отдаёт `workflowVariableSections`,
 *     только без `items`: `{key, icon, label, title}`. В первой найденной секции и
 *     стоит имя: список не показывает переменную дважды.
 *
 * ⚠ Имени, которого нет ни в реестре, ни в следах шагов, в карте нет. Показывать
 * его всё равно надо — но чем, решает не разбор, а `VAR_GROUP_UNKNOWN`: у обоих
 * списков ответ обязан быть один.
 *
 * ⚠ Карта, а не вопрос про одно имя: списки спрашивают про десятки имён подряд, а
 * разбивка стоит разбора метаданных всех шагов. Перебирать её на каждое имя — та
 * самая работа, которую видно пальцами в фильтре графа.
 */
export function variableGroupIndex(variables, stepsData, workflows, tools, hiddenNames,
                                   isBranchRoad = false) {
    const groups = groupWorkflowVariables(variables, stepsData, workflows, tools, hiddenNames,
                                          isBranchRoad);
    const index = new Map();

    for (const {items, ...section} of workflowVariableSections(groups)) {
        items.forEach(one => {
            if (one?.name && !index.has(one.name)) index.set(one.name, section);
        });
    }

    return index;
}

/**
 * Порядок и подписи групп — единые для списка `#variablesContainer`, селектов
 * переменных, чипов трассы и панели графа.
 *
 * Returns:
 *     Массив секций по порядку показа: `{key, icon, label, title, items}`.
 *     `title` — собранная подпись «значок + название», её просят заголовки;
 *     `icon` и `label` врозь нужны спискам, где значок стоит чипом, а название
 *     живёт подсказкой.
 *
 * ⚠⚠ Значок объявлен **полем**, а не первым словом подписи. Он им и был — и
 * доставали его разбором `title.split(' ')[0]`: подпись показывают человеку, а по
 * ней восстанавливали структуру. Неразрывный пробел, название без значка,
 * перестановка слов — и в чипе молча оказалось бы слово вместо знака.
 *
 * ⚠ Секцию `undefined` списки показов **пропускают** там, где список — выбор
 * (селекты доводов): показывать в выборе имя, которого ни в одном списке нет и
 * которое на прогоне не раскроется, значит предлагать человеком писать битовое
 * значение. Списки же, где переменную только показывают (`#variablesContainer`,
 * панель графа), её рисуют: красный цвет и значок ⚠️ — то, что списки уже
 * различают глазами, там и так работают списком.
 */
export function workflowVariableSections(groups) {
    return [
        {key: 'input', icon: '📥', label: 'Входящие переменные', items: groups.inputGroup},
        {key: 'common', icon: '🇬', label: 'Глобальные переменные', items: groups.commonGroup},
        {key: 'node', icon: '🇳', label: 'Node переменные', items: groups.nodeGroup},
        {key: 'tool', icon: '⚙️', label: 'Tool переменные', items: groups.toolGroup},
        {key: 'workflow', icon: '🇼', label: 'Workflow переменные', items: groups.workflowGroup},
        // ⚠ Значок тот же, что у типа шага `branch`: связь «эти значения кладёт
        // вон тот шаг» должна читаться без объяснений. Пустую секцию списки не
        // рисуют, поэтому у обычных подпотоков её не видно вовсе.
        {key: 'branch', icon: '🌿', label: 'Topic & Action переменные',
         items: groups.branchGroup || []},
        // ⚠ Перед dynamic: «про то, что не заведено нигде» важнее для глаза, чем
        // «про то, что кладёт шаг», а пустую секцию списки не рисуют вовсе.
        {key: 'undefined', icon: '⚠️', label: 'Undefined переменные', items: groups.undefinedGroup || []},
        // ⚠ Последней: она про то, что появляется само, и заглядывают туда реже
        // прочих. Порядок этого перечня — он же порядок вкладок и групп в селектах.
        {key: 'dynamic', icon: '🌀', label: 'Dynamic переменные', items: groups.dynamicGroup},
    ].map(section => ({...section, title: `${section.icon} ${section.label}`}));
}


// ── детали реализации ──

/** Имена переменных из строки: метки подстановки и условия блоков. */
function textVariables(text, into) {
    if (typeof text !== 'string') return;

    for (const match of text.matchAll(VAR_MARK_RE)) into.add(match[1]);

    for (const match of text.matchAll(VAR_IF_RE)) {
        // ⚠ Условие может нести несколько имён — и по обе стороны оператора
        // (`a and b`, `kind == other`), поэтому разбирается на части.
        for (const atom of match[1].matchAll(VAR_IF_ATOM_RE)) {
            const word = atom[0];

            // Кавычки — значит слово, а не переменная.
            if (word[0] === "'" || word[0] === '"') continue;
            if (VAR_IF_SKIP.has(word)) continue;

            into.add(word);
        }
    }

    // ⚠ У цикла читается источник и выражение `start=`: `k` и `v` он заводит
    // сам, и попади они сюда — оказались бы в «Undefined», где им не место.
    // Собирает их `textBoundVariables`, и она же отвечает за `[<set …>]`.
    for (const match of text.matchAll(VAR_FOR_RE)) {
        into.add(match[3]);

        // ⚠⚠ `start=` принимает и имя переменной (`start=from`): без разбора
        // такое имя не нашлось бы ни в «где используется», ни в подсветке, и
        // выглядело бы неиспользуемым при живой ссылке на него.
        for (const atom of (match[4] || '').matchAll(VAR_IF_ATOM_RE)) {
            const word = atom[0];

            if (word[0] === "'" || word[0] === '"') continue;

            into.add(word);
        }
    }

    // ⚠⚠ В выражении присваивания имена — настоящее чтение: `[<set k = k + 1>]`
    // читает `k`. Слева от знака равенства — наоборот, объявление, и его здесь
    // нет намеренно.
    for (const match of text.matchAll(VAR_SET_RE)) {
        for (const atom of match[2].matchAll(VAR_IF_ATOM_RE)) {
            const word = atom[0];

            if (word[0] === "'" || word[0] === '"') continue;

            into.add(word);
        }
    }
}


/**
 * Имена, которые текст заводит сам: `[<for k,v in …>]` и `[<set имя = …>]`.
 *
 * ⚠⚠ Отдельно от «что шаг читает», потому что это объявление, а не чтение.
 * Смешай их в одну кучу — и `k` одновременно числился бы неопределённым (никто
 * не кладёт) и используемым, то есть страница ругалась бы на место объявления.
 */
function textBoundVariables(text, into) {
    if (typeof text !== 'string') return;

    for (const match of text.matchAll(VAR_FOR_RE)) {
        into.add(match[1]);

        if (match[2]) into.add(match[2]);
    }

    for (const match of text.matchAll(VAR_SET_RE)) into.add(match[1]);
}

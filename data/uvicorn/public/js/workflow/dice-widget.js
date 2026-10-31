import {fillVariablesSelectOptions, syncHiddenRow} from './variables.js';

// Редактор жребия: переменные, их варианты и шансы выпадения.
//
// ⚠⚠ Своим модулем, а не ещё двумя сотнями строк в `step-widgets.js`. Тот уже
// на девятьсот строк и держит пять виджетов разом; шестой сделал бы его файлом,
// который открывают только по необходимости.
//
// ⚠ Инструмент `dice` — единственный, у кого выходы **не объявлены заранее**:
// их имена придумывает человек здесь же. Поэтому общий вид «входы слева, выходы
// справа» ему не подходит, и у него свой.

// Имена инструментов, ради которых всё это. ⚠ Сверяются с `tool.name` в базе:
// переименуют там — здесь перестанут находиться, и человек увидит общий вид с
// JSON-простынёй в поле ввода вместо списка вариантов.
//
// ⚠⚠ Два, а не одно: `dice_batch` — тот же жребий, только бросает серию на
// пачку. Описание у них одинаковое, и редактировать его человек обязан
// одинаково — иначе у одного из двух шагов он правит текст JSON руками.
export const DICE_TOOL_NAME = 'dice';
export const DICE_TOOL_BATCH = 'dice_batch';
export const DICE_TOOL_NAMES = [DICE_TOOL_NAME, DICE_TOOL_BATCH];

// Довод инструмента, в который уезжает описание жребия.
// ⚠ Обязан совпадать с именем аргумента функции `dice(spec)`: движок кладёт
// значения в аргументы **по имени** (`inputs_map`), а не по порядку.
const DICE_ARG = 'spec';

// Довод, которым `dice_batch` узнаёт длину серии. ⚠ Имя переменной, а не
// число: сколько реплик в пачке, решает заход, и зашитое число соврало бы
// на первом же пакете другого размера.
const DICE_ARG_TIMES = 'times';

// Приставка, которой движок отличает литерал от имени переменной
// (`ai_framework_manager`: `var_name.startswith('_const_')`).
const DICE_CONST = '_const_';

// Сколько вариантов заводится сразу и сколько их должно остаться минимум.
// ⚠ Два — не круглое число, а смысл: один вариант это не жребий, а постоянное
// значение, и такое описание инструмент отвергает.
const DICE_OPTIONS_MIN = 2;

// Сумма долей одной переменной. ⚠ То же число, что в `dice.py`; расходиться им
// нельзя — редактор пропустил бы описание, на котором заход упадёт.
const DICE_PERCENT_TOTAL = 100;

// Доля-«остаток»: всё, что не разобрали соседи. ⚠ Слово то же, что в `dice.py`.
const DICE_REST = 'rest';

/**
 * Участвует ли доля в арифметике формы.
 *
 * ⚠⚠ Три вида долей, и два из них считать нельзя: метка `%имя%` раскроется
 * только в заходе, «остаток» вычисляется от суммы остальных. Поровну делим и
 * подрезаем **только числа** — иначе форма затёрла бы метку числом, молча
 * отменив настройку сайта.
 */
function _isNumberShare(text) {
    const raw = String(text || '').trim();

    return !!raw && !raw.startsWith('%') && raw.toLowerCase() !== DICE_REST;
}

/**
 * Нарисовать редактор жребия внутри готового блока.
 *
 * @param {HTMLElement} host куда рисовать; очищается.
 * @param {object} current текущее `tool_invoke` шага.
 * @param {function} save принимает готовое `{tool_name, inputs_map, outputs_map}`.
 * @param {string} toolName какой из двух жребиев: `dice` или `dice_batch`.
 */
export function renderDiceWidget(host, current, save, toolName = DICE_TOOL_NAME) {
    host.innerHTML = '';

    // ⚠ Имя берём от выбранного инструмента, а не от первого из пары: сохрани
    // виджет своё зашитое имя — человек выбрал бы `dice_batch`, а в шаг уехал
    // бы `dice`, и серия превратилась бы в один бросок молча.
    const isBatch = String(toolName) === DICE_TOOL_BATCH;

    const list = document.createElement('div');
    list.className = 'dice-list';
    list.style = 'display: flex; flex-direction: column; gap: 10px;';

    // Поле «сколько бросков» — только у серии, и только выбором переменной.
    const timesSelect = document.createElement('select');
    timesSelect.className = 'form-control dice-times';
    timesSelect.style = 'flex: 1; padding: 5px; font-size: 12px; height: 32px;';

    const collect = () => {
        const spec = {};
        const outputs = {};

        list.querySelectorAll('.dice-var').forEach(block => {
            const name = block.querySelector('.dice-var-name').value.trim();
            if (!name) return;

            const options = {};
            block.querySelectorAll('.dice-option').forEach(row => {
                const value = row.querySelector('.dice-option-text').value.trim();
                const share = row.querySelector('.dice-option-share').value.trim();
                if (value) options[value] = _shareOut(share);
            });

            spec[name] = options;
            // ⚠⚠ Выход зовём тем же именем, что и переменную: иначе в промпте
            // пришлось бы писать `%dice_<шаг>_result_<имя>%`, где номер шага
            // свой у каждой базы — та самая ссылка, что ломается при переносе.
            outputs[name] = name;
        });

        // ⚠⚠⚠ Описание уезжает **в переменную потока**, а не литералом.
        // Литерал (`_const_{…}`) движок отвергает отказом — значения живут в
        // переменных, и форма обязана писать туда же, откуда читает.
        //
        // ⚠ Имя переменной берём то, что уже стоит в шаге: его завёл человек,
        // на него ссылаются другие места, и переименование формой было бы
        // правкой, которой он не просил. Имени нет (шаг только завели) —
        // пишем литералом, как раньше: лучше запись, которую примет старая
        // база, чем ссылка на переменную, которой никто не создавал.
        const wasSpec = String(((current || {}).inputs_map || {})[DICE_ARG] || '');
        const varName = wasSpec && !wasSpec.startsWith(DICE_CONST) ? wasSpec : '';

        if (varName) {
            // ⚠ Значение переменной правим **на странице**: виджет её не
            // сохраняет — это делает общая кнопка «Сохранить workflow»,
            // одна на все переменные. Своё сохранение здесь означало бы два
            // писателя одной строки.
            _specToVariable(varName, spec);
        }

        const inputs = {[DICE_ARG]: varName || (DICE_CONST + JSON.stringify(spec))};

        if (isBatch && timesSelect.value) {
            inputs[DICE_ARG_TIMES] = timesSelect.value;
        }

        save({tool_name: toolName, inputs_map: inputs, outputs_map: outputs});
    };

    const addVariable = (name = '', options = null) => {
        list.appendChild(_variableBlock(name, options, collect, () => {
            // ⚠ Последнюю переменную удалить нельзя: шаг без единого выхода
            // ничего не делает, а выглядит настроенным.
            if (list.querySelectorAll('.dice-var').length > 1) return true;
            return false;
        }));
        collect();
    };

    const addButton = _button('+ переменная', '#3182ce');
    addButton.style.alignSelf = 'flex-start';
    addButton.onclick = () => addVariable();

    host.appendChild(_hint(
        'Каждая переменная получает одно из своих значений по жребию. Доля — '
        + 'число, метка переменной (%percent_setting%: шанс задаёт настройка '
        + 'сайта) или «остаток» — всё, что не разобрали соседи. Не набрали ста '
        + 'процентов и остатка нет — в разнице не выпадает ничего, и переменная '
        + 'приходит пустой.'
        + (isBatch
            ? ' Серия: каждая переменная бросается столько раз, сколько скажет '
              + 'переменная ниже, и приходит нумерованным списком.'
            : '')));

    if (isBatch) {
        host.appendChild(_timesRow(timesSelect, current, collect));
    }

    host.appendChild(list);
    host.appendChild(addButton);

    const saved = _specIn(current);
    const names = Object.keys(saved);

    if (names.length) {
        names.forEach(name => addVariable(name, saved[name]));
    } else {
        // ⚠ Выбрали инструмент — переменная заводится сразу, с двумя вариантами
        // по половине. Пустой редактор пришлось бы «начинать», а начатый видно
        // сразу, что он умеет.
        addVariable();
    }
}

// ── Внутреннее ──────────────────────────────────────────────────────────────

/** Описание жребия из сохранённого `inputs_map`. Пусто — ничего не настроено.
 *
 * ## ⚠⚠ Два места, где оно может лежать, и второе — главное
 *
 * Исторически описание клалось **литералом** (`_const_{…}`) прямо в
 * `inputs_map`. Литерал с тех пор запрещён: движок отвечает на него отказом, а
 * значения переехали в **переменные потока** (`spec: "dice_photo_spec"`).
 *
 * ⚠⚠⚠ Читать после переезда виджет не научили, и форма показывала **пустой
 * жребий у всех шагов во всех workflow** — при живых, работающих описаниях.
 * Хуже пустоты было то, что сохранение такой формы затирало `inputs_map`
 * пустым описанием: открыл посмотреть, нажал «Сохранить» — и жребий потерян.
 *
 * Поэтому читаем оба вида: имя переменной разворачиваем по списку страницы,
 * литерал понимаем ради старых баз, которые ещё не переехали.
 */
function _specIn(current) {
    const raw = String(((current || {}).inputs_map || {})[DICE_ARG] || '');

    if (!raw) return {};

    const text = raw.startsWith(DICE_CONST) ? raw.slice(DICE_CONST.length)
                                            : _specByName(raw);

    if (!text) return {};

    try {
        const got = JSON.parse(text);
        return (got && typeof got === 'object' && !Array.isArray(got)) ? got : {};
    } catch (e) {
        return {};
    }
}

/** Значение переменной потока по имени. Пусто — такой переменной нет.
 *
 * ⚠ Берём из `window.allCurrentVariables` — того же списка, которым нарисована
 * первая колонка страницы; им же сверяются метки долей ниже. Второй источник
 * тех же имён разошёлся бы с первым молча.
 *
 * ⚠ Имя приезжает как есть (`dice_photo_spec`), но процентные метки внутри
 * описания пишутся в обёртке (`%percent_setting%`) — поэтому обёртку снимаем:
 * `inputs_map` обеих записей встречается в живых базах.
 */
function _specByName(name) {
    const want = String(name || '').replace(/^%/, '').replace(/%$/, '');
    const known = window.allCurrentVariables;

    if (!want || !Array.isArray(known)) return '';

    const found = known.find(one => String(one && one.name) === want);

    return found ? String(found.default ?? found.value ?? '') : '';
}

/** Положить описание в переменную потока — в память страницы и в её поле.
 *
 * ⚠⚠ Пишем **и в список состояния, и в поле на странице**: список читает сам
 * виджет (следующее открытие формы), а поле — общая кнопка «Сохранить
 * workflow», которая и уносит правку в базу. Обнови мы одно, человек увидел бы
 * свои доли в форме и не нашёл их после сохранения.
 *
 * ⚠ Поля может не быть (список переменных свёрнут) — тогда довольно списка:
 * страница перечитывает его при раскрытии.
 */
function _specToVariable(name, spec) {
    const text = JSON.stringify(spec);
    const known = window.allCurrentVariables;

    if (Array.isArray(known)) {
        const one = known.find(row => String(row && row.name) === name);
        if (one) one.default = text;
    }

    // ⚠⚠ Строку списка обновляет **та же функция**, что и правка переменной
    // руками (`syncHiddenRow`): общая кнопка «Сохранить workflow» читает
    // именно её поля. Свой селектор здесь был бы вторым знанием о разметке
    // списка и разошёлся бы с ним на первой перевёрстке.
    const found = Array.isArray(known)
        ? known.find(one => String(one && one.name) === name) : null;

    if (found) syncHiddenRow(found);
}


/** Доля в том виде, в каком уезжает в JSON: число либо метка строкой. */
function _shareOut(text) {
    // ⚠ Метка и «остаток» уезжают строкой как есть: их читает инструмент.
    if (!_isNumberShare(text)) return text.trim();
    const num = Number(String(text).replace(',', '.'));

    return Number.isFinite(num) ? num : 0;
}

/** Блок одной переменной: имя, её варианты, итог по долям. */
function _variableBlock(name, options, collect, mayRemove) {
    const block = document.createElement('div');
    block.className = 'dice-var';
    block.style = 'background: #fff; border: 1px solid #e2e8f0; border-radius: 6px;'
        + ' padding: 8px; display: flex; flex-direction: column; gap: 6px;';

    const head = document.createElement('div');
    head.style = 'display: flex; align-items: center; gap: 8px;';

    const nameInput = document.createElement('input');
    nameInput.className = 'form-control dice-var-name';
    nameInput.placeholder = 'имя переменной, например mail_opening';
    nameInput.value = name || '';
    nameInput.style = 'flex: 1; padding: 5px; font-size: 12px; height: 32px;'
        + ' font-weight: 600; color: #ea3d3d;';
    nameInput.oninput = collect;

    const dropVar = _button('×', '#a0aec0');
    dropVar.title = 'убрать переменную';
    dropVar.onclick = () => {
        if (!mayRemove()) return;
        block.remove();
        collect();
    };

    head.appendChild(nameInput);
    head.appendChild(dropVar);

    const rows = document.createElement('div');
    rows.className = 'dice-options';
    rows.style = 'display: flex; flex-direction: column; gap: 4px;';

    const total = document.createElement('div');
    total.className = 'dice-total';
    total.style = 'font-size: 11px; color: #64748b;';

    const foot = document.createElement('div');
    foot.style = 'display: flex; align-items: center; gap: 8px;';

    const addOption = _button('+ вариант', '#48bb78');
    addOption.onclick = () => {
        rows.appendChild(_optionRow('', null, block, collect));
        // ⚠⚠ Доли пересчитываются поровну при добавлении и удалении варианта:
        // так их сумма всегда сходится сама, и человеку не приходится держать
        // в голове арифметику ради того, чтобы просто добавить строку. Правки
        // руками после этого никто не отменяет.
        _spread(block);
        _retotal(block);
        collect();
    };

    foot.appendChild(addOption);
    foot.appendChild(total);

    block.appendChild(head);
    block.appendChild(rows);
    block.appendChild(foot);

    const given = options && typeof options === 'object' ? Object.entries(options) : [];

    if (given.length) {
        given.forEach(([value, share]) =>
            rows.appendChild(_optionRow(value, share, block, collect)));
    } else {
        for (let i = 0; i < DICE_OPTIONS_MIN; i += 1) {
            rows.appendChild(_optionRow('', null, block, collect));
        }
        _spread(block);
    }

    _retotal(block);

    return block;
}

/** Строка варианта: текст, доля, выбор переменной для доли, удаление. */
function _optionRow(value, share, block, collect) {
    const row = document.createElement('div');
    row.className = 'dice-option';
    row.style = 'display: flex; align-items: center; gap: 6px;';

    // ⚠⚠ Поле **раскрывается в фокусе** (`_growing`): варианты жребия бывают
    // длиной в две строки («начни с того, чем она была занята, когда вспомнила о
    // нём»), и в одну строку input их приходилось прокручивать вслепую.
    const text = _growing(value, 'значение, которое получит переменная', collect);

    const shareInput = document.createElement('input');
    shareInput.className = 'form-control dice-option-share';
    shareInput.value = share === null || share === undefined ? '' : String(share);
    shareInput.oninput = () => {
        _clamp(shareInput, block);
        // ⚠ Заодно снимаем пометку о негодном значении: человек правит имя, и
        // красная рамка на каждой букве недописанного — помеха.
        _shareBase(shareInput);
        _retotal(block);
        collect();
    };
    // ⚠⚠ Проверяем **на потере фокуса**, а не на вводе: имя набирают по букве, и
    // `%dice_m` негодно ровно до последнего знака. Ругаться раньше — ругаться на
    // человека за то, что он ещё печатает.
    shareInput.onblur = () => _shareCheck(block);
    _shareBase(shareInput);

    // ⚠⚠ **Селекта «взять долю из переменной» здесь нет намеренно.** Он был и
    // подставлял в это же поле `%имя%` либо `rest` — то есть делал ровно то, что
    // человек делает набором, и занимал при этом сто семьдесят пикселей в
    // **каждой** строке, хотя в большинстве строк лежит обычное число.
    //
    // Его работ было две, и обе закрыты дешевле: опечатку в имени ловит сам
    // инструмент (метка, не раскрывшаяся к его вызову, — это отказ с именем
    // переменной в тексте, а не молчаливый ноль), а про «остаток» и метки
    // говорят подсказка сверху и placeholder.
    const drop = _button('×', '#a0aec0');
    drop.title = 'убрать вариант';
    drop.onclick = () => {
        const rows = block.querySelectorAll('.dice-option');
        // ⚠ Ниже двух не опускаемся — инструмент такое описание отвергнет, и
        // узнать об этом на живом заходе дороже, чем не дать нажать здесь.
        if (rows.length <= DICE_OPTIONS_MIN) return;
        row.remove();
        _spread(block);
        _retotal(block);
        collect();
    };

    row.appendChild(text);
    row.appendChild(shareInput);
    row.appendChild(drop);

    return row;
}

// Сколько строк показывает раскрытое поле варианта.
//
// ⚠ Четыре: самый длинный вариант в живых жребиях — про восемьдесят знаков, и при
// ширине колонки это три строки. Четвёртая — запас, чтобы у предела не появлялась
// прокрутка, ради избавления от которой всё и сделано.
const DICE_TEXT_ROWS = 4;

// Общий вид обоих состояний поля: свёрнутого и раскрытого. ⚠ Одной строкой на
// оба — иначе при подмене узла поле дёргалось бы шрифтом или отступом.
const DICE_TEXT_STYLE = 'flex: 1; padding: 4px; font-size: 12px;';

/**
 * Поле варианта, которое **в фокусе становится `textarea`, а вне фокуса — снова
 * `input`**.
 *
 * ## ⚠⚠ Зачем подменять узел, а не растить `textarea` на месте
 *
 * Вариант жребия бывает длиной в две-три строки, и в `input` его читают
 * прокруткой вслепую: видно середину фразы без начала и конца. Раскрытое поле
 * показывает её целиком.
 *
 * Держать `textarea` всегда, меняя ей `rows` с 1 на 4, было бы проще — но
 * свёрнутая `textarea` не равна `input`: она переносит слова и ловит колесо мыши,
 * то есть список из восьми вариантов начинает прокручиваться внутри строк вместо
 * страницы. Поэтому подменяем узел.
 *
 * ## ⚠ Что здесь легко сломать
 *
 * **Класс.** Значения собираются по `.dice-option-text` (`collect`): потеряй его
 * замена — жребий сохранился бы без вариантов, и молча.
 *
 * **Фокус и каретка.** Событие `focus` случается на старом узле; после замены
 * фокус надо поставить руками, иначе человек нажал на поле, а печатать некуда.
 * Каретку переносим по `selectionStart` — без этого клик в середину фразы уводил
 * бы её в начало.
 *
 * @param {string} value что лежит в поле.
 * @param {string} hint placeholder — один на оба состояния.
 * @param {function} collect звать на каждое изменение: он собирает жребий.
 * @returns {HTMLElement} свёрнутое поле; дальше оно меняется само.
 */
function _growing(value, hint, collect) {
    const make = (tag) => {
        const el = document.createElement(tag);
        el.className = 'form-control dice-option-text';
        el.placeholder = hint;
        el.value = value;
        el.oninput = () => {
            // ⚠ Своё значение держим сами: узлы сменяются, и `value` нового
            // берётся отсюда. Читать его у прежнего узла нельзя — он уже удалён.
            value = el.value;
            collect();
        };

        if (tag === 'textarea') {
            el.rows = DICE_TEXT_ROWS;
            // ⚠ Растягивать не даём: строка варианта стоит в ряду с долей и
            // крестиком, и ручка изменения размера съезжала бы на них.
            el.style = DICE_TEXT_STYLE + ' resize: none;';
        } else {
            el.type = 'text';
            // ⚠ Высота задана явно и та же, что у поля доли рядом: без неё
            // свёрнутое поле на пиксель выше, и ряд «прыгает» на каждый уход
            // фокуса.
            el.style = DICE_TEXT_STYLE + ' height: 30px;';
        }

        return el;
    };

    // Раскрытие: фокус переносим на новый узел вместе с кареткой.
    //
    // ⚠⚠ Фокус ставится **только при раскрытии**. Сделай это и при сворачивании —
    // свёрнутый `input` получил бы фокус, тут же сработал бы его `onfocus`, и поле
    // раскрылось бы снова: уйти из него стало бы невозможно. Отсюда две функции, а
    // не одна с флагом: разница не в настройке, а в смысле.
    const open = (from, to) => {
        // ⚠ Позицию каретки снимаем **до** замены: у удалённого узла её уже нет.
        const at = from.selectionStart;
        from.replaceWith(to);
        to.focus();
        // ⚠ В `try`: браузер вправе отказать в выделении, если узел ещё не
        // отрисован, а ронять из-за каретки весь редактор незачем.
        try {
            to.setSelectionRange(at ?? to.value.length, at ?? to.value.length);
        } catch (e) {
            /* каретка не встала — поле всё равно в фокусе и годно к правке */
        }
    };

    // ⚠⚠ Обработчик берёт узел **доводом**, а не из замыкания. Замыкание помнило
    // бы самый первый `input`, а он после первой же замены удалён: второй щелчок
    // по полю пытался бы заменить мёртвый узел и не делал ничего. Ошибку эту я и
    // допустил, пока не проследил второй цикл до конца.
    const collapsed = (node) => {
        node.onfocus = () => {
            const big = make('textarea');
            // ⚠ Сворачиваем **без** переноса фокуса — просто подменяем узел.
            big.onblur = () => big.replaceWith(collapsed(make('input')));
            open(node, big);
        };

        return node;
    };

    // ⚠ Узлы создаём по требованию, а не держим пару наготове: при восьми
    // вариантах это восемь лишних `textarea`, живущих ради одного щелчка.
    return collapsed(make('input'));
}

// Ширина поля доли по тому, что в нём лежит. ⚠ Числу хватает узкого: больше
// «100» там не бывает, а широкое поле под двузначное число сдвигает вправо всё
// остальное — при восьми вариантах это заметно сразу.
//
// Ширина поля доли — **одна на все значения**. ⚠⚠ Подгонять её под содержимое
// я пробовал (число 48, метка 150) и это оказалось хуже: поле прыгает, пока в нём
// печатают, а предсказать, что туда впишут, нельзя — сегодня там «50», завтра
// `%dice_mail_story_percent%`. Ширина берётся по самому длинному из законных
// значений, то есть по метке.
const DICE_SHARE_WIDTH = '150px';

// Красный: и рамка, и текст негодного значения.
const DICE_BAD_COLOR = '#e53e3e';

/**
 * Вернуть полю доли обычный вид — заодно сняв пометку о негодном значении.
 *
 * ⚠ Отдельной функцией, потому что зовут её из двух разных мест и по разным
 * поводам: при вводе — чтобы красная рамка не мешала дописывать имя, при
 * проверке — чтобы начать с чистого листа и пометить заново только плохое.
 */
function _shareBase(field) {
    field.style = `width: ${DICE_SHARE_WIDTH}; padding: 4px; font-size: 12px;`
        + ' height: 30px;';
    // ⚠ Подсказка — единственное место, где человек узнаёт про «остаток» и
    // метки: селекта, который их подставлял, больше нет.
    field.placeholder = '50 · rest · %имя%';
    field.title = 'шанс в процентах, «rest» — остаток до 100%,'
        + ' либо метка переменной %имя%';
}

/**
 * Пометить негодные доли в блоке переменной; годные вернуть к обычному виду.
 *
 * ⚠⚠ **Проверяем весь блок, а не одно поле.** Два «остатка» — ошибка **пары**:
 * поодиночке каждый законен. Правка одного обязана снимать пометку со второго, а
 * этого не сделать, глядя на поле в отдельности.
 *
 * @param {HTMLElement} block блок одной переменной жребия.
 */
function _shareCheck(block) {
    const fields = [...block.querySelectorAll('.dice-option-share')];
    const rests = fields.filter(one => _isRestShare(one.value)).length;

    fields.forEach(field => {
        _shareBase(field);

        const why = _shareWrong(field.value, rests);
        if (!why) return;

        field.style.borderColor = DICE_BAD_COLOR;
        field.style.color = DICE_BAD_COLOR;
        field.title = why;
    });
}

/** «Остаток» ли это. ⚠ Регистр и пробелы — как у `dice.py`: «Rest» сойдёт. */
function _isRestShare(text) {
    return String(text || '').trim().toLowerCase() === DICE_REST;
}

/**
 * Чем плоха доля. Пусто — годная.
 *
 * ⚠⚠ Каждый из трёх отказов инструмент выдаёт **на живом заходе**, то есть на
 * письме живому человеку. Здесь они стоят трёх сравнений, а там — неушедшего
 * письма и получаса поисков в журнале.
 *
 * ⚠ Пустое поле законно: инструмент читает его как ноль, «этот вариант не
 * выпадает». Так гасят вариант, не удаляя его.
 */
function _shareWrong(raw, rests) {
    const text = String(raw || '').trim();

    if (!text) return '';

    if (_isRestShare(text)) {
        // ⚠ Два «остатка» инструмент отвергает: делить остаток между ними
        // пришлось бы по правилу, которого никто не задавал.
        return rests > 1
            ? 'Остаток уже отдан другому варианту. Он может быть только один —'
              + ' иначе неизвестно, как делить его между ними.'
            : '';
    }

    if (text.startsWith('%')) {
        // ⚠⚠ Сверяем по `window.allCurrentVariables` — тому самому списку,
        // которым нарисована первая колонка страницы. Метки, которой там нет, в
        // заходе не будет тоже: движок оставит её в тексте как есть, а жребий
        // ответит отказом.
        //
        // ⚠ Пустой список — не повод ругаться: переменные приезжают своим
        // запросом, и до его ответа «не нашли» значит «ещё не знаем».
        const known = window.allCurrentVariables;
        if (!Array.isArray(known) || !known.length) return '';

        const name = text.replace(/^%/, '').replace(/%$/, '');

        return known.some(one => String(one && one.name) === name) ? ''
            : `Переменной «${name}» нет среди переменных этого workflow — метка`
              + ' не раскроется, и жребий ответит отказом. Проверьте имя по'
              + ' списку слева.';
    }

    // ⚠ Осталось число — и здесь ловится самое тихое: «rst» или «40%%» уезжали
    // в описание как есть, а инструмент читал их отказом «доля не число».
    return Number.isFinite(Number(text.replace(',', '.'))) ? ''
        : 'Доля — это число, «rest» или метка %имя%. Такое значение жребий не'
          + ' прочитает и ответит отказом.';
}

/** Разложить сто процентов поровну между вариантами с числовой долей.
 *
 * ⚠ Доли-метки не трогаем и в счёт не берём: их значение известно только в
 * заходе, и переписать метку числом значило бы молча отменить настройку.
 */
function _spread(block) {
    const fields = [...block.querySelectorAll('.dice-option-share')]
        .filter(one => _isNumberShare(one.value));

    if (!fields.length) return;

    const each = Math.floor(DICE_PERCENT_TOTAL / fields.length);
    let left = DICE_PERCENT_TOTAL - each * fields.length;

    fields.forEach(one => {
        // Остаток от деления раздаём первым строкам по единице: 34 / 33 / 33.
        one.value = String(each + (left > 0 ? 1 : 0));
        if (left > 0) left -= 1;
    });
}

/** Не дать сумме перевалить за сто: лишнее срезаем у поля, которое правят. */
function _clamp(field, block) {
    const text = field.value.trim();
    if (!_isNumberShare(text)) return;

    const num = Number(text.replace(',', '.'));
    if (!Number.isFinite(num)) return;

    const others = [...block.querySelectorAll('.dice-option-share')]
        .filter(one => one !== field)
        .reduce((sum, one) => sum + _numberOf(one.value), 0);

    if (num < 0) field.value = '0';
    if (others + num > DICE_PERCENT_TOTAL) field.value = String(Math.max(0, DICE_PERCENT_TOTAL - others));
}

/** Слово «вариант» в нужном числе: 1 вариант, 2 варианта, 5 вариантов. */
function _optionsWord(qty) {
    const two = qty % 100;
    const one = qty % 10;

    if (two > 10 && two < 20) return 'вариантов';
    if (one === 1) return 'вариант';
    if (one > 1 && one < 5) return 'варианта';

    return 'вариантов';
}

/** Подпись с итогом: сколько набрано, сколько вариантов и что значит недобор. */
function _retotal(block) {
    const fields = [...block.querySelectorAll('.dice-option-share')];
    const marks = fields.filter(one => one.value.trim().startsWith('%')).length;
    const rests = fields.filter(
        one => one.value.trim().toLowerCase() === DICE_REST).length;
    const sum = fields.reduce((acc, one) => acc + _numberOf(one.value), 0);
    const foot = block.querySelector('.dice-total');

    if (!foot) return;

    // Три разных исхода, и путать их нельзя: остаток кем-то занят, остаток ничей,
    // либо итог вообще неизвестен до захода.
    const left = DICE_PERCENT_TOTAL - sum;
    let tail = '';

    if (rests) {
        // ⚠ Остаток занят — недобора не бывает: сумма сходится при любой
        // настройке, ради чего «остаток» и заведён.
        tail = ` · остаток (${marks ? 'считается в заходе' : left + '%'}) забирает свой вариант`;
    } else if (marks) {
        tail = ` и ещё ${marks} из переменных — итог известен только в заходе`;
    } else if (left > 0) {
        // ⚠⚠ Недобор — **законное** описание, а не недоделка: в оставшихся
        // процентах переменная приходит пустой, и `%if%` читает это как «не
        // надо». Так задаётся «в 40% случаев добавь рассказ» без пустышки.
        tail = ` · в остальных ${left}% не выпадает ничего`;
    }

    // ⚠ Счёт вариантов — сразу после процентов, до разговора про остаток:
    // в переменной их бывает под сотню, и вручную такое не считают. Нужен он
    // ровно тогда, когда список длинный, то есть когда его не видно целиком.
    const qty = `${fields.length} ${_optionsWord(fields.length)}`;

    foot.textContent = `сумма: ${sum}% · ${qty}${tail}`;
    foot.style.color = sum > DICE_PERCENT_TOTAL ? '#e53e3e' : '#64748b';
}

/** Число из поля доли; метка и мусор считаются нулём. */
function _numberOf(text) {
    const raw = String(text || '').trim();
    if (!_isNumberShare(raw)) return 0;
    const num = Number(raw.replace(',', '.'));

    return Number.isFinite(num) ? num : 0;
}

/** Ряд «сколько бросков» для серии: подпись и выбор переменной. */
function _timesRow(select, current, collect) {
    const row = document.createElement('div');
    row.className = 'dice-times-row';
    row.style = 'display: flex; align-items: center; gap: 8px;'
        + ' background: #fff; padding: 6px 10px; border: 1px solid #e2e8f0;'
        + ' border-radius: 4px;';

    const label = document.createElement('span');
    label.style = 'font-size: 12px; color: #334155; white-space: nowrap;';
    label.textContent = 'Бросков на переменную:';

    // ⚠⚠ Только выбором переменной, без поля для числа. Длина серии равна
    // размеру пачки, а он приходит заходом — зашитое число совпадало бы с ним
    // ровно до первого пакета другого размера, и разойтись они могли бы молча.
    const saved = ((current || {}).inputs_map || {})[DICE_ARG_TIMES] || '';
    fillVariablesSelectOptions(select, saved, '-- переменная с числом --');
    select.onchange = collect;

    row.appendChild(label);
    row.appendChild(select);

    return row;
}

function _hint(text) {
    const node = document.createElement('div');
    node.style = 'font-size: 11px; color: #64748b; font-style: italic;'
        + ' background: #fff; padding: 6px 10px; border: 1px dashed #cbd5e0;'
        + ' border-radius: 4px;';
    node.textContent = text;

    return node;
}

function _button(text, color) {
    const node = document.createElement('button');
    node.type = 'button';
    node.textContent = text;
    node.style = `border: 1px solid ${color}; color: ${color}; background: #fff;`
        + ' border-radius: 4px; font-size: 11px; padding: 3px 8px; cursor: pointer;';

    return node;
}

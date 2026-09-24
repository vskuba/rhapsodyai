// Редактор жребия: переменные, их варианты и шансы выпадения.
//
// ⚠⚠ Своим модулем, а не ещё двумя сотнями строк в `step-widgets.js`. Тот уже
// на девятьсот строк и держит пять виджетов разом; шестой сделал бы его файлом,
// который открывают только по необходимости.
//
// ⚠ Инструмент `dice` — единственный, у кого выходы **не объявлены заранее**:
// их имена придумывает человек здесь же. Поэтому общий вид «входы слева, выходы
// справа» ему не подходит, и у него свой.

import {fillVariablesSelectOptions} from './variables.js';

// Имя инструмента, ради которого всё это. ⚠ Сверяется с `tool.name` в базе:
// переименуют там — здесь перестанет находиться, и человек увидит общий вид.
export const DICE_TOOL_NAME = 'dice';

// Довод инструмента, в который уезжает описание жребия.
// ⚠ Обязан совпадать с именем аргумента функции `dice(spec)`: движок кладёт
// значения в аргументы **по имени** (`inputs_map`), а не по порядку.
const DICE_ARG = 'spec';

// Приставка, которой движок отличает литерал от имени переменной
// (`ai_framework_manager`: `var_name.startswith('_const_')`).
const DICE_CONST = '_const_';

// Сколько вариантов заводится сразу и сколько их должно остаться минимум.
// ⚠ Два — не круглое число, а смысл: один вариант это не жребий, а постоянное
// значение, и такое описание инструмент отвергает.
const DICE_OPTIONS_MIN = 2;

// Сумма долей одной переменной. ⚠ То же число, что в `dice.py`; расходиться им
// нельзя — редактор пропустил бы описание, на котором заход упадёт.
const DICE_TOTAL = 100;

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
 */
export function renderDiceWidget(host, current, save) {
    host.innerHTML = '';

    const list = document.createElement('div');
    list.className = 'dice-list';
    list.style = 'display: flex; flex-direction: column; gap: 10px;';

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

        save({
            tool_name: DICE_TOOL_NAME,
            inputs_map: {[DICE_ARG]: DICE_CONST + JSON.stringify(spec)},
            outputs_map: outputs,
        });
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
        + 'приходит пустой.'));
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

/** Описание жребия из сохранённого `inputs_map`. Пусто — ничего не настроено. */
function _specIn(current) {
    const raw = ((current || {}).inputs_map || {})[DICE_ARG] || '';
    const text = String(raw).startsWith(DICE_CONST)
        ? String(raw).slice(DICE_CONST.length) : '';

    if (!text) return {};

    try {
        const got = JSON.parse(text);
        return (got && typeof got === 'object' && !Array.isArray(got)) ? got : {};
    } catch (e) {
        return {};
    }
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

    const text = document.createElement('input');
    text.className = 'form-control dice-option-text';
    text.placeholder = 'значение, которое получит переменная';
    text.value = value || '';
    text.style = 'flex: 1; padding: 4px; font-size: 12px; height: 30px;';
    text.oninput = collect;

    const shareInput = document.createElement('input');
    shareInput.className = 'form-control dice-option-share';
    shareInput.value = share === null || share === undefined ? '' : String(share);
    shareInput.oninput = () => {
        _clamp(shareInput, block);
        _shareFit(shareInput);
        _retotal(block);
        collect();
    };
    _shareFit(shareInput);

    // ⚠ Доля из переменной вводится **тем же полем**: отдельный переключатель
    // «число или переменная» добавил бы состояние, которое видно только по нему,
    // а метка `%имя%` говорит о себе сама. Селект рядом лишь вставляет её,
    // чтобы имя не набирали руками с опечатками.
    const pick = document.createElement('select');
    pick.className = 'form-control dice-option-var';
    // ⚠⚠ Шире поля доли, и это не вкусовщина: в списке лежат **имена
    // переменных** (`dice_mail_question_percent`) и «остаток до 100%». В узком
    // селекте не читается ни то, ни другое — человек выбирает вслепую и узнаёт,
    // что выбрал, только по тому, что подставилось в соседнее поле.
    pick.style = 'width: 170px; padding: 2px; font-size: 11px; height: 30px;';
    pick.innerHTML = '<option value="">— долю из —</option>';
    // ⚠⚠ «Остаток» стоит **первым пунктом**, до списка переменных: у пары
    // «да/нет» с долей из настройки это единственный верный способ задать вторую
    // половину. Впиши туда число — и стоит человеку подвинуть настройку, как
    // сумма перевалит за сотню, а увидит он это отказом на живом заходе.
    pick.innerHTML += `<option value="${DICE_REST}">остаток до 100%</option>`;
    fillVariablesSelectOptions(pick, '');
    pick.title = 'взять долю из переменной или отдать остаток';
    pick.onchange = () => {
        if (pick.value) {
            shareInput.value = pick.value === DICE_REST
                ? DICE_REST : `%${pick.value}%`;
            _shareFit(shareInput);
            _retotal(block);
            collect();
        }
        pick.value = '';
    };

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
    row.appendChild(pick);
    row.appendChild(drop);

    return row;
}

// Ширина поля доли по тому, что в нём лежит. ⚠ Числу хватает узкого: больше
// «100» там не бывает, а широкое поле под двузначное число сдвигает вправо всё
// остальное — при восьми вариантах это заметно сразу.
//
// ⚠⚠ Метке узкого мало: `%dice_mail_story_percent%` в полсотни пикселей не
// читается вовсе, а именно по ней видно, что долю задаёт настройка сайта.
// Прятать это за обрезкой — прятать самое важное в строке.
const DICE_SHARE_WIDTH = {number: '48px', rest: '64px', mark: '150px'};

/**
 * Подогнать ширину поля доли под то, что в нём лежит.
 *
 * ⚠ Ширину ведёт **одна** функция: значение поля меняется из трёх мест (ввод
 * руками, выбор из селекта, раскладка поровну), и три копии правила разошлись бы
 * — поле то сжималось бы на метке, то оставалось широким под числом.
 */
function _shareFit(field) {
    const raw = String(field.value || '').trim();
    const kind = _isNumberShare(raw) ? 'number'
        : (raw.startsWith('%') ? 'mark' : 'rest');

    field.style = `width: ${DICE_SHARE_WIDTH[kind]}; padding: 4px;`
        + ' font-size: 12px; height: 30px;'
        + ` text-align: ${kind === 'number' ? 'right' : 'left'};`;
    field.title = kind === 'number'
        ? 'шанс в процентах'
        : 'долю задаёт это значение: метка переменной или остаток до 100%';
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

    const each = Math.floor(DICE_TOTAL / fields.length);
    let left = DICE_TOTAL - each * fields.length;

    fields.forEach(one => {
        // Остаток от деления раздаём первым строкам по единице: 34 / 33 / 33.
        one.value = String(each + (left > 0 ? 1 : 0));
        if (left > 0) left -= 1;
        _shareFit(one);
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
    if (others + num > DICE_TOTAL) field.value = String(Math.max(0, DICE_TOTAL - others));
}

/** Подпись с итогом: сколько набрано и что значит недобор. */
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
    const left = DICE_TOTAL - sum;
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

    foot.textContent = `сумма: ${sum}%${tail}`;
    foot.style.color = sum > DICE_TOTAL ? '#e53e3e' : '#64748b';
}

/** Число из поля доли; метка и мусор считаются нулём. */
function _numberOf(text) {
    const raw = String(text || '').trim();
    if (!_isNumberShare(raw)) return 0;
    const num = Number(raw.replace(',', '.'));

    return Number.isFinite(num) ? num : 0;
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

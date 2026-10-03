// Вкладка «History»: правки этого workflow — кто, когда и что на что.
//
// ## ⚠⚠⚠ Зачем вкладка
//
// 03.10.2026 цикл инвайтов стал давать один шаблон вместо одиннадцати: у шага
// `workflow_invoke` поле `repeat.count` потеряло метку `%invite_count%` и стало
// единицей. Ошибки не случилось ни одной — прогон шёл, пул набирался, — а следа
// правки не было нигде: время поломки искали по числу разных текстов в чужой
// базе, с точностью до трёх минут.
//
// Отсюда предмет: показать правки так, чтобы на вопрос «когда это сломалось»
// отвечал один взгляд.
//
// ⚠ Это не журнал прогонов. Прогоны — `/admin/workflow_trace`, там видно, как
// workflow **работал**; здесь — как его **меняли**.

import {getData} from '../api.js';
import {editorWorkflowId} from './utils.js';

// Сколько правок на странице. ⚠ Тридцать — как у журнала прогонов: страницы
// стоят рядом и листаются одним пейджером, разные размеры читались бы как
// разница по существу, которой нет.
const HISTORY_PER = 30;

// Род предмета — словами. ⚠ `step` в ленте рядом с человеческим «изменено»
// выглядит чужим.
const OBJECT_WORDS = {workflow: 'workflow', step: 'шаг', variable: 'переменная'};

// Поля самого workflow — человеческими именами.
//
// ⚠ Только свои поля, и намеренно. Пути внутрь метаданных шага
// (`metadata.workflow_invoke.repeat.count`) остаются как есть: это адрес, по
// которому правку ищут в редакторе, и перевод сделал бы его ненаходимым.
const FIELD_WORDS = {
    name: 'технический id',
    title: 'название',
    description: 'описание',
    node_id: 'нода',
    group_name: 'группа',
    subflow: 'sub-workflow',
    type: 'род',
    'default': 'значение по умолчанию',
};

// Флаг — словами. ⚠ Ключи строками: значение приходит и числом (`0` из базы),
// и строкой (`"1"` из формы), а в ленте это одно и то же «да».
const BOOL_WORDS = {'0': 'нет', '1': 'да', 'false': 'нет', 'true': 'да'};

// Род переменной — теми же словами, что в реестре слева
// (`workflowVariableSections`). ⚠ Своими словами нельзя: человек сверяет
// запись истории с тем, что видит в списке, и расхождение читается как правка
// чего-то другого.
const VAR_TYPE_WORDS = {
    input: 'входящая',
    workflow: 'workflow',
    global: 'глобальная',
};

// Значок правки — чтобы вид события читался до чтения слов.
//
// ⚠⚠ Выбирается по паре «действие + поле», а не по одному действию:
// переименование — это тот же `update`, и без поля оно неотличимо от правки
// промпта. Разбор — в `_sign`.
//
// ⚠ Поля, которые человек правит руками, сюда не попадают: значок ставится
// только тому, что служба узнаёт наверняка. Незнакомому — общий «изменено».
const SIGN_WORDS = {
    create: '➕',
    delete: '🗑️',
    reorder: '🔀',
    import: '📦',
    update: '✏️',
    // Особые случаи `update`, по полю.
    rename: '🏷️',
    move: '📁',
    text: '📝',
};

// Поля, у которых правка — это переименование либо переезд. ⚠ `name` — это
// технический id workflow, и смена его такое же переименование, как у `title`.
const SIGN_FIELDS = {
    title: 'rename',
    name: 'rename',
    node_id: 'move',
    group_name: 'move',
};

// Что сделали — в роде предмета. ⚠ `reorder` назван «порядок шагов», а не
// «перестановка»: в ленте читают глазами, и существительное находится быстрее
// отглагольного.
//
// ⚠⚠ Род обязателен: слово стоит вплотную к предмету, и «заведено переменная»
// спотыкает на каждой строке. У правки самого workflow предмет не пишется
// вовсе, и там идёт безличное средним родом — «изменено».
const ACTION_WORDS = {
    create: {n: 'заведено', m: 'заведён', f: 'заведена'},
    update: {n: 'изменено', m: 'изменён', f: 'изменена'},
    delete: {n: 'удалено', m: 'удалён', f: 'удалена'},
    reorder: {n: 'порядок шагов'},
    import: {n: 'импорт'},
};

// Род предмета для согласования: шаг — мужской, переменная — женский, сам
// workflow предметом не пишется и идёт безличным средним.
const OBJECT_GENDER = {workflow: 'n', step: 'm', variable: 'f'};

// Кто правил. ⚠ Правки агента лежат **в той же ленте** (решение человека): метка
// нужна затем, чтобы человеческие не терялись среди машинных, а не затем, чтобы
// их разделить.
const AUTHOR_WORDS = {human: '', agent: '🤖 агент', import: '📦 импорт'};

// Состояние вкладки: какой workflow показан, на какой странице и с каким отбором.
//
// ⚠ Отбор держим здесь, а не в DOM: страница перерисовывается целиком, и
// прочитай мы его из разметки — он слетал бы на каждой перерисовке.
const view = {workflowId: 0, page: 1, object: '', objectId: 0};

// Спрашивали ли уже пояс установки. ⚠ Один раз за жизнь страницы: настройка за
// время работы вкладки не меняется, а запрос на каждое её открытие — лишний.
let _tzAsked = false;


/**
 * Открыть вкладку: прочитать правки и нарисовать ленту.
 *
 * ⚠ Зовётся на каждое открытие, а не один раз: правки идут и пока вкладка
 * закрыта — своей рукой в соседнем окне, чужой или агентом.
 */
export async function openWorkflowHistory() {
    const workflowId = editorWorkflowId();
    const host = document.getElementById('workflowHistory');
    if (!host) return;

    host.style.display = 'block';

    // ⚠⚠ Пояс спрашиваем **до** отрисовки и один раз за жизнь страницы:
    // `loadTz` ходит в `/setting/list`, а вкладку открывают много раз.
    // Забытый вызов и был причиной времени в UTC: `fmtTz` без него считает
    // сдвиг нулём и молчит об этом.
    if (!_tzAsked) {
        _tzAsked = true;
        if (window.loadTz) await window.loadTz();
    }

    if (!workflowId) {
        host.innerHTML = _note('Выберите workflow — история показывается по нему');

        return;
    }

    // Сменился workflow — отбор и страница ни при чём: они были про прошлый.
    if (String(view.workflowId) !== String(workflowId)) {
        view.workflowId = workflowId;
        view.page = 1;
        view.object = '';
        view.objectId = 0;
    }

    await _draw(host);
}


/**
 * Показать историю одного шага — из редактора шага.
 *
 * ⚠ Отбор ставится здесь, а не фильтром в ленте: человек пришёл с вопросом
 * «что было с этим шагом», и заставлять его искать шаг в общем списке значит
 * задать вопрос заново.
 */
export async function openStepHistory(stepId) {
    view.workflowId = editorWorkflowId();
    view.object = 'step';
    view.objectId = Number(stepId) || 0;
    view.page = 1;

    document.getElementById('tabHistory')?.click();
}


// ── Приватное ────────────────────────────────────────────────────────────────

async function _draw(host) {
    host.innerHTML = _note('Читаем историю…');

    let answer;
    try {
        answer = await getData(_url());
    } catch (e) {
        // ⚠ Говорим прямо: пустая лента и «не прочиталось» — разные вещи, и
        // молчание тут читалось бы как «правок не было».
        host.innerHTML = _note(`Историю не прочитать: ${e}`);

        return;
    }

    const rows = (answer && answer.result) || [];
    const parts = [_head(answer)];

    if (!rows.length) {
        parts.push(_note(view.object
            ? 'У этого предмета правок не записано'
            : 'Правок пока не записано'));
    } else {
        // ⚠ Обёртка со своей прокруткой: путь поля и строки диффа бывают
        // длиннее колонки, и без неё таблица растянула бы страницу вбок.
        parts.push('<div class="history-feed"><table class="history-table">'
            + '<thead><tr>'
            // ⚠ Колонка значка без заголовка: слово над ней («вид», «что»)
            // объясняло бы то, что и так понятно с первого взгляда.
            + '<th>Дата</th><th></th><th>Действие</th><th>До</th><th>После</th>'
            + '<th>Шаг</th><th>Кто и что сделал</th>'
            + '</tr></thead><tbody>'
            + rows.map(_row).join('')
            + '</tbody></table></div>');
        parts.push(_pager(answer));
    }

    host.innerHTML = parts.join('');
    _wire(host);
}

function _url() {
    const ask = [`limit=${HISTORY_PER}`, `page=${view.page}`];
    if (view.object) ask.push(`object=${view.object}`);
    if (view.objectId) ask.push(`object_id=${view.objectId}`);

    return `/workflow/${view.workflowId}/history?${ask.join('&')}`;
}

function _head(answer) {
    const total = Number((answer && answer.total) || 0);
    // ⚠ Чипс отбора с крестиком, а не выпадающий список: отбор здесь бывает
    // ровно один (шаг или род), и список из двух состояний — это кнопка.
    const chip = view.object
        ? `<button type="button" class="history-chip" data-history-all="1">`
          + `${OBJECT_WORDS[view.object] || view.object}`
          + `${view.objectId ? ' #' + (Number(view.objectId) || 0) : ''} ✕</button>`
        : '';

    return '<div class="history-head">'
        + `<span>Правок: ${total}</span>${chip}</div>`;
}

/**
 * Запись истории — строками таблицы: по одной на каждое изменение.
 *
 * ## ⚠⚠⚠ Строка таблицы — изменение, а не запись
 *
 * У одной записи правок бывает несколько (`changes`), и колонки «До»/«После»
 * требуют **пары** значений: уложи запись в один ряд — пришлось бы сваливать
 * все «до» в одну ячейку и все «после» в другую, и соответствие между ними
 * читалось бы по порядку. Поэтому ряд на изменение.
 *
 * ⚠ Дата и прочее печатаются **только в первом** ряду записи: повтор одного и
 * того же времени в трёх рядах подряд читается как три события. Связь рядов
 * держит общая рамка группы (`history-first` снизу).
 *
 * ⚠⚠ Запись без изменений (`reorder`, создание) тоже даёт ряд: событие было, и
 * пропусти мы его — лента врала бы молчанием. «До»/«После» у него пустые.
 */
function _row(one) {
    const when = _when(one.created_at);
    const who = one.username || AUTHOR_WORDS[one.author] || '—';
    const mark = AUTHOR_WORDS[one.author] ? ` ${AUTHOR_WORDS[one.author]}` : '';
    // ⚠⚠ Через `_safe` **и** незнакомые значения `action`/`object`. Сегодня это
    // `ENUM` базы и подделать их нечем, но правило здесь одно на все вставки:
    // лента собирается склейкой HTML, и «это поле точно безопасное» — ровно то
    // рассуждение, которым дыры и заводятся. Имена ключей в `field` человек
    // правит руками, и они приезжают в ленту тем же путём.
    const said = ACTION_WORDS[one.action];
    const gender = OBJECT_GENDER[one.object] || 'n';
    const what = said ? (said[gender] || said.n) : _safe(one.action);
    const id = Number(one.object_id) || 0;

    // ⚠⚠⚠ Имя предмета живёт в колонке «Что менялось», а не рядом с автором.
    // Там его и ищут: вопрос «что правили» — про предмет и его поле, а «кто и
    // что сделал» отвечает на другой. Прежде имя стояло справа, и чтобы понять
    // строку, глаз ходил через всю таблицу и обратно.
    //
    // ⚠ У правки самого workflow род и имя **не пишем**. Вкладка показывает
    // историю одного workflow, его имя стоит в шапке страницы, и строка
    // «workflow «Инвайт: шаблон: один»» повторяла бы известное — а повтор
    // известного стоит места, которое нужно сути правки.
    // ⚠⚠⚠ Шаг сюда **не пишется**: у него своя колонка. Имя шага — то, по
    // чему правку ищут чаще всего, и колонка даёт пробежать его столбцом
    // сверху вниз; продублируй мы имя и здесь, строка читалась бы дважды.
    const subject = one.object !== 'variable' ? '' : (() => {
        const object = OBJECT_WORDS[one.object] || _safe(one.object);
        const name = one.object_name
            ? `«${_safe(one.object_name)}»` : (id ? `#${id}` : '');

        return `<div class="history-subject">${object} ${name}</div>`;
    })();

    // Колонка «Шаг»: название, а не номер. ⚠ Номер у шага меняется от
    // перестановки, и запись недельной давности указывала бы им на чужой шаг;
    // имя переживает перестановку. Пусто — правка не про шаг.
    const step = one.object === 'step'
        ? (one.object_name ? _safe(one.object_name) : (id ? `#${id}` : ''))
        : '';

    // ⚠ Щелчок по строке ведёт **к шагу**: история нужна, чтобы починить, а не
    // чтобы полюбоваться. Тот же порядок, что у ленты событий в DatingAi.
    //
    // ⚠ Номер в атрибут — **числом**: строка из базы попала бы в разметку как
    // есть, и кавычка в ней разорвала бы атрибут.
    const goes = one.object === 'step' && id
        ? ` data-history-step="${id}"` : '';

    // Правая колонка: кто правил, что сделал и с чем. ⚠ Одной ячейкой — это
    // «прочее» по смыслу: смотрят туда, когда нужная строка уже найдена
    // глазами по левым колонкам.
    const about = `<div class="history-who">${_safe(who)}${mark}</div>`
        + `<div class="history-what">${what}</div>`;

    // ⚠ Род предмета доезжает до разбора значений: поле `type` есть и у шага
    // (`return_response_llm`), и у переменной (`input`), и переводить их надо
    // по-разному — иначе перевод угадывает.
    // ⚠ Ячейки собираются **отложенно**: предмет приписывается к первому
    // ряду, а какой он первый — знает цикл ниже, не этот список.
    const changes = (one.changes || [])
        .map(row => (head) => _cells(row, one.object, head));

    if (!changes.length) changes.push((head) => _cells(null, one.object, head));

    const rows = one.changes && one.changes.length ? one.changes : [null];
    const signs = rows.map(row => _sign(one.action, row));

    return changes.map((cells, at) => {
        const first = at === 0;

        return `<tr class="history-tr${first ? ' history-first' : ''}"${goes}>`
            + `<td class="history-when">${first ? when : ''}</td>`
            // ⚠ Значок — в каждом ряду, а не только в первом: он про само
            // изменение, и у записи с переименованием и правкой текста они
            // разные.
            + `<td class="history-sign">${signs[at]}</td>`
            // ⚠ Предмет — только в первом ряду записи, как дата: он у неё один
            // на все правки, и повтор в каждом ряду читался бы как новый
            // предмет.
            + cells(first ? subject : '')
            // ⚠ Имя шага — в каждом ряду записи, в отличие от даты: по этой
            // колонке ищут глазами, и пропуск в середине читался бы как «эта
            // правка не про шаг».
            + `<td class="history-step">${step}</td>`
            + `<td class="history-about">${first ? about : ''}</td>`
            + '</tr>';
    }).join('');
}

/**
 * Значок правки: вид события — до чтения слов.
 *
 * Args:
 *     action: `create` / `update` / `delete` / `reorder` / `import`.
 *     one: само изменение; `null` — у записи их нет.
 *
 * ## ⚠⚠ Почему по паре «действие + поле», а не по одному действию
 *
 * Переименование — это тот же `update`, и по действию оно неотличимо от правки
 * промпта. А глазами лента читается именно по виду события: «что тут удаляли»
 * ищут, пробегая столбец, и `🗑️` находится мгновенно, а слово «удалена» —
 * нет.
 *
 * ⚠ Поле решает **только у `update`**: у создания и удаления вид события задан
 * самим действием, и значок поля («переименовано») там был бы ложью — ничего
 * не переименовывали, предмет завели целиком.
 */
function _sign(action, one) {
    if (action !== 'update') return SIGN_WORDS[action] || SIGN_WORDS.update;

    if (!one) return SIGN_WORDS.update;

    // ⚠ Построчный дифф — это правка текста: промпт, описание. Своим значком,
    // потому что по объёму и смыслу это другое событие, чем смена одного поля.
    if (one.lines) return SIGN_WORDS.text;

    const kind = SIGN_FIELDS[one.field];

    return SIGN_WORDS[kind] || SIGN_WORDS.update;
}

/**
 * Три средние ячейки ряда: что менялось, до и после.
 *
 * Args:
 *     one: одно изменение из `changes`; `null` — у записи их нет вовсе.
 *     object: род предмета — нужен разбору значений.
 *     head: готовая разметка предмета («переменная «invite_done»») либо пусто —
 *         её печатает только первый ряд записи.
 *
 * ⚠⚠ Предмет и поле — в одной ячейке, одно над другим: это ответ на один
 * вопрос «что правили», и разносить его по двум колонкам значило бы заставить
 * читать строку в два приёма.
 */
function _cells(one, object, head = '') {
    if (!one) {
        return `<td class="history-field">${head}</td><td></td><td></td>`;
    }

    if (one.more) {
        return `<td class="history-field">${head}</td>`
            + `<td class="history-more" colspan="2">`
            + `…и ещё ${Number(one.more) || 0} изменений</td>`;
    }

    // ⚠⚠ Длинные значения приходят **только изменившимися строками** (решение
    // человека: полный промпт в истории не нужен). В таблице они ложатся
    // естественно: убранные строки — в «До», добавленные — в «После». Прежде
    // те и другие шли вперемешку одним списком, и глазами их разделяли сами.
    if (one.lines) {
        return `<td class="history-field">${head}${_field(one.field)}</td>`
            + `<td class="history-was">${_lines(one.lines, '-')}</td>`
            + `<td class="history-now">${_lines(one.lines, '+')}</td>`;
    }

    return `<td class="history-field">${head}${_field(one.field)}</td>`
        + `<td class="history-was">${_value(one.was, one.field, object)}</td>`
        + `<td class="history-now">${_value(one.now, one.field, object)}</td>`;
}

/** Строки построчного диффа одной стороны: `-` в «До», `+` в «После». */
function _lines(lines, op) {
    const mine = (lines || []).filter(row => row.more || row.op === op);

    if (!mine.length) return '<i class="history-none">без изменений</i>';

    return mine.map(row => row.more
        ? `<div class="history-more">…и ещё ${Number(row.more) || 0} строк</div>`
        : `<div class="history-line">`
          + `<span class="history-line-no">${Number(row.line) || 0}</span>`
          + `${_safe(row.text)}</div>`).join('');
}

function _value(value, field, object) {
    // ⚠ «Пусто» и «не было» — разные вещи, и показывать их одинаково нельзя:
    // первое человек правил, второго не существовало.
    if (value === null || value === undefined) {
        return '<i class="history-none">нет</i>';
    }

    if (value === '') return '<i class="history-none">пусто</i>';

    const said = _said(field, value, object);
    if (said !== null) return said;

    return _safe(typeof value === 'object'
        ? JSON.stringify(value) : String(value));
}

/**
 * Значение словами — там, где число или код сами по себе ничего не говорят.
 *
 * Returns:
 *     Готовый HTML либо `null`, если поле обычное и переводить нечего.
 *
 * ## ⚠⚠⚠ Зачем: «нода 2 → 3» не отвечает ни на один вопрос
 *
 * Запись истории читают, чтобы понять, **что сделали**. Номер ноды знает база,
 * а человек — имя; пара чисел в ленте требует пойти и посмотреть, какая это
 * нода, то есть ровно того труда, ради избавления от которого лента и
 * заведена. То же у флага (`0 → 1`) и у рода переменной (`workflow → input`).
 *
 * ⚠ Номер не выбрасывается, а уезжает в подсказку: по нему ищут в базе, когда
 * имя неоднозначно или ноду успели переименовать.
 */
function _said(field, value, object) {
    const text = String(value);

    if (field === 'node_id') {
        const name = _nodeName(text);

        return name
            ? `<span title="нода №${_safe(text)}">${_safe(name)}</span>`
            : `<span title="ноды с таким номером больше нет">№${_safe(text)}</span>`;
    }

    if (field === 'subflow') {
        return BOOL_WORDS[text] === undefined ? null : BOOL_WORDS[text];
    }

    // ⚠⚠ Только у переменной: у шага `type` — это род шага
    // (`return_response_llm`), и слово «входящая» там было бы ложью.
    if (field === 'type' && object === 'variable') {
        return VAR_TYPE_WORDS[text] ? _safe(VAR_TYPE_WORDS[text]) : null;
    }

    return null;
}

/**
 * Имя ноды по номеру — из селекта формы, который сервер уже наполнил.
 *
 * ⚠⚠ Не своим запросом и не своим состоянием: список нод на странице один
 * (`main.js` кладёт его в `#node_id`), и второй источник разошёлся бы с ним
 * ровно тогда, когда ноду переименуют.
 */
function _nodeName(id) {
    const select = document.getElementById('node_id');
    if (!select) return '';

    const option = [...select.options].find(one => String(one.value) === String(id));

    return option ? option.textContent.trim() : '';
}

function _pager(answer) {
    const pages = Number((answer && answer.pages) || 1);
    if (pages < 2) return '';

    const page = Number((answer && answer.page) || 1);

    return '<div class="history-pager">'
        + `<button type="button" data-history-page="${page - 1}"`
        + `${page <= 1 ? ' disabled' : ''}>←</button>`
        + `<span>${page} из ${pages}</span>`
        + `<button type="button" data-history-page="${page + 1}"`
        + `${page >= pages ? ' disabled' : ''}>→</button>`
        + '</div>';
}

function _wire(host) {
    host.querySelectorAll('[data-history-page]').forEach(btn => {
        btn.onclick = async () => {
            view.page = Math.max(1, Number(btn.dataset.historyPage) || 1);
            await _draw(host);
        };
    });

    host.querySelector('[data-history-all]')?.addEventListener('click', async () => {
        view.object = '';
        view.objectId = 0;
        view.page = 1;
        await _draw(host);
    });

    host.querySelectorAll('[data-history-step]').forEach(row => {
        row.onclick = () => {
            // ⚠ Через событие страницы, а не импортом `steps.js`: тот тянет
            // редактор целиком, и вышел бы цикл модулей.
            document.dispatchEvent(new CustomEvent('workflow:step-open', {
                detail: {stepId: row.dataset.historyStep},
            }));
        };
    });
}

/**
 * Время правки в поясе установки.
 *
 * ⚠⚠⚠ Здесь стояло «показываем как записано»: довод был, что сдвигать нечем —
 * настройка живёт на сервере. Довод неверен. Пояс отдаётся фронтенду
 * (`/setting/list`, ключ `timezone`), и общий помощник `tz.js` подключён в
 * `base.html` на каждой странице панели — звать `loadTz()` просто забыли. Лента
 * показывала UTC, а соседние страницы — местное время: на вопрос «когда это
 * сломалось» два ответа, разные на величину пояса.
 *
 * ⚠ С секундами: правка шага уходит в базу сама через 400 мс, и две записи в
 * одну минуту — обычное дело. Без секунд лента выглядела бы перетасованной.
 */
function _when(raw) {
    if (window.fmtTz) return _safe(window.fmtTz(raw, true));

    // ⚠ Помощника нет — показываем записанное, но не молча: иначе «UTC» и
    // «местное» неотличимы, и человек сверяет время не с тем.
    return _safe(String(raw || '').replace('T', ' ').slice(0, 19) + ' UTC');
}

/** Имя поля человеку; незнакомое — как есть, это путь внутрь метаданных. */
function _field(name) {
    return _safe(FIELD_WORDS[name] || name);
}

function _safe(text) {
    const box = document.createElement('div');
    box.textContent = String(text === null || text === undefined ? '' : text);

    return box.innerHTML;
}

function _note(text) {
    return `<div class="history-note">${_safe(text)}</div>`;
}

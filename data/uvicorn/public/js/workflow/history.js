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
        parts.push('<div class="history-feed">'
            + rows.map(_row).join('') + '</div>');
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

    // ⚠⚠ У правки самого workflow род и имя **не пишем**. Вкладка показывает
    // историю одного workflow, его имя стоит в шапке страницы, и строка
    // «изменено workflow «Инвайт: шаблон: один»» повторяла известное — а
    // повтор известного в ленте стоит места, которое нужно сути правки.
    const subject = one.object === 'workflow' ? '' : (() => {
        const object = OBJECT_WORDS[one.object] || _safe(one.object);
        const name = one.object_name
            ? `«${_safe(one.object_name)}»` : (id ? `#${id}` : '');

        return ` ${object} ${name}`;
    })();

    // ⚠ Щелчок по строке ведёт **к шагу**: история нужна, чтобы починить, а не
    // чтобы полюбоваться. Тот же порядок, что у ленты событий в DatingAi.
    //
    // ⚠ Номер в атрибут — **числом**: строка из базы попала бы в разметку как
    // есть, и кавычка в ней разорвала бы атрибут.
    const goes = one.object === 'step' && id
        ? ` data-history-step="${id}"` : '';

    return `<div class="history-row"${goes}>`
        + `<div class="history-when">${when}</div>`
        + `<div class="history-who">${_safe(who)}${mark}</div>`
        + `<div class="history-what">${what}${subject}</div>`
        + `<div class="history-diff">${(one.changes || []).map(_diff).join('')}</div>`
        + '</div>';
}

function _diff(one) {
    if (one.more) {
        return `<div class="history-more">…и ещё ${Number(one.more) || 0} изменений</div>`;
    }

    // ⚠ Длинные значения приходят **только изменившимися строками** (решение
    // человека: полный промпт в истории не нужен). Показываем их как дифф, с
    // номерами строк — по ним ищут глазами в поле промпта.
    if (one.lines) {
        return `<div class="history-field">${_field(one.field)}</div>`
            + one.lines.map(row => row.more
                ? `<div class="history-more">…и ещё ${Number(row.more) || 0} строк</div>`
                : `<div class="history-line history-line-${row.op === '+' ? 'add' : 'cut'}">`
                  + `<span class="history-line-no">${Number(row.line) || 0}</span>`
                  + `${row.op === '+' ? '+' : '-'} ${_safe(row.text)}</div>`).join('');
    }

    return `<div class="history-change">`
        + `<span class="history-field">${_field(one.field)}</span>`
        + `<span class="history-was">${_value(one.was)}</span>`
        + '<span class="history-arrow">→</span>'
        + `<span class="history-now">${_value(one.now)}</span>`
        + '</div>';
}

function _value(value) {
    // ⚠ «Пусто» и «не было» — разные вещи, и показывать их одинаково нельзя:
    // первое человек правил, второго не существовало.
    if (value === null || value === undefined) {
        return '<i class="history-none">нет</i>';
    }

    if (value === '') return '<i class="history-none">пусто</i>';

    return _safe(typeof value === 'object'
        ? JSON.stringify(value) : String(value));
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

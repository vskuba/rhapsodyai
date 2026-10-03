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

// Что сделали. ⚠ `reorder` назван «порядок шагов», а не «перестановка»: в ленте
// читают глазами, и существительное находится быстрее отглагольного.
const ACTION_WORDS = {
    create: 'заведено', update: 'изменено', delete: 'удалено',
    reorder: 'порядок шагов', import: 'импорт',
};

// Кто правил. ⚠ Правки агента лежат **в той же ленте** (решение человека): метка
// нужна затем, чтобы человеческие не терялись среди машинных, а не затем, чтобы
// их разделить.
const AUTHOR_WORDS = {human: '', agent: '🤖 агент', import: '📦 импорт'};

// Состояние вкладки: какой workflow показан, на какой странице и с каким отбором.
//
// ⚠ Отбор держим здесь, а не в DOM: страница перерисовывается целиком, и
// прочитай мы его из разметки — он слетал бы на каждой перерисовке.
const view = {workflowId: 0, page: 1, object: '', objectId: 0};


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
    const what = ACTION_WORDS[one.action] || _safe(one.action);
    const object = OBJECT_WORDS[one.object] || _safe(one.object);
    const id = Number(one.object_id) || 0;
    const name = one.object_name
        ? `«${_safe(one.object_name)}»` : (id ? `#${id}` : '');

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
        + `<div class="history-what">${what} ${object} ${name}</div>`
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
        return `<div class="history-field">${_safe(one.field)}</div>`
            + one.lines.map(row => row.more
                ? `<div class="history-more">…и ещё ${Number(row.more) || 0} строк</div>`
                : `<div class="history-line history-line-${row.op === '+' ? 'add' : 'cut'}">`
                  + `<span class="history-line-no">${Number(row.line) || 0}</span>`
                  + `${row.op === '+' ? '+' : '-'} ${_safe(row.text)}</div>`).join('');
    }

    return `<div class="history-change">`
        + `<span class="history-field">${_safe(one.field)}</span>`
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

function _when(raw) {
    // ⚠ Время приходит как есть, строкой базы: сдвигать его часовым поясом
    // здесь нечем — настройка живёт на сервере, и врать на час хуже, чем
    // показать то, что записано.
    const text = String(raw || '').replace('T', ' ');

    return _safe(text.slice(0, 19));
}

function _safe(text) {
    const box = document.createElement('div');
    box.textContent = String(text === null || text === undefined ? '' : text);

    return box.innerHTML;
}

function _note(text) {
    return `<div class="history-note">${_safe(text)}</div>`;
}

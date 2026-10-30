// Вкладка «Намерения»: что агент пообещал или заметил за парой.
//
// Строка здесь — одна находка: метка словом (`she_promised_send_photo`) и
// время. Кладёт их инструмент `companion_intention.py` по ходу разговора,
// страница только читает.
//
// ⚠⚠ Время — рабочее значение, а не украшение ленты. Им следующий прогон режет
// историю разговора надвое и ищет новое намерение только в свежей половине.
// Поэтому оно стоит у каждой записи и не сворачивается в «сегодня»: человек
// приходит сюда ровно с вопросом «почему обещание приехало дважды».
//
// ⚠ Канала у намерения нет, в отличие от разговора: обещание, данное письмом,
// остаётся тем же обещанием в чате. Поэтому пара здесь — пара, а не тройка.
//
// Устройство страницы — `.claude/docs/session.md`.

import {getData, postData} from '../api.js';
import {filterLoad, filterSave, htmlEscape, labelClip, pluralOf, selectFill,
        selectValueRestore, stampList, sumOf} from './util.js';

// Приставка ключей отбора. ⚠ Своя у вкладки: `owner_id` соседней про другой
// предмет, и общий ключ переносил бы выбор между несвязанными списками.
const INTENTION_STORE_PREFIX = 'intention_';

// Докуда режем подпись стороны в `<select>`. ⚠ То же число, что у соседней
// вкладки: ширина сайдбара одна на страницу.
const INTENTION_LABEL_MAX = 34;

const el = {};
const state = {pairs: [], shown: [], current: null};

// Счётчик запросов: ответ на устаревший отбор не должен перерисовывать ленту.
// ⚠ Тот же приём, что у соседней вкладки, — отборы щёлкают быстрее сети.
let intentionRequest = 0;


export function sessionIntentionInit() {
    el.owner = document.getElementById('intentionOwner');
    el.companion = document.getElementById('intentionCompanion');
    el.kind = document.getElementById('intentionKind');
    el.limit = document.getElementById('intentionLimit');
    el.list = document.getElementById('intentionSelect');
    el.title = document.getElementById('intentionTitle');
    el.stream = document.getElementById('intentionStream');

    if (!el.list) return;

    selectValueRestore(el.limit, filterLoad(`${INTENTION_STORE_PREFIX}limit`));

    filtersBind();
    start();
}


// ── Отборы ───────────────────────────────────────────────────────────────────

/** Полная выборка пар — только чтобы наполнить отборы сторон.
 *
 * ⚠ Запрос без отборов, отдельно от основного: списку в сайдбаре нужен отбор,
 * а отборам — все стороны. Собери их из отфильтрованного ответа, и выбранный
 * собеседник выкинул бы из списка всех остальных.
 */
async function pairsLoadAll() {
    const data = await postData('/session/intention/list', {});

    state.pairs = data.result || [];

    sidesFill();
    selectValueRestore(el.owner, filterLoad(`${INTENTION_STORE_PREFIX}owner`));
    companionFill();
    selectValueRestore(el.companion,
        filterLoad(`${INTENTION_STORE_PREFIX}companion`));
}

/** Виды намерений в отбор — своей ручкой.
 *
 * ⚠ Не из списка пар: вид не должен исчезать из отбора оттого, что сузили
 * пару, — иначе выбранное условие пропадало бы само.
 */
async function kindsLoad() {
    const data = await getData('/session/intention/kind/list');
    const kinds = data.result || [];

    selectFill(el.kind, [
        {value: '', text: `Любое (${sumOf(kinds, 'count')})`},
        ...kinds.map(one => ({
            value: one.intention,
            text: `${labelClip(one.intention, INTENTION_LABEL_MAX)} (${one.count})`,
            title: one.intention,
        })),
    ]);

    selectValueRestore(el.kind, filterLoad(`${INTENTION_STORE_PREFIX}kind`));
}

function sidesFill() {
    selectFill(el.owner, [
        {value: '', text: `Все (${sumOf(state.pairs, 'intention_count')})`},
        ...sideEntries(state.pairs, 'owner'),
    ]);
    companionFill();
}

function companionFill() {
    const owner = el.owner.value;
    const scoped = owner
        ? state.pairs.filter(one => one.owner_unique_id === owner)
        : state.pairs;

    selectFill(el.companion, [
        {value: '', text: `Все (${sumOf(scoped, 'intention_count')})`},
        ...sideEntries(scoped, 'companion'),
    ]);
}

/** Стороны для отбора: ключ, подпись и число намерений за ней.
 *
 * ⚠ Ключом идёт `unique_id`, а не номер записи: номер у намерения не выходит
 * наружу вовсе, и вводить его в страницу ради отбора значило бы завести второй
 * способ назвать ту же сторону.
 */
function sideEntries(pairs, side) {
    const counts = {};
    const titles = {};

    pairs.forEach(one => {
        const key = one[`${side}_unique_id`];

        counts[key] = (counts[key] || 0) + Number(one.intention_count || 0);
        titles[key] = one[`${side}_title`] || key;
    });

    return Object.keys(counts).map(key => ({
        value: key,
        text: `${labelClip(titles[key], INTENTION_LABEL_MAX)} (${counts[key]})`,
        // ⚠ Ключ подсказкой: заголовков-близнецов в справочнике хватает, и без
        // него варианты отбора неразличимы.
        title: `${titles[key]} · ${key}`,
    }));
}

function filtersBind() {
    el.owner.onchange = async () => {
        filterSave(`${INTENTION_STORE_PREFIX}owner`, el.owner.value);
        companionFill();
        filterSave(`${INTENTION_STORE_PREFIX}companion`, el.companion.value);
        await pairsLoad();
    };

    el.companion.onchange = async () => {
        filterSave(`${INTENTION_STORE_PREFIX}companion`, el.companion.value);
        await pairsLoad();
    };

    // ⚠ Вид намерения отбирает и список пар, и ленту внутри: условие одно, и
    // расходиться им незачем — «пар нет» и «в паре пусто» иначе означали бы
    // разные отборы.
    el.kind.onchange = async () => {
        filterSave(`${INTENTION_STORE_PREFIX}kind`, el.kind.value);
        await pairsLoad();
    };

    el.limit.onchange = () => {
        filterSave(`${INTENTION_STORE_PREFIX}limit`, el.limit.value);

        if (state.current) rowsLoad(state.current);
    };

    el.list.onchange = () => {
        const pair = state.shown?.[el.list.selectedIndex];

        if (pair) rowsLoad(pair);
    };
}

function filtersValue() {
    return {
        owner_unique_id: el.owner.value || '',
        companion_unique_id: el.companion.value || '',
        intention: el.kind.value || '',
    };
}


// ── Пары ─────────────────────────────────────────────────────────────────────

/** Список пар под текущий отбор.
 *
 * ⚠⚠ Открывается запомненная пара, а не верхняя: отбор меняют, чтобы
 * посмотреть на ТУ ЖЕ пару другим срезом. Открывай мы верхнюю, смена вида
 * намерения уводила бы с пары, ради которой сюда и пришли. Запомненной нет под
 * новым отбором — тогда верхняя, самая свежая.
 */
async function pairsLoad(keep = null) {
    const request = ++intentionRequest;

    el.list.innerHTML = '<option>Загрузка...</option>';

    const data = await postData('/session/intention/list', filtersValue());

    if (request !== intentionRequest) return;

    const pairs = data.result || [];

    state.shown = pairs;
    el.list.innerHTML = '';

    if (!pairs.length) {
        el.list.innerHTML = '<option disabled>Намерений нет</option>';
        state.current = null;
        el.title.textContent = 'Выберите пару';
        el.stream.innerHTML = '<div class="placeholder">Под этот отбор намерений нет</div>';

        return;
    }

    pairs.forEach(one => el.list.appendChild(pairOption(one)));

    const wanted = keep || pairRemembered();
    const at = wanted
        ? pairs.findIndex(one => pairKey(one) === pairKey(wanted))
        : -1;

    el.list.selectedIndex = at >= 0 ? at : 0;
    await rowsLoad(pairs[el.list.selectedIndex]);
}

function pairOption(pair) {
    const option = document.createElement('option');
    const kinds = pair.intention_kinds > 1 ? `, видов ${pair.intention_kinds}` : '';

    option.textContent = `${stampList(pair.last_at)}  ${pairLabel(pair)}`
        + `  ✦${pair.intention_count}${kinds}`;
    option.title = `${pair.owner_unique_id} → ${pair.companion_unique_id}`;

    return option;
}

function pairLabel(pair) {
    return `${pair.owner_title || pair.owner_unique_id}`
        + ` → ${pair.companion_title || pair.companion_unique_id}`;
}

function pairKey(pair) {
    return `${pair.owner_unique_id} ${pair.companion_unique_id}`;
}

function pairRemembered() {
    const owner = filterLoad(`${INTENTION_STORE_PREFIX}pair_owner`);
    const companion = filterLoad(`${INTENTION_STORE_PREFIX}pair_companion`);

    return owner && companion
        ? {owner_unique_id: owner, companion_unique_id: companion}
        : null;
}


// ── Лента ────────────────────────────────────────────────────────────────────

async function rowsLoad(pair) {
    if (!pair) return;

    const request = ++intentionRequest;

    state.current = pair;
    filterSave(`${INTENTION_STORE_PREFIX}pair_owner`, pair.owner_unique_id);
    filterSave(`${INTENTION_STORE_PREFIX}pair_companion`, pair.companion_unique_id);

    el.stream.innerHTML = '<div class="placeholder">Загрузка...</div>';

    const data = await postData('/session/intention/rows', {
        owner_unique_id: pair.owner_unique_id,
        companion_unique_id: pair.companion_unique_id,
        intention: el.kind.value || '',
        limit: Number(el.limit.value) || 200,
    });

    if (request !== intentionRequest) return;

    const said = data.result || {};

    titleRender(pair, said.rows || []);
    streamRender(said.rows || [], said.kinds || []);
}

function titleRender(pair, rows) {
    const shown = rows.length;
    const total = Number(pair.intention_count || 0);
    // ⚠ «Показано N из M» — не для красоты: лента обрезана `limit`, и без
    // этого числа человек читал бы «за парой 50 намерений» там, где их двести.
    const word = pluralOf(total, 'намерение', 'намерения', 'намерений');
    const tail = shown < total
        ? `показано ${shown} из ${total}`
        : `${total} ${word}`;

    el.title.innerHTML =
        `<span class="detail-pair">${htmlEscape(pairLabel(pair))}</span>`
        + ` <span class="detail-note">· ${htmlEscape(tail)}</span>`;
}

/** Лента: сводка по видам, затем записи.
 *
 * ⚠⚠ Сводка приходит с сервера отдельным счётом и НЕ считается по показанным
 * строкам: лента обрезана `limit`, и «7 раз» означало бы «7 из показанных»,
 * а на длинной истории врало бы тем сильнее, чем интереснее случай.
 */
function streamRender(rows, kinds) {
    if (!rows.length) {
        el.stream.innerHTML = '<div class="placeholder">У этой пары намерений нет</div>';

        return;
    }

    const parts = [];

    if (kinds.length) {
        parts.push('<div class="intention-kinds">'
            + kinds.map(kindCard).join('')
            + '</div>');
    }

    parts.push(rows.map(rowCard).join(''));
    el.stream.innerHTML = parts.join('');
}

function kindCard(kind) {
    const span = kind.first_at === kind.last_at
        ? stampList(kind.last_at)
        : `${stampList(kind.first_at)} … ${stampList(kind.last_at)}`;

    return '<div class="intention-kind">'
        + `<span class="intention-chip">${htmlEscape(kind.intention)}</span>`
        + `<span class="intention-kind-count">${kind.count}×</span>`
        + `<span class="intention-kind-span">${htmlEscape(span)}</span>`
        + '</div>';
}

/** Запись ленты: номер, метка, время.
 *
 * ⚠ Метка лежит в своей ячейке (`.intention-row-mark`), а не чипом напрямую:
 * ячейке задана наименьшая ширина, и этим даты выстраиваются в колонку даже
 * когда метки разной длины. Без неё дата вставала бы вплотную к каждой метке,
 * и столбца, по которому скользит глаз, не выходило бы.
 */
function rowCard(row) {
    return '<div class="intention-row">'
        + `<span class="intention-row-id">#${row.id}</span>`
        + '<span class="intention-row-mark">'
        + `<span class="intention-chip">${htmlEscape(row.intention)}</span>`
        + '</span>'
        + `<span class="intention-row-at">${htmlEscape(stampList(row.created_at))}</span>`
        + '</div>';
}


async function start() {
    await pairsLoadAll();
    await kindsLoad();
    await pairsLoad();
}
